#!/usr/bin/env python3
"""Ensure Filtered Stream rules exist on X. Sync only if count is 0.

Does not change rules when any already exist (avoids unnecessary churn).
Prints JSON summary to stdout (no secrets). Exit 0 if rule_count > 0.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.config import require_env  # noqa: E402
from src.rules_sync import sync_rules_to_x  # noqa: E402
from src.secrets import OnePasswordError, verify_startup_secrets  # noqa: E402
from src.x_api import XClient  # noqa: E402


def main() -> int:
    try:
        verify_startup_secrets(require_secret=True)
    except OnePasswordError as e:
        print(json.dumps({"ok": False, "error": str(e), "rule_count": 0, "synced": False}))
        return 1

    bearer = require_env("X_BEARER_TOKEN")
    client = XClient(bearer)
    rules = client.get_rules()
    rule_count = len(rules)
    synced = False
    sync_summary = None

    if rule_count == 0:
        sync_summary = sync_rules_to_x(dry_run=False)
        rules = client.get_rules()
        rule_count = len(rules)
        synced = True

    out = {
        "ok": rule_count > 0,
        "rule_count": rule_count,
        "synced": synced,
    }
    if sync_summary is not None:
        out["sync"] = {
            "rule_count": sync_summary.get("rule_count"),
            "ticker_count": sync_summary.get("ticker_count"),
            "skipped": sync_summary.get("skipped"),
            "fingerprint": (sync_summary.get("fingerprint") or "")[:12],
        }
    print(json.dumps(out))
    return 0 if rule_count > 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
