# pipeline/build_manifest.py (v2 — improved)
# Uses master index directly for org selection + download URLs
import os
import pandas as pd

PROJECT   = os.getenv("PROJECT_DIR", os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
INDEX_SRC = os.getenv("MASTER_INDEX", os.path.join(PROJECT, "data", "indexes", "master_index.parquet"))
TARGET    = int(os.getenv("TARGET_ORGS", "25000"))
YEARS     = {"2020", "2021", "2022", "2023", "2024"}
FORMS     = {"990", "990EZ", "990PF"}  # skip 990T and 990N per brief

# ── Load master index ────────────────────────────────────────
print("Loading master_index.parquet...")
idx = pd.read_parquet(INDEX_SRC)
idx.columns = [c.strip().upper() for c in idx.columns]
print(f"Total rows: {len(idx):,}")

# ── Clean types ──────────────────────────────────────────────
idx["EIN"]       = idx["EIN"].astype(str).str.strip().str.zfill(9)
idx["TAXYEAR"]   = idx["TAXYEAR"].astype(str).str[:4]
idx["OBJECTID"]  = idx["OBJECTID"].astype(str).str.strip()

# Numeric columns for ranking
for col in ["TOTALREVENUECY", "TOTALASSETSBKEOY", "TOTALEXPENSESCY"]:
    idx[col] = pd.to_numeric(idx[col], errors="coerce").fillna(0)

# ── Filter to 2020-2024 + valid form types ───────────────────
pool = idx[
    idx["TAXYEAR"].isin(YEARS) &
    idx["FORMTYPE"].isin(FORMS)
].copy()

print(f"\n2020-2024 filings (990/EZ/PF only): {len(pool):,}")
print(pool["TAXYEAR"].value_counts().sort_index())
print(pool["FORMTYPE"].value_counts())

# ── Select 25K orgs by actual revenue (not BMF code) ─────────
# Use max revenue across all filings per EIN as ranking metric
ein_revenue = pool.groupby("EIN")["TOTALREVENUECY"].max().reset_index()
ein_revenue.columns = ["EIN", "MAX_REVENUE"]
top_eins = set(
    ein_revenue.nlargest(TARGET, "MAX_REVENUE")["EIN"].tolist()
)

print(f"\nSelected {len(top_eins):,} EINs by highest revenue")

# ── Build manifest for those orgs ────────────────────────────
manifest = pool[pool["EIN"].isin(top_eins)][[
    "EIN", "OBJECTID", "TAXYEAR", "FORMTYPE", "URL",
    "ORGANIZATIONNAME", "TOTALREVENUECY", "TOTALASSETSBKEOY",
    "TOTALEXPENSESCY"
]].copy()

manifest.columns = [
    "EIN", "OBJECT_ID", "FILING_YEAR", "FORM_TYPE", "URL",
    "ORG_NAME", "TOTAL_REVENUE", "TOTAL_ASSETS", "TOTAL_EXPENSES"
]

# ── Stats ────────────────────────────────────────────────────
print(f"\n{'='*55}")
print(f"Total filings to download: {len(manifest):,}")
print(f"\nBy year:")
print(manifest["FILING_YEAR"].value_counts().sort_index())
print(f"\nBy form type:")
print(manifest["FORM_TYPE"].value_counts())
print(f"\nUnique orgs: {manifest['EIN'].nunique():,}")

# Year coverage per org
coverage = manifest.groupby("EIN")["FILING_YEAR"].nunique()
print(f"\nYear coverage per org:")
print(coverage.value_counts().sort_index().to_string())

# Top 5 orgs by revenue
top5 = manifest.drop_duplicates("EIN").nlargest(5, "TOTAL_REVENUE")
print(f"\nTop 5 orgs by revenue:")
for _, r in top5.iterrows():
    rev = r['TOTAL_REVENUE']
    print(f"  {r['EIN']} | {r['ORG_NAME'][:50]:50s} | ${rev:>15,.0f}")

est_gb = (len(manifest) * 180) / (1024 * 1024)  # KB → GB
print(f"\nEstimated download: ~{est_gb:.1f} GB")

# ── Save ─────────────────────────────────────────────────────
os.makedirs(os.path.join(PROJECT, "data", "indexes"), exist_ok=True)
manifest.to_csv(os.path.join(PROJECT, "data", "indexes", "download_manifest.csv"), index=False)
print(f"Saved → data/indexes/download_manifest.csv")
