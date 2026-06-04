import { getDirectoryPagesForSitemap, getStaticPathsData } from '../lib/db'; 
import { slugify } from '../lib/seo'; 
import { getNteeSlug } from '../lib/ntee'; 

const SITE_URL = import.meta.env.PUBLIC_SITE_URL ?? 'https://nonprofits.philanthropy.org';
const citySlug = (city, state) => `${city.toLowerCase().replace(/[^a-z0-9]+/g, '-')}-${state.toLowerCase()}`;
 
export async function GET() { 
  const orgs = await getStaticPathsData(); 
  const directoryPages = await getDirectoryPagesForSitemap(); 
 
  const urls = []; 
 
  urls.push({ loc: '/', priority: '1.0' }); 
  urls.push({ loc: '/search', priority: '0.8' }); 
  urls.push({ loc: '/states', priority: '0.8' }); 
 
  for (const state of directoryPages.states) {
    urls.push({
      loc: `/state/${state.toLowerCase()}`,
      priority: '0.6',
    });
  }

  for (const { city, state } of directoryPages.cities) {
    urls.push({
      loc: `/city/${citySlug(city, state)}`,
      priority: '0.5',
    });
  }
 
  for (const org of orgs) { 
    urls.push({ 
      loc: `/${org.ein}/${slugify(org.canonical_name)}`, 
      priority: '0.7', 
    }); 
  } 
 
  const categorySlugs = [...new Set(directoryPages.nteeCodes.map(getNteeSlug))];
  for (const slug of categorySlugs) { 
    urls.push({ 
      loc: `/category/${slug}`, 
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
