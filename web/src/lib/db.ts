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
 
export async function getOrganization(ein: string): Promise<Organization | null> { 
  const { rows } = await pool.query('SELECT * FROM organizations WHERE ein = $1', [ein]); 
  return rows[0] || null; 
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

