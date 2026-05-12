/**
 * SEO helpers — generate title tags, meta descriptions, and structured data.
 * Follows the exact formulas from the project brief.
 */

export function formatEin(ein: string): string {
  return `${ein.slice(0, 2)}-${ein.slice(2)}`;
}

export function slugify(name: string): string {
  return name
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-|-$/g, '');
}

export function generateTitle(orgName: string, ein: string): string {
  return `${orgName} - Form 990, EIN ${formatEin(ein)}, Financials | Philanthropy.org`;
}

export function generateMetaDescription(
  orgName: string,
  ein: string,
  city: string | null,
  state: string | null,
  latestYear: number | null
): string {
  const location = [city, state].filter(Boolean).join(', ');
  const yearPart = latestYear ? `Latest filing: ${latestYear}.` : '';
  return `View ${orgName}'s IRS Form 990 filings, EIN ${formatEin(ein)}, total revenue, expenses, mission, and key personnel.${location ? ` Located in ${location}.` : ''} ${yearPart}`.trim();
}

export function getSubsectionLabel(subsection: string | null): string {
  if (!subsection) return '';
  const labels: Record<string, string> = {
    '501(c)(3)': 'Charitable Organization',
    '501(c)(4)': 'Social Welfare Organization',
    '501(c)(5)': 'Labor/Agricultural Organization',
    '501(c)(6)': 'Business League',
    '501(c)(7)': 'Social/Recreational Club',
    '501(c)(8)': 'Fraternal Beneficiary Society',
    '501(c)(10)': 'Domestic Fraternal Society',
    '501(c)(12)': 'Benevolent Life Insurance Association',
    '501(c)(19)': 'Veterans Organization',
  };
  const label = labels[subsection];
  return label ? `${subsection} — ${label}` : subsection;
}

export function generateOrgSchema(
  orgName: string,
  ein: string,
  city: string | null,
  state: string | null,
  street: string | null,
  zip: string | null,
  yearFormed: number | null
): Record<string, any> {
  return {
    '@context': 'https://schema.org',
    '@type': 'NGO',
    name: orgName,
    identifier: formatEin(ein),
    ...(street || city || state || zip ? {
      address: {
        '@type': 'PostalAddress',
        ...(street ? { streetAddress: street } : {}),
        ...(city ? { addressLocality: city } : {}),
        ...(state ? { addressRegion: state } : {}),
        ...(zip ? { postalCode: zip } : {}),
      }
    } : {}),
    ...(yearFormed ? { foundingDate: String(yearFormed) } : {}),
  };
}
