#!/usr/bin/env python3
"""One-shot: sheet (or fail) → ticker cache → Filtered Stream rules.

Same work as the twice-daily scheduler job. Does not detect posts.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.rules_sync import sync_rules_to_x  # noqa: E402
from src.scheduler import refresh_job  # noqa: E402
from src.sheet_sync import sync_from_csv  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--csv", type=Path, help="Use CSV instead of Google Sheet")
    p.add_argument("--dry-run-rules", action="store_true")
    args = p.parse_args()
    if args.csv:
        print(json.dumps(sync_from_csv(args.csv), indent=2))
        print(json.dumps(sync_rules_to_x(dry_run=args.dry_run_rules), indent=2, default=str))
        return 0
    if args.dry_run_rules:
        print(json.dumps(sync_rules_to_x(dry_run=True), indent=2, default=str))
        return 0
    refresh_job()
    return 0


if __name__ == "__main__":
    sys.exit(main())
