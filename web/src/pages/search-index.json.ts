import { getSearchIndexData } from '../lib/db';

export async function GET() {
  const organizations = await getSearchIndexData();

  return new Response(JSON.stringify(organizations), {
    headers: {
      'Content-Type': 'application/json',
    },
  });
}
