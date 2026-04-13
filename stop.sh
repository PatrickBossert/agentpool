#!/usr/bin/env bash
# stop.sh — stop all AgentPool services
set -e
cd "$(dirname "$0")"

for pid_file in .pids/*.pid; do
  [ -f "$pid_file" ] && kill "$(cat "$pid_file")" 2>/dev/null && rm "$pid_file"
done

docker compose stop
echo "All AgentPool services stopped."
