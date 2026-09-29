"""Cross-account source race tracking: who posts the same story first.

Fingerprints prefer normalized press_release_url; else cashtags + short text.
Persists each event to logs/source_race.jsonl and aggregates in logs/source_stats.json.
"""

from __future__ import annotations

import json
import logging
import re
import threading
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from src.config import ROOT

logger = logging.getLogger("x_pr_monitor.source_race")

RACE_LOG_PATH = ROOT / "logs" / "source_race.jsonl"
STATS_PATH = ROOT / "logs" / "source_stats.json"
RECENT_RACES_LIMIT = 50
TEXT_FP_CHARS = 96

_CASHTAG_RE = re.compile(r"\$([A-Za-z]{1,6})\b")

def _parse_ts(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    s = str(value).strip()
    if not s:
        return None
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def normalize_pr_url(url: str) -> str | None:
    """Host + path only; strip query/utm/fragment; lowercase host; drop trailing slash."""
    raw = (url or "").strip()
    if not raw:
        return None
    try:
        p = urlparse(raw)
    except Exception:
        return None
    host = (p.netloc or "").lower()
    if host.startswith("www."):
        host = host[4:]
    if not host:
        return None
    path = p.path or "/"
    if path != "/" and path.endswith("/"):
        path = path.rstrip("/")
    # Drop query entirely (utm etc.); keep bare host+path fingerprint
    return f"{host}{path}"


def extract_cashtags(text: str) -> list[str]:
    found = {m.group(1).upper() for m in _CASHTAG_RE.finditer(text or "")}
    return sorted(found)


def short_text_fingerprint(text: str) -> str:
    norm = re.sub(r"\s+", " ", (text or "").strip().lower())
    # Drop urls and cashtags noise for stabler matching across accounts
    norm = re.sub(r"https?://\S+", "", norm)
    norm = re.sub(r"\$[a-z]{1,6}\b", "", norm)
    norm = re.sub(r"\s+", " ", norm).strip()
    return norm[:TEXT_FP_CHARS]


def story_fingerprint(alert: dict[str, Any]) -> tuple[str, str]:
    """Return (fingerprint, kind) where kind is 'pr_url' or 'ticker_text'."""
    pr = alert.get("press_release_url")
    if pr:
        norm = normalize_pr_url(str(pr))
        if norm:
            return f"url:{norm}", "pr_url"

    text = alert.get("text") or ""
    tags = extract_cashtags(text)
    fp_text = short_text_fingerprint(text)
    tag_part = ",".join(tags) if tags else "_"
    return f"tt:{tag_part}|{fp_text}", "ticker_text"


def _median(values: list[float]) -> float | None:
    if not values:
        return None
    s = sorted(values)
    n = len(s)
    mid = n // 2
    if n % 2:
        return float(s[mid])
    return float((s[mid - 1] + s[mid]) / 2.0)


def _empty_source_stat() -> dict[str, Any]:
    return {
        "first_place_count": 0,
        "total_seen": 0,
        "avg_lag_when_not_first": None,
        "median_lag_when_not_first": None,
        "_lags": [],  # internal; stripped on write
    }


class SourceRaceTracker:
    """Thread-safe race tracker with JSONL + aggregate JSON persistence."""

    def __init__(
        self,
        race_log_path: Path | None = None,
        stats_path: Path | None = None,
    ) -> None:
        self.race_log_path = race_log_path or RACE_LOG_PATH
        self.stats_path = stats_path or STATS_PATH
        self._lock = threading.Lock()
        # fingerprint -> race state
        self._races: dict[str, dict[str, Any]] = {}
        self._sources: dict[str, dict[str, Any]] = defaultdict(_empty_source_stat)
        self._recent: list[dict[str, Any]] = []
        self.race_log_path.parent.mkdir(parents=True, exist_ok=True)
        self.stats_path.parent.mkdir(parents=True, exist_ok=True)
        self._load_stats()

    def _load_stats(self) -> None:
        if not self.stats_path.is_file():
            return
        try:
            data = json.loads(self.stats_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as e:
            logger.warning("Could not load source_stats.json: %s", e)
            return
        for handle, st in (data.get("sources") or {}).items():
            entry = _empty_source_stat()
            entry["first_place_count"] = int(st.get("first_place_count") or 0)
            entry["total_seen"] = int(st.get("total_seen") or 0)
            entry["avg_lag_when_not_first"] = st.get("avg_lag_when_not_first")
            entry["median_lag_when_not_first"] = st.get("median_lag_when_not_first")
            # Rebuild lag list approximately from median/avg is lossy; keep empty
            # so new observations recompute cleanly. Historical counts preserved.
            self._sources[handle] = entry
        self._recent = list(data.get("recent_races") or [])[-RECENT_RACES_LIMIT:]

    def _alert_ts(self, alert: dict[str, Any]) -> datetime:
        for key in ("received_at", "created_at"):
            dt = _parse_ts(alert.get(key))
            if dt is not None:
                return dt
        return datetime.now(timezone.utc)

    def record(self, alert: dict[str, Any]) -> dict[str, Any] | None:
        """Record an alert into the race. Returns the race event dict or None."""
        handle = (alert.get("source_handle") or "").lstrip("@").strip()
        if not handle:
            return None
        fp, kind = story_fingerprint(alert)
        if not fp or fp == "tt:_|":
            return None

        seen_at = self._alert_ts(alert)
        tweet_id = str(alert.get("tweet_id") or "")

        with self._lock:
            race = self._races.get(fp)
            if race is None:
                race = {
                    "fingerprint": fp,
                    "kind": kind,
                    "first_seen_by_source": handle,
                    "first_seen_at": seen_at.isoformat(),
                    "sources": {},
                }
                self._races[fp] = race

            sources_map: dict[str, Any] = race["sources"]
            if handle in sources_map:
                # Already counted this source for this story
                return None

            first_at = _parse_ts(race["first_seen_at"]) or seen_at
            lag = max(0.0, (seen_at - first_at).total_seconds())
            is_first = len(sources_map) == 0

            source_entry = {
                "source_handle": handle,
                "tweet_id": tweet_id,
                "seen_at": seen_at.isoformat(),
                "lag_seconds": round(lag, 3),
                "is_first": is_first,
            }
            sources_map[handle] = source_entry

            st = self._sources[handle]
            st["total_seen"] += 1
            if is_first:
                st["first_place_count"] += 1
                race["first_seen_by_source"] = handle
                race["first_seen_at"] = seen_at.isoformat()
            else:
                st["_lags"].append(lag)
                lags: list[float] = st["_lags"]
                st["avg_lag_when_not_first"] = round(sum(lags) / len(lags), 3)
                st["median_lag_when_not_first"] = (
                    round(_median(lags), 3) if lags else None
                )

            event = {
                "fingerprint": fp,
                "kind": kind,
                "source_handle": handle,
                "tweet_id": tweet_id,
                "seen_at": seen_at.isoformat(),
                "lag_seconds": round(lag, 3),
                "is_first": is_first,
                "first_seen_by_source": race["first_seen_by_source"],
                "press_release_url": alert.get("press_release_url"),
                "text_preview": (alert.get("text") or "")[:120],
            }

            # Update recent races snapshot (one entry per fingerprint, newest last)
            snap = {
                "fingerprint": fp,
                "kind": kind,
                "first_seen_by_source": race["first_seen_by_source"],
                "first_seen_at": race["first_seen_at"],
                "sources": [
                    {
                        "source_handle": s["source_handle"],
                        "lag_seconds": s["lag_seconds"],
                        "tweet_id": s["tweet_id"],
                        "seen_at": s["seen_at"],
                    }
                    for s in sorted(
                        sources_map.values(),
                        key=lambda x: x["lag_seconds"],
                    )
                ],
            }
            self._recent = [r for r in self._recent if r.get("fingerprint") != fp]
            self._recent.append(snap)
            self._recent = self._recent[-RECENT_RACES_LIMIT:]

            self._append_jsonl(event)
            self._write_stats()
            return event

    def _append_jsonl(self, event: dict[str, Any]) -> None:
        try:
            with self.race_log_path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(event, ensure_ascii=False) + "\n")
        except OSError as e:
            logger.warning("Failed to append source_race.jsonl: %s", e)

    def _public_sources(self) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for handle, st in self._sources.items():
            out[handle] = {
                "first_place_count": st["first_place_count"],
                "total_seen": st["total_seen"],
                "avg_lag_when_not_first": st["avg_lag_when_not_first"],
                "median_lag_when_not_first": st["median_lag_when_not_first"],
            }
        return out

    def _write_stats(self) -> None:
        payload = {
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "sources": self._public_sources(),
            "recent_races": list(self._recent),
        }
        try:
            tmp = self.stats_path.with_suffix(".json.tmp")
            tmp.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
            tmp.replace(self.stats_path)
        except OSError as e:
            logger.warning("Failed to write source_stats.json: %s", e)

    def get_stats(self) -> dict[str, Any]:
        """Prefer on-disk aggregate (shared with stream process); else in-memory."""
        if self.stats_path.is_file():
            try:
                data = json.loads(self.stats_path.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    return {
                        "updated_at": data.get("updated_at")
                        or datetime.now(timezone.utc).isoformat(),
                        "sources": data.get("sources") or {},
                        "recent_races": data.get("recent_races") or [],
                    }
            except (OSError, json.JSONDecodeError) as e:
                logger.warning("Could not read source_stats.json: %s", e)
        with self._lock:
            return {
                "updated_at": datetime.now(timezone.utc).isoformat(),
                "sources": self._public_sources(),
                "recent_races": list(self._recent),
            }


TRACKER = SourceRaceTracker()


def record(alert: dict[str, Any]) -> dict[str, Any] | None:
    """Module-level entry used by the pipeline."""
    try:
        return TRACKER.record(alert)
    except Exception:
        logger.exception("source_race.record failed")
        return None


def get_stats() -> dict[str, Any]:
    return TRACKER.get_stats()
