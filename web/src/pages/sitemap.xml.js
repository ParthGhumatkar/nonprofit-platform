import { getAllOrganizations } from '../lib/db'; 
import { slugify } from '../lib/seo'; 
import { getAllNteeCategories } from '../lib/ntee'; 

const SITE_URL = import.meta.env.PUBLIC_SITE_URL ?? 'https://nonprofits.philanthropy.org';
 
export async function GET() { 
  const orgs = await getAllOrganizations(); 
  const nteeCats = getAllNteeCategories(); 
 
  const urls = []; 
 
  urls.push({ loc: '/', priority: '1.0' }); 
  urls.push({ loc: '/search', priority: '0.8' }); 
  urls.push({ loc: '/states', priority: '0.8' }); 
 
  for (const org of orgs) { 
    urls.push({ 
      loc: `/${org.ein}/${slugify(org.canonical_name)}`, 
      lastmod: org.updated_at ? new Date(org.updated_at).toISOString().split('T')[0] : null, 
      priority: '0.7', 
    }); 
  } 
 
  for (const cat of nteeCats) { 
    urls.push({ 
      loc: `/category/${cat.slug}`, 
      priority: '0.5', 
    }); 
  } 
 
  const xml = `<?xml version="1.0" encoding="UTF-8"?> 
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"> 
${urls.map(u => 
    `  <url> 
    <loc>${SITE_URL.replace(/\/$/, '')}${u.loc}</loc> 
    ${u.lastmod ? `<lastmod>${u.lastmod}</lastmod>` : ''} 
    <priority>${u.priority}</priority> 
  </url>` 
  ).join('\n')} 
</urlset>`; 
 
  return new Response(xml, { 
    headers: { 
      'Content-Type': 'application/xml', 
    }, 
  }); 
}
