import psycopg2
import os

neon = psycopg2.connect(os.environ["NEON_URL"])
neon.autocommit = True
cur = neon.cursor()

cur.execute("""
CREATE OR REPLACE FUNCTION update_updated_at()
RETURNS TRIGGER AS $func$
BEGIN
    NEW.updated_at = now();
    RETURN NEW;
END;
$func$ LANGUAGE plpgsql;
""")
print("Function created!")

cur.execute("""
CREATE OR REPLACE TRIGGER update_organizations_updated_at
    BEFORE UPDATE ON organizations
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at();
""")
print("Trigger created!")

cur.execute("""
CREATE INDEX IF NOT EXISTS idx_orgs_name_trgm 
    ON organizations USING gin (canonical_name gin_trgm_ops);
""")
print("Index created!")

cur.execute("""
SELECT table_name FROM information_schema.tables 
WHERE table_schema = 'public'
ORDER BY table_name;
""")
tables = [r[0] for r in cur.fetchall()]
print("Tables:", tables)
neon.close()
