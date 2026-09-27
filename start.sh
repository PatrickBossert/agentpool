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

# Where the local ChromaDB keeps its data.
#
# Not a guess and not a new setting. Three things already agree on it: docker-compose.yml
# mounts ./data/chroma, the server the owner had started by hand was running with
# `--path data/chroma`, and that directory holds the only chroma.sqlite3 on the machine
# outside an abandoned worktree. There is no second store to choose between, so nothing here
# needs to be made configurable to avoid picking the wrong one.
CHROMA_PATH="data/chroma"

# Host and port come from .env, because `api/config.py` declares `chroma_host`/`chroma_port` and
# `.env.example` invites an operator to set them.
#
# **Hardcoding 8002 here recreated the very failure the block below refuses.** With
# `CHROMA_PORT=8003`, the probe asked 8002, saw nothing, and started a *second* server on
# 8002 - while the application opened 8003 - then announced 8002 as the running store. That is
# "a check that examines a different store from the code", which `check_vector_store` was
# repaired for one file over; the two remedies in one product must not disagree about where the
# store is. `check_vector_store`'s local remedy already prints `--port {settings.chroma_port}`.
#
# The defaults match `api/config.py`'s, and are the only place this file states them.
CHROMA_HOST="$(env_value CHROMA_HOST)"; [ -n "$CHROMA_HOST" ] || CHROMA_HOST="localhost"
CHROMA_PORT="$(env_value CHROMA_PORT)"; [ -n "$CHROMA_PORT" ] || CHROMA_PORT="8002"

# Whether something is already answering as ChromaDB on the port.
#
# **curl, not bash's /dev/tcp.** macOS ships bash 3.2, which is built without /dev/tcp, so
# the usual `(exec 3<>/dev/tcp/localhost/8002)` idiom fails *identically* whether the port is
# open or closed. On this machine it reported "closed" against a server that was serving -
# and a false negative here is the specific failure this block must not have, because it ends
# with a second server started on top of an operator's own. It also asks for the heartbeat
# rather than merely opening a socket, so "a process holds the port" and "ChromaDB is
# answering" are not confused. Both API versions are tried: v2 is what the pinned CLI
# answers, v1 is what the 0.6.3 image in docker-compose.yml answers.
# Answers 0 (answering), 1 (not answering), or 2 (cannot tell).
#
# **"Cannot tell" is not "not answering".** Without curl there is no way to probe, and treating
# that as "nothing is running" starts a server on top of whatever is already there - the degrade-
# rather-than-fail shape, arriving in the function written to prevent it. The caller skips with
# an honest reason instead.
chroma_answering() {
  have curl || return 2
  curl -fsS -m 3 -o /dev/null "http://$CHROMA_HOST:$CHROMA_PORT/api/v2/heartbeat" 2>/dev/null && return 0
  curl -fsS -m 3 -o /dev/null "http://$CHROMA_HOST:$CHROMA_PORT/api/v1/heartbeat" 2>/dev/null && return 0
  return 1
}

# The whole decision, as a pure function of four facts, so it can be driven directly.
#
# start.sh cannot be covered by pytest, and launching the stack to find out what it would do
# is not a test. Separating the decision from the doing means every branch can be exercised in
# a second with no service started and nothing written - see `scripts/check_start_sh_chroma.sh`,
# which drives all five. The caller below probes the four facts and acts on the answer; this
# function touches nothing.
#
# Order is load-bearing. The cloud check is first because a deployment using Chroma Cloud must
# start no local server whatever else is installed. "Already answering" is second because the
# operator may have started one by hand, and starting a second on the same port is how the
# store this project reads ends up not being the store it writes.
# Arguments, each "1" or "0": CHROMA_API_KEY set, already answering, venv CLI present,
# docker present. Written as plain if/elif rather than `&&` short-circuits so it behaves the
# same should anyone ever put `set -e` back at the top of this file.
chroma_decision() {
  if [ "$1" = "1" ]; then
    echo "cloud"
  elif [ "$2" = "unknown" ]; then
    # Cannot probe, so cannot promise the port is free. Refusing to start is the safe
    # direction: a missed start is visible in the skip list, a duplicate server is not.
    echo "cannot-probe"
  elif [ "$2" = "1" ]; then
    echo "already-running"
  elif [ "$3" = "1" ]; then
    echo "cli"
  elif [ "$4" = "1" ]; then
    echo "docker"
  else
    echo "none"
  fi
}

# Everything above this line defines and decides; everything below it starts services.
#
# `START_SH_DECISIONS_ONLY=1 . ./start.sh` therefore gives a caller the functions with nothing
# launched, written, or connected to, which is what lets the branches be driven at all. It is a
# testing seam and nothing reads it in normal operation - the variable is unset, the guard is
# false, and the script runs exactly as it did.
if [ -n "${START_SH_DECISIONS_ONLY:-}" ]; then
  return 0 2>/dev/null || exit 0
fi

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

# ── ChromaDB ─────────────────────────────────────────────────────────────────
# The vector store. Needed whenever CHROMA_API_KEY is unset - that is how ingest_service and
# chroma_query pick CloudClient over HttpClient - so this is skipped outright when Chroma
# Cloud is in use, rather than starting a local server nothing will connect to.
#
# **This block used to say "docker not installed (ChromaDB needs it)", and that is false.**
# ChromaDB ships a CLI, `venv/bin/chroma`, and `chroma run --path ... --port 8002` serves
# exactly what the container serves, so the stated reason was never the real one.
#
# Scope, stated honestly, because the first version of this comment overstated it: on *this*
# machine `CHROMA_API_KEY` is set, so the cloud branch wins first and that message has never
# actually been printed here - the engagement's vectors are in the cloud account and no local
# server was ever needed. The message is wrong for a deployment **without** the key, which is
# the one this branch fixes, and which is what an on-premises secure-mode customer runs.
#
# The venv CLI is preferred over Docker because it is the interpreter this project already
# pins and requires; Docker is kept as the fallback for a deployment that has standardised on
# the container. Both are named in the skip message when neither is available, so an operator
# is told what to install rather than being sent to install the one thing this block used to
# know about.
CHROMA_HAVE_KEY=0;   [ -n "$(env_value CHROMA_API_KEY)" ] && CHROMA_HAVE_KEY=1
chroma_answering; case $? in
  0) CHROMA_ANSWERING=1 ;;
  2) CHROMA_ANSWERING="unknown" ;;
  *) CHROMA_ANSWERING=0 ;;
esac
CHROMA_HAVE_CLI=0;   [ -x "./venv/bin/chroma" ] && CHROMA_HAVE_CLI=1
CHROMA_HAVE_DOCKER=0; have docker && CHROMA_HAVE_DOCKER=1

case "$(chroma_decision "$CHROMA_HAVE_KEY" "$CHROMA_ANSWERING" "$CHROMA_HAVE_CLI" "$CHROMA_HAVE_DOCKER")" in
  cloud)
    SKIPPED+=("Local ChromaDB - CHROMA_API_KEY is set, so Chroma Cloud is in use")
    ;;
  cannot-probe)
    SKIPPED+=("ChromaDB - curl is not installed, so this script cannot tell whether one is already listening on $CHROMA_HOST:$CHROMA_PORT. Refusing to start a second one. Install curl, or start it yourself with './venv/bin/chroma run --host $CHROMA_HOST --port $CHROMA_PORT --path $CHROMA_PATH'.")
    ;;
  already-running)
    # Deliberately starts nothing. The operator who started this by hand is the reason the
    # store has any data at all, and a second server on the same port would either fail to
    # bind or split reads from writes.
    STARTED+=("ChromaDB       http://$CHROMA_HOST:$CHROMA_PORT (already running - left alone)")
    ;;
  cli)
    echo "Starting ChromaDB on $CHROMA_HOST:$CHROMA_PORT (venv CLI, --path $CHROMA_PATH)..."
    mkdir -p "$CHROMA_PATH"
    ./venv/bin/chroma run --host "$CHROMA_HOST" --port "$CHROMA_PORT" --path "$CHROMA_PATH" \
      >/dev/null 2>&1 &
    echo $! > .pids/chroma.pid
    STARTED+=("ChromaDB       http://$CHROMA_HOST:$CHROMA_PORT (venv CLI, $CHROMA_PATH)")
    ;;
  docker)
    echo "Starting ChromaDB via Docker (no venv/bin/chroma found)..."
    if docker compose up -d 2>/dev/null; then
      STARTED+=("ChromaDB       http://$CHROMA_HOST:$CHROMA_PORT (Docker, $CHROMA_PATH)")
    else
      SKIPPED+=("ChromaDB - 'docker compose up' failed (is Docker running?) and there is no venv/bin/chroma")
    fi
    ;;
  *)
    SKIPPED+=("ChromaDB - neither venv/bin/chroma nor docker is available. Install it into the venv with './venv/bin/pip install chromadb', or install Docker. Retrieval and document ingest will fail until one of them is running.")
    ;;
esac

# No LiteLLM proxy. LiteLLM is a **library** here: crew agents build `LLM(...)` with a
# base_url taken from the project's own settings and call the provider directly, and nothing in
# the codebase has ever read `litellm_proxy_url` or spoken to :4000. This block started one
# anyway and announced it to the operator as a running service, with a comment saying it was
# "only needed for local / sensitive-mode routing" - which is the opposite of true: local
# routing goes to the project's `local_fast_url` / `local_deep_url`, Ollama on :11434 by
# default. Retired in sp66 along with litellm_config.yaml and the setting.

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
