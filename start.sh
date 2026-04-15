#!/usr/bin/env bash
# start.sh — start all AgentPool services
set -e
cd "$(dirname "$0")"
source .venv/bin/activate

mkdir -p .pids

echo "Starting Docker services (ChromaDB + n8n)..."
docker compose up -d

echo "Starting LiteLLM proxy on :4000..."
litellm --config litellm_config.yaml --port 4000 &
echo $! > .pids/litellm.pid

echo "Starting FastAPI on :8000..."
uvicorn api.main:app --host 0.0.0.0 --port 8000 --reload &
echo $! > .pids/fastapi.pid

echo "Starting Chainlit on :8001..."
cd chainlit_app && chainlit run app.py --port 8001 &
echo $! > .pids/chainlit.pid
cd ..

echo "Starting React UI on :3000..."
cd ui && npm run dev -- --port 3000 &
echo $! > ../.pids/ui.pid
cd ..

echo ""
echo "AgentPool services running:"
echo "  FastAPI:   http://localhost:8000/docs"
echo "  Chainlit:  http://localhost:8001"
echo "  React UI:  http://localhost:3000"
echo "  n8n:       http://localhost:5678"
echo "  ChromaDB:  http://localhost:8002"
echo "  LiteLLM:   http://localhost:4000"
echo "  llama.cpp: http://localhost:10000 (existing)"
