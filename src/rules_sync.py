"""Rebuild Filtered Stream rules from source accounts + ticker cache.

This is filter maintenance only — it does NOT poll for posts.
Post detection is exclusively via X→webhook push.
"""

from __future__ import annotations

import logging
from typing import Any

from src.config import require_env
from src.tickers import build_stream_rules, load_source_accounts, load_tickers, rules_fingerprint
from src.x_api import XClient

logger = logging.getLogger("x_pr_monitor.rules_sync")


def preview_rules() -> list[dict[str, str]]:
    return build_stream_rules(load_tickers(), load_source_accounts())


def sync_rules_to_x(*, dry_run: bool = False) -> dict[str, Any]:
    """Push current ticker/account rules to X Filtered Stream rules API."""
    rules = preview_rules()
    fp = rules_fingerprint(rules)
    summary: dict[str, Any] = {
        "rule_count": len(rules),
        "ticker_count": len(load_tickers()),
        "accounts": load_source_accounts(),
        "fingerprint": fp,
        "dry_run": dry_run,
        "rules_preview": rules[:5],  # first few for logs
    }
    if dry_run:
        summary["rules"] = rules
        return summary

    if not rules:
        logger.warning("No tickers in cache — refusing to wipe rules without tickers")
        summary["skipped"] = True
        summary["reason"] = "empty_ticker_cache"
        return summary

    client = XClient(require_env("X_BEARER_TOKEN"))
    result = client.sync_rules(rules)
    summary["x_result"] = result
    logger.info(
        "Synced %d Filtered Stream rules (tickers=%d, fingerprint=%s)",
        len(rules),
        summary["ticker_count"],
        fp[:12],
    )
    return summary
