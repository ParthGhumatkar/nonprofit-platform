import psycopg2, os
neon = psycopg2.connect(os.environ["NEON_URL"])
nc = neon.cursor()
nc.execute("""
SELECT column_name, ordinal_position
FROM information_schema.columns
WHERE table_name = 'filings'
ORDER BY ordinal_position
""")
for r in nc.fetchall():
    print(r)
neon.close()
