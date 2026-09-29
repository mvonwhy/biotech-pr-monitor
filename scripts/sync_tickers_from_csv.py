#!/usr/bin/env python3
"""Manual CSV → local ticker cache (when Google API creds are not set).

CSV must have a Ticker column (or pass --column). Never writes to Google Sheet.

  python scripts/sync_tickers_from_csv.py /path/to/export.csv
  python scripts/sync_tickers_from_csv.py export.csv --sync-rules
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.rules_sync import sync_rules_to_x  # noqa: E402
from src.sheet_sync import sync_from_csv  # noqa: E402


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("csv_path", type=Path)
    p.add_argument("--column", default="Ticker")
    p.add_argument("--sync-rules", action="store_true", help="Also push Filtered Stream rules to X")
    p.add_argument("--dry-run-rules", action="store_true")
    args = p.parse_args()
    if not args.csv_path.exists():
        print(f"ERROR: {args.csv_path} not found", file=sys.stderr)
        return 2
    summary = sync_from_csv(args.csv_path, column=args.column)
    print(json.dumps(summary, indent=2))
    if args.sync_rules or args.dry_run_rules:
        print(json.dumps(sync_rules_to_x(dry_run=args.dry_run_rules), indent=2, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
