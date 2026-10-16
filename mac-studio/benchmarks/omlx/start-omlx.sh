#!/usr/bin/env bash
# start-omlx.sh — run the oMLX trial server (0.7.0, uv venv here) on
# 127.0.0.1:8000, in the background, as mdella. Not a LaunchDaemon: trial only.
#   ~/projects/omlx-trial/start-omlx.sh          start (no-op if already up)
#   ~/projects/omlx-trial/start-omlx.sh stop     stop
# Per-model settings (alias agentworld-oq4, sampling): ~/.omlx/model_settings.json
# Logs: ~/.omlx/logs/server.log.  SSD KV cache: ~/.omlx/cache.
# The process renames itself "omlx-server", so find it by its port, not by name.
set -euo pipefail
D="$(cd "$(dirname "$0")" && pwd)"
pid() { lsof -tnP -iTCP:8000 -sTCP:LISTEN 2>/dev/null || true; }
if [ "${1:-}" = stop ]; then
  p=$(pid); [ -n "$p" ] && kill "$p" && echo "stopped $p" || echo "not running"; exit 0
fi
[ -n "$(pid)" ] && { echo "already running (pid $(pid))"; exit 0; }
cd "$D"
nohup .venv/bin/omlx serve --model-dir "$D/models" --host 127.0.0.1 --port 8000 > "$D/server.log" 2>&1 &
for _ in $(seq 1 30); do curl -fsS --max-time 2 http://127.0.0.1:8000/v1/models >/dev/null 2>&1 && break; sleep 1; done
curl -fsS http://127.0.0.1:8000/v1/models && echo
