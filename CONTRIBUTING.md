# Contributing

This guide is for developers adding features or fixing bugs. Read it before touching
any code. It explains the decisions baked into the codebase and the steps required to
do common tasks correctly.

---

## Architecture decisions (and why)

### 1. Static generation — not SSR

Astro is configured with `output: 'static'` in `astro.config.mjs`. At build time Astro
queries the database, loops over every organisation, and pre-renders one HTML file per
page. After the build there is no application server — nginx serves plain files.

**Why:** The entire SEO value of this platform comes from Google crawling individual
organisation pages. Static pages load faster, can be served from a CDN, and require no
runtime infrastructure. The trade-off is that every data update requires a full rebuild.

**What breaks when you change this:** If you switch to `output: 'server'` or
`output: 'hybrid'`, you must add an SSR adapter (e.g. `@astrojs/node`), update the
Dockerfile to run Node instead of nginx, and rethink the deployment. Do not do this
without a clear reason.

### 2. Raw XML stored alongside parsed fields

`db/schema.sql` stores the full XML text in `filings.raw_xml (TEXT)` next to the
structured `filings.parsed_data (JSONB)`. This is intentional.

**Why:** The IRS 990 schema has hundreds of fields. The current pipeline extracts ~13
financial fields plus mission, grants, and compensation. Future phases need access to
fields not yet extracted (Schedule R related parties, Schedule H hospital community
benefit, etc.) without re-downloading the files. Storing raw XML is the escape hatch.

**Known cost:** At full scale (~125,000 filings × ~180 KB each) `raw_xml` will grow to
~22 GB inside the database. This is acceptable for Phase 1. Plan to move it to object
storage (e.g. S3) before scaling to 600K+ organisations.

### 3. EIN is the primary key everywhere

The IRS Employer Identification Number is used as the primary key in `organizations`
and as the foreign key in every child table. EINs are 9-digit strings, zero-padded
(e.g. `042103547`).

**Why:** EINs are the IRS-assigned, stable, public identifier for every nonprofit. They
appear on every 990 filing and in every data source (BMF, Schedule I grantee lists,
GuideStar, etc.). Using EIN avoids artificial surrogate keys and makes cross-dataset
joins straightforward.

**What this means in practice:** Always store EINs as 9-character zero-padded strings.
`bmf_loader.py` and `download_xml.py` both call `.zfill(9)`. Never strip leading zeros.

### 4. IRSx instead of a custom XML parser

The `irsx` library (`>=0.3.3`) is a schema-aware IRS 990 parser maintained by
ProPublica. It handles the multi-year, multi-version IRS XML schema (which has changed
significantly across 2013-2024) and returns a normalised Python dict.

**Why:** Writing a custom parser for the IRS 990 XML schema is a 6–12 month project.
The schema changes every year, field names differ between 990 and 990-PF, and the
nesting is inconsistent. IRSx handles all of this. The `parse_irsx.py` script adds
thin business logic on top (mission extraction from Schedule O, compensation fallback
from Part VII when Schedule J is absent).

**Do not replace IRSx** unless a specific field it does not support is required. If you
need a field it does not expose, use `f.get_schedule('IRS990')` and read the raw dict.

### 5. The three content additions that make pages rank

Every organisation detail page (`[ein]/[slug].astro`) is built around three blocks that
differentiate it from other nonprofit databases:

1. **Mission statement** (`MissionSection.astro`) — extracted from `MissionDesc` or
   Schedule O. Google uses this to understand what the org does.
2. **Program accomplishments** (`FilingCard.astro`) — extracted from Part III / Schedule O.
   Provides unique, crawlable text for each filing.
3. **Grants made** (`GrantsTable.astro`) — extracted from Schedule I / 990-PF grant
   list. Creates internal link potential (grantee name appearing on the page).

**Do not remove these sections.** They are the reason pages rank above ProPublica and
Cause IQ. If a filing has no mission text, the section is omitted gracefully — do not
add a placeholder.

---

## Adding a new field from a 990 form

Example: you want to add "total number of volunteers" from Form 990 Part I line 6.

**Step 1 — Find the field in parse_irsx.py**

Open `pipeline/parse_irsx.py` and find `parse_990()`. The `sked` variable is the
result of `f.get_schedule('IRS990')`. Look up the XML field name in the IRS 990
schema documentation or search the irsx source. For volunteers it is `VolunteersCnt`.

Add to the `parsed` dict:
```python
'volunteers': safe_str(sked.get('VolunteersCnt')),
```

**Step 2 — Add to the database schema (if storing as a column)**

If the field needs its own column, add it to `db/schema.sql`:
```sql
ALTER TABLE filings ADD COLUMN volunteers INTEGER;
```

Or leave it in `parsed_data JSONB` (preferred for rarely queried fields — no schema
change required).

**Step 3 — Expose it in pipeline/db.py**

If you added a column, update the `INSERT INTO filings` statement in `insert_filing()`
to include the new column.

**Step 4 — Update web/src/lib/db.ts**

Add the field to the `Filing` interface:
```typescript
volunteers: number | null;
```

Update any query functions that need to return it (most use `SELECT *` so no SQL change
is needed, just the interface).

**Step 5 — Display it in the Astro component**

Open `web/src/pages/[ein]/[slug].astro` or the relevant component under
`web/src/components/`. Access the value from `latestFiling.parsed_data.volunteers` (for
JSONB fields) or `latestFiling.volunteers` (for columns).

---

## Adding a new page type

Example: you want to add `/foundation/[state]` — private foundations in a given state.

**How static pages work in this project**

Astro requires every static route to export a `getStaticPaths()` function. This
function queries the database and returns an array of `{ params }` objects. Astro
calls the page once for every params object at build time.

**Step 1 — Create the query in web/src/lib/db.ts**

```typescript
export async function getFoundationsByState(state: string): Promise<Organization[]> {
  const { rows } = await pool.query(
    "SELECT * FROM organizations WHERE state = $1 AND subsection = '501(c)(3)' AND form_type_latest = 'PF' ORDER BY canonical_name",
    [state.toUpperCase()]
  );
  return rows;
}
```

**Step 2 — Create the page file**

Create `web/src/pages/foundation/[state].astro`:

```astro
---
import BaseLayout from '../../layouts/BaseLayout.astro';
import { getFoundationsByState } from '../../lib/db';
import { getDistinctStates } from '../../lib/db';
import { formatEin, slugify } from '../../lib/seo';

export async function getStaticPaths() {
  const states = await getDistinctStates();
  return states.map(s => ({ params: { state: s.toLowerCase() } }));
}

const { state } = Astro.params;
const orgs = await getFoundationsByState(state);
---
<BaseLayout title={`Private Foundations in ${state.toUpperCase()} - Philanthropy.org`}
            description={`${orgs.length} private foundations in ${state.toUpperCase()}`}>
  <!-- your HTML here -->
</BaseLayout>
```

**Step 3 — Add links to the page from navigation**

Add a link in `web/src/layouts/BaseLayout.astro` or from the relevant parent page (e.g.
`state/[state].astro`). Astro only generates pages that are reachable from
`getStaticPaths()` — they do not need to be linked to build, but they do need to be
discoverable.

---

## Running the pipeline locally (without Docker)

```powershell
# Windows PowerShell — from the repo root
cd pipeline
python -m venv .venv
.\.venv\Scripts\Activate.ps1

# Copy and edit the env file
Copy-Item .env.example .env
# Set DATABASE_URL in .env to point at your running Postgres instance

pip install -r requirements.txt

# Build the manifest (needs data/indexes/master_index.parquet)
python build_manifest.py

# Download XML files
python download_xml.py

# Load BMF (optional)
python bmf_loader.py

# Run the ingestion pipeline
python sync.py
```

> **Mac/Linux:**
> ```bash
> source .venv/bin/activate
> ```
> Everything else is identical.

---

## Deployment

### What a production deployment looks like

Based on `docker-compose.yml` and the Dockerfiles, the intended production setup is:

1. **Database**: A hosted PostgreSQL 16 instance (e.g. RDS, Supabase, or a DigitalOcean
   managed DB). The `db` service in `docker-compose.yml` is for local development only.

2. **Pipeline**: Run `pipeline/sync.py` on a scheduled task (cron job or GitHub Actions)
   once per month after new IRS data is published. The pipeline container in
   `docker-compose.yml` is the reference for how to run it.

3. **Frontend build**: Run `npm run build` in `web/` after each pipeline run, then
   deploy `web/dist/` as a static site (Netlify, Vercel, S3 + CloudFront, or the nginx
   Docker container).

4. **nginx Docker**: If self-hosting, build the `web` Docker image after running
   `npm run build` locally. The `web/Dockerfile` is `FROM nginx:alpine` — it only
   copies the pre-built `dist/` folder and `nginx.conf`. There is no Node build step
   inside the container.

### Environment variables that change between dev and prod

| Variable | Dev value | Prod value |
|---|---|---|
| `DATABASE_URL` (web) | `postgresql://nonprofit:devpassword@localhost:5433/...` | Your hosted Postgres URL |
| `DATABASE_URL` (pipeline) | `postgresql://nonprofit:devpassword@localhost:5433/...` | Your hosted Postgres URL |
| `PUBLIC_SITE_URL` | `http://localhost:4321` (or unset) | `https://nonprofits.philanthropy.org` |
| `DB_PASSWORD` (Docker) | `devpassword` (default) | A strong random password |

### How to build the production Docker image

```powershell
# 1. Build the static site locally first (with prod env vars set in web/.env)
cd web
npm run build
cd ..

# 2. Build the Docker image (copies web/dist/ into nginx)
docker build -t nonprofit-web ./web

# 3. Run it
docker run -p 80:80 nonprofit-web
```

---

## What NOT to build (Phase 1 constraints)

Keep this list visible. The platform is a public-data product funded by organic search
traffic. These features are explicitly out of scope for Phase 1 and will not be added
without a product decision:

- **User accounts / login** — all data is public; accounts add GDPR surface and support
  burden with no revenue model to justify it yet.
- **Paid tiers / paywalls** — the traffic strategy depends on all pages being publicly
  crawlable. Gating content destroys the SEO value.
- **AI commentary / generated summaries** — adds hallucination risk on financial data
  and legal liability. IRS filings are already public documents; paraphrasing them adds
  no value.
- **Website URLs / social media** — the IRS BMF and 990 XML do not contain website URLs
  or social media handles. Do not scrape them; it creates a maintenance burden and data
  quality risk.
- **Year-over-year % change indicators** — the pipeline stores multiple years but the
  UI deliberately does not show "revenue up 12% YoY" labels. Percentage changes on
  incomplete multi-year data mislead users; implement only when multi-year coverage is
  verified.
- **Peer organisation matching** — "similar nonprofits" widgets require a similarity
  model. Not in scope until the basic dataset is complete.
