from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "pending_alerts_for_notify.py"


def run_helper(alerts: Path, cursor: Path, *extra: str) -> dict:
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--alerts-path", str(alerts), "--cursor-path", str(cursor), *extra],
        check=True,
        capture_output=True,
        text=True,
    )
    assert result.stderr == ""
    return json.loads(result.stdout)


def test_reads_from_byte_cursor_without_advancing(tmp_path: Path) -> None:
    alerts = tmp_path / "alerts.jsonl"
    cursor = tmp_path / "cursor.json"
    first = {"tweet_id": "1", "text": "hello"}
    second = {"tweet_id": "2", "text": "world"}
    alerts.write_text(json.dumps(first) + "\n" + json.dumps(second) + "\n", encoding="utf-8")

    response = run_helper(alerts, cursor)

    assert response["new"] == [first, second]
    assert response["next_cursor"] == alerts.stat().st_size
    assert not cursor.exists()


def test_advance_persists_cursor_and_redacts_sensitive_keys(tmp_path: Path) -> None:
    alerts = tmp_path / "alerts.jsonl"
    cursor = tmp_path / "cursor.json"
    alerts.write_text(
        json.dumps({"tweet_id": "1", "api_token": "do-not-print"}) + "\n",
        encoding="utf-8",
    )

    response = run_helper(alerts, cursor, "--advance")

    assert response["new"] == [{"tweet_id": "1", "api_token": "[REDACTED]"}]
    assert json.loads(cursor.read_text(encoding="utf-8")) == {
        "offset": alerts.stat().st_size
    }
    assert run_helper(alerts, cursor)["new"] == []
