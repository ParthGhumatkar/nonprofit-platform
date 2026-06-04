# -*- coding: utf-8 -*-
import psycopg2
import psycopg2.extras
import json
import os

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

def copy_table(local_cur, table, where_clause, params, columns):
    col_list = ", ".join(columns)
    local_cur.execute(f"SELECT {col_list} FROM {table} WHERE {where_clause}", params)
    rows = local_cur.fetchall()
    if not rows:
        print(f"  {table}: 0 rows")
        return
    neon = psycopg2.connect(NEON_URL)
    nc = neon.cursor()
    insert_cols = ", ".join(columns)
    clean = [tuple(serialize(v) for v in row) for row in rows]
    for i in range(0, len(clean), 50):
        psycopg2.extras.execute_values(
            nc,
            f"INSERT INTO {table} ({insert_cols}) VALUES %s ON CONFLICT DO NOTHING",
            clean[i:i+50], page_size=50
        )
        neon.commit()
    nc.close()
    neon.close()
    print(f"  {table}: {len(rows)} rows copied")

local = psycopg2.connect(LOCAL_URL)
lc = local.cursor()

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

lc.execute("SELECT id FROM filings WHERE ein = ANY(%s)", (all_eins,))
filing_ids = [r[0] for r in lc.fetchall()]

comp_cols = get_columns(lc, "compensation")
mission_cols = get_columns(lc, "mission_statements")
program_cols = get_columns(lc, "program_accomplishments")

print("Copying compensation...")
copy_table(lc, "compensation", "filing_id = ANY(%s)", (filing_ids,), comp_cols)
print("Copying missions...")
copy_table(lc, "mission_statements", "filing_id = ANY(%s)", (filing_ids,), mission_cols)
print("Copying programs...")
copy_table(lc, "program_accomplishments", "filing_id = ANY(%s)", (filing_ids,), program_cols)

neon = psycopg2.connect(NEON_URL)
nc = neon.cursor()
for table in ["organizations","filings","grants","compensation","mission_statements","program_accomplishments"]:
    nc.execute(f"SELECT count(*) FROM {table}")
    print(f"Neon {table}: {nc.fetchone()[0]}")
neon.close()
local.close()
print("Done!")
