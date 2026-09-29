"""In-memory + JSONL alert store."""

from __future__ import annotations

import json
import threading
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.config import ALERT_LOG_PATH, ALERT_MEMORY_LIMIT


class AlertStore:
    def __init__(
        self,
        log_path: Path | None = None,
        memory_limit: int | None = None,
    ) -> None:
        self.log_path = log_path or ALERT_LOG_PATH
        self.memory_limit = memory_limit or ALERT_MEMORY_LIMIT
        self._lock = threading.Lock()
        self._recent: deque[dict[str, Any]] = deque(maxlen=self.memory_limit)
        self.log_path.parent.mkdir(parents=True, exist_ok=True)

    def append(self, event: dict[str, Any]) -> dict[str, Any]:
        record = dict(event)
        record.setdefault("received_at", datetime.now(timezone.utc).isoformat())
        with self._lock:
            self._recent.appendleft(record)
            with self.log_path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
        return record

    def list_recent(self, limit: int = 50) -> list[dict[str, Any]]:
        with self._lock:
            return list(self._recent)[:limit]


STORE = AlertStore()
