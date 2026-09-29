"""X Filtered Stream HTTP client — long-lived GET /2/tweets/search/stream.

Pay Per Use / non-Enterprise path: one persistent connection; X charges per
matched post. Rules are managed separately via /2/tweets/search/stream/rules
(see src/rules_sync.py). Webhook delivery requires Enterprise enrollment.
"""

from __future__ import annotations

import json
import logging
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

import httpx

from src.config import ROOT
from src.normalize import normalize_tweet
from src.pipeline import process_events

logger = logging.getLogger("x_pr_monitor.stream")

STREAM_URL = "https://api.x.com/2/tweets/search/stream"
STREAM_PARAMS = {
    "tweet.fields": "created_at,author_id,entities,referenced_tweets,text",
    "expansions": "author_id",
    "user.fields": "username",
}

DEFAULT_STATUS_PATH = ROOT / "logs" / "stream_status.json"
DEFAULT_LOG_PATH = ROOT / "logs" / "stream.log"

# Backoff: exponential, capped ~60s (per project preference).
BACKOFF_START_S = 1.0
BACKOFF_CAP_S = 60.0
# Keep-alive is ~20s; read timeout slightly above that to detect stalls.
READ_TIMEOUT_S = 30.0
CONNECT_TIMEOUT_S = 30.0


class StreamStatus:
    """Thread-safe connection status written to a JSON file for /stream/status."""

    def __init__(self, path: Path | None = None) -> None:
        self.path = path or DEFAULT_STATUS_PATH
        self._lock = threading.Lock()
        self._state: dict[str, Any] = {
            "connected": False,
            "http_status": None,
            "connected_at": None,
            "last_heartbeat_at": None,
            "last_tweet_at": None,
            "alerts_accepted": 0,
            "tweets_seen": 0,
            "reconnects": 0,
            "last_error": None,
            "rule_count": None,
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._flush()

    def update(self, **kwargs: Any) -> None:
        with self._lock:
            self._state.update(kwargs)
            self._state["updated_at"] = datetime.now(timezone.utc).isoformat()
            self._flush()

    def bump(self, key: str, n: int = 1) -> None:
        with self._lock:
            self._state[key] = int(self._state.get(key) or 0) + n
            self._state["updated_at"] = datetime.now(timezone.utc).isoformat()
            self._flush()

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return dict(self._state)

    def _flush(self) -> None:
        try:
            self.path.write_text(
                json.dumps(self._state, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
        except OSError as e:
            logger.warning("Could not write stream status file: %s", e)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _retry_after_seconds(response: httpx.Response, fallback: float) -> float:
    raw = response.headers.get("retry-after") or response.headers.get("Retry-After")
    if not raw:
        return fallback
    try:
        return max(float(raw), 1.0)
    except ValueError:
        return fallback


def handle_stream_line(
    line: str,
    *,
    status: StreamStatus | None = None,
    process: Callable[[list[dict[str, Any]]], list[dict[str, Any]]] = process_events,
) -> int:
    """Parse one NDJSON line. Returns number of alerts accepted (0 for keep-alive/errors)."""
    stripped = line.strip()
    if not stripped:
        if status:
            status.update(last_heartbeat_at=_now_iso())
        logger.debug("stream keep-alive")
        return 0

    try:
        payload = json.loads(stripped)
    except json.JSONDecodeError:
        logger.warning("Non-JSON stream line (len=%d): %s…", len(stripped), stripped[:80])
        return 0

    if not isinstance(payload, dict):
        return 0

    # Error objects occasionally appear on the stream body
    if "errors" in payload and "data" not in payload:
        logger.warning("Stream error payload: %s", json.dumps(payload)[:400])
        if status:
            status.update(last_error=str(payload.get("errors"))[:300])
        return 0

    data = payload.get("data")
    if not isinstance(data, dict) or not data.get("id"):
        if status:
            status.update(last_heartbeat_at=_now_iso())
        return 0

    if status:
        status.bump("tweets_seen")
        status.update(last_tweet_at=_now_iso())

    tw = dict(data)
    if "matching_rules" in payload:
        tw["matching_rules"] = payload["matching_rules"]
    includes = payload.get("includes") or {}
    norm = normalize_tweet(tw, includes)
    if not norm:
        logger.info("Dropped non-original tweet id=%s", data.get("id"))
        return 0

    stored = process([norm])
    n = len(stored)
    if status and n:
        status.bump("alerts_accepted", n)
    if n:
        logger.info(
            "stream accepted %d alert(s) tweet_id=%s handle=%s",
            n,
            norm.get("tweet_id"),
            norm.get("source_handle"),
        )
    return n


def connect_once(
    bearer_token: str,
    *,
    status: StreamStatus | None = None,
    process: Callable[[list[dict[str, Any]]], list[dict[str, Any]]] = process_events,
) -> tuple[int, float | None]:
    """Open one stream connection.

    Returns (http_status_or_0, retry_after_seconds).
    http_status 0 means clean disconnect after a successful HTTP 200 session.
    retry_after is set for 429 when the header is present.
    """
    headers = {
        "Authorization": f"Bearer {bearer_token}",
        "User-Agent": "x-pr-monitor-filtered-stream/1.0",
    }
    timeout = httpx.Timeout(
        connect=CONNECT_TIMEOUT_S,
        read=READ_TIMEOUT_S,
        write=30.0,
        pool=30.0,
    )
    logger.info("Connecting to Filtered Stream GET %s …", STREAM_URL)
    with httpx.Client(timeout=timeout, headers=headers) as client:
        with client.stream("GET", STREAM_URL, params=STREAM_PARAMS) as resp:
            code = resp.status_code
            if code != 200:
                retry_after: float | None = None
                if code == 429:
                    retry_after = _retry_after_seconds(resp, BACKOFF_CAP_S)
                try:
                    body = resp.read().decode("utf-8", errors="replace")[:500]
                except Exception:
                    body = "<unreadable>"
                logger.error("Stream connect failed HTTP %s: %s", code, body)
                if status:
                    status.update(
                        connected=False,
                        http_status=code,
                        last_error=f"HTTP {code}: {body[:300]}",
                    )
                return code, retry_after

            logger.info("Filtered Stream connected (HTTP 200)")
            if status:
                status.update(
                    connected=True,
                    http_status=200,
                    connected_at=_now_iso(),
                    last_heartbeat_at=_now_iso(),
                    last_error=None,
                )

            for line in resp.iter_lines():
                handle_stream_line(line, status=status, process=process)

    logger.warning("Stream connection ended (server closed or idle timeout")
    if status:
        status.update(connected=False)
    return 0, None


def run_forever(
    bearer_token: str,
    *,
    status: StreamStatus | None = None,
    process: Callable[[list[dict[str, Any]]], list[dict[str, Any]]] = process_events,
    stop_event: threading.Event | None = None,
) -> None:
    """Reconnect loop with exponential backoff (cap ~60s). Honors 429 Retry-After."""
    status = status or StreamStatus()
    stop_event = stop_event or threading.Event()
    backoff = BACKOFF_START_S

    while not stop_event.is_set():
        retry_after: float | None = None
        try:
            code, retry_after = connect_once(bearer_token, status=status, process=process)
        except httpx.TimeoutException as e:
            logger.warning("Stream timeout / stall: %s — reconnecting", e)
            if status:
                status.update(connected=False, last_error=f"timeout: {e}")
            code = -1
        except httpx.TransportError as e:
            logger.warning("Stream transport error: %s — reconnecting", e)
            if status:
                status.update(connected=False, last_error=f"transport: {type(e).__name__}")
            code = -1
        except Exception as e:
            logger.exception("Unexpected stream error: %s", e)
            if status:
                status.update(connected=False, last_error=str(e)[:300])
            code = -1

        if stop_event.is_set():
            break

        status.bump("reconnects")

        if code == 401 or code == 403:
            logger.error(
                "Fatal stream HTTP %s (auth or plan). Stopping reconnect loop. "
                "Webhook delivery needs Enterprise; stream GET needs Filtered Stream access.",
                code,
            )
            return

        if code == 0:
            backoff = BACKOFF_START_S

        if code == 429 and retry_after is not None:
            wait = retry_after
            logger.warning("HTTP 429 — Retry-After=%.1fs", wait)
        elif code == 429:
            wait = max(backoff, BACKOFF_CAP_S)
            logger.warning("HTTP 429 rate limited — sleeping %.1fs before retry", wait)
        else:
            wait = backoff

        logger.info("Reconnecting in %.1fs (backoff, cap=%.0fs)…", wait, BACKOFF_CAP_S)

        if stop_event.wait(wait):
            break
        backoff = min(max(backoff, BACKOFF_START_S) * 2, BACKOFF_CAP_S)


def configure_stream_logging(log_path: Path | None = None) -> None:
    """Attach a file handler so connection/heartbeat lines land in logs/stream.log."""
    path = log_path or DEFAULT_LOG_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    root = logging.getLogger("x_pr_monitor")
    root.setLevel(logging.INFO)
    # Avoid duplicate handlers on re-entry
    for h in list(root.handlers):
        if isinstance(h, logging.FileHandler) and Path(getattr(h, "baseFilename", "")) == path.resolve():
            return
    fh = logging.FileHandler(path, encoding="utf-8")
    fh.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
    root.addHandler(fh)
    # Also ensure console if not already configured
    if not any(isinstance(h, logging.StreamHandler) and not isinstance(h, logging.FileHandler) for h in root.handlers):
        sh = logging.StreamHandler()
        sh.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        root.addHandler(sh)
