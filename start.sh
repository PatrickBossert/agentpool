#!/usr/bin/env bash
# start.sh — start all FutureMomentum services
set -e
cd "$(dirname "$0")"

# Load environment variables
if [ -f .env ]; then
  export $(grep -v '^#' .env | xargs)
fi

mkdir -p .pids

echo "Starting Docker services (ChromaDB + n8n)..."
docker compose up -d

echo "Starting LiteLLM proxy on :4000..."
litellm --config litellm_config.yaml --port 4000 &
echo $! > .pids/litellm.pid

echo "Starting FastAPI on :8000..."
/opt/homebrew/bin/python3.13 -m uvicorn api.main:app --host 0.0.0.0 --port 8000 --reload &
echo $! > .pids/fastapi.pid

echo "Starting Chainlit on :8001..."
cd chainlit_app && /opt/homebrew/bin/chainlit run app.py --port 8001 &
echo $! > .pids/chainlit.pid
cd ..

echo "Starting React UI on :3000..."
cd ui && npm run dev -- --port 3000 &
echo $! > ../.pids/ui.pid
cd ..

echo "Starting Caddy on :80..."
/opt/homebrew/bin/caddy run --config Caddyfile --adapter caddyfile &
echo $! > .pids/caddy.pid

echo "Starting Cloudflare Tunnel..."
/opt/homebrew/bin/cloudflared tunnel run --token "$CLOUDFLARE_TUNNEL_TOKEN" &
echo $! > .pids/cloudflared.pid

echo ""
echo "FutureMomentum services running:"
echo "  FastAPI:      http://localhost:8000/docs"
echo "  Chainlit:     http://localhost:8001"
echo "  React UI:     http://localhost:3000"
echo "  Caddy (local) http://localhost:80"
echo "  n8n:          http://localhost:5678"
echo "  ChromaDB:     http://localhost:8002"
echo "  LiteLLM:      http://localhost:4000"
echo "  Public URL:   https://futuremomentum.ai/dashboard"
