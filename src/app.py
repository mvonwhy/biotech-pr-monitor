"""
FastAPI webhook receiver (Enterprise Filtered Stream Webhooks).
Under Pay Per Use the active ingest path is GET /2/tweets/search/stream
(see scripts/run_filtered_stream.py); this receiver may sit unused.

HARD CONSTRAINTS (BioTech PR Monitor):
- Detection is X Filtered Stream Webhooks → POST /webhooks/x (push only).
- Monitoring consumes zero inference tokens; detection is X→webhook push only.
  Matching is performed by X stream rules; this process never polls X for tweets
  and never calls an LLM in the core path.
- Original tweets only (stream operators + receiver drop of reply/RT/quote).
- Pipeline: filter originals → match tickers (already by X) → resolve PR URL
  → analysis hooks (no-op / non-LLM by default) → log/alert.
- The only scheduled work elsewhere is twice-daily ticker→rules refresh
  (filter maintenance, not post detection).
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import FastAPI, Header, HTTPException, Query, Request
from fastapi.responses import JSONResponse

from src.alerts import STORE
from contextlib import asynccontextmanager

from src.config import env, require_env
from src.secrets import OnePasswordError, verify_startup_secrets
from src.crc import crc_response_token, verify_webhook_signature
from src.normalize import extract_events_from_webhook
from src.pipeline import process_events
from src import source_race

logger = logging.getLogger("x_pr_monitor.receiver")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

@asynccontextmanager
async def lifespan(_app: FastAPI):
    """Resolve 1Password secrets and confirm X_API_SECRET is available (value never logged)."""
    try:
        status = verify_startup_secrets(require_secret=True)
        logger.info("Startup secrets status (names only): %s", status)
    except OnePasswordError as e:
        logger.error("Secret load failed: %s", e)
        raise
    yield


app = FastAPI(
    title="X PR Monitor Webhook Receiver",
    description=(
        "CRC-verified receiver for X Filtered Stream Webhooks. "
        "Monitoring consumes zero inference tokens; detection is X→webhook push only. "
        "Secrets load from 1Password CLI (op://) at startup."
    ),
    version="0.1.0",
    lifespan=lifespan,
)


def _consumer_secret() -> str:
    return require_env("X_API_SECRET")


def _stream_status_snapshot() -> dict[str, Any] | None:
    """Read shared status file written by scripts/run_filtered_stream.py (if any)."""
    from pathlib import Path
    import json

    from src.config import ROOT

    path = ROOT / "logs" / "stream_status.json"
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


@app.get("/health")
def health() -> dict[str, Any]:
    stream = _stream_status_snapshot()
    return {
        "ok": True,
        "mode": "filtered_stream_http" if stream and stream.get("connected") else "webhook_or_idle",
        "inference_tokens": 0,
        "originals_only": True,
        "stream_connected": bool(stream and stream.get("connected")),
        "note": (
            "Active path under Pay Per Use: GET /2/tweets/search/stream. "
            "Webhook delivery needs Enterprise. Zero inference tokens in core path."
        ),
    }


@app.get("/stream/status")
def stream_status() -> dict[str, Any]:
    """Connection heartbeat from the filtered-stream process (shared JSON file)."""
    snap = _stream_status_snapshot()
    if snap is None:
        return {
            "ok": True,
            "running": False,
            "connected": False,
            "note": "No stream_status.json yet — start scripts/run_filtered_stream.py",
        }
    return {"ok": True, "running": True, **snap}


@app.get("/webhooks/x")
def webhook_crc(crc_token: str = Query(..., description="X CRC challenge token")) -> JSONResponse:
    """X CRC challenge (Account Activity / Filtered Stream Webhooks compatible)."""
    token = crc_response_token(crc_token, _consumer_secret())
    return JSONResponse({"response_token": token})


@app.post("/webhooks/x")
async def webhook_ingest(
    request: Request,
    x_twitter_webhooks_signature: str | None = Header(default=None),
) -> dict[str, Any]:
    """
    Entrypoint for all new-post alerts (SOLE production ingest path).

    Flow: verify signature → extract originals → resolve PR URL → analysis hooks → JSONL.
    No polling. Core path uses no LLM. Zero inference tokens unless opt-in hooks enabled.
    """
    body = await request.body()
    secret = env("X_API_SECRET") or ""
    skip = (env("SKIP_SIGNATURE_VERIFY") or "").lower() in ("1", "true", "yes")
    if secret and not skip:
        if not verify_webhook_signature(body, x_twitter_webhooks_signature, secret):
            raise HTTPException(status_code=403, detail="invalid webhook signature")

    try:
        payload = await request.json()
    except Exception:
        return {"ok": True, "accepted": 0, "dropped_non_original": 0}

    if not isinstance(payload, dict):
        return {"ok": True, "accepted": 0}

    events = extract_events_from_webhook(payload)
    stored = process_events(events)
    if stored:
        logger.info(
            "accepted %d original alert(s) via webhook push (pr_links=%s)",
            len(stored),
            sum(1 for s in stored if s.get("press_release_url")),
        )
    return {"ok": True, "accepted": len(stored), "alerts": stored}


@app.post("/alerts")
async def post_alert(request: Request) -> dict[str, Any]:
    """Optional internal ingest for already-normalized events (tests / forwarders)."""
    payload = await request.json()
    if isinstance(payload, dict) and "alert" not in payload and "alerts" not in payload:
        stored = process_events([payload])
        return {"ok": True, "accepted": len(stored), "alerts": stored}
    events = extract_events_from_webhook(payload if isinstance(payload, dict) else {})
    stored = process_events(events)
    return {"ok": True, "accepted": len(stored), "alerts": stored}


@app.get("/alerts")
def get_alerts(limit: int = Query(50, ge=1, le=500)) -> dict[str, Any]:
    return {"ok": True, "alerts": STORE.list_recent(limit)}

@app.get("/source-stats")
def source_stats() -> dict[str, Any]:
    """Aggregate cross-account race stats (who posts the same story first)."""
    return {"ok": True, **source_race.get_stats()}

