"""Ticker cache + Filtered Stream rule builder.

Tickers are stock symbols (e.g. MRNA), NOT X @handles.
Source accounts (BioStocks, etc.) are fixed in config/source_accounts.json.

Rules match ORIGINAL tweets only: -is:reply -is:retweet -is:quote
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.config import SOURCE_ACCOUNTS_PATH, TICKER_CACHE_PATH

# X Filtered Stream rule length limits vary by plan; stay under 512 for Basic.
RULE_MAX_CHARS = 480
RULE_TAG_PREFIX = "prmon"
# Prefer X operators to exclude non-originals at the stream edge.
ORIGINAL_ONLY = "-is:reply -is:retweet -is:quote"


def _normalize_ticker(raw: str) -> str | None:
    t = raw.strip().upper().lstrip("$")
    if not t or not re.fullmatch(r"[A-Z][A-Z0-9.\-]{0,9}", t):
        return None
    return t


def load_source_accounts(path: Path | None = None) -> list[str]:
    p = path or SOURCE_ACCOUNTS_PATH
    data = json.loads(p.read_text(encoding="utf-8"))
    return [str(h).lstrip("@") for h in data.get("accounts", [])]


def load_tickers(path: Path | None = None) -> list[str]:
    p = path or TICKER_CACHE_PATH
    if not p.exists():
        return []
    data = json.loads(p.read_text(encoding="utf-8"))
    out: list[str] = []
    seen: set[str] = set()
    for raw in data.get("tickers", []):
        t = _normalize_ticker(str(raw))
        if t and t not in seen:
            seen.add(t)
            out.append(t)
    return out


def save_tickers(
    tickers: list[str],
    *,
    source: str,
    path: Path | None = None,
) -> Path:
    p = path or TICKER_CACHE_PATH
    p.parent.mkdir(parents=True, exist_ok=True)
    normalized: list[str] = []
    seen: set[str] = set()
    for raw in tickers:
        t = _normalize_ticker(str(raw))
        if t and t not in seen:
            seen.add(t)
            normalized.append(t)
    payload: dict[str, Any] = {
        "tickers": normalized,
        "synced_at": datetime.now(timezone.utc).isoformat(),
        "source": source,
        "count": len(normalized),
        "soft_cache": True,
        "source_of_truth": "Google Drive Trade Plan / tab 2026 / column Ticker",
        "notes": "SOFT CACHE — refreshable from Trade Plan 2026 Ticker column (or CSV). Not locked; not X handles. Sheet is source of truth.",
    }
    p.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return p


def build_stream_rules(
    tickers: list[str] | None = None,
    accounts: list[str] | None = None,
    *,
    max_chars: int = RULE_MAX_CHARS,
) -> list[dict[str, str]]:
    """Build Filtered Stream rules for original posts only.

    Syntax per rule (chunked by ticker groups to stay under max_chars)::

      (from:BioStocks OR from:BioPharmIQ OR from:BPharmCatalyst)
      ($MRNA OR MRNA OR $GILD OR GILD ...)
      -is:reply -is:retweet -is:quote

    - Cashtag ``$TICKER`` matches cashtag mentions.
    - Bare ``TICKER`` matches the keyword token (may over-match short symbols).
    - ``-is:reply -is:retweet -is:quote`` keeps originals only at the X edge.
    """
    accounts = accounts or load_source_accounts()
    tickers = tickers if tickers is not None else load_tickers()
    if not accounts:
        raise ValueError("No source accounts configured")
    if not tickers:
        return []

    from_clause = "(" + " OR ".join(f"from:{a}" for a in accounts) + ")"
    # Overhead: from + space + ticker parens + space + original-only operators
    overhead = len(from_clause) + 3 + 1 + len(ORIGINAL_ONLY)

    rules: list[dict[str, str]] = []
    chunk: list[str] = []
    chunk_len = 0
    tag_i = 0

    def flush() -> None:
        nonlocal chunk, chunk_len, tag_i
        if not chunk:
            return
        ticker_clause = "(" + " OR ".join(chunk) + ")"
        value = f"{from_clause} {ticker_clause} {ORIGINAL_ONLY}"
        tag_i += 1
        rules.append({"value": value, "tag": f"{RULE_TAG_PREFIX}-{tag_i}"})
        chunk = []
        chunk_len = 0

    for t in tickers:
        piece = f"${t} OR {t}"
        extra = len(piece) + (4 if chunk else 0)
        if chunk and overhead + chunk_len + extra > max_chars:
            flush()
            extra = len(piece)
        chunk.append(piece)
        chunk_len += extra

    flush()
    return rules


def rules_fingerprint(rules: list[dict[str, str]]) -> str:
    values = sorted(r["value"] for r in rules)
    return hashlib.sha256("\n".join(values).encode("utf-8")).hexdigest()
