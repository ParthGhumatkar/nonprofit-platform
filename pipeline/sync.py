"""
Monthly sync orchestrator — XML filings only.
"""
import os, sys, time, logging
from datetime import datetime
from parse_irsx import parse_file
from db import get_stats, backfill_org_metadata

RAW_XML_DIR = os.getenv("RAW_XML_DIR", "./data/raw_xml")
MIN_FILE_SIZE = 20000

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout), logging.FileHandler("sync.log")],
)
logger = logging.getLogger(__name__)

def sync_xml():
    logger.info("=== XML Sync Start ===")
    total = parsed = skipped = errors = 0; start_time = time.time()
    if not os.path.isdir(RAW_XML_DIR):
        logger.error(f"RAW_XML_DIR not found: {RAW_XML_DIR}"); return
    for ein in sorted(os.listdir(RAW_XML_DIR)):
        ein_path = os.path.join(RAW_XML_DIR, ein)
        if not os.path.isdir(ein_path): continue
        for year in sorted(os.listdir(ein_path)):
            year_path = os.path.join(ein_path, year)
            if not os.path.isdir(year_path): continue
            for fname in sorted(os.listdir(year_path)):
                if not fname.endswith(".xml"): continue
                fpath = os.path.join(year_path, fname); total += 1
                try:
                    result = parse_file(fpath, min_file_size=MIN_FILE_SIZE)
                except Exception as e:
                    logger.error(f"ERROR {ein}/{year}/{fname}: {e}"); errors += 1; continue
                if result.get("skip"):
                    skipped += 1
                    if total <= 10 or total % 1000 == 0: logger.debug(f'SKIP {ein}/{year} — {result.get("reason")}')
                else:
                    parsed += 1
                    logger.info(f'OK  {ein}/{year} | {result.get("form_type"):<6} | grants={result.get("grants",0):<4} comp={result.get("comp",0):<3} mission={"YES" if result.get("mission") else "NO"}')
                if total % 1000 == 0:
                    elapsed = time.time() - start_time; rate = total / elapsed if elapsed > 0 else 0
                    logger.info(f"Progress: {total} files ({parsed} parsed, {skipped} skipped, {errors} errors) — {rate:.1f} files/sec")
    elapsed = time.time() - start_time
    logger.info(f"=== XML Sync Complete: {total} files, {parsed} parsed, {skipped} skipped, {errors} errors in {elapsed:.0f}s ===")

def run():
    logger.info("=" * 60)
    logger.info(f"NONPROFIT PLATFORM SYNC — {datetime.now().isoformat()}")
    logger.info("=" * 60)
    sync_xml()
    backfill_org_metadata()
    stats = get_stats()
    logger.info("=" * 60)
    logger.info(f'PLATFORM STATS: {stats["organizations"]} organizations, {stats["filings"]} filings, {stats["organizations_with_filings"]} orgs with filings')
    logger.info("=" * 60)

if __name__ == "__main__":
    run()
