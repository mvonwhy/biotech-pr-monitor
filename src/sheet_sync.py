"""Read-only ticker sync from Google Sheet (or local CSV/JSON).

NEVER writes back to the spreadsheet.
This does NOT detect posts — it only refreshes the local ticker cache used
to rebuild Filtered Stream rules.
config/tickers.json is a SOFT CACHE: always overwrite it from the sheet/CSV;
never treat a prior snapshot as permanently locked.
"""

from __future__ import annotations

import csv
import json
import logging
from pathlib import Path
from typing import Any

from src.config import (
    GOOGLE_SERVICE_ACCOUNT_JSON,
    GOOGLE_SHEET_ID,
    SHEET_TAB,
    SHEET_TICKER_COLUMN,
    TICKER_CACHE_PATH,
)
from src.tickers import load_tickers, save_tickers

logger = logging.getLogger("x_pr_monitor.sheet_sync")


def tickers_from_csv(path: Path, column: str = "Ticker") -> list[str]:
    with path.open(newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        if not reader.fieldnames:
            return []
        # Case-insensitive column match
        col_map = {c.lower(): c for c in reader.fieldnames}
        key = col_map.get(column.lower())
        if not key:
            raise ValueError(f"Column {column!r} not in CSV headers: {reader.fieldnames}")
        return [row[key] for row in reader if row.get(key)]


def tickers_from_google_sheet(
    sheet_id: str | None = None,
    tab: str | None = None,
    column: str | None = None,
    service_account_json: str | None = None,
) -> list[str]:
    """Pull Ticker column via Google Sheets API (service account). Read-only."""
    sheet_id = sheet_id or GOOGLE_SHEET_ID
    tab = tab or SHEET_TAB
    column = column or SHEET_TICKER_COLUMN
    sa_path = service_account_json or GOOGLE_SERVICE_ACCOUNT_JSON
    if not sa_path:
        raise RuntimeError(
            "GOOGLE_SERVICE_ACCOUNT_JSON not set. "
            "Use scripts/sync_tickers_from_csv.py or drop tickers into config/tickers.json."
        )
    try:
        from google.oauth2 import service_account
        from googleapiclient.discovery import build
    except ImportError as e:
        raise RuntimeError(
            "google-api-python-client / google-auth not installed. "
            "pip install google-api-python-client google-auth  "
            "or use the CSV sync script instead."
        ) from e

    scopes = ["https://www.googleapis.com/auth/spreadsheets.readonly"]
    creds = service_account.Credentials.from_service_account_file(sa_path, scopes=scopes)
    service = build("sheets", "v4", credentials=creds, cache_discovery=False)
    # Fetch header row + data
    result = (
        service.spreadsheets()
        .values()
        .get(spreadsheetId=sheet_id, range=f"'{tab}'")
        .execute()
    )
    rows: list[list[Any]] = result.get("values") or []
    if not rows:
        return []
    headers = [str(h).strip() for h in rows[0]]
    col_map = {h.lower(): i for i, h in enumerate(headers)}
    idx = col_map.get((column or "Ticker").lower())
    if idx is None:
        raise ValueError(f"Column {column!r} not in sheet headers: {headers}")
    out: list[str] = []
    for row in rows[1:]:
        if idx < len(row) and str(row[idx]).strip():
            out.append(str(row[idx]).strip())
    return out


def sync_from_sheet() -> dict[str, Any]:
    """Fetch sheet → write local ticker cache. Returns summary."""
    before = set(load_tickers())
    tickers = tickers_from_google_sheet()
    save_tickers(tickers, source=f"google_sheet:{GOOGLE_SHEET_ID}/{SHEET_TAB}")
    after = set(load_tickers())
    return {
        "count": len(after),
        "added": sorted(after - before),
        "removed": sorted(before - after),
        "path": str(TICKER_CACHE_PATH),
    }


def sync_from_csv(csv_path: Path, column: str = "Ticker") -> dict[str, Any]:
    before = set(load_tickers())
    tickers = tickers_from_csv(csv_path, column=column)
    save_tickers(tickers, source=f"csv:{csv_path}")
    after = set(load_tickers())
    return {
        "count": len(after),
        "added": sorted(after - before),
        "removed": sorted(before - after),
        "path": str(TICKER_CACHE_PATH),
    }


def sync_from_json_list(tickers: list[str], source: str = "manual") -> dict[str, Any]:
    before = set(load_tickers())
    save_tickers(tickers, source=source)
    after = set(load_tickers())
    return {
        "count": len(after),
        "added": sorted(after - before),
        "removed": sorted(before - after),
        "path": str(TICKER_CACHE_PATH),
    }


def load_cache_meta() -> dict[str, Any]:
    if not TICKER_CACHE_PATH.exists():
        return {}
    return json.loads(TICKER_CACHE_PATH.read_text(encoding="utf-8"))
