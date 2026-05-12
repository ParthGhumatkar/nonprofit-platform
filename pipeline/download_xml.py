# pipeline/download_xml.py
# Downloads 990 XMLs directly into data/raw_xml/{EIN}/{YEAR}/ structure
# Uses HTTPS URLs from manifest — no AWS CLI needed
# Resumable: skips files that already exist

import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import pandas as pd
import requests
from urllib3.exceptions import InsecureRequestWarning


def download_one(task: dict, session: requests.Session):
    os.makedirs(task["dest_dir"], exist_ok=True)
    try:
        r = session.get(task["url"], timeout=30)
        if r.status_code == 200:
            with open(task["dest"], "wb") as f:
                f.write(r.content)
            return True, task
        else:
            return False, {**task, "error": f"HTTP {r.status_code}"}
    except Exception as e:
        return False, {**task, "error": str(e)[:100]}


def main():
    PROJECT = os.getenv(
        "PROJECT_DIR",
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    )
    MANIFEST = os.path.join(PROJECT, "data", "indexes", "download_manifest.csv")
    RAW_DIR = os.path.join(PROJECT, "data", "raw_xml")
    WORKERS = int(os.getenv("DOWNLOAD_WORKERS", "10"))
    S3_BASE = "https://gt990datalake-rawdata.s3.amazonaws.com/EfileData/XmlFiles/"

    # Suppress SSL warnings (corporate proxy)
    requests.packages.urllib3.disable_warnings(InsecureRequestWarning)

    session = requests.Session()
    session.verify = False  # corporate SSL proxy

    df = pd.read_csv(MANIFEST, dtype=str)
    total = len(df)

    # Build task list, skip already downloaded
    tasks = []
    skipped = 0

    for _, row in df.iterrows():
        ein = str(row["EIN"]).zfill(9)
        obj_id = str(row["OBJECT_ID"]).strip()
        year = str(row["FILING_YEAR"])
        url = str(row.get("URL", "")).strip()

        fname = f"{obj_id}_public.xml"
        dest_dir = os.path.join(RAW_DIR, ein, year)
        dest = os.path.join(dest_dir, fname)

        if os.path.exists(dest):
            skipped += 1
            continue

        # Use URL from manifest if available, otherwise construct it
        if not url or url == "nan":
            url = f"{S3_BASE}{fname}"

        tasks.append(
            {"url": url, "dest": dest, "dest_dir": dest_dir,
             "ein": ein, "year": year, "obj_id": obj_id}
        )

    print(f"Total filings: {total:,}")
    print(f"Already downloaded: {skipped:,}")
    print(f"To download: {len(tasks):,}")
    print(f"Workers: {WORKERS}")
    print(f"{'='*55}\n")

    done = errors = 0
    failed = []
    start = time.time()

    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        futures = {pool.submit(download_one, t, session): t for t in tasks}

        for i, future in enumerate(as_completed(futures), 1):
            ok, result = future.result()
            if ok:
                done += 1
            else:
                errors += 1
                failed.append(result)

            if i % 500 == 0:
                elapsed = time.time() - start
                rate = i / elapsed
                eta = (len(tasks) - i) / rate / 60 if rate > 0 else 0
                print(
                    f"  {i:,}/{len(tasks):,} | ✓ {done:,} | ✗ {errors} "
                    f"| {rate:.1f} files/sec | ETA {eta:.0f} min"
                )

    elapsed = time.time() - start
    print(f"\n{'='*55}")
    print(f"Done in {elapsed/60:.1f} minutes")
    print(f"Downloaded: {done:,} | Skipped: {skipped:,} | Failed: {errors}")

    if failed:
        pd.DataFrame(failed).to_csv(
            os.path.join(PROJECT, "data", "indexes", "failed_downloads.csv"),
            index=False,
        )
        print("Failed list → data/indexes/failed_downloads.csv")


if __name__ == "__main__":
    main()
