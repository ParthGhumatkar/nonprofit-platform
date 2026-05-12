CREATE EXTENSION IF NOT EXISTS pg_trgm;

-- ============================================================
-- Nonprofit Data Platform â€” Database Schema
-- ============================================================

-- Organizations (one row per EIN, canonical from BMF + latest filing)
CREATE TABLE organizations (
    ein             TEXT PRIMARY KEY,
    canonical_name  TEXT NOT NULL,
    city            TEXT,
    state           TEXT,
    zip             TEXT,
    street          TEXT,
    ntee_code       TEXT,
    ntee_category   TEXT,
    subsection      TEXT,
    year_formed     INTEGER,
    ruling_date     DATE,
    pub78_status    TEXT,
    tax_year_latest INTEGER,
    form_type_latest TEXT,
    created_at      TIMESTAMPTZ DEFAULT now(),
    updated_at      TIMESTAMPTZ DEFAULT now()
);

-- Name variations (tracked for Phase 2 entity resolution)
CREATE TABLE organization_names (
    id      SERIAL PRIMARY KEY,
    ein     TEXT REFERENCES organizations(ein),
    name    TEXT NOT NULL,
    source  TEXT,  -- 'filing' or 'bmf'
    tax_year INTEGER,
    UNIQUE(ein, name, tax_year)
);

-- Filings (one row per tax return)
CREATE TABLE filings (
    id              SERIAL PRIMARY KEY,
    ein             TEXT REFERENCES organizations(ein),
    object_id       TEXT UNIQUE NOT NULL,
    tax_year        INTEGER NOT NULL,
    period_begin    DATE,
    period_end      DATE,
    form_type       TEXT NOT NULL,  -- 990, 990EZ, 990PF
    received_date   DATE,
    raw_xml         TEXT,           -- Full XML stored as text
    parsed_data     JSONB,          -- Full parsed 990 main form
    created_at      TIMESTAMPTZ DEFAULT now()
);

-- Grants made (Schedule I for 990, GrantOrContributionPdDurYrGrp for 990PF)
CREATE TABLE grants (
    id              SERIAL PRIMARY KEY,
    filing_id       INTEGER REFERENCES filings(id) ON DELETE CASCADE,
    grantee_name    TEXT,
    grantee_ein     TEXT,
    amount          NUMERIC,
    purpose         TEXT,
    city            TEXT,
    state           TEXT
);

-- Compensation (Schedule J / Part VII / 990PF officers)
CREATE TABLE compensation (
    id              SERIAL PRIMARY KEY,
    filing_id       INTEGER REFERENCES filings(id) ON DELETE CASCADE,
    person_name     TEXT NOT NULL,
    title           TEXT,
    base_comp       NUMERIC,
    bonus           NUMERIC,
    other_comp      NUMERIC,
    related_comp    NUMERIC,
    total_comp      NUMERIC
);

-- Program accomplishments (Schedule O / Part III)
CREATE TABLE program_accomplishments (
    id              SERIAL PRIMARY KEY,
    filing_id       INTEGER REFERENCES filings(id) ON DELETE CASCADE,
    description     TEXT NOT NULL
);

-- Mission statements (per filing)
CREATE TABLE mission_statements (
    id              SERIAL PRIMARY KEY,
    filing_id       INTEGER REFERENCES filings(id) ON DELETE CASCADE,
    mission_text    TEXT NOT NULL
);

-- ============================================================
-- INDEXES
-- ============================================================

CREATE INDEX idx_filings_ein_year    ON filings(ein, tax_year DESC);
CREATE INDEX idx_filings_form_type   ON filings(form_type);
CREATE INDEX idx_filings_period_end  ON filings(period_end DESC);
CREATE INDEX idx_grants_filing       ON grants(filing_id);
CREATE INDEX idx_grants_amount       ON grants(amount DESC);
CREATE INDEX idx_comp_filing         ON compensation(filing_id);
CREATE INDEX idx_orgs_state          ON organizations(state);
CREATE INDEX idx_orgs_city           ON organizations(city);
CREATE INDEX idx_orgs_ntee           ON organizations(ntee_code);
CREATE INDEX idx_orgs_name_trgm      ON organizations USING gin (canonical_name gin_trgm_ops);
CREATE INDEX idx_orgs_name_lower     ON organizations (lower(canonical_name));

-- ============================================================
-- HELPER: auto-update updated_at
-- ============================================================

CREATE OR REPLACE FUNCTION update_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = now();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_organizations_updated_at
    BEFORE UPDATE ON organizations
    FOR EACH ROW EXECUTE FUNCTION update_updated_at();

