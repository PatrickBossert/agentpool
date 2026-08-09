# CLAUDE.md — AgentPool project context

This file is loaded automatically by Claude Code. It captures conventions, key files, and context so new sessions can resume without re-reading the codebase.

---

## Style guide

These rules apply to all content produced for this project — UI labels, copy, comments, agent backstories, error messages, and documentation.

| Rule | Detail |
|------|--------|
| **English** | British English (UK) spellings throughout |
| **-ise / -ize** | Always `-ise` — e.g. *organise*, *prioritise*, *humanise*, *recognise* |
| **-our / -or** | Always `-our` — e.g. *behaviour*, *colour*, *favour*, *labour* |
| **-re / -er** | Always `-re` — e.g. *centre*, *fibre*, *theatre* |
| **-ogue / -og** | Always `-ogue` — e.g. *catalogue*, *dialogue* |
| **Dashes** | Short (en) dash ` - ` with spaces, not em dash (`—`) in web content |
| **Icons** | Stylised SVG icons (Lucide React) in all UI — no emoji in rendered web content |
| **Punctuation** | Oxford comma in lists of three or more items |

---

## Tech stack

| Layer | Technology |
|-------|-----------|
| Runtime | **Python 3.13 required** — see below |
| Backend | FastAPI (async), aiosqlite, Pydantic v2, pydantic-settings |
| AI crews | CrewAI, Anthropic Claude Opus (PAM always; others configurable) |
| Vector store | ChromaDB — `CloudClient` when `CHROMA_API_KEY` is set, else `HttpClient` on :8002 |
| Auth | JWT (python-jose), bcrypt (direct — NOT passlib; see below) |
| Frontend | React 18, TypeScript, Vite, Tailwind CSS v3, React Router v6 |
| Email | Resend HTTP API (httpx — not SMTP) |
| Voice | ElevenLabs (TTS) + Web Speech API + Deepgram (STT) |
| Workflow | n8n (Docker, :5678) — triggers /orchestrate webhook |
| Infra | Docker Compose (ChromaDB + n8n), Caddy (prod), cloudflared (prod) |

---

## Critical: Python version

**Python 3.13 only. 3.14 will not install.** Both `crewai` and `litellm` declare `Requires-Python >=3.10,<3.14`, so pip on 3.14 silently falls back to ancient crewai versions and then fails with `No matching distribution found`.

Create the venv against a 3.13 interpreter explicitly:
```bash
uv python install 3.13                              # or: brew install python@3.13
$(uv python find 3.13) -m venv venv
./venv/bin/pip install -r requirements.txt
```

Never copy a `venv/` between machines — console-script shebangs hardcode absolute paths and break.

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

# Integration tests — opt-in, and they cost money
pytest -m integration
```

Tests use in-memory SQLite — no running services required.

`tests/integration` is deselected by `addopts` in `pytest.ini`. Those tests call the real
Anthropic API and expect ChromaDB on :8002, so a bare `pytest` used to spend credit on
infrastructure that is usually not running. Collecting them also **changed the result of
unit tests** — see the patch-target entry below — so the deselection is not only about cost.

**Run the backend suite twice before believing it is green.** `tests/conftest.py` points
`DATABASE_DIR` at a fixed `/tmp/agentpool_test` that persists between runs, so a test which writes
a hardcoded row id poisons its own database: it passes once and fails on every run afterwards. That
defect shipped through eight task reviews before a second run caught it. Tests that need isolation
must use `monkeypatch.setenv("DATABASE_DIR", str(tmp_path))` with `get_settings.cache_clear()` on
both sides; tests using the shared `client` fixture must scope every assertion to a row they
created rather than hardcoding an id or counting globally.

## Reviewing changes: the recurring failure mode

Five times on this project a test has verified a property **one layer away from where it holds**.
In every case the shipped code was correct and the test could not distinguish correct from
incorrect:

- `check_write` tested; the tool calling it not.
- `staleness` tested; the endpoint assembling it not.
- An approval guard tested for one of its two conditions.
- `_fetch_change_requests` tested; the injection using it not.
- A radio tested as *rendered*; not as *sent*.
- `check_write` refused an undeclared key; the test asserted `"test_state" in write_result`,
  and the *refusal message quotes the key it is refusing*. The write half of a round-trip
  test could not fail. Assert the success prefix, not a substring drawn from your own call.
- Four crew tests patched `agents.tools.registry.get_tools_for_agent` — where the function
  is **defined** — while the crew module binds its own reference via `from ... import`.
  Patch where the name is *looked up*. Worse, their `import` sat inside the `with patch(...)`
  block, so the first test imported the module under the mock and the module kept that dead
  MagicMock for the whole session: one test poisoning the module made the next three pass.
  Alone, 12 passed; behind anything that imports the crew module first, 4 failed — and the
  production bug they were hiding (`create_business_plan_crew` raises `ValueError: Unknown
  agent: visual_illustrator`) had been live on master the entire time.

When a test passes alone and fails in the suite, the isolated pass is the thing to distrust —
it is usually the one running under state no production caller ever has.

Pure functions and rendered state are cheap to assert, so they get asserted — and the assertion
lands beside the property rather than on it. When reviewing, ask: **"what calls this, and is
*that* tested?"** and **"would this test fail if the code were wrong?"** The second question is
different from "does this test pass", and far more productive here.

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

When adding a new `_migrate_*` function, bump `_SCHEMA_VERSION` in `api/database.py` in the
same change and add the new function to the migration block `get_connection` runs. Forgetting
fails unsafe, not loudly: `get_connection` only re-runs the migration block when
`PRAGMA user_version < _SCHEMA_VERSION`, so a new migration added without bumping the version
silently never runs on any database that has already been opened once at the current version -
no error, no warning, just rows that stay unmigrated forever on every existing deployment.

---

## API conventions

- Router files: `api/routers/<resource>.py`
- Service functions: `api/services/<feature>_service.py`
- Auth: JWT bearer token, `Depends(get_current_user)` on protected routes
- 404 helper: `_404(msg)` raises `HTTPException(404)`
- No ORM — all SQL is raw strings in `api/database.py`

**There are two review doors, and anything touching review feedback must serve both:**

| Door | Handler | Called from |
|------|---------|-------------|
| `POST /projects/{slug}/review` | `submit_review` | `RerunDialog.tsx` "Suggest a revision", `AgentStatusTab.tsx` inline "Revise" |
| `PATCH /projects/{slug}/reviews/{id}` | `resolve_hitl_review` | `ReviewDialog.tsx` |

Nothing in the code says why both exist. Wiring only one silently turns the other's flows into
no-ops — notes that save, display in the UI, and never reach the agent. `RerunDialog` also **fans
out**, posting one review per crew output, so anything assembling review feedback into a prompt
must deduplicate or it repeats the same instruction N times.

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

- Crew factories: `agents/crews/<crew_name>_crew.py`
- Agent modules: `agents/<domain>/<agent_name>.py` — grouped by domain, not suffixed. Domains are `discovery`, `value_design`, `architecture`, `delivery`, `business_plan`, `pam` (e.g. `agents/discovery/interview_coordinator.py`)
- Tool modules: `agents/tools/<tool_name>.py` — no `_tool` suffix (e.g. `agents/tools/chroma_query.py`)
- Tool registry: `agents/tools/registry.py` — `get_tools_for_agent(agent_name, slug, ...)` maps **agent** names to tool lists
- Crew dispatch: `api/services/run_service.py` — `build_and_run_crew()` imports each crew factory inline; `_CREW_AGENT_NAMES` maps crew names to their agent lists. There is no standalone crew registry module.
- All crews return structured JSON; output files written to `projects/<slug>/outputs/`

There is no top-level `crews/` directory — everything lives under `agents/`.

Each agent declares a capability tier in `agents/model_registry.py` - `fast` or `deep` - and the
project's `llm_mode` binds that tier to a model. Crew factories never choose a model; they call
`get_llm_for_agent(agent_name, slug)`, and a source guard fails if one names a model.

PAM has no exemption. It is `deep` and routes to the local model for a sensitive project like
every other agent, because it holds `SQLiteStateTool` and can read project outputs - an
always-hosted orchestrator was a hole in the secure-mode guarantee rather than a quality choice.

A sensitive project with no local model configured for a tier raises `LocalModelUnavailable`
rather than falling back. There is no hosted fallback and no borrowing of the other tier.

---

## Anchoring: themes and requirements sit where the insight lives

Themes and requirements must anchor at the level where the insight lives - L0 for
governance, assurance and vertical themes; L1 for functional; L2 for decision and
effectiveness; L3 for tactical and efficiency. Anchoring everything at `n.n.n` loses
resolution and systematically skews value proposition generation toward L3 efficiency.

This is a pipeline-shaping property, not a formatting preference. If nothing else exists to
anchor to, L3 becomes the only altitude the evidence is ever expressed at, and every
proposition built downstream inherits the bias.

The tree is the canonical spine. `0` is the organisation; `0.A` and `0.S` are its
organisation-level role nodes (audit, corporate services frontline); each L1 entity carries
the `<L1>.C` and `<L1>.F` role nodes it warrants. L2 and L3 belong to exactly one L1 -
nothing is shared or duplicated. Role nuance never lives on the node; it lives on the
stakeholder, which is what lets one `F` programme serve both `1.F` and `2.F` while the
answers still differ.

**IDs are a permanent contract.** The ledger may grow and may retire, but may never
redefine or forget. Two things enforce that, and neither is a refusal: `DeriveRegistryTool`
keeps the label an id already carries, so a regenerated tree cannot rewrite the ledger; and
`tree_validation` raises `id_redefined` when a label changes in a way that is not merely
typographic. Alex rebuilds the whole chain on every run and re-emits every label, so
punctuation drift is routine - one run produced 59 label changes and not one was a
redefinition.

Fuller account: `docs/superpowers/specs/2026-08-06-l0-anchor-and-level-anchored-synthesis-design.md`.

---

## Resolving an output: ask the ledger, never the disk

`agent_outputs.is_current` + `file_path` is the authority on which version of an output is
current. `insert_agent_output_sync` maintains it on every write and `revert_to_version`
repoints it on every revert - which is the case a filename-ordering scheme cannot express,
since the newer files stay on disk.

**Use `current_output_path(slug, output_type)`, not `latest_output_path`.** The latter
globs `stem_v*` and returns the highest number, which caused four separate incidents: the
clean-baseline demotion, the `value_chain_tree_v13` shadow, a version-counter reset, and
Maya reading a 15 July summary on every run for three weeks - naming a party a human had
corrected out on 4 August. `latest_output_path` survives only as the fallback for a first
write and for hand-written files.

Two invariants this depends on, both asserted in `tests/test_output_type_families.py`: one
filename family answers to exactly one output type, and one output type has exactly one
`is_current` row.

Fuller account: `docs/superpowers/specs/2026-08-06-output-resolution-by-ledger-design.md`.

---

## Running the API while agents are running

Start the server **without `--reload`**. Editing any watched `.py` file restarts the worker
and kills every in-flight crew run - the error surfaces as
`{"error": "Server restart interrupted run"}`, which is what killed runs 21 and 27. The
cost is that the server no longer picks up code changes: restart it after backend edits,
and never while a run is in flight.

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
| `agents/crews/pam_crew.py` | Project Automation Manager (top-level orchestrator) |
| `agents/tools/registry.py` | Agent name → tool list mapping |
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
- Slack bot must be manually invited to the target channel (`/invite @TaskReimagination` in Slack) before `SlackNotifyTool` works
- `taskreimagination.ai` must be a verified sender domain in Resend before reminder emails deliver
- The Architecture page (`/architecture`) is not linked from the nav — navigate directly
- The `business_plan` crew has never completed a real run. It only became buildable when
  `visual_illustrator` was registered; before that `create_business_plan_crew` raised
  before its first task. Treat its first run as an experiment.
- Deepgram (STT) and ElevenLabs (TTS) are used in secure mode by decision, both being
  streamed with no content retention. Local speech services are future work, not a
  current requirement.
- Avery still blocks on `HumanInputTool` for up to 24 hours during an interview programme,
  and nothing notifies the crew when a session completes. It does not affect interviewee
  experience, which is why sub-project B left it alone.
- `complete_session` and `_find_session_db` in `api/services/interview_service.py` open
  their connections with a bare `aiosqlite.connect(db_path)`, not
  `api.database.get_connection(slug)`. WAL survives that, because it is a persistent
  property of the database file once any code path sets it; `busy_timeout` does not, since
  it is per-connection and nothing sets it on this path. Found while proving twenty
  concurrent interview completions in `tests/test_interview_concurrency.py` - it did not
  fail the test on this workload, but the `get_connection` guarantee does not actually
  reach the `/complete` endpoint's writes. Worth a follow-up task.

---

## Environment variables

All env vars are documented in `.env.example`. Never commit `.env`. Key vars:

- `ADMIN_USERNAME` / `ADMIN_PASSWORD` — **required**, no defaults
- `JWT_SECRET` — generate with `openssl rand -hex 32`
- `N8N_BASIC_AUTH_USER` / `N8N_BASIC_AUTH_PASSWORD` — must match docker-compose.yml
- `PUBLIC_URL` — full public URL used in interview email links
