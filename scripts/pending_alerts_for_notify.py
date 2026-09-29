#!/usr/bin/env python3
"""Read alerts that have not yet been handed to a chat notifier.

The cursor is a byte offset into ``logs/alerts.jsonl``.  Reading never changes
it; ``--advance`` writes the returned offset after the JSON response has been
flushed to stdout.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ALERTS_PATH = ROOT / "logs" / "alerts.jsonl"
DEFAULT_CURSOR_PATH = ROOT / "logs" / "alert_notify_cursor.json"

# These are defensive redactions in case an unexpected producer writes a
# credential-shaped field into the alert log. Normal pipeline alert fields are
# unaffected.
_SENSITIVE_KEY_PARTS = (
    "api_key",
    "apikey",
    "access_token",
    "auth_token",
    "authorization",
    "bearer_token",
    "client_secret",
    "credential",
    "password",
    "private_key",
    "secret",
    "token",
)


def _is_sensitive_key(key: str) -> bool:
    normalized = key.lower().replace("-", "_")
    return any(part in normalized for part in _SENSITIVE_KEY_PARTS)


def _without_secrets(value: Any) -> Any:
    """Return JSON-compatible data with credential-shaped keys redacted."""
    if isinstance(value, dict):
        return {
            key: "[REDACTED]" if _is_sensitive_key(str(key)) else _without_secrets(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_without_secrets(item) for item in value]
    return value


def load_cursor(path: Path) -> int:
    """Load a byte-offset cursor, treating a missing file as offset zero."""
    if not path.exists():
        return 0
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot read cursor file {path}: invalid JSON") from exc
    offset = payload.get("offset") if isinstance(payload, dict) else None
    if isinstance(offset, bool) or not isinstance(offset, int) or offset < 0:
        raise ValueError(f"cursor file {path} must contain a non-negative integer offset")
    return offset


def read_pending(alerts_path: Path, offset: int) -> tuple[list[dict[str, Any]], int]:
    """Read complete JSONL records from *offset* without modifying the log."""
    if not alerts_path.exists():
        return [], 0 if offset == 0 else offset

    end_offset = alerts_path.stat().st_size
    if offset > end_offset:
        raise ValueError("cursor offset is beyond the current alerts log")

    records: list[dict[str, Any]] = []
    next_offset = offset
    with alerts_path.open("rb") as alerts_file:
        if offset:
            alerts_file.seek(offset - 1)
            if alerts_file.read(1) != b"\n":
                raise ValueError("cursor offset does not point to a JSONL line boundary")
        alerts_file.seek(offset)

        while alerts_file.tell() < end_offset:
            raw = alerts_file.readline()
            if not raw or not raw.endswith(b"\n"):
                # A writer may currently be appending this line. Leave it for
                # the next invocation rather than advancing past partial JSON.
                break
            next_offset = alerts_file.tell()
            line = raw[:-1].rstrip(b"\r")
            if not line.strip():
                continue
            try:
                record = json.loads(line.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise ValueError(
                    f"invalid JSON in alerts log near byte offset {next_offset}"
                ) from exc
            if not isinstance(record, dict):
                raise ValueError(
                    f"alerts log record near byte offset {next_offset} is not an object"
                )
            records.append(_without_secrets(record))

    return records, next_offset


def write_cursor(path: Path, offset: int) -> None:
    """Atomically persist the byte offset."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as cursor_file:
            json.dump({"offset": offset}, cursor_file)
            cursor_file.write("\n")
            cursor_file.flush()
            os.fsync(cursor_file.fileno())
        os.replace(temporary_name, path)
    except Exception:
        try:
            os.unlink(temporary_name)
        except FileNotFoundError:
            pass
        raise


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--alerts-path", type=Path, default=DEFAULT_ALERTS_PATH, help="alerts JSONL path"
    )
    parser.add_argument(
        "--cursor-path", type=Path, default=DEFAULT_CURSOR_PATH, help="cursor JSON path"
    )
    parser.add_argument(
        "--advance",
        action="store_true",
        help="persist next_cursor after flushing the JSON response",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        offset = load_cursor(args.cursor_path)
        records, next_offset = read_pending(args.alerts_path, offset)
        response = {"new": records, "next_cursor": next_offset}
        sys.stdout.write(json.dumps(response, ensure_ascii=False, separators=(",", ":")) + "\n")
        sys.stdout.flush()
        if args.advance:
            write_cursor(args.cursor_path, next_offset)
    except (OSError, ValueError) as exc:
        print(f"pending_alerts_for_notify: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
