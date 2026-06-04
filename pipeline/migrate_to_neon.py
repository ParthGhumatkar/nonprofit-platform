# -*- coding: utf-8 -*-
import psycopg2
import psycopg2.extras
import json
import os
from datetime import date, datetime

LOCAL_URL = "postgresql://nonprofit:devpassword@localhost:5433/nonprofit_platform"
NEON_URL = os.environ["NEON_URL"]

PINNED = [
    "232657933","042103580","620646012","530196605",
    "363673599","237327031","042105820","956032310",
    "237431709","131635294"
]

def serialize(val):
    if isinstance(val, (dict, list)):
        return json.dumps(val)
    return val

def get_columns(cur, table):
    cur.execute("""
        SELECT column_name FROM information_schema.columns
        WHERE table_name = %s ORDER BY ordinal_position
    """, (table,))
    return [r[0] for r in cur.fetchall()]

def copy_table(local_cur, table, where_clause, params, columns, transform=None):
    """Copy rows from local to neon using explicit column names."""
    col_list = ", ".join(columns)
    local_cur.execute(f"SELECT {col_list} FROM {table} WHERE {where_clause}", params)
    rows = local_cur.fetchall()
    if not rows:
        print(f"  {table}: 0 rows")
        return
    if transform:
        rows = [transform(list(r)) for r in rows]

    neon = psycopg2.connect(NEON_URL)
    nc = neon.cursor()
    placeholders = ", ".join(["%s"] * len(columns))
    insert_cols = ", ".join(columns)
    clean = [tuple(serialize(v) for v in row) for row in rows]
    for i in range(0, len(clean), 50):
        chunk = clean[i:i+50]
        psycopg2.extras.execute_values(
            nc,
            f"INSERT INTO {table} ({insert_cols}) VALUES %s ON CONFLICT DO NOTHING",
            chunk,
            page_size=50
        )
        neon.commit()
    nc.close()
    neon.close()
    print(f"  {table}: {len(rows)} rows copied")

local = psycopg2.connect(LOCAL_URL)
lc = local.cursor()

# Select 100 EINs
lc.execute("""
    SELECT ein FROM (
        SELECT DISTINCT o.ein,
            (SELECT (f2.parsed_data->>'total_revenue')::numeric
             FROM filings f2 WHERE f2.ein = o.ein
             ORDER BY f2.tax_year DESC LIMIT 1) as rev
        FROM organizations o
        WHERE o.ein != ALL(%s)
        AND EXISTS (SELECT 1 FROM filings f WHERE f.ein = o.ein)
    ) t ORDER BY rev DESC NULLS LAST LIMIT 90
""", (PINNED,))
all_eins = PINNED + [r[0] for r in lc.fetchall()]
print(f"Selected {len(all_eins)} orgs")

# Get column lists (excluding raw_xml for filings)
org_cols = get_columns(lc, "organizations")
filing_cols = [c for c in get_columns(lc, "filings") if c != "raw_xml"]
grant_cols = get_columns(lc, "grants")
comp_cols = get_columns(lc, "compensation")
mission_cols = get_columns(lc, "mission_statements")
program_cols = get_columns(lc, "program_accomplishments")

# Date fixer for filings
def fix_filing_dates(row):
    # find date column positions
    for i, col in enumerate(filing_cols):
        if col in ("period_begin", "period_end", "received_date"):
            v = row[i]
            if v is not None and not isinstance(v, date):
                try:
                    row[i] = datetime.strptime(str(v), "%Y-%m-%d").date()
                except:
                    row[i] = None
    return row

# Copy organizations
print("Copying organizations...")
copy_table(lc, "organizations", "ein = ANY(%s)", (all_eins,), org_cols)

# Copy filings (no raw_xml, safe dates)
print("Copying filings...")
copy_table(lc, "filings", "ein = ANY(%s)", (all_eins,), filing_cols, fix_filing_dates)

# Get filing IDs
lc.execute("SELECT id FROM filings WHERE ein = ANY(%s)", (all_eins,))
filing_ids = [r[0] for r in lc.fetchall()]

# Copy grants (top 500 per filing, no negatives) — special query
print("Copying grants...")
grant_col_list = ", ".join(grant_cols)
lc.execute(f"""
    SELECT {grant_col_list} FROM (
        SELECT *, ROW_NUMBER() OVER (
            PARTITION BY filing_id ORDER BY amount DESC NULLS LAST
        ) as rn
        FROM grants WHERE filing_id = ANY(%s) AND amount >= 0
    ) ranked WHERE rn <= 500
""", (filing_ids,))
grant_rows = lc.fetchall()
if grant_rows:
    neon = psycopg2.connect(NEON_URL)
    nc = neon.cursor()
    clean = [tuple(serialize(v) for v in row) for row in grant_rows]
    insert_cols = ", ".join(grant_cols)
    for i in range(0, len(clean), 50):
        psycopg2.extras.execute_values(
            nc,
            f"INSERT INTO grants ({insert_cols}) VALUES %s ON CONFLICT DO NOTHING",
            clean[i:i+50], page_size=50
        )
        neon.commit()
    nc.close()
    neon.close()
print(f"  grants: {len(grant_rows)} rows copied")

# Copy compensation, missions, programs
print("Copying compensation...")
copy_table(lc, "compensation", "filing_id = ANY(%s)", (filing_ids,), comp_cols)
print("Copying missions...")
copy_table(lc, "mission_statements", "filing_id = ANY(%s)", (filing_ids,), mission_cols)
print("Copying programs...")
copy_table(lc, "program_accomplishments", "filing_id = ANY(%s)", (filing_ids,), program_cols)

# Summary
neon = psycopg2.connect(NEON_URL)
nc = neon.cursor()
for table in ["organizations","filings","grants","compensation","mission_statements","program_accomplishments"]:
    nc.execute(f"SELECT count(*) FROM {table}")
    print(f"Neon {table}: {nc.fetchone()[0]}")
neon.close()
local.close()
print("Migration complete!")