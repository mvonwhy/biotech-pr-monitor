"""Environment and path helpers. Secrets resolve via 1Password CLI when set to op://."""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

# Soft inject at import (logs warning if op:// present but CLI not ready).
# Hard check runs in app lifespan via verify_startup_secrets().
from src.secrets import OnePasswordError, inject_op_secrets  # noqa: E402

try:
    _OP_RESOLVED = inject_op_secrets()
except OnePasswordError as _e:
    _OP_RESOLVED = []
    import logging as _logging
    _logging.getLogger("x_pr_monitor.config").warning(
        "1Password secrets not injected yet: %s", _e
    )


def env(key: str, default: str | None = None) -> str | None:
    return os.getenv(key, default)


def require_env(key: str) -> str:
    val = os.getenv(key)
    if not val:
        raise RuntimeError(f"Missing required env var: {key}")
    if val.strip().startswith("op://"):
        raise RuntimeError(
            f"{key} is still an unresolved op:// reference. "
            "Install/sign in to 1Password CLI (`op signin`) or check the item id/field."
        )
    return val


def path_from_env(key: str, default_rel: str) -> Path:
    raw = os.getenv(key, default_rel)
    p = Path(raw)
    if not p.is_absolute():
        p = ROOT / p
    return p


WEBHOOK_HOST = env("WEBHOOK_HOST", "127.0.0.1") or "127.0.0.1"
WEBHOOK_PORT = int(env("WEBHOOK_PORT", "8787") or "8787")
WEBHOOK_URL = env("WEBHOOK_URL", f"http://127.0.0.1:{WEBHOOK_PORT}/webhooks/x") or ""
PUBLIC_WEBHOOK_URL = env("PUBLIC_WEBHOOK_URL", "") or ""
ALERT_LOG_PATH = path_from_env("ALERT_LOG_PATH", "logs/alerts.jsonl")
ALERT_MEMORY_LIMIT = int(env("ALERT_MEMORY_LIMIT", "200") or "200")
TICKER_CACHE_PATH = path_from_env("TICKER_CACHE_PATH", "config/tickers.json")
SOURCE_ACCOUNTS_PATH = path_from_env("SOURCE_ACCOUNTS_PATH", "config/source_accounts.json")
GOOGLE_SHEET_ID = env("GOOGLE_SHEET_ID", "1Xa4HDvSMC5HxG7G92tOQOIeDlF2AP-F32hwbwvrHPlw") or ""
SHEET_TAB = env("SHEET_TAB", "2026") or "2026"
SHEET_TICKER_COLUMN = env("SHEET_TICKER_COLUMN", "Ticker") or "Ticker"
GOOGLE_SERVICE_ACCOUNT_JSON = env("GOOGLE_SERVICE_ACCOUNT_JSON", "") or ""
SHEET_REFRESH_TIMES = env("SHEET_REFRESH_TIMES", "08:12,16:12") or "08:12,16:12"
SHEET_REFRESH_CRON = env("SHEET_REFRESH_CRON", "") or ""

# Optional: single item UUID for docs / tooling (fields still referenced via op:// paths)
OP_X_API_ITEM_ID = env("OP_X_API_ITEM_ID", "") or ""
