# FutureMomentum AgentPool

AI-driven business strategy platform. Multi-agent crews analyse organisations, surface value opportunities, build roadmaps, interview stakeholders, and produce boardroom-ready outputs — Business Plan, Value Chain, Initiative Register, and client Report PDF.

---

## Architecture overview

```
Browser  →  React SPA (ui/)          →  FastAPI (api/)   →  SQLite per project
                                     →  ChromaDB          →  RAG / document store
                                     →  CrewAI crews      →  Claude Opus / local LLM
n8n      →  webhook triggers         →  /orchestrate      →  PAM crew → child crews
Caddy    →  reverse proxy (prod)
cloudflared  →  tunnel to public URL (prod)
```

Services:

| Service   | Local port | Docker service |
|-----------|-----------|---------------|
| FastAPI   | 8000      | — (run directly) |
| ChromaDB  | 8002      | `chromadb`    |
| n8n       | 5678      | `n8n`         |
| React dev | 3000      | — (Vite)      |
| Caddy     | 80/443    | — (prod only) |

---

## Prerequisites

- Python 3.11+ (3.13 tested; **use a venv**)
- Node 18+
- Docker + Docker Compose
- [Caddy](https://caddyserver.com/docs/install) (production only)
- [cloudflared](https://developers.cloudflare.com/cloudflare-one/connections/connect-apps/install-and-setup/tunnel-guide/) (production only)

---

## Setup

### 1. Clone and create virtual environment

```bash
git clone <repo-url> agentpool1
cd agentpool1
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 2. Configure environment

```bash
cp .env.example .env
```

Edit `.env` and fill in **every** value. Key fields:

| Variable | Description |
|----------|-------------|
| `ANTHROPIC_API_KEY` | Claude API key — required for all crews |
| `ADMIN_USERNAME` | Login username for the web UI |
| `ADMIN_PASSWORD` | Login password for the web UI |
| `JWT_SECRET` | Random secret for signing auth tokens — generate with `openssl rand -hex 32` |
| `N8N_BASIC_AUTH_USER` | n8n dashboard login username |
| `N8N_BASIC_AUTH_PASSWORD` | n8n dashboard login password |
| `RESEND_API_KEY` | Resend API key for reminder emails (optional) |
| `ELEVENLABS_API_KEY` | Voice synthesis for stakeholder interviews (optional) |
| `DEEPGRAM_API_KEY` | Speech-to-text transcription (optional) |
| `TAVILY_API_KEY` | Web search for Discovery crew (optional) |
| `PUBLIC_URL` | Full public URL — used in interview email links |

### 3. Start Docker services

```bash
docker compose up -d
```

Starts ChromaDB on `:8002` and n8n on `:5678`.

### 4. Start the API

```bash
source .venv/bin/activate
uvicorn api.main:app --reload --port 8000
```

### 5. Start the React UI

```bash
cd ui
npm install
npm run dev
```

Open `http://localhost:3000/dashboard` (or `http://localhost:3000/dashboard/login`).

---

## First-time login

Use the `ADMIN_USERNAME` / `ADMIN_PASSWORD` values from your `.env`.

The admin account is created automatically on first startup using these env vars. If you change them after first run, you must also update the hashed password in `data/system.db` (or delete the file to reset).

---

## Creating a project

1. Click **New Project** in the sidebar.
2. Fill in client name, slug (URL-safe identifier), and industry.
3. Upload any source documents (PDFs, DOCX) on the **Documents** page — they are automatically ingested into ChromaDB.
4. Configure project settings (interview method, value chain focus areas, etc.) on the **Settings** page.

---

## Running the pipeline

Click **Run Pipeline** on the Dashboard. This sends a webhook to n8n, which triggers the PAM (Project Automation Manager) orchestration endpoint at `POST /orchestrate`.

The PAM crew runs in two phases:

1. **Awaiting assignment** — runs the Discovery Mapping crew, then pauses for a human to assign stakeholders on the Assignment page.
2. **Post-assignment** — runs the remaining crews in sequence: Discovery Interviews → Value Design → Architecture → Delivery Planning → Business Plan.

Progress is visible in the **Runs** tab and the neural agent tree on the Dashboard.

---

## Crew execution order

```
PAM orchestrator
  └── Discovery Mapping crew
        (pause — human assigns stakeholders)
  └── Discovery Interviews crew
  └── Value Design crew
  └── Architecture crew
  └── Delivery Planning crew
  └── Business Plan crew
```

Each crew writes structured JSON to `projects/<slug>/outputs/`.

---

## n8n workflows

n8n workflows live in `workflows/`. Import them via **Settings → Import from file** in the n8n UI (`http://localhost:5678`).

Required workflows:
- `orchestrate.json` — receives webhook, calls `/orchestrate`
- `reminder_emails.json` — scheduled reminder dispatch

n8n credentials (Slack OAuth2 API, etc.) are configured in the n8n UI, not in `.env`.

---

## Voice interviews

Stakeholders receive an email with a link to `/dashboard/interview/:sessionToken`. The page uses:
- **ElevenLabs** for AI voice synthesis (requires `ELEVENLABS_API_KEY`)
- **Web Speech API** (browser built-in) for speech recognition
- **Deepgram** as fallback transcription (requires `DEEPGRAM_API_KEY`)

Interview sessions are tracked in the **Discovery → Interviews** tab. Completed transcripts feed directly into the Discovery Interviews crew.

---

## Production deployment (Caddy + cloudflared)

See `docs/superpowers/specs/` for the SP16a deployment spec.

Quick summary:
1. Set `PUBLIC_URL` to your public domain in `.env`
2. Set `CLOUDFLARE_TUNNEL_TOKEN` in `.env`
3. Run `./start.sh` — starts API, Caddy, and cloudflared tunnel

Caddy serves the React build at `/dashboard`, proxies `/api` to FastAPI, and `/n8n` to n8n.

---

## Testing

```bash
# Run all tests
pytest

# Run with coverage
pytest --cov=api --cov-report=term-missing

# Run a specific test file
pytest tests/test_campaigns.py -v
```

The test suite uses SQLite in-memory fixtures. No running services are required.

Current status: **400+ tests passing** (see memory index for per-sprint counts).

---

## Project structure

```
agentpool1/
├── api/                    FastAPI application
│   ├── main.py             App factory + router registration
│   ├── auth.py             JWT + bcrypt password hashing
│   ├── config.py           Pydantic Settings (reads .env)
│   ├── database.py         All async SQLite helpers
│   ├── routers/            One file per resource
│   └── services/           Business logic (crews, campaigns, etc.)
├── crews/                  CrewAI crew factories
│   ├── agents/             Individual agent definitions
│   └── tools/              Custom CrewAI tools
├── projects/               Per-client data (gitignored except example/)
│   └── example/            Reference project config
├── ui/                     React + TypeScript SPA
│   └── src/
│       ├── pages/          One file per route
│       ├── components/     Shared components
│       ├── api/            API client functions
│       └── context/        Auth context
├── workflows/              n8n workflow JSON exports
├── data/                   SQLite databases + ChromaDB (gitignored)
├── docs/superpowers/       Design specs and implementation plans
├── docker-compose.yml      ChromaDB + n8n
├── .env.example            Environment variable template
├── requirements.txt        Python dependencies
└── start.sh                Production start script
```

---

## Key environment variables reference

See `.env.example` for the full list with descriptions. Never commit `.env`.

---

## Troubleshooting

**Login fails after updating ADMIN_PASSWORD**
The admin user is created once and stored hashed in `data/system.db`. Delete `data/system.db` and restart to recreate with new credentials.

**ChromaDB connection refused**
Run `docker compose up -d chromadb` and verify port 8002 is listening.

**n8n webhook not firing**
Ensure `N8N_WEBHOOK_URL` in `.env` matches the webhook URL configured in n8n. The n8n container must be running.

**Voice interview page blank**
Browser must support Web Speech API (Chrome/Edge). Check that `PUBLIC_URL` is set correctly so interview links resolve.

**Resend emails not sending**
Verify `RESEND_API_KEY` is set and `futuremomentum.ai` is a verified sender domain in the Resend dashboard.

**python-pptx ImportError**
Install inside the venv: `pip install python-pptx`. Do not use system pip on macOS with Homebrew Python.
