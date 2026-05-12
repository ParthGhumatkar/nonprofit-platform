# Nonprofit Platform

A free, SEO-optimised explorer for U.S. nonprofit tax filings, designed to run at
`nonprofits.philanthropy.org`. A Python pipeline downloads IRS Form 990 XML files from
public S3 storage, parses them, and stores structured data in PostgreSQL. Astro then
reads the database at build time and generates one static HTML page per organisation,
giving search engines a fast, crawlable page for every nonprofit in the dataset.

---

## What it does

- Ingests IRS Form 990, 990-EZ, and 990-PF XML filings from the GivingTuesday public
  data lake (covering 2011-2024) and stores them in a PostgreSQL database.
- Extracts financial figures, mission statements, program descriptions, grants made, and
  executive compensation from each filing.
- Generates a static website — one page per nonprofit — with financial trend charts,
  filing history, grants tables, and compensation data.
- Provides browsable directory pages organised by U.S. state, city, and NTEE nonprofit
  category.
- Produces a complete `/sitemap.xml` automatically so every page is indexed.

---

## Tech stack

| Layer | Tool | Version | Purpose |
|---|---|---|---|
| Database | PostgreSQL | 16 (alpine) | Primary datastore |
| Ingestion runtime | Python | 3.12 (slim) | Pipeline scripts |
| XML parser | irsx | >=0.3.3 | Parses IRS 990-series XML schema |
| XML backend | lxml | >=5.0 | Low-level XML processing |
| DB driver (Python) | psycopg2-binary | >=2.9 | Connects pipeline to Postgres |
| Env loading | python-dotenv | >=1.0 | Reads `.env` in pipeline |
| Manifest/download | pandas | >=2.0 | Reads parquet index, CSV manifest |
| Parquet support | pyarrow | >=14.0 | Required by pandas for parquet |
| HTTP download | requests | >=2.31 | Downloads XML files from S3 |
| Frontend framework | Astro | ^5.0.0 | Static site generator |
| CSS framework | Tailwind CSS | ^4.0.0 | Utility-first styling |
| DB driver (Node) | pg | ^8.13.0 | Reads Postgres at Astro build time |
| Charts (CDN) | Chart.js | 4.4.0 | Financial sparkline charts (CDN, not bundled) |
| Interactivity (CDN) | Alpine.js | 3.x.x | Collapsible filing cards (CDN, not bundled) |
| Web server | nginx | alpine | Serves the compiled static site |
| Orchestration | Docker Compose | 3.8 | Runs DB + pipeline + web locally |

---

## Prerequisites

Install all of the following before starting:

| Tool | Minimum version | Install guide |
|---|---|---|
| Docker Desktop | 4.x | https://docs.docker.com/desktop/ |
| Node.js | 20 | https://nodejs.org/ |
| Python | 3.12 | https://www.python.org/downloads/ |
| Git | 2.x | https://git-scm.com/ |

> **AWS CLI is not required.** The downloader (`pipeline/download_xml.py`) uses HTTPS
> directly. You only need AWS CLI if you want to use `aws s3 sync` instead.

---

## Project structure

```
nonprofit-platform/
│
├── .gitignore                  Excludes node_modules, dist, .env, data blobs
├── docker-compose.yml          Defines db / pipeline / web services
├── nginx.conf                  nginx config copied into the web container
├── README.md                   This file
├── CONTRIBUTING.md             Developer guide
├── PROJECT_HANDOVER.md         Full architecture audit document
│
├── db/
│   ├── schema.sql              Creates all 7 tables, indexes, trigger
│   └── schema-annotated.sql    schema.sql with explanatory inline comments
│
├── pipeline/                   Python ingestion pipeline (runs in Docker or venv)
│   ├── Dockerfile              python:3.12-slim; CMD python sync.py
│   ├── requirements.txt        Python dependencies
│   ├── build_manifest.py       Reads master_index.parquet → downloads manifest CSV
│   ├── download_xml.py         Downloads XML files listed in the manifest
│   ├── sync.py                 Orchestrator: walks raw_xml/, calls parse_irsx
│   ├── parse_irsx.py           Parses 990 and 990-PF XML, writes to DB
│   ├── db.py                   All PostgreSQL helpers (upsert, insert, query)
│   ├── bmf_loader.py           Loads NCCS BMF CSV for NTEE codes and org metadata
│   └── .env.example            Template for pipeline environment variables
│
├── web/                        Astro static frontend
│   ├── Dockerfile              nginx:alpine; serves compiled dist/
│   ├── astro.config.mjs        output: static; Tailwind Vite plugin; site URL
│   ├── package.json            JS dependencies (astro, pg, tailwindcss, chart.js)
│   ├── package-lock.json       Lockfile
│   ├── .env.example            Template for web environment variables
│   ├── .env                    Your local secrets (gitignored)
│   └── src/
│       ├── layouts/
│       │   └── BaseLayout.astro    <head>, header, footer, Alpine/Chart.js CDN loaders
│       ├── components/
│       │   ├── FilingCard.astro        Collapsible per-year filing summary
│       │   ├── FinancialChart.astro    Sparkline chart card (renders a <canvas>)
│       │   ├── GrantsTable.astro       Table of grants made by the org
│       │   ├── CompensationTable.astro Table of officer compensation
│       │   └── MissionSection.astro    Blue pull-quote mission statement block
│       ├── lib/
│       │   ├── db.ts           pg Pool + all query functions used at build time
│       │   ├── ntee.ts         NTEE code → category label helpers and slugs
│       │   └── seo.ts          Title/description/schema.org generators
│       ├── pages/
│       │   ├── index.astro             Homepage with search box and stats
│       │   ├── search.astro            Search page (BROKEN — see Known Issues)
│       │   ├── states.astro            List of all states
│       │   ├── 404.astro               404 page
│       │   ├── sitemap.xml.js          Programmatic XML sitemap
│       │   ├── [ein]/[slug].astro      Org detail page (one per nonprofit)
│       │   ├── state/[state].astro     All orgs in a state
│       │   ├── city/[city].astro       All orgs in a city (slug: chicago-il)
│       │   └── category/[ntee].astro   All orgs in an NTEE major category
│       └── styles/
│           └── global.css      Inter font import, Tailwind base, .num class
│
└── data/                       Local data files (all gitignored)
    ├── bmf/                    Drop bmf_extract.csv here for BMF enrichment
    ├── indexes/                master_index.parquet and download_manifest.csv live here
    ├── raw_xml/                Parsed XML files: {EIN}/{YEAR}/{object_id}_public.xml
    ├── zips/                   Raw zip archives (if using aws s3 sync)
    └── temp_extract/           Unzip workspace
```

---

## Local setup — step by step

### 1. Clone the repository

```powershell
git clone <repo-url> nonprofit-platform
cd nonprofit-platform
```

### 2. Create the web environment file

```powershell
Copy-Item web\.env.example web\.env
```

Open `web/.env` and set `DATABASE_URL`. For local Docker the default value works
as-is:

```
DATABASE_URL=postgresql://nonprofit:devpassword@localhost:5433/nonprofit_platform
```

### 3. Start the database

```powershell
docker compose up -d db
```

Wait about 10 seconds for the healthcheck to pass. The schema is applied automatically
from `db/schema.sql` on first start.

Verify it is running:

```powershell
docker compose exec db psql -U nonprofit -d nonprofit_platform -c "\dt"
```

You should see 7 tables listed.

### 4. Install Python dependencies

The pipeline scripts run outside Docker during data preparation. Create a virtual
environment and install:

```powershell
cd pipeline
python -m venv .venv
.\.venv\Scripts\Activate.ps1   # Windows PowerShell
# Mac/Linux: source .venv/bin/activate
pip install -r requirements.txt
cd ..
```

### 5. Place the master index file

`build_manifest.py` needs `data/indexes/master_index.parquet` (the IRS filing index,
~1.3 GB). Download it from the GivingTuesday data lake:

```powershell
# Windows PowerShell — requires AWS CLI or you can use curl
aws s3 cp "s3://gt990datalake-rawdata/Indices/990xmls/index_all_years_efiledata_xmls_created_on_2026-03-20.parquet" `
    "data\indexes\master_index.parquet" `
    --no-sign-request --no-verify-ssl
```

> **Mac/Linux:**
> ```bash
> aws s3 cp s3://gt990datalake-rawdata/Indices/990xmls/index_all_years_efiledata_xmls_created_on_2026-03-20.parquet \
>     data/indexes/master_index.parquet \
>     --no-sign-request --no-verify-ssl
> ```

### 6. Build the download manifest

This selects the top 25,000 organisations by revenue across 2020-2024 and writes a CSV
of all filings to download:

```powershell
cd pipeline
python build_manifest.py
cd ..
```

Output: `data/indexes/download_manifest.csv` (~22 MB, ~125,000 rows for 25K orgs × 5
years).

> To change the number of organisations, set the environment variable:
> ```powershell
> $env:TARGET_ORGS = "10000"
> python pipeline\build_manifest.py
> ```

### 7. Download the XML filing files

```powershell
cd pipeline
python download_xml.py
cd ..
```

This downloads each XML file from `https://gt990datalake-rawdata.s3.amazonaws.com` into
`data/raw_xml/{EIN}/{YEAR}/{object_id}_public.xml`. It is resumable — re-running skips
already-downloaded files.

**Estimated time:** At ~10 parallel workers downloading ~125,000 files averaging
~180 KB each (~21 GB total), expect **60–120 minutes** depending on your connection.

Progress is printed every 500 files. Any failures are written to
`data/indexes/failed_downloads.csv`.

### 8. (Optional) Load BMF organisation metadata

The IRS Business Master File adds NTEE codes, ruling dates, and deductibility status.
If you have a BMF CSV at `data/bmf/bmf_extract.csv`, run:

```powershell
cd pipeline
python bmf_loader.py
cd ..
```

Without this step, organisations from 990 filings still appear but lack NTEE category
labels and ruling dates.

### 9. Run the ingestion pipeline

```powershell
cd pipeline
python sync.py
cd ..
```

This walks every file under `data/raw_xml/`, parses each XML, and writes organisations,
filings, grants, compensation, and mission data to the database. Already-ingested files
are skipped automatically.

**Estimated time:** At roughly 5–10 files/second, parsing 125,000 files takes
**3–7 hours**. Run overnight.

Logs appear on stdout and are written to `pipeline/sync.log`.

### 10. Install frontend dependencies

```powershell
cd web
npm install
cd ..
```

### 11. Build the frontend

```powershell
cd web
npm run build
cd ..
```

Astro queries the database, generates one HTML file per organisation, and writes
everything to `web/dist/`. With 25,000 organisations this takes **10–30 minutes**.

### 12. Preview the site locally

```powershell
cd web
npm run preview
```

Open `http://localhost:4321` in your browser.

---

## Optional steps

### Load the site with Docker (full stack)

After step 11, the `web/dist/` folder exists. The Docker web service copies it into
nginx:

```powershell
docker compose up --build web
```

Open `http://localhost:3000`.

> **Note:** `docker compose build web` does **not** run `npm run build` inside the
> container. You must build locally first and then build the Docker image.

### Increase download parallelism

```powershell
$env:DOWNLOAD_WORKERS = "20"
cd pipeline
python download_xml.py
```

---

## Environment variables

### `web/.env`

| Variable | Default | Required | What it does |
|---|---|---|---|
| `DATABASE_URL` | `postgresql://nonprofit:YOUR_PASSWORD@localhost:5433/nonprofit_platform` | Yes | Connection string used by `pg` at Astro build time to query all orgs and filings |
| `PUBLIC_SITE_URL` | `https://nonprofits.philanthropy.org` | No | Sets canonical URLs and sitemap `<loc>` entries; read by `astro.config.mjs` and `sitemap.xml.js` |

### `pipeline/.env` (or set as environment variables)

| Variable | Default | Required | What it does |
|---|---|---|---|
| `DATABASE_URL` | none | Yes | PostgreSQL connection string for the pipeline |
| `RAW_XML_DIR` | `./data/raw_xml` | No | Directory where XML files are stored |
| `BMF_DIR` | `./data/bmf` | No | Directory where `bmf_extract.csv` is stored |
| `NCCS_BMF_URL` | `https://nccsdata.s3.us-east-1.amazonaws.com/raw/bmf/2025-12-BMF.csv` | No | Override the BMF download URL |
| `PROJECT_DIR` | parent of `pipeline/` | No | Root project directory, used by build_manifest.py and download_xml.py |
| `MASTER_INDEX` | `{PROJECT_DIR}/data/indexes/master_index.parquet` | No | Path to the IRS master index parquet file |
| `TARGET_ORGS` | `25000` | No | Number of organisations to include in the manifest |
| `DOWNLOAD_WORKERS` | `10` | No | Parallel download threads in download_xml.py |

---

## Data pipeline — how it works

```
GivingTuesday S3 data lake
s3://gt990datalake-rawdata/
│
│  Step 1 — Build manifest (build_manifest.py, ~2 min)
│  Reads Indices/990xmls/master_index.parquet (1.3 GB).
│  Selects top 25K orgs by revenue across 2020-2024.
│  Writes data/indexes/download_manifest.csv with one row per filing.
│
│  Step 2 — Download XMLs (download_xml.py, 60-120 min)
│  Reads download_manifest.csv.
│  Downloads each XML from S3 over HTTPS (10 workers, resumable).
│  Saves to data/raw_xml/{EIN}/{YEAR}/{object_id}_public.xml.
│
▼
data/raw_xml/
│
│  Step 3 — (Optional) BMF enrichment (bmf_loader.py, ~10 min)
│  Reads data/bmf/bmf_extract.csv (IRS Business Master File, ~337 MB).
│  Upserts NTEE codes, ruling dates, deductibility status into organizations table.
│
│  Step 4 — Ingest (sync.py → parse_irsx.py → db.py, 3-7 hours)
│  Walks every .xml file in data/raw_xml/.
│  Skips files <20 KB (990-N stubs) and already-ingested object_ids.
│  Calls parse_990() or parse_990pf() depending on form type.
│  Extracts: org metadata, 13 financial fields, mission, programs, grants, compensation.
│  Upserts organizations; inserts filings, grants, compensation, missions, programs.
│  Runs backfill_org_metadata() to fill in missing subsection codes.
│
▼
PostgreSQL (port 5433 locally, 5432 inside Docker)
│
│  Step 5 — Build frontend (npm run build, 10-30 min)
│  Astro queries getOrganizations(), getFilings(), getGrants(), etc. at build time.
│  Generates one HTML page per org at web/dist/{ein}/{slug}/index.html.
│  Generates state, city, category directory pages.
│  Generates /sitemap.xml.
│
▼
web/dist/   (static HTML/CSS/JS — no server required after build)
│
▼
nginx serves web/dist/ on port 80 (Docker: host port 3000)
```

---

## Database

All tables are defined in `db/schema.sql`. See `db/schema-annotated.sql` for full
column-level documentation.

| Table | Stores |
|---|---|
| `organizations` | One row per EIN: name, address, NTEE code, subsection (e.g. 501(c)(3)), latest tax year, and timestamps |
| `organization_names` | Historical name variants per EIN (populated for Phase 2 entity resolution; currently empty) |
| `filings` | One row per tax return: tax year, form type, period dates, full raw XML, and a JSONB blob of the 13 parsed financial fields plus mission and program text |
| `grants` | Each grant made by an organisation in a given filing (from Schedule I or 990-PF grant list) |
| `compensation` | Each officer's pay in a given filing (base, bonus, other, related, total) |
| `program_accomplishments` | Narrative program descriptions from Schedule O / Part III, one row per paragraph |
| `mission_statements` | The organisation's mission text, one row per filing |

---

## Frontend pages

All pages are pre-rendered at build time. Routes are derived from the database contents.

| Route | Source file | What it renders |
|---|---|---|
| `/` | `pages/index.astro` | Homepage: search box, live org/filing counts, browse links |
| `/search` | `pages/search.astro` | Search by name or EIN — **currently broken under static build** |
| `/states` | `pages/states.astro` | Grid of all states that have organisations in the DB |
| `/state/{state}` | `pages/state/[state].astro` | All organisations in a state, 50 per page |
| `/city/{city-state}` | `pages/city/[city].astro` | All orgs in a city, e.g. `/city/chicago-il` |
| `/category/{ntee}` | `pages/category/[ntee].astro` | All orgs in an NTEE major group (26 categories) |
| `/{ein}/{slug}` | `pages/[ein]/[slug].astro` | Organisation detail: mission, financials, grants, compensation, filing history |
| `/sitemap.xml` | `pages/sitemap.xml.js` | Programmatic XML sitemap for all orgs and category pages |
| `/404` | `pages/404.astro` | 404 page with search box |

---

## Known issues

| Issue | Affected file | Workaround |
|---|---|---|
| **Search page does not work** — Astro `output: 'static'` freezes `Astro.url.searchParams` at build time, so `?q=` is always empty | `web/src/pages/search.astro` | Use browser find-in-page or navigate directly to `/{ein}/{slug}` |
| **Pagination broken on directory pages** — `?page=N` query strings are not preserved in static output; only page 1 renders | `state/[state].astro`, `city/[city].astro`, `category/[ntee].astro` | View page 1 only until path-segment pagination is implemented |
| **`docker compose up web` requires a prior local build** — `web/Dockerfile` is `nginx:alpine` and just copies `dist/`; there is no Astro build step inside the container | `web/Dockerfile`, `docker-compose.yml` | Run `cd web && npm run build` locally before running `docker compose up --build web` |
| **`raw_xml TEXT` stored inline in the database** — at full scale (~125K filings × ~180 KB each) this is ~22 GB inside the `filings` table | `db/schema.sql` | Acceptable for Phase 1; plan to move raw XML to external storage before 600K-org scale |
| **`searchOrganizations` does not use the trigram GIN index** — the `ILIKE '%query%'` leading wildcard prevents index use | `web/src/lib/db.ts`, `pipeline/db.py` | Acceptable for small datasets; needs rewriting to use trigram similarity before production at scale |
| **BMF enrichment not called from `sync.py`** — NTEE codes and ruling dates will be missing unless `bmf_loader.py` is run separately | `pipeline/sync.py`, `pipeline/bmf_loader.py` | Run `python pipeline/bmf_loader.py` manually before or after `sync.py` |
| **`chart.js` listed in `web/package.json` but loaded via CDN** — the npm package is unused | `web/package.json` | The CDN version works; the npm dependency can be removed |
| **NTEE map exists in two places** — `pipeline/bmf_loader.py NTEE_CODES` and `web/src/lib/ntee.ts NTEE_MAP` must be kept in sync manually | Both files | A comment in each file warns to keep them in sync; no automated check exists |

---

## Monthly data refresh

When new IRS filings are published (typically monthly), run these steps in order:

```powershell
# 1. Rebuild the manifest (picks up any new filings for the tracked orgs)
cd pipeline
python build_manifest.py
cd ..

# 2. Download new XML files (skips already-downloaded files automatically)
cd pipeline
python download_xml.py
cd ..

# 3. Run the ingestion pipeline (skips already-ingested object_ids automatically)
cd pipeline
python sync.py
cd ..

# 4. Rebuild the frontend
cd web
npm run build
cd ..

# 5. Redeploy (copy web/dist/ to your server, or rebuild the Docker image)
```

> If the IRS master index has been updated, re-download it before step 1:
> ```powershell
> aws s3 cp "s3://gt990datalake-rawdata/Indices/990xmls/index_all_years_efiledata_xmls_created_on_2026-03-20.parquet" `
>     "data\indexes\master_index.parquet" `
>     --no-sign-request --no-verify-ssl
> ```
