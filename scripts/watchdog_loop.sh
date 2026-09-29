#!/usr/bin/env bash
# Thin forever loop: run ensure_stack.sh every 60s.
# Useful as: nohup /workspace/x-pr-monitor/scripts/watchdog_loop.sh >> /workspace/x-pr-monitor/logs/watchdog.log 2>&1 &
set -u
ROOT="/workspace/x-pr-monitor"
ENSURE="$ROOT/scripts/ensure_stack.sh"
INTERVAL="${WATCHDOG_INTERVAL_SEC:-60}"

cd "$ROOT" || exit 1
mkdir -p logs

echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) watchdog_loop start interval=${INTERVAL}s"
while true; do
  "$ENSURE" || true
  sleep "$INTERVAL"
done
