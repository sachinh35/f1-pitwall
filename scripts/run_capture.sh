#!/usr/bin/env bash
# Watchdog for scripts/capture_stream.py: restarts it if the process ever exits, so raw
# JSONL capture survives a hard crash (OOM, segfault in a C extension, etc.) - not just
# the in-process SignalR reconnect logic capture_stream.py already handles itself.
#
# Usage:
#   ./scripts/run_capture.sh <session-name> [token]
#
# Run detached so it survives the terminal closing, e.g.:
#   nohup ./scripts/run_capture.sh quali_2026_07_25 > logs/capture.log 2>&1 &
#
# Stop it with: pkill -f "run_capture.sh <session-name>" (also stop the child
# capture_stream.py process it spawns, e.g. via pkill -f "capture_stream.*<session-name>").
set -u

SESSION_NAME="${1:?Usage: run_capture.sh <session-name> [token]}"
TOKEN="${2:-}"

cd "$(dirname "$0")/.."

while true; do
  echo "$(date -u +%FT%TZ) starting capture_stream.py (session=${SESSION_NAME})"
  if [ -n "$TOKEN" ]; then
    uv run python -m scripts.capture_stream --session-name "$SESSION_NAME" --token "$TOKEN"
  else
    uv run python -m scripts.capture_stream --session-name "$SESSION_NAME"
  fi
  EXIT_CODE=$?
  echo "$(date -u +%FT%TZ) capture_stream.py exited with code ${EXIT_CODE} - restarting in 5s"
  sleep 5
done
