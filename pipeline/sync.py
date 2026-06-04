"""
Monthly sync orchestrator — XML filings parsed in parallel with multiprocessing.

Each worker process:
  - Loads its own .env via load_dotenv()
  - Reads DATABASE_URL from its own environment
  - Opens its own psycopg2 connection on demand (each db.py helper opens a
    fresh connection — connections are never shared across processes)

Windows-compatible: forces the 'spawn' start method (no fork).
"""

import os
import sys
import time
import logging
import multiprocessing
from datetime import datetime

from dotenv import load_dotenv


load_dotenv()

RAW_XML_DIR = os.getenv("RAW_XML_DIR", "./data/raw_xml")
MIN_FILE_SIZE = 5000

DEFAULT_WORKERS = max(1, (os.cpu_count() or 2) // 2)
PIPELINE_WORKERS = max(1, int(os.getenv("PIPELINE_WORKERS", str(DEFAULT_WORKERS))))

PROGRESS_EVERY = 500
CHUNKSIZE = 8

logger = logging.getLogger("sync")


def _configure_main_logging():
    """Configure logging for the main process only.

    Writes to stdout and sync.log. Called from run() rather than at module
    import time so that every spawned worker does not reopen sync.log.
    """
    root = logging.getLogger()
    for h in list(root.handlers):
        root.removeHandler(h)
    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")
    sh = logging.StreamHandler(sys.stdout)
    sh.setFormatter(fmt)
    fh = logging.FileHandler("sync.log")
    fh.setFormatter(fmt)
    root.addHandler(sh)
    root.addHandler(fh)
    root.setLevel(logging.INFO)


def _ein_year_from_path(filepath):
    parts = os.path.normpath(filepath).split(os.sep)
    if len(parts) >= 3:
        return parts[-3], parts[-2]
    return "unknown", "unknown"


def collect_xml_files(root):
    """Return a sorted list of every .xml under {root}/{EIN}/{YEAR}/*.xml."""
    files = []
    if not os.path.isdir(root):
        return files
    for ein in sorted(os.listdir(root)):
        ein_path = os.path.join(root, ein)
        if not os.path.isdir(ein_path):
            continue
        for year in sorted(os.listdir(ein_path)):
            year_path = os.path.join(ein_path, year)
            if not os.path.isdir(year_path):
                continue
            for fname in sorted(os.listdir(year_path)):
                if fname.endswith(".xml"):
                    files.append(os.path.join(year_path, fname))
    return files


def _init_worker():
    """Run once per worker process at startup.

    Loads .env so DATABASE_URL is present in os.environ BEFORE db.py is
    imported in the child. Configures a minimal stderr logger so any
    worker-side exceptions are visible.
    """
    load_dotenv()
    if not os.getenv("DATABASE_URL"):
        raise RuntimeError(
            "DATABASE_URL environment variable is required in worker process"
        )
    logging.basicConfig(
        level=logging.WARNING,
        format="%(asctime)s [%(levelname)s] [worker %(process)d] %(message)s",
        handlers=[logging.StreamHandler(sys.stderr)],
        force=True,
    )


def process_one(filepath):
    """Worker entry point — parse one XML file, return a result dict.

    Result shape:
      {'status': 'parsed' | 'skipped' | 'error',
       'ein': str, 'year': str, 'path': str,
       ...extra fields per status}

    parse_irsx is imported lazily so the db.py module-level
    `DATABASE_URL = os.getenv(...)` check runs AFTER _init_worker() has
    loaded the .env file.
    """
    ein, year = _ein_year_from_path(filepath)
    try:
        from parse_irsx import parse_file
        result = parse_file(filepath, min_file_size=MIN_FILE_SIZE)
    except Exception as e:
        return {
            "status": "error",
            "ein": ein,
            "year": year,
            "path": filepath,
            "error": f"{type(e).__name__}: {e}",
        }

    if result.get("skip"):
        return {
            "status": "skipped",
            "ein": ein,
            "year": year,
            "path": filepath,
            "reason": result.get("reason"),
        }

    return {
        "status": "parsed",
        "ein": ein,
        "year": year,
        "path": filepath,
        "form_type": result.get("form_type"),
        "grants": result.get("grants", 0),
        "comp": result.get("comp", 0),
        "mission": bool(result.get("mission")),
    }


def _log_progress(done, total, parsed, skipped, errors, start_time):
    elapsed = time.time() - start_time
    rate = done / elapsed if elapsed > 0 else 0.0
    remaining = max(0, total - done)
    eta_min = (remaining / rate / 60.0) if rate > 0 else 0.0
    logger.info(
        f"Progress: {done:,}/{total:,} "
        f"(parsed={parsed:,} skipped={skipped:,} errors={errors:,}) "
        f"— {rate:.1f} files/sec — ETA {eta_min:.1f} min"
    )


def _log_summary(done, total, parsed, skipped, errors, start_time, interrupted=False):
    elapsed = time.time() - start_time
    rate = done / elapsed if elapsed > 0 else 0.0
    banner = "=== XML Sync Interrupted ===" if interrupted else "=== XML Sync Complete ==="
    logger.info("=" * 60)
    logger.info(banner)
    logger.info(f"Files found:   {total:,}")
    logger.info(f"Files done:    {done:,}")
    logger.info(f"  parsed:      {parsed:,}")
    logger.info(f"  skipped:     {skipped:,}")
    logger.info(f"  errors:      {errors:,}")
    logger.info(f"Elapsed:       {elapsed:.0f}s ({elapsed / 60.0:.1f} min)")
    logger.info(f"Avg rate:      {rate:.1f} files/sec")
    logger.info("=" * 60)


def sync_xml():
    """Walk RAW_XML_DIR, parse every .xml in parallel with a worker pool."""
    logger.info("=== XML Sync Start ===")
    logger.info(f"RAW_XML_DIR      = {RAW_XML_DIR}")
    logger.info(f"PIPELINE_WORKERS = {PIPELINE_WORKERS} (cpu_count={os.cpu_count()})")
    logger.info(f"MIN_FILE_SIZE    = {MIN_FILE_SIZE} bytes")

    if not os.path.isdir(RAW_XML_DIR):
        logger.error(f"RAW_XML_DIR not found: {RAW_XML_DIR}")
        return

    scan_start = time.time()
    logger.info("Scanning for XML files...")
    files = collect_xml_files(RAW_XML_DIR)
    total = len(files)
    logger.info(f"Found {total:,} XML files in {time.time() - scan_start:.1f}s")

    if total == 0:
        logger.warning("No XML files found — nothing to do.")
        return

    parsed = skipped = errors = done = 0
    start_time = time.time()
    interrupted = False

    # spawn is required on Windows and safe on every other platform.
    ctx = multiprocessing.get_context("spawn")
    pool = ctx.Pool(processes=PIPELINE_WORKERS, initializer=_init_worker)

    try:
        for result in pool.imap_unordered(process_one, files, chunksize=CHUNKSIZE):
            done += 1
            status = result.get("status")
            if status == "parsed":
                parsed += 1
            elif status == "skipped":
                skipped += 1
            else:
                errors += 1
                logger.error(
                    f"ERROR {result.get('ein')}/{result.get('year')} "
                    f"{os.path.basename(result.get('path', ''))}: "
                    f"{result.get('error')}"
                )

            if done % PROGRESS_EVERY == 0:
                _log_progress(done, total, parsed, skipped, errors, start_time)

        pool.close()
        pool.join()
    except KeyboardInterrupt:
        interrupted = True
        logger.warning("KeyboardInterrupt received — terminating worker pool...")
        pool.terminate()
        pool.join()
    except Exception:
        pool.terminate()
        pool.join()
        raise

    _log_summary(done, total, parsed, skipped, errors, start_time, interrupted=interrupted)


def run():
    """Entry point. Configures logging, runs sync_xml, then backfill + stats."""
    _configure_main_logging()
    logger.info("=" * 60)
    logger.info(f"NONPROFIT PLATFORM SYNC — {datetime.now().isoformat()}")
    logger.info("=" * 60)

    try:
        sync_xml()
    except KeyboardInterrupt:
        logger.warning("Interrupted during sync_xml().")
        return

    logger.info("Running backfill_org_metadata()...")
    try:
        from db import backfill_org_metadata, get_stats
        backfill_org_metadata()
        stats = get_stats()
        logger.info("=" * 60)
        logger.info(
            f"PLATFORM STATS: {stats['organizations']:,} organizations, "
            f"{stats['filings']:,} filings, "
            f"{stats['organizations_with_filings']:,} orgs with filings"
        )
        logger.info("=" * 60)
    except KeyboardInterrupt:
        logger.warning("Backfill interrupted by user.")


if __name__ == "__main__":
    try:
        run()
    except KeyboardInterrupt:
        sys.stderr.write("\nInterrupted before completion.\n")
        sys.exit(130)
