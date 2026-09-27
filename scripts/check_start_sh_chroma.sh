#!/usr/bin/env bash
# scripts/check_start_sh_chroma.sh - drive start.sh's ChromaDB decision, without starting one.
#
# start.sh is shell, so no pytest covers it, and "launch the stack and look" is not a test: it
# starts a vector store, a web server and a UI, and on this machine there is a crew run in
# flight. The decision is therefore a pure function of four facts (`chroma_decision` in
# start.sh) and this script drives every branch of it directly - no service started, no file
# written, no socket opened.
#
# Run from the repository root:  ./scripts/check_start_sh_chroma.sh
#
# What this covers and what it does not. It covers the *decision*: given what is installed and
# what is already running, which route does the launcher take. It does not cover the acting
# half - that `chroma run` actually serves, or that `docker compose up` works - because both
# start a server. The acting half was verified by hand once, and the way it was verified is
# recorded in the report rather than pretended at here.
set -u

cd "$(dirname "$0")/.."
ROOT="$PWD"

# Sourcing start.sh with this set defines the functions and returns before anything starts.
# start.sh cds to its own directory, which for a sourced file is resolved against *this*
# script's $0 - harmless, since nothing below calls anything that reads the filesystem, but we
# come back so the summary is printed from a predictable place.
# shellcheck disable=SC1091
START_SH_DECISIONS_ONLY=1 . ./start.sh
cd "$ROOT"

PASS=0
FAIL=0

# expect <expected> <api_key> <answering> <have_cli> <have_docker> <description>
expect() {
  local expected="$1"; shift
  local got
  got="$(chroma_decision "$1" "$2" "$3" "$4")"
  local desc="$5"
  if [ "$got" = "$expected" ]; then
    PASS=$((PASS + 1))
    printf '  ok    %-16s %s\n' "$got" "$desc"
  else
    FAIL=$((FAIL + 1))
    printf '  FAIL  expected %-16s got %-16s %s\n' "$expected" "$got" "$desc"
  fi
}

echo "start.sh ChromaDB decision - every branch:"

# The five routes, each reached on its own terms.
expect cloud           1 0 0 0 "CHROMA_API_KEY set - Chroma Cloud is in use, start nothing local"
expect cannot-probe    0 unknown 1 1 "curl missing - cannot tell if one is running, so start nothing"
expect already-running 0 1 1 1 "already answering on :8002 - leave the operator's server alone"
expect cli             0 0 1 0 "venv/bin/chroma present - the preferred local route"
expect docker          0 0 0 1 "no venv CLI but docker present - the container fallback"
expect none            0 0 0 0 "neither available - skip with an honest reason"

echo "Precedence - the orderings that matter:"

# The cloud branch must win over every local route. This is the regression that would send a
# deployment's material to Chroma Cloud *and* leave a local server running beside it, and it
# is the branch the brief singled out as correct today and not to be lost.
expect cloud 1 1 1 1 "CHROMA_API_KEY wins even when everything else is available"
expect cloud 1 0 1 1 "CHROMA_API_KEY wins over both local routes"
expect cloud 1 1 0 0 "CHROMA_API_KEY wins over a server already running"

# "Already running" must win over both ways of starting one. This is the failure the brief
# described happening in practice - a second server started on top of one an operator had
# started by hand.
expect already-running 0 1 1 0 "a running server is not replaced by the venv CLI"
expect already-running 0 1 0 1 "a running server is not replaced by Docker"
expect already-running 0 1 0 0 "a running server is left alone even with no way to start one"

# "Cannot tell" must never be read as "nothing is running" - that is how a second server gets
# started on top of an operator's own, which is the outcome this whole block exists to refuse.
expect cannot-probe    0 unknown 1 0 "unprobeable is not the same as absent, with the CLI available"
expect cannot-probe    0 unknown 0 1 "unprobeable is not the same as absent, with Docker available"
expect cloud           1 unknown 1 1 "the cloud branch still wins when the probe is unavailable"

# The venv CLI is preferred to Docker, which is the substantive change: the old block knew
# only about Docker and reported its absence as the reason ChromaDB could not run.
expect cli 0 0 1 1 "the venv CLI is preferred when both routes are available"

echo
if [ "$FAIL" -eq 0 ]; then
  echo "All $PASS decision checks passed."
else
  echo "$FAIL of $((PASS + FAIL)) decision checks FAILED."
  exit 1
fi
