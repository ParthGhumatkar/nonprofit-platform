"""
Select 100 organizations for a demo dataset: 10 pinned EINs plus
the top 90 by latest-filing revenue. Writes EINs to data/demo_eins.txt.
"""

import os
import logging

from db import get_conn

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

PROJECT = os.getenv(
    "PROJECT_DIR",
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
)
OUTPUT_PATH = os.path.join(PROJECT, "data", "demo_eins.txt")

# Always include these 10 (order preserved in output)
PINNED_EINS = [
    "232657933",  # Lehigh Valley United Way
    "042103580",  # Harvard
    "620646012",  # St. Jude
    "530196605",  # American Red Cross
    "363673599",  # Feeding America
    "237327031",  # Habitat for Humanity
    "042105820",  # MIT
    "956032310",  # Stanford
    "237431709",  # Gates Foundation
    "131635294",  # United Way Worldwide
]


def select_demo_eins():
    """Return ordered list of 100 EINs: pinned first, then top 90 by revenue."""
    pinned = PINNED_EINS

    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT DISTINCT o.ein
            FROM organizations o
            JOIN filings f ON f.ein = o.ein
            WHERE o.ein NOT IN %s
            ORDER BY (
                SELECT (parsed_data->>'total_revenue')::numeric
                FROM filings f2
                WHERE f2.ein = o.ein
                ORDER BY tax_year DESC
                LIMIT 1
            ) DESC NULLS LAST
            LIMIT 90
            """,
            (tuple(pinned),),
        )
        top90 = [row[0] for row in cur.fetchall()]

    return pinned + top90


def fetch_summary_rows(eins):
    """Fetch display fields for the summary table, in EIN list order."""
    if not eins:
        return []

    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT
                o.ein,
                o.canonical_name,
                o.city,
                o.state,
                (
                    SELECT parsed_data->>'total_revenue'
                    FROM filings f
                    WHERE f.ein = o.ein
                    ORDER BY tax_year DESC
                    LIMIT 1
                ) AS revenue,
                (
                    SELECT form_type
                    FROM filings f
                    WHERE f.ein = o.ein
                    ORDER BY tax_year DESC
                    LIMIT 1
                ) AS form_type
            FROM organizations o
            WHERE o.ein = ANY(%s)
            """,
            (eins,),
        )
        by_ein = {row[0]: row for row in cur.fetchall()}

    return [by_ein[ein] for ein in eins if ein in by_ein]


def format_revenue(val):
    if val is None:
        return "-"
    try:
        n = float(val)
    except (TypeError, ValueError):
        return str(val)
    if n >= 1e9:
        return f"${n / 1e9:.2f}B"
    if n >= 1e6:
        return f"${n / 1e6:.2f}M"
    if n >= 1e3:
        return f"${n / 1e3:.0f}K"
    return f"${n:.0f}"


def print_summary(rows):
    """Print ein | name | city | state | revenue | form_type."""
    headers = ("ein", "name", "city", "state", "revenue", "form_type")
    col_widths = [9, 42, 18, 6, 12, 8]

    def fmt_row(cells):
        parts = []
        for i, cell in enumerate(cells):
            s = str(cell) if cell is not None else "-"
            if i == 1 and len(s) > col_widths[i]:
                s = s[: col_widths[i] - 1] + "…"
            parts.append(s.ljust(col_widths[i])[: col_widths[i]])
        return " | ".join(parts)

    print(fmt_row(headers))
    print("-+-".join("-" * w for w in col_widths))
    for ein, name, city, state, revenue, form_type in rows:
        print(
            fmt_row(
                (
                    ein,
                    name or "-",
                    city or "-",
                    state or "-",
                    format_revenue(revenue),
                    form_type or "-",
                )
            )
        )


def write_eins_file(eins, path):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        for ein in eins:
            f.write(f"{ein}\n")
    logger.info("Wrote %d EINs to %s", len(eins), path)


def main():
    eins = select_demo_eins()
    if len(eins) != 100:
        logger.warning("Expected 100 EINs, got %d", len(eins))

    write_eins_file(eins, OUTPUT_PATH)

    rows = fetch_summary_rows(eins)
    print(f"\nDemo set: {len(eins)} organizations ({len(PINNED_EINS)} pinned + {len(eins) - len(PINNED_EINS)} by revenue)\n")
    print_summary(rows)

    missing = set(eins) - {r[0] for r in rows}
    if missing:
        logger.warning("No organization row for EINs: %s", ", ".join(sorted(missing)))


if __name__ == "__main__":
    main()
