#!/usr/bin/env bash
# Idempotent stack recovery for x-pr-monitor after cloud reset / process death.
# Exit 0 if healthy after ensure; exit 1 if still broken.
# Never prints secrets. Writes logs/watchdog_last.json for agent routines.
set -u

ROOT="/workspace/x-pr-monitor"
cd "$ROOT" || exit 1
mkdir -p logs

export PATH="/home/box/.local/bin:${PATH:-/usr/local/bin:/usr/bin:/bin}"
UVICORN_BIN="$ROOT/.venv/bin/uvicorn"
PYTHON_BIN="$ROOT/.venv/bin/python"
CLOUDFLARED_BIN="/home/box/.local/bin/cloudflared"
HEALTH_URL="http://127.0.0.1:8787/health"
STALE_HEARTBEAT_SEC=180
UVICORN_WAIT_SEC=20

ACTIONS=()
ERRORS=()
TS="$(date -u +%Y-%m-%dT%H:%M:%SZ)"

json_escape() {
  # minimal escape for embedding in JSON strings
  printf '%s' "$1" | python3 -c 'import json,sys; print(json.dumps(sys.stdin.read())[1:-1])'
}

append_action() { ACTIONS+=("$1"); }
append_error() { ERRORS+=("$1"); }

health_ok() {
  curl -fsS -m 3 "$HEALTH_URL" >/dev/null 2>&1
}

uvicorn_running() {
  pgrep -f '[u]vicorn src.app:app' >/dev/null 2>&1
}

cloudflared_running() {
  pgrep -f '[c]loudflared tunnel' >/dev/null 2>&1
}

stream_pids() {
  pgrep -f '[s]cripts/run_filtered_stream' 2>/dev/null || true
}

# --- 1) Uvicorn ---
if health_ok; then
  :
elif uvicorn_running && health_ok; then
  :
else
  if ! health_ok; then
    # If something is listening but unhealthy, leave it; else start fresh.
    if ! uvicorn_running; then
      append_action "start_uvicorn"
      nohup "$UVICORN_BIN" src.app:app --host 127.0.0.1 --port 8787 \
        >> logs/uvicorn.log 2>&1 &
    else
      append_action "wait_existing_uvicorn"
    fi
    deadline=$((SECONDS + UVICORN_WAIT_SEC))
    while (( SECONDS < deadline )); do
      if health_ok; then
        break
      fi
      sleep 1
    done
    if ! health_ok; then
      append_error "uvicorn_health_failed_after_${UVICORN_WAIT_SEC}s"
    fi
  fi
fi

HEALTH=false
if health_ok; then
  HEALTH=true
fi

# --- 2) cloudflared ---
TUNNEL_RUNNING=false
if [[ ! -x "$CLOUDFLARED_BIN" ]]; then
  append_error "cloudflared_missing_at_${CLOUDFLARED_BIN}"
elif cloudflared_running; then
  TUNNEL_RUNNING=true
else
  append_action "start_cloudflared"
  # Truncate marker so we can pick up a fresh trycloudflare URL if emitted
  : >> logs/cloudflared.log
  nohup "$CLOUDFLARED_BIN" tunnel --url http://127.0.0.1:8787 --no-autoupdate \
    >> logs/cloudflared.log 2>&1 &
  sleep 2
  if cloudflared_running; then
    TUNNEL_RUNNING=true
    # Nice-to-have: parse trycloudflare URL
    url="$(grep -oE 'https://[a-zA-Z0-9.-]+\.trycloudflare\.com' logs/cloudflared.log 2>/dev/null | tail -1 || true)"
    if [[ -n "${url:-}" ]]; then
      printf '%s\n' "$url" > logs/tunnel_url.txt
      append_action "wrote_tunnel_url"
    fi
  else
    append_error "cloudflared_failed_to_start"
  fi
fi

# --- 3) Rules (sync only if count is 0) ---
RULE_COUNT=0
RULES_OK=false
rules_out="$("$PYTHON_BIN" scripts/ensure_rules.py 2>/tmp/ensure_rules.err || true)"
if [[ -n "$rules_out" ]]; then
  RULE_COUNT="$(printf '%s' "$rules_out" | python3 -c 'import json,sys; d=json.load(sys.stdin); print(int(d.get("rule_count") or 0))' 2>/dev/null || echo 0)"
  synced="$(printf '%s' "$rules_out" | python3 -c 'import json,sys; d=json.load(sys.stdin); print("true" if d.get("synced") else "false")' 2>/dev/null || echo false)"
  if [[ "$synced" == "true" ]]; then
    append_action "synced_rules_was_zero"
  fi
  if (( RULE_COUNT > 0 )); then
    RULES_OK=true
  else
    append_error "rule_count_zero"
  fi
else
  err="$(head -c 200 /tmp/ensure_rules.err 2>/dev/null || true)"
  append_error "ensure_rules_failed:${err:-unknown}"
fi
rm -f /tmp/ensure_rules.err

# --- 4) Filtered stream ---
STREAM_CONNECTED=false
stream_needs_restart=false

stream_status_check() {
  "$PYTHON_BIN" - <<'PY'
import json
from datetime import datetime, timezone
from pathlib import Path

p = Path("logs/stream_status.json")
if not p.is_file():
    print("missing")
    raise SystemExit(0)
try:
    d = json.loads(p.read_text(encoding="utf-8"))
except (OSError, json.JSONDecodeError):
    print("bad_json")
    raise SystemExit(0)
connected = bool(d.get("connected"))
hb = d.get("last_heartbeat_at")
stale = True
if hb:
    try:
        # support Z and +00:00
        ts = hb.replace("Z", "+00:00")
        dt = datetime.fromisoformat(ts)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        age = (datetime.now(timezone.utc) - dt).total_seconds()
        stale = age > 180
    except ValueError:
        stale = True
if connected and not stale:
    print("ok")
elif not connected:
    print("disconnected")
else:
    print("stale")
PY
}

pids="$(stream_pids)"
status_flag="$(stream_status_check)"

if [[ -z "$pids" ]]; then
  stream_needs_restart=true
elif [[ "$status_flag" != "ok" ]]; then
  stream_needs_restart=true
fi

if $stream_needs_restart; then
  if [[ -n "$pids" ]]; then
    append_action "kill_stale_stream"
    # shellcheck disable=SC2086
    kill $pids 2>/dev/null || true
    sleep 1
    # force if still up
    leftover="$(stream_pids)"
    if [[ -n "$leftover" ]]; then
      # shellcheck disable=SC2086
      kill -9 $leftover 2>/dev/null || true
      sleep 1
    fi
  fi
  if $RULES_OK; then
    append_action "start_filtered_stream"
    # Rules already ensured; do not re-sync (may have 4 rules already)
    nohup env PYTHONPATH=. "$PYTHON_BIN" scripts/run_filtered_stream.py --no-sync-rules \
      >> logs/stream.log 2>&1 &
    # give it a moment to connect
    for _ in 1 2 3 4 5 6 7 8 9 10; do
      sleep 1
      status_flag="$(stream_status_check)"
      if [[ "$status_flag" == "ok" ]]; then
        break
      fi
    done
  else
    append_error "skip_stream_start_no_rules"
  fi
fi

status_flag="$(stream_status_check)"
if [[ "$status_flag" == "ok" ]]; then
  STREAM_CONNECTED=true
elif [[ -n "$(stream_pids)" ]]; then
  # process up but not yet connected / heartbeat not ok
  append_error "stream_not_connected:${status_flag}"
else
  append_error "stream_not_running"
fi

# --- Summary ---
OK=false
if $HEALTH && $STREAM_CONNECTED && $RULES_OK; then
  OK=true
fi

# Build JSON via python for correctness
ACTIONS_JSON="$(printf '%s\n' "${ACTIONS[@]+"${ACTIONS[@]}"}" | python3 -c 'import json,sys; print(json.dumps([l for l in sys.stdin.read().splitlines() if l]))')"
ERRORS_JSON="$(printf '%s\n' "${ERRORS[@]+"${ERRORS[@]}"}" | python3 -c 'import json,sys; print(json.dumps([l for l in sys.stdin.read().splitlines() if l]))')"

export WD_OK="$OK" WD_HEALTH="$HEALTH" WD_STREAM="$STREAM_CONNECTED" WD_TUNNEL="$TUNNEL_RUNNING"
export WD_RULE_COUNT="$RULE_COUNT" WD_TS="$TS"
export WD_ACTIONS_JSON="$ACTIONS_JSON" WD_ERRORS_JSON="$ERRORS_JSON"

"$PYTHON_BIN" - <<'PY'
import json
import os
from pathlib import Path

def flag(name: str) -> bool:
    return os.environ.get(name, "").lower() in ("1", "true", "yes")

summary = {
    "ok": flag("WD_OK"),
    "actions": json.loads(os.environ.get("WD_ACTIONS_JSON") or "[]"),
    "health": flag("WD_HEALTH"),
    "stream_connected": flag("WD_STREAM"),
    "rule_count": int(os.environ.get("WD_RULE_COUNT") or 0),
    "tunnel_running": flag("WD_TUNNEL"),
    "ts": os.environ.get("WD_TS") or "",
    "errors": json.loads(os.environ.get("WD_ERRORS_JSON") or "[]"),
}
Path("logs/watchdog_last.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
print(json.dumps(summary))
PY

if $OK; then
  exit 0
fi
exit 1
