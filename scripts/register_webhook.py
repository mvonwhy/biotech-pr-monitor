#!/usr/bin/env python3
"""Register public HTTPS webhook with X and link Filtered Stream delivery.

Steps:
  1. Ensure local receiver is reachable via PUBLIC_WEBHOOK_URL (ngrok/cloudflare; no port).
  2. POST /2/webhooks with that URL (X will CRC-challenge GET /webhooks/x).
  3. Sync Filtered Stream rules from ticker cache + source accounts.
  4. POST /2/tweets/search/webhooks/:webhook_id to attach stream → webhook.

Requires: X_BEARER_TOKEN, X_API_SECRET (for CRC), PUBLIC_WEBHOOK_URL
Does NOT poll tweets. Post detection remains webhook push only.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.config import PUBLIC_WEBHOOK_URL, require_env  # noqa: E402
from src.rules_sync import sync_rules_to_x  # noqa: E402
from src.x_api import XClient  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--url",
        default=PUBLIC_WEBHOOK_URL or "",
        help="Public HTTPS webhook URL ending in /webhooks/x (no port)",
    )
    parser.add_argument("--skip-rules", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    url = (args.url or "").strip()
    if not url:
        print("ERROR: set PUBLIC_WEBHOOK_URL or pass --url", file=sys.stderr)
        return 2
    if not url.startswith("https://"):
        print("ERROR: PUBLIC_WEBHOOK_URL must be https:// (use a tunnel in local dev)", file=sys.stderr)
        return 2
    if ":8787" in url or url.rstrip("/").count(":") > 1:
        print(
            "WARNING: registered URL should not include a non-default port; "
            "use https://<tunnel-host>/webhooks/x",
            file=sys.stderr,
        )

    if args.dry_run:
        print(json.dumps({"would_register": url, "skip_rules": args.skip_rules}, indent=2))
        return 0

    client = XClient(require_env("X_BEARER_TOKEN"))
    existing = client.list_webhooks()
    print("Existing webhooks:", json.dumps(existing, indent=2))

    created = client.create_webhook(url)
    print("Created webhook:", json.dumps(created, indent=2))
    webhook_id = None
    if isinstance(created, dict):
        webhook_id = (created.get("data") or {}).get("id") or created.get("id")
    if not webhook_id:
        print("ERROR: could not parse webhook id from create response", file=sys.stderr)
        return 1

    if not args.skip_rules:
        rules_summary = sync_rules_to_x(dry_run=False)
        print("Rules sync:", json.dumps({k: rules_summary[k] for k in rules_summary if k != "x_result"}, indent=2))

    link = client.link_filtered_stream_webhook(str(webhook_id))
    print("Linked Filtered Stream → webhook:", json.dumps(link, indent=2))
    print("Done. Matching ORIGINAL posts will POST to", url)
    return 0


if __name__ == "__main__":
    sys.exit(main())
