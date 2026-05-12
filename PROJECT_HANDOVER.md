# Project Handover — Nonprofit Platform

> A static-first IRS Form 990 explorer for U.S. nonprofits.
> Built with a Python ingestion pipeline, PostgreSQL 16, and Astro 5.

Author of this document: handover audit pass (2026-05-12).
Last code touch: `2026-05-11`.

---

## 1. Project Overview

### What the platform does
The platform ingests IRS Form 990, 990-EZ, and 990-PF e-file XML returns, normalizes them into a relational schema in PostgreSQL, and renders a fully **statically-generated** website at build time — one detail page per nonprofit — with financial charts, mission text, program areas, grants made, and executive compensation.

It is designed to power `nonprofits.philanthropy.org` (the site URL is hardcoded in `web/astro.config.mjs`).

### Business model and goal
- **Free public-data product** sitting under the Philanthropy.org brand umbrella.
- Cross-promotes the parent network (Foundations Directory, Job Board, GIVING Magazine, PlannedGiving.com) via header, footer, and a sidebar card on every org page.
- **Scale target: ~600,000+ U.S. nonprofits** (every active 501(c) entity that files a 990 series return). The homepage hero copy and meta description both reference this number.
- SEO-driven traffic strategy — every org gets a canonical URL `/{ein}/{slug}`, a per-page JSON-LD `NGO` schema, OpenGraph + Twitter meta, and an entry in `/sitemap.xml`.

### Tech stack (every tool and version)

#### Ingestion (`pipeline/`)
| Tool | Version | Purpose |
|---|---|---|
| Python | 3.12 (slim) | Runtime |
| `irsx` | `>=0.3.3` | IRS 990 XML parser (schema-aware) |
| `lxml` | `>=5.0` | XML backend |
| `psycopg2-binary` | `>=2.9` | PostgreSQL driver |
| `python-dotenv` | `>=1.0` | Loads `.env` |

#### Database
| Tool | Version | Purpose |
|---|---|---|
| PostgreSQL | 16 alpine (Docker image) | Primary store |
| `pg_trgm` extension | (built-in) | Fuzzy name search (GIN index on `organizations.canonical_name`) |

#### Frontend (`web/`)
| Tool | Version | Purpose |
|---|---|---|
| Astro | `^5.0.0` | Static site generator (`output: 'static'`) |
| Tailwind CSS | `^4.0.0` (via `@tailwindcss/vite`) | Styling |
| `pg` | `^8.13.0` | Node Postgres driver used at build time |
| Alpine.js | `3.x.x` (CDN) | Collapsible filing cards |
| Chart.js | `4.4.0` (CDN) | Financial trend charts |
| Inter font | Google Fonts | Typography |
| `alpinejs` | `^3.15.12` (root `package.json`) | Orphan dep — actual Alpine is CDN |

#### Serving / Orchestration
| Tool | Version | Purpose |
|---|---|---|
| Docker Compose | `3.8` | Local orchestration |
| nginx | `alpine` | Serves the built `dist/` |

---

## 2. Architecture

### Data flow
```
   IRS bulk e-file XML            NCCS BMF CSV
   (s3://gt990datalake-rawdata    (NCCS S3 — currently
    or apps.irs.gov/.../xml)        disabled in sync.py)
            │                              │
            ▼                              ▼
   data/raw_xml/{EIN}/{YEAR}/      data/bmf/bmf_extract.csv
            │                              │
            └───────────────┬──────────────┘
                            ▼
        ┌───────────────────────────────────────┐
        │ pipeline/sync.py                      │
        │   ├─ bmf_loader.load_bmf_csv()        │
        │   ├─ parse_irsx.parse_file(...)       │
        │   │     ├─ parse_990()                │
        │   │     └─ parse_990pf()              │
        │   └─ db.backfill_org_metadata()       │
        └────────────────────┬──────────────────┘
                             ▼
                   PostgreSQL 16 (port 5433)
                   organizations / filings /
                   grants / compensation /
                   mission_statements /
                   program_accomplishments /
                   organization_names
                             │
                             ▼
        ┌───────────────────────────────────────┐
        │ web/  Astro 5 build (`astro build`)   │
        │   getStaticPaths → SELECT every org   │
        │   prerender 1 HTML page per org       │
        │   + state / city / category pages     │
        │   + /sitemap.xml                      │
        └────────────────────┬──────────────────┘
                             ▼
                       web/dist/ (static)
                             │
                             ▼
                       nginx:alpine
                       (Docker, port 80)
```

### Docker services and ports
Defined in `docker-compose.yml`:

| Service | Image / Build | Internal port | Host port | Notes |
|---|---|---|---|---|
| `db` | `postgres:16-alpine` | `5432` | **`5433`** | Schema auto-loaded from `./db/schema.sql` via `/docker-entrypoint-initdb.d/01-schema.sql`. Healthcheck: `pg_isready`. Volume: `pgdata`. |
| `pipeline` | builds `./pipeline/Dockerfile` | — | — | One-shot. `CMD ["python", "sync.py"]`. Volumes: `./data/raw_xml`, `./data/bmf`. Waits for `db` healthy. |
| `web` | builds `./web/Dockerfile` | `4321` (compose claims) | **`3000:4321`** | ⚠️ Broken — image is `nginx:alpine` listening on `80`, not `4321`. Should be `3000:80`. |

### Environment variables

| Var | Used by | Default | Required |
|---|---|---|---|
| `DATABASE_URL` | `pipeline/db.py`, `web/src/lib/db.ts` | none (Python raises, TS throws) | **Yes** |
| `DB_PASSWORD` | `docker-compose.yml` | `devpassword` | No |
| `RAW_XML_DIR` | `pipeline/sync.py` | `/data/raw_xml` (in container) / `./data/raw_xml` (local) | No |
| `BMF_DIR` | `pipeline/sync.py`, `pipeline/bmf_loader.py` | `/data/bmf` (container) / `./data/bmf` (local) | No |
| `NCCS_BMF_URL` | `pipeline/bmf_loader.py` | `https://nccsdata.s3.us-east-1.amazonaws.com/raw/bmf/2025-12-BMF.csv` | No |
| `PUBLIC_SITE_URL` | `web/astro.config.mjs` | `https://nonprofits.philanthropy.org` | No (but required for correct canonical URLs in production) |

`web/.env` currently contains:
```
DATABASE_URL=postgresql://nonprofit:devpassword@localhost:5433/nonprofit_platform
```

---

## 3. Directory Structure

```
nonprofit-platform/
├── PROJECT_HANDOVER.md         ← this file
├── docker-compose.yml          ← 3 services: db, pipeline, web
├── nginx.conf                  ← server config copied into web container
├── package.json                ← orphan; only lists alpinejs (Alpine actually loaded via CDN)
├── package-lock.json
├── gen_frontend.py             ← ⚠️ legacy scaffolding script — DO NOT RUN, would overwrite BaseLayout.astro
│
├── data/                       ← Local volumes (gitignored in practice)
│   ├── bmf/                    ← NCCS BMF CSV drop zone (currently empty)
│   ├── raw_xml/                ← IRS XML drop zone: {EIN}/{YEAR}/{object_id}.xml
│   ├── indexes/                ← Reserved (empty)
│   ├── temp_extract/           ← Reserved for unzipped IRS bulk archives
│   └── zips/                   ← Raw downloaded ZIPs from IRS / GivingTuesday
│
├── db/
│   └── schema.sql              ← 7 tables, 11 indexes, 1 trigger, pg_trgm extension
│
├── pipeline/
│   ├── Dockerfile              ← python:3.12-slim, installs requirements
│   ├── requirements.txt        ← irsx, lxml, psycopg2-binary, python-dotenv
│   ├── sync.py                 ← Orchestrator entrypoint (sync_bmf → sync_xml → backfill → stats)
│   ├── parse_irsx.py           ← parse_990 / parse_990pf, mission/grants/comp extraction
│   ├── bmf_loader.py           ← NCCS BMF CSV loader + NTEE_CODES map (A–Z)
│   └── db.py                   ← psycopg2 helpers: upsert_organization, insert_filing, etc.
│
└── web/
    ├── Dockerfile              ← nginx:alpine, COPY dist /usr/share/nginx/html
    ├── astro.config.mjs        ← static output, tailwindcss Vite plugin, site URL
    ├── package.json            ← astro ^5, chart.js ^4.4, pg ^8.13, tailwindcss ^4
    ├── package-lock.json
    ├── .env                    ← ⚠️ contains DEV DATABASE_URL — do not ship
    ├── .astro/                 ← Astro cache (auto)
    ├── dist/                   ← Last build output (7 dry-run org pages present)
    ├── public/                 ← Static assets root
    └── src/
        ├── layouts/
        │   └── BaseLayout.astro    ← <head>, header, footer, Alpine CDN, Chart.js initializer
        ├── components/
        │   ├── FilingCard.astro        ← Per-year collapsible card (Alpine x-data)
        │   ├── FinancialChart.astro    ← Sparkline card; emits canvas hydrated by BaseLayout
        │   ├── GrantsTable.astro       ← Schedule I table; links grantee EINs to their org page
        │   ├── CompensationTable.astro ← Officer compensation table
        │   ├── MissionSection.astro    ← Blue pull-quote rendering
        │   └── ProgramsSection.astro   ← ⚠️ Dead code — inline implementation lives in [slug].astro
        ├── lib/
        │   ├── db.ts               ← pg Pool, 11 typed query functions
        │   ├── ntee.ts             ← NTEE_MAP (A–Z), slug helpers
        │   └── seo.ts              ← formatEin, slugify, generateTitle/MetaDescription/OrgSchema
        ├── pages/
        │   ├── index.astro                 ← Home: hero, search, 3 stat tiles
        │   ├── search.astro                ← ⚠️ Broken under static build
        │   ├── states.astro                ← Grid of all states
        │   ├── states/[state].astro        ← per-state org list (see state/)
        │   ├── state/[state].astro         ← Pre-rendered per state, paginated (?page=N broken)
        │   ├── city/[city].astro           ← Slug format: `chicago-il`
        │   ├── category/[ntee].astro       ← One per NTEE major group (26)
        │   ├── [ein]/[slug].astro          ← The marquee org page
        │   ├── sitemap.xml.js              ← Programmatic sitemap
        │   └── 404.astro
        └── styles/
            └── global.css              ← Inter import, tailwindcss, .num tabular-nums
```

### Built dry-run organizations (in `web/dist/`)
The last successful build pre-rendered these 7 EINs:

| EIN | Slug |
|---|---|
| `042103580` | president-and-fellows-of-harvard-college |
| `131635294` | (see dist/) |
| `131644147` | (see dist/) |
| `232657933` | (see dist/) |
| `530196605` | (see dist/) |
| `620646012` | (see dist/) |
| `911663695` | (see dist/) |

These are the canonical test set — verify all 7 render cleanly after any pipeline or template change.

---

## 4. Database Schema

Defined in `db/schema.sql`. PostgreSQL 16. Requires `pg_trgm`.

### Tables

#### `organizations` (one row per EIN — canonical record)
| Column | Type | Notes |
|---|---|---|
| `ein` | TEXT PRIMARY KEY | 9-digit, zero-padded |
| `canonical_name` | TEXT NOT NULL | From latest filing or BMF, whichever was last seen |
| `city`, `state`, `zip`, `street` | TEXT | Address |
| `ntee_code` | TEXT | e.g. `B82` |
| `ntee_category` | TEXT | Human-readable bucket from NTEE_CODES |
| `subsection` | TEXT | e.g. `501(c)(3)`, `501(c)(4)` |
| `year_formed` | INTEGER | Derived from `ruling_date[:4]` |
| `ruling_date` | DATE | BMF field, YYYYMM → YYYY-MM-01 |
| `pub78_status` | TEXT | Deductibility code (`PC`, `PF`, etc.) |
| `tax_year_latest` | INTEGER | Monotonic, `GREATEST(existing, new)` |
| `form_type_latest` | TEXT | `990`, `990EZ`, or `990PF` |
| `created_at`, `updated_at` | TIMESTAMPTZ | Auto-managed via trigger |

#### `organization_names` (Phase 2 — entity resolution placeholder)
| Column | Type |
|---|---|
| `id` | SERIAL PK |
| `ein` | TEXT FK → organizations(ein) |
| `name` | TEXT |
| `source` | TEXT (`'filing'` or `'bmf'`) |
| `tax_year` | INTEGER |
| Unique | (ein, name, tax_year) |

*Currently not written to — exists for future name-variant tracking.*

#### `filings` (one row per return)
| Column | Type | Notes |
|---|---|---|
| `id` | SERIAL PK | |
| `ein` | TEXT FK | |
| `object_id` | TEXT UNIQUE NOT NULL | IRS object id; used for upsert |
| `tax_year` | INTEGER NOT NULL | |
| `period_begin`, `period_end` | DATE | |
| `form_type` | TEXT NOT NULL | `990`, `990EZ`, `990PF` |
| `received_date` | DATE | From `ReturnTs` or `BuildTs` |
| `raw_xml` | TEXT | ⚠️ **Stored inline — major bloat risk** |
| `parsed_data` | JSONB | Structured financials, mission, programs |
| `created_at` | TIMESTAMPTZ | |

#### `grants`
| Column | Type | Notes |
|---|---|---|
| `id` | SERIAL PK | |
| `filing_id` | INTEGER FK ON DELETE CASCADE | |
| `grantee_name` | TEXT | |
| `grantee_ein` | TEXT | ⚠️ **No index** — but used by `GrantsTable` to link |
| `amount` | NUMERIC | |
| `purpose` | TEXT | |
| `city`, `state` | TEXT | |

#### `compensation`
| Column | Type |
|---|---|
| `id` | SERIAL PK |
| `filing_id` | INTEGER FK ON DELETE CASCADE |
| `person_name` | TEXT NOT NULL |
| `title` | TEXT |
| `base_comp`, `bonus`, `other_comp`, `related_comp`, `total_comp` | NUMERIC |

#### `program_accomplishments`
`id`, `filing_id` (cascade), `description TEXT NOT NULL`. Split on `\n\n` from Schedule O / Part III.

#### `mission_statements`
`id`, `filing_id` (cascade), `mission_text TEXT NOT NULL`. One per filing.

### Indexes (and why)

| Index | Purpose |
|---|---|
| `idx_filings_ein_year (ein, tax_year DESC)` | The `getFilings(ein) ORDER BY tax_year DESC` query path |
| `idx_filings_form_type` | Filter by 990 / 990PF / 990EZ |
| `idx_filings_period_end DESC` | Recent-filings queries |
| `idx_grants_filing` | Grant lookups per filing |
| `idx_grants_amount DESC` | Top-grants sort |
| `idx_comp_filing` | Compensation lookups |
| `idx_orgs_state` | State directory pages |
| `idx_orgs_city` | City directory pages |
| `idx_orgs_ntee` | NTEE category pages |
| `idx_orgs_name_trgm (gin, gin_trgm_ops)` | Fuzzy name search |
| `idx_orgs_name_lower` | `WHERE lower(canonical_name) LIKE ...` |

### Trigger
`trg_organizations_updated_at` calls `update_updated_at()` BEFORE UPDATE to keep `updated_at` accurate.

### Known schema issues
1. ⚠️ **`filings.raw_xml TEXT` inline** — at 600k+ filings × ~50KB avg = ~30GB on the main table. Move to a sibling table or external object store.
2. **`grants.grantee_ein` has no index** — slow if we ever query "what did EIN X receive".
3. **`searchOrganizations` uses leading-wildcard `ILIKE`** — won't use the trigram GIN index. Rewrite to `WHERE canonical_name % $1 ORDER BY similarity DESC`.
4. **`organization_names` table is never populated.**

---

## 5. Pipeline (`pipeline/`)

### 5.1 `sync.py` — the orchestrator

Entry: `python sync.py`. The `run()` function executes 4 steps:

```
Step 1: sync_bmf()
   ├─ Looks for {BMF_DIR}/bmf_extract.csv
   ├─ ⚠️ If missing, immediately sets bmf_path = None (download is DISABLED)
   └─ If present, calls bmf_loader.load_bmf_csv()

Step 2: sync_xml()
   ├─ Walks RAW_XML_DIR/{EIN}/{YEAR}/*.xml in sorted order
   ├─ For each XML: parse_irsx.parse_file(fpath, min_file_size=20_000)
   ├─ Counters: total, parsed, skipped, errors
   └─ Logs every 1000 files: "Progress: 1000 files (X parsed, Y skipped, Z errors) — R.R files/sec"

Step 3: db.backfill_org_metadata()
   └─ For orgs with NULL subsection: derives '501(c)(3)' from form_type=990PF
      or 'private foundation' keyword in mission text.

Step 4: db.get_stats()
   └─ Logs: "{orgs} organizations, {filings} filings, {ein_count} orgs with filings"
```

`MIN_FILE_SIZE = 20_000` bytes — files smaller than 20KB are treated as 990-N e-postcard stubs and skipped.

Logs to stdout **and** to `sync.log` in the working directory (`logging.FileHandler('sync.log')`).

### 5.2 `parse_irsx.py` — XML → structured data

#### `parse_file(filepath, min_file_size=20000)`
1. Skip if file < `min_file_size`.
2. Extract `object_id` from filename (`{object_id}.xml`).
3. Call `db.filing_exists(object_id)` — skip if already ingested.
4. Read raw XML bytes (utf-8 with replace).
5. Instantiate `irsx.filing.Filing(object_id, filepath=filepath)`, call `.process()`, attach `raw_xml`.
6. Check `f.list_schedules()`:
   - If `IRS990PF` present → `parse_990pf(...)`
   - Else if `IRS990` present → `parse_990(...)` (handles both 990 and 990-EZ)
   - Else: skip with reason `'Unsupported form type'`

#### `parse_990(f, schedules)` (990 + 990-EZ)
- Pulls `IRS990` schedule + `ReturnHeader990x`.
- Extracts EIN, `BusinessName`, `TaxYr`, period begin/end, `USAddress`.
- `derive_subsection(sked)` inspects `Organization501c3Ind`, `Organization4947a1Ind`, `Organization501cInd`, `Organization501cTypeTxt` (handles `X`/`1`/`TRUE`).
- Upserts org.
- Builds `parsed_data` JSON with 13 keys: `total_revenue`, `total_expenses`, `total_assets`, `total_liabilities`, `net_assets`, `contributions`, `prog_revenue`, `invest_income`, `other_revenue`, `grants_paid`, `salaries`, `fundraising_fees`, plus computed `net_income`.
- **Mission extraction is clever**:
  - If `MissionDesc` contains `"SCHEDULE O"` → reads `IRS990ScheduleO.SupplementalInformationDetail`, matches `FormAndLineReferenceDesc` for `"mission"` / `"part i"` / `"line 1"` (mission) vs `"part iii"` / `"program service"` / `"program accomplishment"` (programs).
  - Otherwise → uses `MissionDesc` + walks `ProgramServiceAccomplishmentGrp` for `DescriptionProgramServiceAccomTxt`.
- **DAF detection**: if `IRS990ScheduleD` present, checks `DonorAdvisedFundInd` / `DonorAdvisedFundHeldCnt` — sets `parsed_data.daf_activity = True`.
- **Compensation**: prefers `IRS990ScheduleJ.RltdOrgOfficerTrstKeyEmplGrp` (with base/bonus/other/related). Falls back to `Form990PartVIISectionAGrp` (base only via `ReportableCompFromOrgAmt`).
- **Grants**: `IRS990ScheduleI.RecipientTable` → grantee_name (`RecipientBusinessName`), `RecipientEIN`, `CashGrantAmt`, `PurposeOfGrantTxt`, `USAddress`.

#### `parse_990pf(f, schedules)` (private foundations)
- Always tags subsection as `501(c)(3)`.
- Uses `deep_get()` (recursive dict/list traversal) because 990-PF nests financials deeper than 990.
- Financial fields drawn from `TotalRevAndExpnssAmt`, `TotOprExpensesRevAndExpnssAmt`, `FMVAssetsEOYAmt`, `TotalNetInvstIncmAmt`, etc.
- Mission: `MissionDscriptionOrSignificantActyTxt` with a generic fallback string.
- Grants: `GrantOrContributionPdDurYrGrp` → `RecipientBusinessName`, `Amt`, `GrantOrContributionPurposeTxt`. No city/state on PF grants.
- Compensation: `OfficerDirTrstKeyEmplGrp.CompensationAmt`.

#### 990-EZ
Falls into `parse_990` because it presents under the `IRS990` schedule. Most parsed_data fields will be sparse — that's fine, the frontend `FilingCard` skips falsy values.

### 5.3 `db.py` — psycopg2 interface

- Module-level `load_dotenv()`, then reads `DATABASE_URL` (raises `RuntimeError` if missing).
- `@contextmanager get_conn()` — opens connection, commits on success, rolls back on exception, closes on exit.
- ⚠️ **Anti-pattern: every helper opens its own connection.** Parsing one XML file produces ~6 cycles: upsert_org, insert_filing, insert_grants, insert_compensation, insert_programs, insert_mission. At 600k filings this is ~3.6M short-lived TCP connections.
- `upsert_organization` — `ON CONFLICT (ein) DO UPDATE` with `COALESCE` (never null-clobbers existing values) and `GREATEST` for `tax_year_latest`.
- `insert_filing` — `ON CONFLICT (object_id)` for idempotency. Returns the new `id` via `RETURNING id`.
- `insert_grants` / `insert_compensation` — `DELETE WHERE filing_id = %s` then bulk insert via `psycopg2.extras.execute_values`.
- `insert_programs` — splits text on `\n\n` and bulk inserts one row per paragraph.
- `insert_mission` — single row replace.
- `filing_exists(object_id)` — used by `parse_file` to short-circuit re-ingest.
- `backfill_org_metadata()` — `JOIN LATERAL` to find each org's most recent filing, then derives `subsection` for orgs where it's NULL.
- `backfill_bmf_fields(rows)` — dynamic UPDATE for arbitrary BMF fields. **Currently unused** (no caller).
- `_to_numeric(val)` — strips commas, returns `None` on failure.

### 5.4 `bmf_loader.py`
- `NCCS_BMF_URL` defaults to `https://nccsdata.s3.us-east-1.amazonaws.com/raw/bmf/2025-12-BMF.csv`, env-overridable.
- `download_bmf(output_dir)` tries 3 URLs (this month, last month, two months back). **Unreachable from sync.py.**
- `load_bmf_csv(filepath)` — reads CSV, pads EIN to 9 digits via `zfill`, derives `year_formed` from `RULING_DATE[:4]`, maps NTEE first letter via `NTEE_CODES`, calls `upsert_organization`.
- `NTEE_CODES`: A–Z dict — comment instructs to keep in sync with `web/src/lib/ntee.ts NTEE_MAP`.

### Known pipeline bugs
1. ⚠️ **BMF download disabled** in `sync.py` `sync_bmf()` — when CSV is missing it silently sets `bmf_path = None` and returns. Result: orgs that have *no* 990 filed will be missing entirely; orgs that do have filings will lack BMF-only fields (`ntee_code`, `ruling_date`, `pub78_status`) unless backfilled separately.
2. ⚠️ **Connection-per-row** in `db.py`. Performance bottleneck at scale.
3. **`backfill_bmf_fields` is dead code** — never called.
4. **`organization_names` table never populated** — Phase 2 placeholder.
5. **990-EZ has no dedicated parser** — works only because the schedule name overlaps `IRS990`. Many EZ-specific fields are missed.

---

## 6. Frontend (`web/`)

Astro 5, **`output: 'static'`**. Every page is pre-rendered at build time by querying PostgreSQL. After build, the only runtime requirement is nginx.

### Page routes

| Route | File | Renders | Status |
|---|---|---|---|
| `/` | `pages/index.astro` | Hero + search form + 3 stat tiles (orgs, filings, "Free Public Data") | ✅ Works |
| `/search` | `pages/search.astro` | Reads `?q=` and lists matches | ⚠️ **Broken** — `Astro.url.searchParams` is empty in static builds |
| `/states` | `pages/states.astro` | Grid of all distinct states (`getDistinctStates`) | ✅ Works |
| `/state/{state}` | `pages/state/[state].astro` | All orgs in a state, paged 50/page | ⚠️ Pagination broken (`?page=N` lost in static output) |
| `/city/{city-state}` | `pages/city/[city].astro` | All orgs in a city. Slug format: `chicago-il` (last `-` split) | ⚠️ Pagination broken |
| `/category/{ntee}` | `pages/category/[ntee].astro` | All orgs in an NTEE major group | ⚠️ Pagination broken |
| `/{ein}/{slug}` | `pages/[ein]/[slug].astro` | **The org detail page** | ✅ Works |
| `/sitemap.xml` | `pages/sitemap.xml.js` | Sitemap of `/`, `/search`, `/states`, every org, every category | ✅ Works |
| `/404` | `pages/404.astro` | 404 with search box | ✅ Works |

### The org detail page (`/[ein]/[slug]`)
Structure top to bottom:
1. **Breadcrumb**: `Nonprofit Explorer / {state} / {org name}`.
2. **Hero**: Form-type badge (emerald), subsection badge with human label (`getSubsectionLabel`), NTEE category badge (blue). H1 = `canonical_name`. Meta row: EIN, location, tax-exempt-since year.
3. **Mission Statement** — `<MissionSection>` (blue pull-quote).
4. **DAF callout** — amber warning card if `parsed_data.daf_activity` is true.
5. **Financial Overview** — 2×2 grid of `<FinancialChart>` for `total_revenue`, `total_expenses`, `total_assets`, `total_liabilities`.
6. **Program Areas** — inline (NOT using `ProgramsSection.astro`). Splits `parsed_data.program_accomplishments` on `\n\s*\n`.
7. **Grants Made** — `<GrantsTable filingId={latestFiling.id}>` (own DB query).
8. **Executive Compensation** — `<CompensationTable filingId={latestFiling.id}>` (own DB query).
9. **Filing History** — one `<FilingCard>` per filing (newest first).
10. **Sidebar** (lg:sticky): organization details `dl/dt/dd`, Philanthropy.org Network cross-links, "Data last updated" stamp.

### Components

| Component | What it does |
|---|---|
| `BaseLayout.astro` | `<head>` with title/description/canonical/OG/Twitter/JSON-LD; sticky header; 4-column footer; defer-loads Alpine CDN; hand-rolls a Chart.js loader that finds every `canvas[data-years]` and instantiates a tabular-numerals line chart. |
| `FilingCard.astro` | Alpine `x-data="{ open: false }"` collapsible. 4 KPI tiles (revenue, expenses, assets, net income). Expanded: revenue breakdown + expense breakdown with %, balance sheet color-coded tiles, IRS.gov link + PDF link. ⚠️ The IRS PDF URL pattern (`apps.irs.gov/pub/epostcard/cor/{ein}_{year}_990_{object_id}.pdf`) is unverified. |
| `FinancialChart.astro` | Card with label + latest-year value formatted as USD. Renders a `<canvas data-years data-values data-color>` for hydration by the BaseLayout initializer. |
| `GrantsTable.astro` | Fixed-width 3-column table (Grantee / Purpose / Amount). Auto-links grantees that have an EIN. |
| `CompensationTable.astro` | 6-column table (Name / Title / Base / Bonus / Other / Total). |
| `MissionSection.astro` | Blue left-bar pull-quote, paragraph-split on `\n\s*\n`. |
| `ProgramsSection.astro` | ⚠️ **Dead code** — the org page inlines its own program rendering. |

### Libraries

#### `web/src/lib/db.ts`
- Singleton `pg.Pool({ connectionString: import.meta.env.DATABASE_URL })`.
- Throws on startup if `DATABASE_URL` is missing.
- 11 functions: `getOrganization`, `getFilings`, `getLatestFiling`, `getGrants`, `getCompensation`, `getOrganizationsByState`, `getOrganizationsByCity`, `getOrganizationsByNtee`, `searchOrganizations`, `getAllOrganizations`, `getDistinctStates`, `getDistinctNteeCodes`, `getDistinctCities`, `getStats`.
- ⚠️ `searchOrganizations` uses `canonical_name ILIKE '%q%'` — can't use the GIN trgm index because of the leading `%`.

#### `web/src/lib/ntee.ts`
- 26-entry `NTEE_MAP` (mirror of Python `NTEE_CODES`).
- `getNteeCategory(code)`, `getNteeSlug(code)`, `getNteeBySlug(slug)`, `getAllNteeCategories()`.

#### `web/src/lib/seo.ts`
- `formatEin('123456789')` → `'12-3456789'`.
- `slugify(name)` → `lowercase-with-dashes`.
- `generateTitle(name, ein)` → `"{name} - Form 990, EIN {ein}, Financials | Philanthropy.org"`.
- `generateMetaDescription(name, ein, city, state, latestYear)` → templated.
- `getSubsectionLabel('501(c)(3)')` → `"501(c)(3) — Charitable Organization"` (9 known mappings).
- `generateOrgSchema(...)` → `schema.org/NGO` JSON-LD with `PostalAddress` and `foundingDate`.

### Known frontend bugs
1. 🔴 **`/search` is broken** — `output: 'static'` does not preserve query strings. The page always renders the "Enter an organization name or EIN to search." empty state.
2. 🔴 **All paginated pages (`?page=N`)** — same root cause. Only page 1 is ever reachable.
3. 🔴 **Docker port mapping is wrong** — `docker-compose.yml` maps `3000:4321` but the `nginx:alpine` container listens on `80`. Should be `3000:80`.
4. 🟠 **Build time / size will explode at scale** — `getAllOrganizations()` for 600k orgs = 600k pre-rendered HTML pages. Need to filter (e.g. only orgs with ≥1 filing or top-N by revenue) or move to on-demand rendering.
5. 🟠 **NTEE_MAP duplicated** between `pipeline/bmf_loader.py` and `web/src/lib/ntee.ts`.
6. 🟡 `CHART_JS_CDN` constant in `BaseLayout.astro` is defined but unused — the URL is hardcoded again inside the loader function.
7. 🟡 `ProgramsSection.astro` is dead code.
8. 🟡 `web/.env` contains real dev credentials and should be moved to `.env.example`.
9. 🟡 Two `state` page files exist: `pages/state/[state].astro` and an empty `pages/states/` directory inside dist — verify only one canonical route survives.

---

## 7. Data Sources

### Primary: GivingTuesday 990 Data Lake (pre-2022 + 2022+)
- **S3 bucket**: `s3://gt990datalake-rawdata`
- **Key prefix**: `EfileData/XmlFiles/`
- **Coverage**: all years 2011-2024 (the only source for pre-2022).
- **File naming convention**: `{YEAR}{SEQUENCE}_public.xml` (e.g. `202401301234567_public.xml`).
- **Access**: requires anonymous S3 access. AWS CLI needs `--no-sign-request --no-verify-ssl` flags.

### Secondary: IRS TEOS (2022 onwards)
- **Base URL**: `https://apps.irs.gov/pub/epostcard/990/xml/{YEAR}/`
- **Coverage**: 2022, 2023, 2024+ only.
- **Use case**: faster / cleaner source for recent years; mirror of part of the GivingTuesday lake.
- ⚠️ **Pre-2022 data is ONLY available from the GivingTuesday lake.**

### Tertiary: NCCS Business Master File (BMF)
- **URL**: `https://nccsdata.s3.us-east-1.amazonaws.com/raw/bmf/{YYYY-MM}-BMF.csv`
- **Provides**: NTEE codes, ruling date, deductibility status, subsection — fields not always present in filings.
- **Status**: download is disabled in `sync.py`. If you want BMF enrichment, manually drop `bmf_extract.csv` into `./data/bmf/` before running sync.

### Expected on-disk layout after download
```
data/
├── zips/                          ← raw downloaded archives (optional)
├── temp_extract/                  ← unzipping workspace
├── raw_xml/
│   └── {EIN}/{YEAR}/{object_id}.xml
└── bmf/
    └── bmf_extract.csv            ← optional NCCS BMF
```

The pipeline expects `raw_xml/{EIN}/{YEAR}/*.xml`. If GivingTuesday files arrive in a flat directory, you must reorganize them by EIN and year before running (or extend `sync.py` to handle flat layouts).

---

## 8. Current Status

### What works right now
- ✅ Database schema applies cleanly; `pg_trgm` extension auto-enabled.
- ✅ `pipeline/sync.py` end-to-end on the 7 dry-run organizations.
- ✅ All 7 dry-run org pages render correctly (HTML in `web/dist/`).
- ✅ Org detail page rendering: mission, financial charts (Chart.js), DAF callout, grants table, compensation table, filing cards (Alpine collapsible), sidebar, JSON-LD schema.
- ✅ Static homepage with live counts.
- ✅ `/states`, `/state/{abbr}` (page 1), `/category/{ntee}` (page 1).
- ✅ `/sitemap.xml` generation.
- ✅ Idempotent ingestion via `ON CONFLICT (object_id)` and `filing_exists()`.
- ✅ 990 and 990-PF parsers handle nearly all real-world cases observed.

### What is broken
- 🔴 `/search` page (static build can't read query strings).
- 🔴 All `?page=N` pagination across state / city / category pages.
- 🔴 Docker `web` service port mapping (`3000:4321` instead of `3000:80`).
- 🟠 BMF download in `sync_bmf()` is hard-disabled — orgs without a 990 won't appear; NTEE/ruling-date enrichment lost.
- 🟠 `searchOrganizations` cannot use the trgm GIN index due to leading-wildcard `ILIKE`.

### What has never been built
- ❌ Full data load — only 7 dry-run orgs are in the system.
- ❌ Production deployment (Hetzner + Cloudflare combo planned, not provisioned).
- ❌ Entity resolution / name variant tracking (`organization_names` table exists but is unused).
- ❌ Client-side search (the broken `/search` page needs replacing with Pagefind or a client fetch to a JSON index).
- ❌ Path-segment pagination (`/state/ca/page/2`).
- ❌ Incremental / scheduled sync (cron, GitHub Actions, anything).
- ❌ Monitoring, alerting, error reporting.
- ❌ Tests — no unit tests, no integration tests, no fixtures.
- ❌ CI/CD pipeline.
- ❌ XML download script — must be done manually with AWS CLI.

---

## 9. Known Bugs — by Severity

### 🔴 Critical (block production deployment)

| # | Bug | File | Effect |
|---|---|---|---|
| C1 | `/search` page broken under static build | `web/src/pages/search.astro` | Always shows empty state — search is non-functional |
| C2 | All `?page=N` pagination broken | `state/[state].astro`, `city/[city].astro`, `category/[ntee].astro` | Only page 1 of every list is reachable |
| C3 | Docker web port mismatch | `docker-compose.yml` (`3000:4321`) vs `web/Dockerfile` (nginx on 80) | `docker compose up web` is unreachable from the host |

### 🟠 High (must address before scaling)

| # | Bug | File | Effect |
|---|---|---|---|
| H1 | BMF download disabled | `pipeline/sync.py` `sync_bmf()` | Orgs without a 990 missing; NTEE/ruling enrichment absent |
| H2 | Connection-per-row inserts | `pipeline/db.py` (every helper) | Ingestion will be ~10× slower than necessary; risks connection exhaustion |
| H3 | `raw_xml TEXT` stored inline | `db/schema.sql` `filings` table | ~30GB+ bloat at full scale |
| H4 | `searchOrganizations` leading-wildcard | `web/src/lib/db.ts`, `pipeline/db.py` | Trigram GIN index unused; full scan on 600k rows |
| H5 | `getAllOrganizations()` for `getStaticPaths` | `web/src/pages/[ein]/[slug].astro` | Build time / disk usage explodes at 600k orgs |

### 🟡 Medium

| # | Bug | File | Effect |
|---|---|---|---|
| M1 | NTEE map duplicated | `pipeline/bmf_loader.py` (`NTEE_CODES`) + `web/src/lib/ntee.ts` (`NTEE_MAP`) | Silent drift risk |
| M2 | `gen_frontend.py` would overwrite `BaseLayout.astro` | `gen_frontend.py` | Run by accident → loses polished layout |
| M3 | `ProgramsSection.astro` is dead code | `web/src/components/ProgramsSection.astro` | Confusion / drift |
| M4 | `CHART_JS_CDN` constant unused | `web/src/layouts/BaseLayout.astro` | URL hardcoded twice |
| M5 | `web/.env` checked in with creds | `web/.env` | Should be `.env.example` |
| M6 | `grants.grantee_ein` has no index | `db/schema.sql` | Slow reverse lookups |
| M7 | `backfill_bmf_fields` dead code | `pipeline/db.py` | Never called |
| M8 | `organization_names` never populated | `db/schema.sql` + pipeline | Phase 2 placeholder |
| M9 | Filing PDF URL pattern unverified | `web/src/components/FilingCard.astro` | Probably 404s on IRS.gov |
| M10 | 990-EZ has no dedicated parser | `pipeline/parse_irsx.py` | Sparse data for EZ filers |
| M11 | Root `package.json` orphan | `/package.json` | Lists `alpinejs` but Alpine is CDN-loaded |
| M12 | `data/raw_xml` empty | — | Pipeline has nothing to ingest |

### 🟢 Low / Cleanup
- Whitespace/trailing spaces in several `.astro` files (post-line content like `--- \n`).
- `web/dist/states/` vs `web/dist/state/` — verify only one canonical route exists.

---

## 10. Next Steps — In Priority Order

### Phase 1 — Fix the 3 critical bugs (1-2 days)
1. **Fix `/search`** — convert to client-side search. Cheapest path: pre-generate a `pagefind` index against `dist/`, or emit `/search-index.json` (EIN + name + state) at build time and have `search.astro` ship a small Alpine fetch + filter. Avoid hybrid SSR until necessary.
2. **Fix pagination** — convert `?page=N` to path segments and generate via `getStaticPaths`. E.g. `/state/ca/` → `/state/ca/page/2`. Update internal links in `state/[state].astro`, `city/[city].astro`, `category/[ntee].astro`.
3. **Fix Docker port mapping** — change `docker-compose.yml` web service to `3000:80`.

### Phase 2 — Get the data (2-3 days)
4. **Download 2020-2024 from GivingTuesday lake** (commands in section 12).
5. **Reorganize files** into `data/raw_xml/{EIN}/{YEAR}/{object_id}.xml` layout.
6. **Optional: drop NCCS BMF CSV** into `data/bmf/bmf_extract.csv` for enrichment.

### Phase 3 — Run the pipeline (1 day, depending on volume)
7. Spin up Postgres: `docker compose up -d db`.
8. Run pipeline: `docker compose run --rm pipeline`.
9. Watch `sync.log` for `ERROR` and `SKIP` rates.

### Phase 4 — Verify (½ day)
10. **Verify all 7 dry-run orgs still render correctly** after the build with real data:
    - `042103580` (Harvard)
    - `131635294`, `131644147`, `232657933`, `530196605`, `620646012`, `911663695`
11. Spot-check 20 random orgs for: working charts, mission text, no empty pages, correct filing counts.
12. Validate `sitemap.xml` size and that 50 random URLs in it resolve.

### Phase 5 — Production deployment (2-3 days)
13. **Hetzner**: provision a VPS (CX31 or CX41 minimum given the build's memory footprint). Install Docker, docker-compose. Deploy compose stack.
14. **Cloudflare**: point `nonprofits.philanthropy.org` at the VPS. Enable proxy, full-strict TLS, page rules to cache `/_astro/*` and `*.html` aggressively (the site is fully static).
15. Set `PUBLIC_SITE_URL=https://nonprofits.philanthropy.org` for the build.
16. Configure a cron/GitHub Action to re-run sync monthly when new IRS bulk data drops, then re-build the site.

### Phase 6 — Scale (ongoing)
17. Address H1–H5 (BMF, connection pooling, raw_xml externalization, search index, build-time filtering).
18. Wire up monitoring (Sentry / simple uptime monitor).
19. Build out client-side filtering on directory pages.

---

## 11. How to Run Everything

> **All commands assume Windows PowerShell at `C:\Users\91937\Desktop\nonprofit-platform`.**

### 11.1 Prerequisites
- Docker Desktop running.
- Node 20+ installed (for local frontend dev).
- Python 3.12 + pip installed (optional — pipeline runs in Docker).
- AWS CLI installed (for downloading IRS data).

### 11.2 Start the database
```powershell
docker compose up -d db
```
Wait ~10 seconds for the healthcheck (`pg_isready`) to pass. Postgres is now on `localhost:5433` with database `nonprofit_platform`, user `nonprofit`, password `devpassword`.

To verify:
```powershell
docker compose exec db psql -U nonprofit -d nonprofit_platform -c "\dt"
```
You should see 7 tables: `organizations`, `organization_names`, `filings`, `grants`, `compensation`, `program_accomplishments`, `mission_statements`.

### 11.3 Run the pipeline
After you have XML files in `data/raw_xml/{EIN}/{YEAR}/`:

**Option A — Docker (recommended, matches production)**
```powershell
docker compose run --rm pipeline
```
This runs `python sync.py` inside the container.

**Option B — Local Python (faster iteration)**
```powershell
cd pipeline
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
$env:DATABASE_URL = "postgresql://nonprofit:devpassword@localhost:5433/nonprofit_platform"
$env:RAW_XML_DIR  = "..\data\raw_xml"
$env:BMF_DIR      = "..\data\bmf"
python sync.py
```

Watch for log lines:
```
OK  042103580/2023 | 990    | grants=12   comp=8   mission=YES
SKIP ... — Already in database
Progress: 1000 files (X parsed, Y skipped, Z errors) — N.N files/sec
```

A `sync.log` will be written in the working directory.

### 11.4 Build the frontend
```powershell
cd web
npm install                       # one-time
npm run build                     # static build → web/dist/
```

`npm run build` (a.k.a. `astro build`) queries the database for every org and emits one HTML file per org under `web/dist/{ein}/{slug}/index.html`, plus all directory pages, plus `sitemap.xml`.

For development (live reload, hot HMR):
```powershell
cd web
npm run dev
```
Astro dev server runs on `http://localhost:4321`.

### 11.5 Serve the built site locally
**Option A — directly via Astro preview**
```powershell
cd web
npm run preview                   # localhost:4321
```

**Option B — full Docker stack (requires fixing the port mapping bug C3 first)**
```powershell
# After fixing docker-compose.yml web service to "3000:80":
docker compose up --build web
# Open http://localhost:3000
```

### 11.6 Access the database directly
```powershell
docker compose exec db psql -U nonprofit -d nonprofit_platform
```
Useful sanity queries:
```sql
SELECT count(*) FROM organizations;
SELECT count(*) FROM filings;
SELECT ein, canonical_name, tax_year_latest FROM organizations ORDER BY tax_year_latest DESC LIMIT 10;
SELECT ein, count(*) AS filing_count FROM filings GROUP BY ein ORDER BY filing_count DESC LIMIT 10;
```

### 11.7 Reset everything
```powershell
docker compose down -v             # wipes pgdata volume
Remove-Item -Recurse -Force web\dist, web\.astro
```

---

## 12. Download Commands for IRS Data

### 12.1 GivingTuesday 990 Data Lake (covers 2011-2024)

Bucket: `s3://gt990datalake-rawdata`
Key prefix: `EfileData/XmlFiles/`
Required flags: `--no-sign-request --no-verify-ssl`

**List what's available for a year:**
```powershell
aws s3 ls s3://gt990datalake-rawdata/EfileData/XmlFiles/ --no-sign-request --no-verify-ssl
```

**Download a specific year (e.g. 2024):**
```powershell
aws s3 sync s3://gt990datalake-rawdata/EfileData/XmlFiles/2024/ data\zips\2024\ --no-sign-request --no-verify-ssl
```

**Download 2020–2024 sequentially:**
```powershell
foreach ($yr in 2020,2021,2022,2023,2024) {
  aws s3 sync "s3://gt990datalake-rawdata/EfileData/XmlFiles/$yr/" "data\zips\$yr\" --no-sign-request --no-verify-ssl
}
```

**Download 2011–2019 (pre-2022 — only available here):**
```powershell
foreach ($yr in 2011..2019) {
  aws s3 sync "s3://gt990datalake-rawdata/EfileData/XmlFiles/$yr/" "data\zips\$yr\" --no-sign-request --no-verify-ssl
}
```

### 12.2 IRS TEOS direct (2022+ only)

```powershell
# List a year's zip files
Invoke-WebRequest "https://apps.irs.gov/pub/epostcard/990/xml/2024/" -OutFile data\indexes\2024.html

# Download a specific zip (example pattern — adjust to actual filenames listed in the page)
Invoke-WebRequest "https://apps.irs.gov/pub/epostcard/990/xml/2024/2024_TEOS_XML_01A.zip" -OutFile data\zips\2024\2024_TEOS_XML_01A.zip
```

### 12.3 Where to store the downloads

```
data/
├── zips/{YEAR}/                  ← raw downloaded archives
├── temp_extract/                 ← unzip workspace
└── raw_xml/{EIN}/{YEAR}/         ← final layout consumed by sync.py
```

### 12.4 Extract + reorganize into pipeline layout

The pipeline expects `data/raw_xml/{EIN}/{YEAR}/{object_id}.xml`. After unzipping, files will be flat with names like `202401301234567_public.xml` where the digits encode `{tax_year}{sequence}`. You'll need a small reorganizer — quick one-liner:

```powershell
# Unzip everything for a year
Expand-Archive -Path "data\zips\2024\*.zip" -DestinationPath "data\temp_extract\2024"

# Walk the flat output and route each file to data\raw_xml\{EIN}\{YEAR}\
# (The EIN is inside the XML itself — easiest path is to parse the header.
#  Until a reorganizer script is added, sync.py expects you to pre-route them.)
```

> **TODO**: write `pipeline/organize_xml.py` that walks `data/temp_extract/{year}/` and routes each XML into `data/raw_xml/{ein}/{year}/` using a fast `lxml` header parse. This script does not exist yet.

### 12.5 Optional: NCCS BMF CSV

```powershell
curl.exe "https://nccsdata.s3.us-east-1.amazonaws.com/raw/bmf/2025-12-BMF.csv" -o data\bmf\bmf_extract.csv
```

If the latest month is missing, try the previous month (`2025-11-BMF.csv`, etc.).

### 12.6 Run the pipeline against the downloaded data

```powershell
docker compose up -d db
docker compose run --rm pipeline
```

Then build the frontend:
```powershell
cd web; npm run build
```

Verify the 7 dry-run orgs still render correctly by spot-checking `web/dist/`:
```
web/dist/042103580/president-and-fellows-of-harvard-college/index.html
web/dist/131635294/.../index.html
web/dist/131644147/.../index.html
web/dist/232657933/.../index.html
web/dist/530196605/.../index.html
web/dist/620646012/.../index.html
web/dist/911663695/.../index.html
```

---

## Appendix A — Key file cheatsheet

| Need to... | Open... |
|---|---|
| Add a new financial field to org pages | `pipeline/parse_irsx.py` (parsed dict) + `web/src/components/FilingCard.astro` + `web/src/components/FinancialChart.astro` |
| Add a new NTEE category | `pipeline/bmf_loader.py` `NTEE_CODES` **and** `web/src/lib/ntee.ts` `NTEE_MAP` (keep in sync) |
| Change SEO title format | `web/src/lib/seo.ts` `generateTitle` |
| Add a new directory page (e.g. by state + NTEE) | new file in `web/src/pages/` with `getStaticPaths`, query function in `web/src/lib/db.ts` |
| Change the database schema | `db/schema.sql` (re-create DB to apply; `docker compose down -v` first) |
| Tune the IRS XML parser | `pipeline/parse_irsx.py` |
| Add a new IRS schedule | `pipeline/parse_irsx.py` `parse_990` (use `f.get_schedule('IRS990ScheduleX')`) |
| Re-style the site | `web/src/styles/global.css` + Tailwind classes in components |

## Appendix B — Quick win checklist

- [ ] Fix C3 (Docker port: `3000:4321` → `3000:80` in `docker-compose.yml`)
- [ ] Fix C1 (`/search` page — replace with client-side index)
- [ ] Fix C2 (path-segment pagination)
- [ ] Delete `gen_frontend.py` (or move to `scripts/archive/`)
- [ ] Delete `web/src/components/ProgramsSection.astro` (dead code)
- [ ] Move `web/.env` → `web/.env.example`
- [ ] Add `pipeline/organize_xml.py` reorganizer
- [ ] Re-enable BMF download in `pipeline/sync.py`
- [ ] Refactor `pipeline/db.py` to share one connection per file
- [ ] Add `CREATE INDEX idx_grants_grantee_ein ON grants(grantee_ein);` to schema
- [ ] Add `LIMIT` filter to `getAllOrganizations()` for build-time scaling
- [ ] Verify IRS PDF URL pattern in `FilingCard.astro` (or remove the link)
