# CLAUDE.md — AgentPool project context

This file is loaded automatically by Claude Code. It captures conventions, key files, and context so new sessions can resume without re-reading the codebase.

---

## Tech stack

| Layer | Technology |
|-------|-----------|
| Backend | FastAPI (async), aiosqlite, Pydantic v2, pydantic-settings |
| AI crews | CrewAI, Anthropic Claude Opus (PAM always; others configurable) |
| Vector store | ChromaDB (HttpClient on :8002) |
| Auth | JWT (python-jose), bcrypt (direct — NOT passlib; see below) |
| Frontend | React 18, TypeScript, Vite, Tailwind CSS v3, React Router v6 |
| Email | Resend HTTP API (httpx — not SMTP) |
| Voice | ElevenLabs (TTS) + Web Speech API + Deepgram (STT) |
| Workflow | n8n (Docker, :5678) — triggers /orchestrate webhook |
| Infra | Docker Compose (ChromaDB + n8n), Caddy (prod), cloudflared (prod) |

---

## Critical: bcrypt / passlib

**Do NOT use passlib.** It is incompatible with bcrypt 5.x (Homebrew Python 3.13).

Use `bcrypt` directly — see `api/auth.py`:
```python
import bcrypt

def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()

def verify_password(plain: str, hashed: str) -> bool:
    return bcrypt.checkpw(plain.encode(), hashed.encode())
```

---

## Test commands

```bash
# All tests
pytest

# With coverage
pytest --cov=api --cov-report=term-missing

# Single file
pytest tests/test_campaigns.py -v
```

Tests use in-memory SQLite — no running services required.

---

## Database conventions

- **One SQLite file per project**: `data/<slug>.db`
- **System DB**: `data/system.db` — users, templates
- All DB access is async via `aiosqlite`
- All helpers are in `api/database.py` — no ORM
- Schema migrations are raw `ALTER TABLE` or `CREATE TABLE IF NOT EXISTS` run in `database.py` on connection open
- Test fixtures manually recreate relevant tables (check `conftest.py` and per-test fixtures)

When adding a new column to an existing table:
1. Add `ALTER TABLE ... ADD COLUMN` to the appropriate `ensure_*_table` function in `database.py`
2. Add the column to the `CREATE TABLE` statement so fresh DBs include it
3. Add the column to test fixtures that create that table manually

---

## API conventions

- Router files: `api/routers/<resource>.py`
- Service functions: `api/services/<feature>_service.py`
- Auth: JWT bearer token, `Depends(get_current_user)` on protected routes
- 404 helper: `_404(msg)` raises `HTTPException(404)`
- No ORM — all SQL is raw strings in `api/database.py`

---

## Frontend conventions

- Pages: `ui/src/pages/` — one file per route
- API client: `ui/src/api/` — one file per resource (`campaigns.ts`, etc.)
- Auth: `useAuth()` from `ui/src/context/AuthContext.tsx`
- Router: `ui/src/router.tsx` — basename `/dashboard`
- Colours: Tailwind config at `ui/tailwind.config.js`
  - Brand teal: `text-brand`, `bg-brand`
  - Surfaces: `bg-surface`, `bg-surface-raised`, `bg-surface-card`
  - Text: `text-primary`, `text-secondary`, `text-muted`

Do NOT use `sky-*` or `blue-*` classes — these were replaced with `brand` tokens.

---

## Crew / agent conventions

- Crew factories: `crews/<crew_name>_crew.py`
- Agent modules: `crews/agents/<agent_name>_agent.py`
- Tool modules: `crews/tools/<tool_name>_tool.py`
- Registry: `crews/registry.py` — maps crew name strings to factory functions
- All crews return structured JSON; output files written to `projects/<slug>/outputs/`

PAM always uses `claude-opus-4-6` regardless of sensitive mode. Other agents use `LOCAL_LLM_MODEL` when sensitive mode is enabled (routes to `LLAMACPP_BASE_URL`).

---

## Key files

| File | Purpose |
|------|---------|
| `api/main.py` | App factory, router registration, lifespan |
| `api/config.py` | All settings (reads `.env`) |
| `api/database.py` | All DB helpers — read this first when adding data |
| `api/auth.py` | JWT + bcrypt — **bcrypt direct, no passlib** |
| `api/services/run_service.py` | Crew execution dispatch |
| `api/services/orchestration_service.py` | PAM two-phase orchestration |
| `api/services/campaign_service.py` | Interview campaigns + Resend email dispatch |
| `crews/pam_crew.py` | Project Automation Manager (top-level orchestrator) |
| `crews/registry.py` | Crew name → factory mapping |
| `ui/src/router.tsx` | All frontend routes |
| `ui/src/pages/Architecture.tsx` | Hidden `/architecture` reference page |
| `docker-compose.yml` | ChromaDB + n8n (credentials from `.env`) |
| `.env.example` | All environment variables documented |

---

## Sprint history summary

This project was built across 16 sprints (SP1–SP16). The memory index in `~/.claude/projects/.../memory/MEMORY.md` has one entry per completed sprint with branch name, test counts, and key changes.

The main branch is `master`. Feature branches follow `feature/sp<N><letter>-<short-description>`.

---

## Known issues / tech debt

- `python-pptx` must be installed inside the venv (not system pip on macOS with Homebrew Python 3.13 / PEP 668)
- Slack bot must be manually invited to the target channel (`/invite @FutureMomentum` in Slack) before `SlackNotifyTool` works
- `futuremomentum.ai` must be a verified sender domain in Resend before reminder emails deliver
- The Architecture page (`/architecture`) is not linked from the nav — navigate directly

---

## Environment variables

All env vars are documented in `.env.example`. Never commit `.env`. Key vars:

- `ADMIN_USERNAME` / `ADMIN_PASSWORD` — **required**, no defaults
- `JWT_SECRET` — generate with `openssl rand -hex 32`
- `N8N_BASIC_AUTH_USER` / `N8N_BASIC_AUTH_PASSWORD` — must match docker-compose.yml
- `PUBLIC_URL` — full public URL used in interview email links
