import pg from 'pg'; 
 
const { Pool } = pg; 
 
const dbUrl = import.meta.env.DATABASE_URL;
if (!dbUrl) {
  throw new Error('DATABASE_URL environment variable is required');
}
const pool = new Pool({ connectionString: dbUrl }); 
 
export interface Organization { 
  ein: string; 
  canonical_name: string; 
  city: string | null; 
  state: string | null; 
  zip: string | null; 
  street: string | null; 
  ntee_code: string | null; 
  ntee_category: string | null; 
  subsection: string | null; 
  year_formed: number | null; 
  ruling_date: string | null; 
  pub78_status: string | null; 
  tax_year_latest: number | null; 
  form_type_latest: string | null; 
  updated_at?: string | Date | null;
} 
 
export interface Filing { 
  id: number; 
  ein: string; 
  object_id: string; 
  tax_year: number; 
  period_begin: string | null; 
  period_end: string | null; 
  form_type: string; 
  received_date: string | null; 
  parsed_data: Record<string, any> | null; 
} 
 
export interface Grant { 
  id: number; 
  filing_id: number; 
  grantee_name: string | null; 
  grantee_ein: string | null; 
  amount: number | null; 
  purpose: string | null; 
  city: string | null; 
  state: string | null; 
} 
 
export interface Compensation { 
  id: number; 
  filing_id: number; 
  person_name: string; 
  title: string | null; 
  base_comp: number | null; 
  bonus: number | null; 
  other_comp: number | null; 
  related_comp: number | null; 
  total_comp: number | null; 
} 
 
export interface OrgFullData extends Organization {
  filings: Filing[];
  grants: Grant[];
  compensation: Compensation[];
}

export interface OrgPathData {
  ein: string;
  canonical_name: string;
}

export interface SearchIndexOrganization {
  ein: string;
  canonical_name: string;
  city: string | null;
  state: string | null;
  ntee_category: string | null;
  total_revenue: string | null;
  filing_count: number;
}

export interface DirectoryPagesForSitemap {
  states: string[];
  cities: { city: string; state: string }[];
  nteeCodes: string[];
}

export async function getOrganization(ein: string): Promise<Organization | null> { 
  const { rows } = await pool.query('SELECT * FROM organizations WHERE ein = $1', [ein]); 
  return rows[0] || null; 
}

/**
 * Fetch an organization plus all its filings, grants, and compensation
 * in a single query. Replaces the N+1 pattern of:
 *   getOrganization() + getFilings() + getGrants(filingId) + getCompensation(filingId)
 * For 24,947 orgs this reduces 125K queries to 25K.
 *
 * Returns null if the EIN is unknown.
 * Filings are sorted in JS because DISTINCT inside json_agg constrains ORDER BY.
 *
 * @note Grants are limited to top 500 by amount.
 * Compensation limited to top 50 by total_comp.
 * Some orgs (e.g. Fidelity DAF) have 300K+ grants — aggregating all of
 * them in a single json_agg crashes the build process. The page only
 * displays the largest grants anyway, so the limit is safe.
 */
export async function getAllOrgData(ein: string): Promise<OrgFullData | null> {
  const { rows } = await pool.query(`
    SELECT
      o.*,
      COALESCE((
        SELECT json_agg(filing_row ORDER BY (filing_row->>'tax_year')::int DESC)
        FROM (
          SELECT DISTINCT ON (f2.tax_year)
            jsonb_build_object(
              'id', f2.id,
              'ein', f2.ein,
              'object_id', f2.object_id,
              'tax_year', f2.tax_year,
              'form_type', f2.form_type,
              'period_begin', f2.period_begin,
              'period_end', f2.period_end,
              'received_date', f2.received_date,
              'parsed_data', f2.parsed_data
            ) AS filing_row
          FROM filings f2
          WHERE f2.ein = o.ein
          ORDER BY f2.tax_year DESC, f2.received_date DESC NULLS LAST, f2.id DESC
        ) deduped
      ), '[]'::json) AS filings,
      COALESCE((
        SELECT json_agg(grant_row)
        FROM (
          SELECT
            g.id, g.filing_id, g.grantee_name, g.grantee_ein,
            g.amount, g.purpose, g.city, g.state
          FROM grants g
          JOIN filings fg ON fg.id = g.filing_id
          WHERE fg.ein = o.ein
            AND g.amount >= 0
          ORDER BY g.amount DESC NULLS LAST
          LIMIT 500
        ) grant_row
      ), '[]'::json) AS grants,
      COALESCE((
        SELECT json_agg(comp_row)
        FROM (
          SELECT
            c.id, c.filing_id, c.person_name, c.title,
            c.base_comp, c.bonus, c.other_comp,
            c.related_comp, c.total_comp
          FROM compensation c
          JOIN filings fc ON fc.id = c.filing_id
          WHERE fc.ein = o.ein
          ORDER BY c.total_comp DESC NULLS LAST
          LIMIT 50
        ) comp_row
      ), '[]'::json) AS compensation
    FROM organizations o
    WHERE o.ein = $1
  `, [ein]);

  if (rows.length === 0) return null;

  return rows[0] as OrgFullData;
}

/**
 * Minimal data needed by getStaticPaths() — only ein + canonical_name
 * for organizations that actually have filings. Avoids loading every
 * column of every organization just to build the route list.
 */
export async function getStaticPathsData(): Promise<OrgPathData[]> {
  const { rows } = await pool.query(`
    SELECT o.ein, o.canonical_name
    FROM organizations o
    WHERE EXISTS (SELECT 1 FROM filings f WHERE f.ein = o.ein)
    ORDER BY o.ein
  `);
  return rows;
}

export async function getDirectoryPagesForSitemap(): Promise<DirectoryPagesForSitemap> {
  const [{ rows: stateRows }, { rows: cityRows }, { rows: nteeRows }] = await Promise.all([
    pool.query('SELECT DISTINCT state FROM organizations WHERE state IS NOT NULL ORDER BY state'),
    pool.query('SELECT DISTINCT city, state FROM organizations WHERE city IS NOT NULL AND state IS NOT NULL ORDER BY state, city'),
    pool.query('SELECT DISTINCT ntee_code FROM organizations WHERE ntee_code IS NOT NULL ORDER BY ntee_code'),
  ]);

  return {
    states: stateRows.map(r => r.state),
    cities: cityRows,
    nteeCodes: nteeRows.map(r => r.ntee_code),
  };
}

export async function getSearchIndexData(): Promise<SearchIndexOrganization[]> {
  const { rows } = await pool.query(`
    SELECT
      o.ein,
      o.canonical_name,
      o.city,
      o.state,
      o.ntee_category,
      (
        SELECT parsed_data->>'total_revenue'
        FROM filings f
        WHERE f.ein = o.ein
        ORDER BY tax_year DESC
        LIMIT 1
      ) AS total_revenue,
      (
        SELECT count(*)::int
        FROM filings f
        WHERE f.ein = o.ein
      ) AS filing_count
    FROM organizations o
    WHERE EXISTS (SELECT 1 FROM filings f2 WHERE f2.ein = o.ein)
    ORDER BY o.ein
  `);
  return rows;
}

/**
 * Fetch ALL orgs (that have at least one filing) plus their filings,
 * top-500 grants and top-50 compensation rows. Used by getStaticPaths()
 * so the per-page DB call can be eliminated entirely — full data is
 * passed through as a page prop instead.
 *
 * Pages built: ~25K. Without this, each page would make its own
 * round-trip to the DB (~25K queries). With this, the build does
 * ceil(25K / 5000) = 5 queries total.
 *
 * Pagination is OFFSET/LIMIT keyed on organizations.ein (PK index)
 * so each page is a fast index scan. Results are accumulated into a
 * single array because getStaticPaths() requires a synchronous return
 * shape.
 *
 * @note Grants are limited to top 500 by amount per org.
 * Compensation limited to top 50 by total_comp per org.
 * Same rationale as getAllOrgData(): some orgs (e.g. Fidelity DAF)
 * have 300K+ grants and aggregating all of them crashes Node.
 */
export async function getAllOrgsFullData(): Promise<OrgFullData[]> {
  const BATCH_SIZE = 5000;
  const all: OrgFullData[] = [];
  let offset = 0;

  while (true) {
    const { rows } = await pool.query(`
      SELECT
        o.*,
        COALESCE((
          SELECT json_agg(filing_row ORDER BY (filing_row->>'tax_year')::int DESC)
          FROM (
            SELECT DISTINCT ON (f2.tax_year)
              jsonb_build_object(
                'id', f2.id,
                'ein', f2.ein,
                'object_id', f2.object_id,
                'tax_year', f2.tax_year,
                'form_type', f2.form_type,
                'period_begin', f2.period_begin,
                'period_end', f2.period_end,
                'received_date', f2.received_date,
                'parsed_data', f2.parsed_data
              ) AS filing_row
            FROM filings f2
            WHERE f2.ein = o.ein
            ORDER BY f2.tax_year DESC, f2.received_date DESC NULLS LAST, f2.id DESC
          ) deduped
        ), '[]'::json) AS filings,
        COALESCE((
          SELECT json_agg(grant_row)
          FROM (
            SELECT
              g.id, g.filing_id, g.grantee_name, g.grantee_ein,
              g.amount, g.purpose, g.city, g.state
            FROM grants g
            JOIN filings fg ON fg.id = g.filing_id
            WHERE fg.ein = o.ein
              AND g.amount >= 0
            ORDER BY g.amount DESC NULLS LAST
            LIMIT 500
          ) grant_row
        ), '[]'::json) AS grants,
        COALESCE((
          SELECT json_agg(comp_row)
          FROM (
            SELECT
              c.id, c.filing_id, c.person_name, c.title,
              c.base_comp, c.bonus, c.other_comp,
              c.related_comp, c.total_comp
            FROM compensation c
            JOIN filings fc ON fc.id = c.filing_id
            WHERE fc.ein = o.ein
            ORDER BY c.total_comp DESC NULLS LAST
            LIMIT 50
          ) comp_row
        ), '[]'::json) AS compensation
      FROM organizations o
      WHERE EXISTS (SELECT 1 FROM filings f WHERE f.ein = o.ein)
      ORDER BY o.ein
      LIMIT $1 OFFSET $2
    `, [BATCH_SIZE, offset]);

    if (rows.length === 0) break;

    all.push(...(rows as OrgFullData[]));

    if (rows.length < BATCH_SIZE) break;
    offset += BATCH_SIZE;
  }

  return all;
} 
 
export async function getFilings(ein: string): Promise<Filing[]> { 
  const { rows } = await pool.query( 
    'SELECT * FROM filings WHERE ein = $1 ORDER BY tax_year DESC', 
    [ein] 
  ); 
  return rows; 
} 
 
export async function getLatestFiling(ein: string): Promise<Filing | null> { 
  const { rows } = await pool.query( 
    'SELECT * FROM filings WHERE ein = $1 ORDER BY tax_year DESC LIMIT 1', 
    [ein] 
  ); 
  return rows[0] || null; 
} 
 
export async function getGrants(filingId: number): Promise<Grant[]> { 
  const { rows } = await pool.query( 
    'SELECT * FROM grants WHERE filing_id = $1 ORDER BY amount DESC NULLS LAST', 
    [filingId] 
  ); 
  return rows; 
} 
 
export async function getCompensation(filingId: number): Promise<Compensation[]> { 
  const { rows } = await pool.query( 
    'SELECT * FROM compensation WHERE filing_id = $1 ORDER BY total_comp DESC NULLS LAST', 
    [filingId] 
  ); 
  return rows; 
} 
 
export async function getOrganizationsByState(state: string): Promise<Organization[]> { 
  const { rows } = await pool.query( 
    'SELECT * FROM organizations WHERE state = $1 ORDER BY canonical_name', 
    [state.toUpperCase()] 
  ); 
  return rows; 
} 
 
export async function getOrganizationsByCity(city: string, state?: string): Promise<Organization[]> { 
  if (state) { 
    const { rows } = await pool.query( 
      'SELECT * FROM organizations WHERE city ILIKE $1 AND state = $2 ORDER BY canonical_name', 
      [city, state.toUpperCase()] 
    ); 
    return rows; 
  } 
  const { rows } = await pool.query( 
    'SELECT * FROM organizations WHERE city ILIKE $1 ORDER BY canonical_name', 
    [city] 
  ); 
  return rows; 
} 
 
export async function getOrganizationsByNtee(nteeCode: string): Promise<Organization[]> { 
  const { rows } = await pool.query( 
    'SELECT * FROM organizations WHERE ntee_code LIKE $1 ORDER BY canonical_name', 
    [nteeCode + '%'] 
  ); 
  return rows; 
} 
 
export async function searchOrganizations(query: string, limit = 50): Promise<Organization[]> { 
  const cleanEin = query.replace(/-/g, '').trim(); 
  if (/^\d{9}$/.test(cleanEin)) { 
    const { rows } = await pool.query('SELECT * FROM organizations WHERE ein = $1', [cleanEin]); 
    if (rows.length > 0) return rows; 
  } 
  const { rows } = await pool.query(
    'SELECT * FROM organizations WHERE canonical_name ILIKE $1 ORDER BY canonical_name LIMIT $2',
    [`%${query}%`, limit]
  ); 
  return rows; 
} 
 
export async function getAllOrganizations(): Promise<Organization[]> { 
  const { rows } = await pool.query('SELECT * FROM organizations ORDER BY canonical_name'); 
  return rows; 
} 
 
export async function getDistinctStates(): Promise<string[]> { 
  const { rows } = await pool.query( 
    'SELECT DISTINCT state FROM organizations WHERE state IS NOT NULL ORDER BY state' 
  ); 
  return rows.map(r => r.state); 
} 
 
export async function getDistinctCities(): Promise<{city: string; state: string}[]> {
  const { rows } = await pool.query(
    'SELECT DISTINCT city, state FROM organizations WHERE city IS NOT NULL AND state IS NOT NULL ORDER BY state, city'
  );
  return rows;
}

export async function getStats() { 
  const { rows: orgRows } = await pool.query('SELECT count(*) as count FROM organizations'); 
  const { rows: filingRows } = await pool.query('SELECT count(*) as count FROM filings'); 
  return { 
    organizations: parseInt(orgRows[0].count), 
    filings: parseInt(filingRows[0].count), 
  }; 
}

