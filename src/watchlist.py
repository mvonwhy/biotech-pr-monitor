"""CLI for source accounts + local ticker cache (not live sheet writes).

Examples:
  python -m src.watchlist accounts list
  python -m src.watchlist tickers list
  python -m src.watchlist tickers add MRNA GILD
  python -m src.watchlist tickers remove MRNA
  python -m src.watchlist rules preview
"""

from __future__ import annotations

import argparse
import json
import sys

from src.config import SOURCE_ACCOUNTS_PATH, TICKER_CACHE_PATH
from src.tickers import (
    build_stream_rules,
    load_source_accounts,
    load_tickers,
    save_tickers,
)


def cmd_accounts_list(_: argparse.Namespace) -> int:
    print(json.dumps({"accounts": load_source_accounts()}, indent=2))
    return 0


def cmd_tickers_list(_: argparse.Namespace) -> int:
    print(json.dumps({"tickers": load_tickers(), "path": str(TICKER_CACHE_PATH)}, indent=2))
    return 0


def cmd_tickers_add(args: argparse.Namespace) -> int:
    current = load_tickers()
    merged = current + list(args.symbols)
    save_tickers(merged, source="cli:add")
    print(json.dumps({"tickers": load_tickers()}, indent=2))
    return 0


def cmd_tickers_remove(args: argparse.Namespace) -> int:
    drop = {s.strip().upper().lstrip("$") for s in args.symbols}
    kept = [t for t in load_tickers() if t not in drop]
    save_tickers(kept, source="cli:remove")
    print(json.dumps({"tickers": load_tickers()}, indent=2))
    return 0


def cmd_rules_preview(_: argparse.Namespace) -> int:
    rules = build_stream_rules()
    print(json.dumps({"count": len(rules), "rules": rules}, indent=2))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="X PR Monitor watchlist / ticker CLI")
    sub = parser.add_subparsers(dest="group", required=True)

    accounts = sub.add_parser("accounts", help=f"Source X accounts ({SOURCE_ACCOUNTS_PATH})")
    acc_sub = accounts.add_subparsers(dest="action", required=True)
    acc_sub.add_parser("list").set_defaults(func=cmd_accounts_list)

    tickers = sub.add_parser("tickers", help="Local ticker cache (sheet sync is preferred)")
    tic_sub = tickers.add_subparsers(dest="action", required=True)
    tic_sub.add_parser("list").set_defaults(func=cmd_tickers_list)
    add_p = tic_sub.add_parser("add")
    add_p.add_argument("symbols", nargs="+")
    add_p.set_defaults(func=cmd_tickers_add)
    rm_p = tic_sub.add_parser("remove")
    rm_p.add_argument("symbols", nargs="+")
    rm_p.set_defaults(func=cmd_tickers_remove)

    rules = sub.add_parser("rules", help="Preview Filtered Stream rules")
    rules_sub = rules.add_subparsers(dest="action", required=True)
    rules_sub.add_parser("preview").set_defaults(func=cmd_rules_preview)

    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    sys.exit(main())
