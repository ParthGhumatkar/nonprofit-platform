-- ============================================================
-- Nonprofit Data Platform — Annotated Database Schema
-- Source: db/schema.sql (do not edit schema.sql directly;
--         add changes here too so annotations stay in sync)
-- ============================================================

-- pg_trgm enables the GIN trigram index on canonical_name used for
-- fuzzy search. Must be created before any trigram index is applied.
CREATE EXTENSION IF NOT EXISTS pg_trgm;

-- ============================================================
-- TABLE: organizations
-- One row per unique EIN (Employer Identification Number).
-- Populated in two ways:
--   1. BMF load (bmf_loader.py): provides NTEE code, ruling date,
--      subsection, deductibility, and base address from the NCCS
--      Business Master File CSV.
--   2. Filing parse (parse_irsx.py via db.upsert_organization):
--      updates address and subsection from each 990 XML header.
-- The UPSERT strategy keeps the most recently seen non-null value
-- for most fields, and the GREATEST tax year for tax_year_latest.
-- ============================================================
CREATE TABLE organizations (
    -- IRS Employer Identification Number. 9 characters, zero-padded
    -- (e.g. '042103547'). Primary key across the entire platform.
    -- Source: BMF column EIN (zfill(9)) or 990 XML f.get_ein().
    -- Never strip leading zeros — many older nonprofits have EINs
    -- starting with 0.
    ein             TEXT PRIMARY KEY,

    -- The display name used on all frontend pages and in search.
    -- Source: BMF column NAME, or BusinessName from the 990 XML header.
    -- The UPSERT uses COALESCE, so the first non-null name wins unless
    -- explicitly overwritten. NOT NULL — every org must have a name.
    canonical_name  TEXT NOT NULL,

    -- Mailing city from the most recent address seen.
    -- Source: BMF CITY column, or USAddress.CityNm from 990 XML.
    -- Used by /state and /city directory pages and search filters.
    city            TEXT,

    -- 2-letter U.S. state abbreviation (e.g. 'CA', 'NY').
    -- Source: BMF STATE column, or USAddress.StateAbbreviationCd.
    -- Indexed — see idx_orgs_state below.
    state           TEXT,

    -- 5-digit ZIP code (truncated from full ZIP+4 in bmf_loader.py).
    -- Source: BMF ZIP column ([:5]), or USAddress.ZIPCd from 990 XML.
    zip             TEXT,

    -- Street address line 1.
    -- Source: BMF STREET column, or USAddress.AddressLine1Txt.
    street          TEXT,

    -- NTEE (National Taxonomy of Exempt Entities) code, e.g. 'B20'.
    -- First letter is the major group (26 groups, A–Z).
    -- Source: BMF NTEE_CD column. NOT populated from 990 XML —
    -- only the BMF load sets this field.
    -- Indexed — see idx_orgs_ntee below.
    -- TODO: many orgs parsed from XMLs before BMF is loaded will have
    --       ntee_code = NULL until bmf_loader.py runs.
    ntee_code       TEXT,

    -- Human-readable label for the first letter of ntee_code.
    -- Derived in bmf_loader.get_ntee_category() and ntee.ts getNteeCategory().
    -- Example: 'B' → 'Education'.
    -- Must be kept in sync with NTEE_CODES in bmf_loader.py and
    -- NTEE_MAP in web/src/lib/ntee.ts.
    ntee_category   TEXT,

    -- IRS 501(c) exemption type, e.g. '501(c)(3)', '501(c)(4)'.
    -- Source: BMF SUBSECTION column (normalised by normalize_subsection()
    -- in bmf_loader.py), or derived from the 990 XML schedule flags in
    -- parse_irsx.derive_subsection().
    -- Used for the "Charitable Organization" label on org pages.
    subsection      TEXT,

    -- Year the organisation was formed / first received IRS recognition.
    -- Derived from the first 4 digits of the BMF RULING_DATE column.
    -- Source: BMF only. Not extracted from 990 XML.
    year_formed     INTEGER,

    -- Date the IRS granted tax-exempt ruling, e.g. '1990-06-01'.
    -- Stored as DATE. Source: BMF RULING_DATE column (converted from
    -- YYYYMM to YYYY-MM-DD in bmf_loader.py).
    ruling_date     DATE,

    -- IRS Publication 78 deductibility code.
    -- Values are typically '1' (deductible) or blank.
    -- Source: BMF DEDUCTIBILITY column.
    pub78_status    TEXT,

    -- Tax year of the most recent filing ingested for this org.
    -- Updated via GREATEST() in the UPSERT so it only moves forward.
    -- Source: TaxYr field from 990 XML header.
    tax_year_latest INTEGER,

    -- Form type of the most recent filing: '990', '990EZ', or '990PF'.
    -- Source: determined by parse_irsx.parse_file() based on which
    -- schedule is present (IRS990 vs IRS990PF).
    form_type_latest TEXT,

    -- Timestamp set on INSERT. Never changed after initial creation.
    created_at      TIMESTAMPTZ DEFAULT now(),

    -- Timestamp updated automatically by the trigger below whenever any
    -- column changes. Used by sitemap.xml.js for <lastmod> tags.
    updated_at      TIMESTAMPTZ DEFAULT now()
);

-- ============================================================
-- TABLE: organization_names
-- Historical name variants for an EIN, tracked for future
-- entity resolution (Phase 2). Not populated by any current
-- pipeline code — this table is empty in Phase 1.
-- The UNIQUE(ein, name, tax_year) constraint prevents duplicates
-- if the same name appears in multiple filings of the same year.
-- ============================================================
CREATE TABLE organization_names (
    id      SERIAL PRIMARY KEY,

    -- Foreign key to organizations. Cascades are not set — orphaned
    -- rows would remain if an org is deleted.
    ein     TEXT REFERENCES organizations(ein),

    -- Name variant as it appeared in the source.
    name    TEXT NOT NULL,

    -- Which source the name came from: 'filing' or 'bmf'.
    source  TEXT,

    -- Tax year the name was observed in.
    tax_year INTEGER,

    -- Prevent duplicate (ein, name, year) combinations.
    UNIQUE(ein, name, tax_year)
);

-- ============================================================
-- TABLE: filings
-- One row per IRS e-filed tax return (identified by object_id).
-- The object_id is the IRS-assigned unique identifier for each
-- electronically filed return (e.g. '202312349012345678').
-- ============================================================
CREATE TABLE filings (
    id              SERIAL PRIMARY KEY,

    -- Foreign key to organizations.
    ein             TEXT REFERENCES organizations(ein),

    -- IRS-assigned unique identifier for this e-filing.
    -- Corresponds to the XML filename without extension.
    -- UNIQUE constraint: if the same object_id is parsed again,
    -- the INSERT ... ON CONFLICT updates the existing row.
    object_id       TEXT UNIQUE NOT NULL,

    -- Calendar year the tax period ended in (e.g. 2023).
    -- Source: TaxYr field from ReturnHeader990x schedule.
    tax_year        INTEGER NOT NULL,

    -- Start of the org's tax period (e.g. '2023-01-01').
    -- Source: TaxPeriodBeginDt from ReturnHeader990x.
    period_begin    DATE,

    -- End of the org's tax period (e.g. '2023-12-31').
    -- Source: TaxPeriodEndDt from ReturnHeader990x.
    period_end      DATE,

    -- Form type: '990', '990EZ', or '990PF'.
    -- 990EZ is parsed via the IRS990 schedule path (same as 990).
    -- 990-N (postcard) filings are skipped (file size < 20 KB).
    form_type       TEXT NOT NULL,

    -- Date the return was received/built by the IRS e-file system.
    -- Source: ReturnTs or BuildTs from ReturnHeader990x.
    received_date   DATE,

    -- Full XML text of the filing stored inline.
    -- WARNING: at scale (~125K filings × ~180 KB avg) this column
    -- will reach ~22 GB. Plan to externalize to S3 before scaling
    -- beyond Phase 1.
    raw_xml         TEXT,

    -- Parsed financial and narrative fields stored as a JSONB blob.
    -- Keys include: total_revenue, total_expenses, total_assets,
    -- total_liabilities, net_assets, contributions, prog_revenue,
    -- invest_income, other_revenue, grants_paid, salaries,
    -- fundraising_fees, net_income, mission, program_accomplishments,
    -- daf_activity.
    -- Values are stored as strings (from safe_str()) — cast to
    -- numeric in TypeScript/Python before arithmetic.
    parsed_data     JSONB,

    created_at      TIMESTAMPTZ DEFAULT now()
);

-- ============================================================
-- TABLE: grants
-- Each row is one grant made to a recipient in a given filing.
-- Source: Schedule I (990 and 990EZ) or GrantOrContributionPdDurYrGrp
-- (990PF). Populated by parse_irsx.insert_grants().
-- On re-parse, existing grants for the filing are deleted first
-- (DELETE WHERE filing_id = X) then re-inserted.
-- ============================================================
CREATE TABLE grants (
    id              SERIAL PRIMARY KEY,

    -- Foreign key to filings. ON DELETE CASCADE: if a filing is
    -- deleted, its grants are removed automatically.
    filing_id       INTEGER REFERENCES filings(id) ON DELETE CASCADE,

    -- Recipient organisation name.
    -- Source: RecipientBusinessName (Schedule I) or
    --         RecipientBusinessName (990PF grant group).
    grantee_name    TEXT,

    -- Recipient EIN if reported.
    -- Source: RecipientEIN from Schedule I.
    -- NOTE: There is no index on grantee_ein — a search for
    -- "which filings made grants to EIN X" will do a full scan.
    -- TODO: add idx_grants_grantee_ein if this query is needed.
    grantee_ein     TEXT,

    -- Cash grant amount in dollars.
    -- Source: CashGrantAmt (Schedule I) or Amt (990PF).
    amount          NUMERIC,

    -- Purpose statement for the grant.
    -- Source: PurposeOfGrantTxt (Schedule I) or
    --         GrantOrContributionPurposeTxt (990PF).
    purpose         TEXT,

    -- City of the grantee (990 Schedule I only; NULL for 990PF grants).
    city            TEXT,

    -- State of the grantee (990 Schedule I only; NULL for 990PF grants).
    state           TEXT
);

-- ============================================================
-- TABLE: compensation
-- Each row is one officer/director/key-employee compensation record
-- for a given filing. Populated by parse_irsx.insert_compensation().
-- On re-parse, existing compensation rows for the filing are deleted
-- first then re-inserted.
-- ============================================================
CREATE TABLE compensation (
    id              SERIAL PRIMARY KEY,

    -- Foreign key to filings. ON DELETE CASCADE.
    filing_id       INTEGER REFERENCES filings(id) ON DELETE CASCADE,

    -- Person name.
    -- Tried first as PersonNm, fallback to BusinessName (for entities
    -- listed as officers, e.g. a management company).
    -- Source: parse_irsx.extract_name().
    person_name     TEXT NOT NULL,

    -- Title or role, e.g. 'Executive Director', 'President'.
    -- Source: TitleTxt from Schedule J or Part VII.
    title           TEXT,

    -- Base salary from the filing organisation.
    -- Source: BaseCompensationFilingOrgAmt (Schedule J) or
    --         ReportableCompFromOrgAmt (Part VII fallback).
    base_comp       NUMERIC,

    -- Bonus and incentive compensation.
    -- Source: BonusFilingOrganizationAmount (Schedule J).
    -- NULL when compensation comes from Part VII fallback (no bonus field).
    bonus           NUMERIC,

    -- Other non-base, non-bonus compensation.
    -- Source: OtherCompensationFilingOrgAmt (Schedule J).
    other_comp      NUMERIC,

    -- Compensation from related organisations.
    -- Source: RelatedOrganizationCompAmt (Schedule J).
    related_comp    NUMERIC,

    -- Total compensation (base + bonus + other + related).
    -- Calculated in Python in parse_irsx; stored as a string-cast integer.
    total_comp      NUMERIC
);

-- ============================================================
-- TABLE: program_accomplishments
-- Narrative descriptions of what the organisation did in a year.
-- Split on double newlines — one row per paragraph.
-- Source: ProgramServiceAccomplishmentGrp (Part III) for 990/990EZ,
--         or Schedule O supplemental information where the reference
--         line matches 'part iii' or 'program service'.
-- 990PF filings do not populate this table (program_accomplishments = NULL).
-- ============================================================
CREATE TABLE program_accomplishments (
    id              SERIAL PRIMARY KEY,

    -- Foreign key to filings. ON DELETE CASCADE.
    filing_id       INTEGER REFERENCES filings(id) ON DELETE CASCADE,

    -- One paragraph of program narrative. NOT NULL by schema — but
    -- insert_programs() only inserts when programs_text is non-empty.
    description     TEXT NOT NULL
);

-- ============================================================
-- TABLE: mission_statements
-- The organisation's primary mission statement for a given filing.
-- One row per filing (insert_mission() deletes then inserts).
-- Source: MissionDesc (Part I line 1) for 990/990EZ.
--         If MissionDesc says "SCHEDULE O", the text is extracted
--         from Schedule O supplemental entries where the reference
--         line matches 'mission' or 'part i'.
--         For 990PF: MissionDscriptionOrSignificantActyTxt, with a
--         fallback default string for foundations without a stated mission.
-- ============================================================
CREATE TABLE mission_statements (
    id              SERIAL PRIMARY KEY,

    -- Foreign key to filings. ON DELETE CASCADE.
    filing_id       INTEGER REFERENCES filings(id) ON DELETE CASCADE,

    -- Full mission statement text.
    mission_text    TEXT NOT NULL
);

-- ============================================================
-- INDEXES
-- ============================================================

-- Covers the most common query pattern: "give me all filings for
-- EIN X, newest first" (used in web/src/lib/db.ts getFilings() and
-- pipeline/db.py get_filings_for_ein()).
CREATE INDEX idx_filings_ein_year    ON filings(ein, tax_year DESC);

-- Allows filtering by form type (990 / 990EZ / 990PF) without a
-- full scan. Useful for pipeline reporting queries.
CREATE INDEX idx_filings_form_type   ON filings(form_type);

-- Supports date-range queries on period_end (e.g. "filings from 2023").
CREATE INDEX idx_filings_period_end  ON filings(period_end DESC);

-- Covers "get all grants for a filing" — the primary lookup in
-- web/src/lib/db.ts getGrants() and GrantsTable.astro.
CREATE INDEX idx_grants_filing       ON grants(filing_id);

-- Allows sorting grants by amount descending efficiently.
-- Used in getGrants() ORDER BY amount DESC NULLS LAST.
CREATE INDEX idx_grants_amount       ON grants(amount DESC);

-- Covers "get all compensation rows for a filing" — the primary
-- lookup in getCompensation() and CompensationTable.astro.
CREATE INDEX idx_comp_filing         ON compensation(filing_id);

-- Supports getOrganizationsByState() and /state/[state] pages.
CREATE INDEX idx_orgs_state          ON organizations(state);

-- Supports getOrganizationsByCity() and /city/[city] pages.
CREATE INDEX idx_orgs_city           ON organizations(city);

-- Supports getOrganizationsByNtee() and /category/[ntee] pages.
CREATE INDEX idx_orgs_ntee           ON organizations(ntee_code);

-- GIN trigram index on canonical_name enables fast fuzzy search
-- using pg_trgm operators (similarity, <%>). The searchOrganizations()
-- function currently uses ILIKE '%query%' which does NOT use this index
-- because of the leading wildcard. TODO: rewrite to use similarity()
-- or word_similarity() so this index is actually used.
CREATE INDEX idx_orgs_name_trgm      ON organizations USING gin (canonical_name gin_trgm_ops);

-- B-tree index on lower(canonical_name) for case-insensitive exact or
-- prefix searches (e.g. WHERE lower(canonical_name) LIKE 'red cross%').
-- Complements the trigram index for different query patterns.
CREATE INDEX idx_orgs_name_lower     ON organizations (lower(canonical_name));

-- ============================================================
-- HELPER: auto-update updated_at
-- Fires BEFORE UPDATE on the organizations table. Sets updated_at
-- to now() so the sitemap.xml.js <lastmod> field is always accurate.
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
