export interface NteeEntry { 
  code: string; 
  category: string; 
} 
 
const NTEE_MAP: Record<string, string> = {
  // NOTE: Keep in sync with pipeline/bmf_loader.py NTEE_CODES 
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
}; 
 
export function getNteeCategory(code: string): string { 
  const prefix = code.charAt(0).toUpperCase(); 
  return NTEE_MAP[prefix] || 'Nonprofit'; 
} 
 
export function getNteeSlug(code: string): string { 
  const cat = getNteeCategory(code); 
  return cat.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, ''); 
} 
 
export function getNteeBySlug(slug: string): { code: string; category: string } | null { 
  for (const [code, category] of Object.entries(NTEE_MAP)) { 
    const s = category.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, ''); 
    if (s === slug) return { code, category }; 
  } 
  return null; 
} 
 
export function getAllNteeCategories(): { code: string; category: string; slug: string }[] { 
  return Object.entries(NTEE_MAP).map(([code, category]) => ({ 
    code, 
    category, 
    slug: category.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, ''), 
  })); 
}
