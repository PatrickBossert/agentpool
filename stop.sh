#!/usr/bin/env bash
# stop.sh - stop the TaskReimagination services.
#
# No `set -e`: a service that is already gone, or a Docker that is not
# installed, must not stop this script from shutting down everything else.
cd "$(dirname "$0")"

STOPPED=0

if [ -d .pids ]; then
  for pid_file in .pids/*.pid; do
    [ -f "$pid_file" ] || continue
    name="$(basename "$pid_file" .pid)"
    pid="$(cat "$pid_file" 2>/dev/null)"
    if [ -n "$pid" ] && kill "$pid" 2>/dev/null; then
      echo "  stopped $name (pid $pid)"
      STOPPED=$((STOPPED + 1))
    else
      echo "  $name was not running"
    fi
    rm -f "$pid_file"
  done
fi

# The UI and Chainlit spawn children that outlive the recorded pid, so clear any
# stragglers holding the ports we own.
for port in 3000 8000 8001 4000; do
  pids="$(lsof -ti :$port 2>/dev/null)"
  if [ -n "$pids" ]; then
    echo "  freeing port $port"
    # shellcheck disable=SC2086
    kill $pids 2>/dev/null
  fi
done

if command -v docker >/dev/null 2>&1; then
  docker compose stop 2>/dev/null && echo "  stopped Docker services"
else
  echo "  skipped Docker services - docker not installed"
fi

echo "Done ($STOPPED tracked service(s) stopped)."
