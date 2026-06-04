import { defineConfig } from 'astro/config';
import tailwindcss from '@tailwindcss/vite';

const siteUrl = process.env.PUBLIC_SITE_URL || 'https://nonprofits.philanthropy.org';

export default defineConfig({
  output: 'static',
  site: siteUrl,
  build: {
    concurrency: 4,
  },
  vite: {
    plugins: [tailwindcss()],
  },
});
