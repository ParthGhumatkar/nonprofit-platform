"""
PostgreSQL database interface for the nonprofit data platform.
Handles connections, inserts, and queries for all pipeline operations.
"""

import os
import json
import logging
from contextlib import contextmanager

import psycopg2
import psycopg2.extras
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL environment variable is required")

logger = logging.getLogger(__name__)


@contextmanager
def get_conn():
    """Yield a database connection with autocommit off."""
    conn = psycopg2.connect(DATABASE_URL)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def upsert_organization(ein, name, city=None, state=None, zip_code=None,
                        street=None, ntee_code=None, ntee_category=None,
                        subsection=None, year_formed=None, ruling_date=None,
                        pub78_status=None, tax_year=None, form_type=None):
    """Insert or update an organization record."""
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO organizations (ein, canonical_name, city, state, zip, street,
                                       ntee_code, ntee_category, subsection,
                                       year_formed, ruling_date, pub78_status,
                                       tax_year_latest, form_type_latest)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (ein) DO UPDATE SET
                canonical_name  = COALESCE(EXCLUDED.canonical_name, organizations.canonical_name),
                city            = COALESCE(EXCLUDED.city, organizations.city),
                state           = COALESCE(EXCLUDED.state, organizations.state),
                zip             = COALESCE(EXCLUDED.zip, organizations.zip),
                street          = COALESCE(EXCLUDED.street, organizations.street),
                ntee_code       = COALESCE(EXCLUDED.ntee_code, organizations.ntee_code),
                ntee_category   = COALESCE(EXCLUDED.ntee_category, organizations.ntee_category),
                subsection      = COALESCE(EXCLUDED.subsection, organizations.subsection),
                year_formed     = COALESCE(EXCLUDED.year_formed, organizations.year_formed),
                ruling_date     = COALESCE(EXCLUDED.ruling_date, organizations.ruling_date),
                pub78_status    = COALESCE(EXCLUDED.pub78_status, organizations.pub78_status),
                tax_year_latest = GREATEST(COALESCE(organizations.tax_year_latest, 0),
                                           COALESCE(EXCLUDED.tax_year_latest, 0)),
                form_type_latest = COALESCE(EXCLUDED.form_type_latest, organizations.form_type_latest)
        """, (ein, name, city, state, zip_code, street,
              ntee_code, ntee_category, subsection,
              year_formed, ruling_date, pub78_status,
              tax_year, form_type))


def insert_filing(ein, object_id, tax_year, form_type, period_begin=None,
                  period_end=None, received_date=None, raw_xml=None, parsed_data=None):
    """Insert a filing record. Returns the filing id."""
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO filings (ein, object_id, tax_year, form_type,
                                 period_begin, period_end, received_date,
                                 raw_xml, parsed_data)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (object_id) DO UPDATE SET
                tax_year    = EXCLUDED.tax_year,
                form_type   = EXCLUDED.form_type,
                period_begin = EXCLUDED.period_begin,
                period_end  = EXCLUDED.period_end,
                received_date = EXCLUDED.received_date,
                raw_xml     = COALESCE(EXCLUDED.raw_xml, filings.raw_xml),
                parsed_data = COALESCE(EXCLUDED.parsed_data, filings.parsed_data)
            RETURNING id
        """, (ein, object_id, tax_year, form_type,
              period_begin, period_end, received_date,
              raw_xml, json.dumps(parsed_data) if parsed_data else None))
        return cur.fetchone()[0]


def insert_grants(filing_id, grants_list):
    """Bulk insert grants for a filing. Clears existing first."""
    if not grants_list:
        return
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("DELETE FROM grants WHERE filing_id = %s", (filing_id,))
        psycopg2.extras.execute_values(cur, """
            INSERT INTO grants (filing_id, grantee_name, grantee_ein, amount, purpose, city, state)
            VALUES %s
        """, [
            (filing_id,
             g.get('grantee'),
             g.get('ein'),
             _to_numeric(g.get('amount')),
             g.get('purpose'),
             g.get('city'),
             g.get('state'))
            for g in grants_list
        ])


def insert_compensation(filing_id, comp_list):
    """Bulk insert compensation rows. Clears existing first."""
    if not comp_list:
        return
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("DELETE FROM compensation WHERE filing_id = %s", (filing_id,))
        psycopg2.extras.execute_values(cur, """
            INSERT INTO compensation (filing_id, person_name, title,
                                      base_comp, bonus, other_comp, related_comp, total_comp)
            VALUES %s
        """, [
            (filing_id,
             c.get('name'),
             c.get('title'),
             _to_numeric(c.get('base')),
             _to_numeric(c.get('bonus')),
             _to_numeric(c.get('other')),
             _to_numeric(c.get('related')),
             _to_numeric(c.get('total')))
            for c in comp_list
        ])


def insert_programs(filing_id, programs_text):
    """Insert program accomplishments. Clears existing first."""
    if not programs_text:
        return
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("DELETE FROM program_accomplishments WHERE filing_id = %s", (filing_id,))
        # Split on double newlines to separate programs
        parts = [p.strip() for p in programs_text.split('\n\n') if p.strip()]
        psycopg2.extras.execute_values(cur, """
            INSERT INTO program_accomplishments (filing_id, description)
            VALUES %s
        """, [(filing_id, p) for p in parts])


def insert_mission(filing_id, mission_text):
    """Insert mission statement. Clears existing first."""
    if not mission_text:
        return
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("DELETE FROM mission_statements WHERE filing_id = %s", (filing_id,))
        cur.execute("""
            INSERT INTO mission_statements (filing_id, mission_text)
            VALUES (%s, %s)
        """, (filing_id, mission_text))


def filing_exists(object_id):
    """Check if a filing already exists in the database."""
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("SELECT 1 FROM filings WHERE object_id = %s", (object_id,))
        return cur.fetchone() is not None


def get_all_eins():
    """Return list of all EINs in the database."""
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("SELECT ein FROM organizations ORDER BY ein")
        return [r[0] for r in cur.fetchall()]


def get_organization(ein):
    """Get full organization record."""
    with get_conn() as conn:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute("SELECT * FROM organizations WHERE ein = %s", (ein,))
        return cur.fetchone()


def get_filings_for_ein(ein):
    """Get all filings for an organization, newest first."""
    with get_conn() as conn:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute("""
            SELECT * FROM filings
            WHERE ein = %s
            ORDER BY tax_year DESC
        """, (ein,))
        return cur.fetchall()


def get_grants_for_filing(filing_id):
    """Get all grants for a filing."""
    with get_conn() as conn:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute("SELECT * FROM grants WHERE filing_id = %s ORDER BY amount DESC", (filing_id,))
        return cur.fetchall()


def get_compensation_for_filing(filing_id):
    """Get all compensation rows for a filing."""
    with get_conn() as conn:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute("SELECT * FROM compensation WHERE filing_id = %s ORDER BY total_comp DESC NULLS LAST", (filing_id,))
        return cur.fetchall()


def get_organizations_by_state(state):
    """Get organizations in a state."""
    with get_conn() as conn:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute("""
            SELECT * FROM organizations
            WHERE state = %s
            ORDER BY canonical_name
        """, (state.upper(),))
        return cur.fetchall()


def get_organizations_by_city(city, state=None):
    """Get organizations in a city, optionally filtered by state."""
    with get_conn() as conn:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        if state:
            cur.execute("""
                SELECT * FROM organizations
                WHERE city ILIKE %s AND state = %s
                ORDER BY canonical_name
            """, (city, state.upper()))
        else:
            cur.execute("""
                SELECT * FROM organizations
                WHERE city ILIKE %s
                ORDER BY canonical_name
            """, (city,))
        return cur.fetchall()


def get_organizations_by_ntee(ntee_code):
    """Get organizations by NTEE code (prefix match)."""
    with get_conn() as conn:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute("""
            SELECT * FROM organizations
            WHERE ntee_code LIKE %s
            ORDER BY canonical_name
        """, (ntee_code + '%',))
        return cur.fetchall()


def search_organizations(query, limit=50):
    """Search organizations by name or EIN."""
    with get_conn() as conn:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        # Try exact EIN match first
        clean_ein = query.replace('-', '').strip()
        if clean_ein.isdigit() and len(clean_ein) == 9:
            cur.execute("""
                SELECT * FROM organizations WHERE ein = %s
            """, (clean_ein,))
            result = cur.fetchone()
            if result:
                return [result]

        # Fuzzy name search
        cur.execute("""
            SELECT * FROM organizations
            WHERE lower(canonical_name) LIKE %s
            ORDER BY canonical_name
            LIMIT %s
        """, (f'%{query.lower()}%', limit))
        return cur.fetchall()


def backfill_org_metadata():
    """Derive missing org metadata from the most recent filing for each org.
    Used when BMF data is unavailable to fill in subsection and other fields."""
    with get_conn() as conn:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        # Find orgs with missing subsection that have filings
        cur.execute("""
            SELECT o.ein, f.form_type, f.parsed_data
            FROM organizations o
            JOIN LATERAL (
                SELECT * FROM filings
                WHERE ein = o.ein
                ORDER BY tax_year DESC
                LIMIT 1
            ) f ON true
            WHERE o.subsection IS NULL
        """)
        rows = cur.fetchall()
        updated = 0
        for row in rows:
            ein = row['ein']
            form_type = row['form_type']
            parsed = row['parsed_data'] or {}
            subsection = None
            if form_type == '990PF':
                subsection = '501(c)(3)'
            elif parsed.get('mission') and 'private foundation' in str(parsed.get('mission', '')).lower():
                subsection = '501(c)(3)'
            if subsection:
                cur.execute(
                    "UPDATE organizations SET subsection = %s WHERE ein = %s",
                    (subsection, ein)
                )
                updated += 1
        conn.commit()
        logger.info(f"Backfilled subsection for {updated} organizations")
        return updated


def backfill_bmf_fields(bmf_rows):
    """Backfill organizations table with BMF-specific fields after CSV is loaded.
    bmf_rows: list of dicts with keys: ein, ntee_code, ntee_category, ruling_date,
              year_formed, pub78_status, city, state, zip_code, street"""
    with get_conn() as conn:
        cur = conn.cursor()
        updated = 0
        for row in bmf_rows:
            ein = row.get('ein')
            if not ein:
                continue
            fields = []
            values = []
            for col in ('ntee_code', 'ntee_category', 'ruling_date', 'year_formed',
                        'pub78_status', 'city', 'state', 'zip', 'street', 'subsection'):
                if col in row and row[col] is not None:
                    fields.append(f"{col} = %s")
                    values.append(row[col])
            if not fields:
                continue
            values.append(ein)
            sql = f"UPDATE organizations SET {', '.join(fields)} WHERE ein = %s"
            try:
                cur.execute(sql, values)
                if cur.rowcount:
                    updated += 1
            except Exception as e:
                logger.error(f"Error backfilling {ein}: {e}")
        conn.commit()
        logger.info(f"Backfilled BMF fields for {updated} organizations")
        return updated


def get_stats():
    """Get platform-wide statistics."""
    with get_conn() as conn:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute("SELECT count(*) as org_count FROM organizations")
        org_count = cur.fetchone()['org_count']
        cur.execute("SELECT count(*) as filing_count FROM filings")
        filing_count = cur.fetchone()['filing_count']
        cur.execute("SELECT count(DISTINCT ein) as ein_count FROM filings")
        ein_count = cur.fetchone()['ein_count']
        return {
            'organizations': org_count,
            'filings': filing_count,
            'organizations_with_filings': ein_count,
        }


def _to_numeric(val):
    """Convert a string value to numeric, returning None if invalid."""
    if val is None:
        return None
    try:
        return float(str(val).replace(',', ''))
    except (ValueError, TypeError):
        return None
