#!/usr/bin/env bash
# start.sh - start the TaskReimagination services.
#
# FastAPI and the React UI are required. Everything else is optional and is
# skipped with a stated reason rather than aborting the whole script.
#
#   ./start.sh          production-style - no auto-reload
#   ./start.sh --dev    auto-reload on file change
#
# Auto-reload restarts the API whenever a file changes, which kills any crew run
# in flight and leaves it marked as interrupted. Do not use --dev on the
# always-on box.
cd "$(dirname "$0")"

DEV_MODE=0
[ "${1:-}" = "--dev" ] && DEV_MODE=1

mkdir -p .pids

STARTED=()
SKIPPED=()

# Read one value from .env without letting the shell evaluate it. Values such as
# FROM_EMAIL contain spaces and angle brackets, so the usual
# `export $(grep -v '^#' .env | xargs)` idiom fails on them - combined with
# `set -e` that aborted this script before it started anything at all.
# The API does not need these exported: pydantic-settings reads .env directly.
env_value() {
  [ -f .env ] || return 0
  sed -n "s/^$1=//p" .env | head -1
}

have() { command -v "$1" >/dev/null 2>&1; }

# ── Python ───────────────────────────────────────────────────────────────────
# The project venv is the only supported interpreter: crewai and litellm both
# declare Requires-Python <3.14, so a Homebrew 3.14 cannot run this project.
PY_UVICORN="./venv/bin/uvicorn"
if [ ! -x "$PY_UVICORN" ]; then
  echo "ERROR: $PY_UVICORN not found - the project venv is missing or incomplete."
  echo "  Rebuild it with a 3.13 interpreter:"
  echo "    uv python install 3.13"
  echo "    \$(uv python find 3.13) -m venv venv"
  echo "    ./venv/bin/pip install -r requirements.txt"
  exit 1
fi

# ── Optional Docker services ─────────────────────────────────────────────────
# ChromaDB is the only Docker service since n8n was retired, and it is needed
# only when CHROMA_API_KEY is unset - that is how ingest_service and chroma_query
# pick CloudClient over HttpClient. So this is skipped outright when Chroma Cloud
# is in use, rather than starting a container nothing will connect to.
if [ -n "$(env_value CHROMA_API_KEY)" ]; then
  SKIPPED+=("Local ChromaDB - CHROMA_API_KEY is set, so Chroma Cloud is in use")
elif have docker; then
  echo "Starting Docker services (ChromaDB)..."
  if docker compose up -d 2>/dev/null; then
    STARTED+=("ChromaDB       http://localhost:8002")
  else
    SKIPPED+=("Docker services - 'docker compose up' failed (is Docker running?)")
  fi
else
  SKIPPED+=("Docker services - docker not installed (ChromaDB needs it)")
fi

# ── LiteLLM proxy - only needed for local / sensitive-mode routing ────────────
if [ -x ./venv/bin/litellm ] && [ -f litellm_config.yaml ]; then
  echo "Starting LiteLLM proxy on :4000..."
  ./venv/bin/litellm --config litellm_config.yaml --port 4000 >/dev/null 2>&1 &
  echo $! > .pids/litellm.pid
  STARTED+=("LiteLLM        http://localhost:4000")
else
  SKIPPED+=("LiteLLM - not in venv or litellm_config.yaml missing (only needed for sensitive mode)")
fi

# ── FastAPI - required ───────────────────────────────────────────────────────
if [ "$DEV_MODE" = "1" ]; then
  echo "Starting FastAPI on :8000 (auto-reload ON - not for the always-on box)..."
  "$PY_UVICORN" api.main:app --host 0.0.0.0 --port 8000 --reload &
else
  echo "Starting FastAPI on :8000..."
  "$PY_UVICORN" api.main:app --host 0.0.0.0 --port 8000 &
fi
echo $! > .pids/fastapi.pid
STARTED+=("FastAPI        http://localhost:8000/docs")

# ── React UI - required ──────────────────────────────────────────────────────
echo "Starting React UI on :3000..."
( cd ui && npm run dev -- --port 3000 >/dev/null 2>&1 &
  echo $! > ../.pids/ui.pid )
STARTED+=("React UI       http://localhost:3000/dashboard")

# ── Caddy - reverse proxy, only needed to serve the tunnel on :80 ────────────
if have caddy && [ -f Caddyfile ]; then
  echo "Starting Caddy on :80..."
  caddy run --config Caddyfile --adapter caddyfile >/dev/null 2>&1 &
  echo $! > .pids/caddy.pid
  STARTED+=("Caddy          http://localhost:80")
else
  SKIPPED+=("Caddy - not installed or Caddyfile missing (only needed to serve publicly)")
fi

# ── Cloudflare Tunnel - public access ────────────────────────────────────────
TUNNEL_TOKEN="$(env_value CLOUDFLARE_TUNNEL_TOKEN)"
if have cloudflared && [ -n "$TUNNEL_TOKEN" ]; then
  echo "Starting Cloudflare Tunnel..."
  cloudflared tunnel run --token "$TUNNEL_TOKEN" >/dev/null 2>&1 &
  echo $! > .pids/cloudflared.pid
  PUBLIC_URL="$(env_value PUBLIC_URL)"
  STARTED+=("Public URL     ${PUBLIC_URL:-<PUBLIC_URL not set>}/dashboard")
elif ! have cloudflared; then
  SKIPPED+=("Cloudflare Tunnel - cloudflared not installed")
else
  SKIPPED+=("Cloudflare Tunnel - CLOUDFLARE_TUNNEL_TOKEN not set in .env")
fi

# ── Summary ──────────────────────────────────────────────────────────────────
echo ""
echo "Running:"
for s in "${STARTED[@]}"; do echo "  $s"; done
if [ ${#SKIPPED[@]} -gt 0 ]; then
  echo ""
  echo "Skipped:"
  for s in "${SKIPPED[@]}"; do echo "  $s"; done
fi
echo ""
echo "Stop everything with ./stop.sh"
