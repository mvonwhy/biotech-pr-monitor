#!/usr/bin/env python3
"""Run X Filtered Stream (GET /2/tweets/search/stream) forever.

Active ingest path under Pay Per Use (no Enterprise webhook attach).
Rules stay on /2/tweets/search/stream/rules — optionally synced at start.

Usage:
  cd /workspace/x-pr-monitor
  PYTHONPATH=. .venv/bin/python scripts/run_filtered_stream.py
  # or:
  PYTHONPATH=. .venv/bin/python -m scripts.run_filtered_stream

  # skip one-time rules sync:
  PYTHONPATH=. .venv/bin/python scripts/run_filtered_stream.py --no-sync-rules
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.config import require_env  # noqa: E402
from src.rules_sync import sync_rules_to_x  # noqa: E402
from src.secrets import OnePasswordError, verify_startup_secrets  # noqa: E402
from src.stream_client import (  # noqa: E402
    StreamStatus,
    configure_stream_logging,
    run_forever,
)
from src.x_api import XClient  # noqa: E402

logger = logging.getLogger("x_pr_monitor.run_stream")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--sync-rules",
        dest="sync_rules",
        action="store_true",
        default=True,
        help="Sync rules to X once at start (default: True)",
    )
    parser.add_argument(
        "--no-sync-rules",
        dest="sync_rules",
        action="store_false",
        help="Do not sync rules; only verify they exist",
    )
    args = parser.parse_args()

    configure_stream_logging()
    logging.getLogger().setLevel(logging.INFO)

    try:
        secret_status = verify_startup_secrets(require_secret=True)
    except OnePasswordError as e:
        print(f"ERROR: secrets: {e}", file=sys.stderr)
        return 1

    print("Secrets status (names only):", secret_status)

    bearer = require_env("X_BEARER_TOKEN")
    client = XClient(bearer)
    rules = client.get_rules()
    rule_count = len(rules)
    print(f"Rules on X: {rule_count}")

    if rule_count == 0 or args.sync_rules:
        if rule_count == 0:
            print("No rules on X — syncing from ticker cache…")
        else:
            print("Syncing rules once at start (--sync-rules)…")
        summary = sync_rules_to_x(dry_run=False)
        # Refresh count after sync
        rules = client.get_rules()
        rule_count = len(rules)
        print(
            "Rules sync done:",
            {
                "rule_count": summary.get("rule_count"),
                "ticker_count": summary.get("ticker_count"),
                "accounts": summary.get("accounts"),
                "fingerprint": (summary.get("fingerprint") or "")[:12],
                "skipped": summary.get("skipped"),
            },
        )
        print(f"Rules on X after sync: {rule_count}")

    if rule_count == 0:
        print("ERROR: still zero rules on X — refusing to open empty stream", file=sys.stderr)
        return 2

    status = StreamStatus()
    status.update(rule_count=rule_count, connected=False, alerts_accepted=0)

    print(
        f"Starting Filtered Stream (rules={rule_count}). "
        "Status → logs/stream_status.json ; logs → logs/stream.log"
    )
    print("Pay Per Use: X charges per matched post on this connection.")
    try:
        run_forever(bearer, status=status)
    except KeyboardInterrupt:
        print("Interrupted — stream stopped.")
        status.update(connected=False)
        return 0

    snap = status.snapshot()
    if snap.get("http_status") in (401, 403):
        print(
            f"Stream stopped after HTTP {snap.get('http_status')}: "
            f"{(snap.get('last_error') or '')[:200]}",
            file=sys.stderr,
        )
        return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
