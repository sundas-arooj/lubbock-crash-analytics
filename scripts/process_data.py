"""Build the crash-level SQLite database from the CRIS export."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.cleaning import SEVERITY_ORDER, load_export
from app.database import connect, write_database
from app.metrics import parse_filters, severity_counts, top_factors


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--csv",
        type=Path,
        default=ROOT / "district_crashes.csv",
        help="Path to the TxDOT CRIS export.",
    )
    parser.add_argument(
        "--db",
        type=Path,
        default=ROOT / "data" / "processed" / "crashes.db",
        help="Where to write the processed database.",
    )
    args = parser.parse_args()

    export = load_export(args.csv)
    destination = write_database(export, args.db)
    connection = connect(destination)
    try:
        filters = parse_filters()
        counts = severity_counts(connection, filters)
        factors = top_factors(connection, filters, limit=10)
    finally:
        connection.close()

    coded = {item["severity"]: item["count"] for item in counts}
    deaths = sum(crash.death_count for crash in export.crashes)
    unmapped = sum(1 for crash in export.crashes if crash.latitude is None)
    without_factors = sum(1 for crash in export.crashes if not crash.factors)
    print(f"Person rows read: {export.person_rows:,}")
    print(f"Crashes written:  {len(export.crashes):,}")
    print(f"District:         {export.district or 'unknown'}")
    print(f"Extract as of:    {export.source_as_of or 'unknown'}")
    print("Severity:")
    for code in SEVERITY_ORDER:
        print(f"  {code}  {coded.get(code, 0):,}")
    print(f"Deaths:           {deaths:,}")
    print(f"No coordinates:   {unmapped:,}")
    print(f"No coded factor:  {without_factors:,}")
    print("Top factors:")
    for item in factors:
        print(f"  {item['rank']:>2}. {item['factor']} ({item['count']:,})")
    print(f"Wrote {destination}")


if __name__ == "__main__":
    main()
