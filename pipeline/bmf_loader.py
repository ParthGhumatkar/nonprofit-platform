"""
BMF (Business Master File) CSV loader.
Downloads NCCS BMF data as a direct CSV and upserts into the database.
Maps NTEE codes to human-readable categories.
"""

import os
import csv
import logging
import urllib.request

from db import upsert_organizations_batch

logger = logging.getLogger(__name__)

# NCCS BMF S3 URL — override via env var, default to latest known URL
NCCS_BMF_URL = os.getenv(
    'NCCS_BMF_URL',
    'https://nccsdata.s3.us-east-1.amazonaws.com/raw/bmf/2025-12-BMF.csv'
)

# NTEE major group mapping (first letter of NTEE code)
# NOTE: Keep in sync with web/src/lib/ntee.ts NTEE_MAP
NTEE_CODES = {
    'A': 'Arts, Culture & Humanities',
    'B': 'Education',
    'C': 'Environment',
    'D': 'Animal-Related',
    'E': 'Health Care',
    'F': 'Mental Health & Crisis Intervention',
    'G': 'Diseases, Disorders & Medical Disciplines',
    'H': 'Medical Research',
    'I': 'Crime & Legal-Related',
    'J': 'Employment',
    'K': 'Food, Agriculture & Nutrition',
    'L': 'Housing & Shelter',
    'M': 'Public Safety, Disaster Preparedness & Relief',
    'N': 'Recreation & Sports',
    'O': 'Youth Development',
    'P': 'Human Services',
    'Q': 'International, Foreign Affairs & National Security',
    'R': 'Civil Rights, Social Action & Advocacy',
    'S': 'Community Improvement & Capacity Building',
    'T': 'Philanthropy, Voluntarism & Grantmaking Foundations',
    'U': 'Science & Technology',
    'V': 'Social Science',
    'W': 'Public & Societal Benefit',
    'X': 'Religion-Related',
    'Y': 'Mutual & Membership Benefit',
    'Z': 'Unknown',
}


def get_ntee_category(ntee_code):
    """Map NTEE code to human-readable category."""
    if not ntee_code or len(ntee_code) < 1:
        return None
    return NTEE_CODES.get(ntee_code[0].upper(), 'Unknown')


def normalize_subsection(val):
    """Convert BMF SUBSECTION values like '3' or '501(c)(3)' to clean 501(c)(X)."""
    if not val:
        return None
    s = str(val).strip()
    if s.startswith('501(c)'):
        return s
    if s.isdigit():
        return f'501(c)({s})'
    return s


def load_bmf_csv(filepath, batch_size=1000):
    """
    Load NCCS BMF data from a local CSV file using batch inserts.
    Expected columns: EIN, NAME, STREET, CITY, STATE, ZIP, NTEE_CD, SUBSECTION,
    RULING_DATE, FOUNDATION, ORGANIZATION, DEDUCTIBILITY, ASSET_CD, INCOME_CD,
    FILING_REQ_CD, TAX_PERIOD
    """
    count = 0
    skipped = 0
    error_count = 0
    buffer = []

    with open(filepath, 'r', encoding='utf-8', errors='replace') as f:
        reader = csv.DictReader(f)
        for row in reader:
            ein = (row.get('EIN') or '').strip()
            if not ein or len(ein) < 9:
                skipped += 1
                continue

            # Pad EIN to 9 digits
            ein = ein.zfill(9)

            name = (row.get('NAME') or '').strip()
            if not name:
                skipped += 1
                continue

            city = (row.get('CITY') or '').strip()
            state = (row.get('STATE') or '').strip()
            zip_code = (row.get('ZIP') or '').strip()[:5]
            street = (row.get('STREET') or '').strip()
            ntee_code = (row.get('NTEE_CD') or '').strip()
            subsection = (row.get('SUBSECTION') or '').strip()
            ruling_date_raw = (row.get('RULING') or '').strip()
            deductibility = (row.get('DEDUCTIBILITY') or '').strip()

            ruling_date = None
            year_formed = None
            try:
                if ruling_date_raw and len(ruling_date_raw) == 6:
                    year = ruling_date_raw[:4]
                    month = ruling_date_raw[4:6]
                    if (year.isdigit() and month.isdigit()
                            and year != '0000' and month != '00'
                            and 1 <= int(month) <= 12
                            and int(year) > 1800):
                        ruling_date = f"{year}-{month}-01"
                        year_formed = int(year)
            except (ValueError, TypeError):
                pass

            ntee_category = get_ntee_category(ntee_code)

            # Build row dict for batch insert
            buffer.append({
                'ein': ein,
                'name': name,
                'city': city or None,
                'state': state or None,
                'zip_code': zip_code or None,
                'street': street or None,
                'ntee_code': ntee_code or None,
                'ntee_category': ntee_category,
                'subsection': normalize_subsection(subsection),
                'year_formed': year_formed,
                'ruling_date': ruling_date if ruling_date else None,
                'pub78_status': deductibility if deductibility else None,
                'tax_year': None,
                'form_type': None,
            })

            count += 1

            # Flush buffer when full
            if len(buffer) >= batch_size:
                try:
                    upsert_organizations_batch(buffer)
                except Exception as e:
                    logger.error(f"Error during batch upsert: {e}")
                    error_count += len(buffer)
                buffer = []

                # Progress logging every 50,000 rows
                if count % 50000 == 0:
                    logger.info(f"BMF progress: {count} loaded, {skipped} skipped, {error_count} errors")

    # Flush remaining rows
    if buffer:
        try:
            upsert_organizations_batch(buffer)
        except Exception as e:
            logger.error(f"Error during final batch upsert: {e}")
            error_count += len(buffer)

    logger.info(f"BMF load complete: {count} loaded, {skipped} skipped, {error_count} errors")
    return count, skipped


def download_bmf(output_dir):
    """Download NCCS BMF CSV from S3. Returns path to downloaded CSV."""
    os.makedirs(output_dir, exist_ok=True)
    csv_path = os.path.join(output_dir, 'bmf_extract.csv')

    urls_to_try = [
        NCCS_BMF_URL,
        NCCS_BMF_URL.replace('2025-12', '2025-11'),  # fallback: previous month
        NCCS_BMF_URL.replace('2025-12', '2025-10'),  # fallback: two months back
    ]

    for url in urls_to_try:
        logger.info(f"Downloading BMF from {url} ...")
        try:
            urllib.request.urlretrieve(url, csv_path)
            logger.info(f"BMF CSV saved to {csv_path}")
            return csv_path
        except Exception as e:
            logger.warning(f"Failed to download from {url}: {e}")
            continue

    raise RuntimeError("Could not download BMF from any URL")


if __name__ == '__main__':
    import sys
    logging.basicConfig(level=logging.INFO)

    if len(sys.argv) > 1:
        filepath = sys.argv[1]
    else:
        filepath = os.path.join(os.getenv('BMF_DIR', './data/bmf'), 'bmf_filtered.csv')

    if os.path.exists(filepath):
        load_bmf_csv(filepath)
    else:
        logger.info(f"BMF file not found: {filepath}")
        filepath = download_bmf(os.path.dirname(filepath))
        load_bmf_csv(filepath)
