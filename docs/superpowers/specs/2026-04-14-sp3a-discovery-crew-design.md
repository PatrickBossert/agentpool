# SP3a: Discovery Crew Design

## Goal

Build the shared tool registry scaffold, PAM orchestrator, and Crew 1 (Discovery) — delivering a fully runnable end-to-end Discovery pipeline that maps a client's value chain, conducts stakeholder interviews, synthesises requirements, and identifies value levers.

## Scope

**In scope:**
- Shared tool registry with 6 tools (Crew 1 needs only)
- PAM (Programme Architecture Manager) — master orchestrator
- Crew 1 Discovery: Value Chain Mapper, Requirements Capture, Requirements Analyst, Value Lever Analyst
- HITL via SQLite + n8n/Slack (Option C)
- Integration tests using `claude-haiku-4-5-20251001`

**Deferred to SP3b+:**
- ExcelOutputTool, WordOutputTool, PowerPointOutputTool
- Crews 2–4 and their agents
- Sector knowledge base population

---

## Architecture

### Approach

`POST /projects/{slug}/run` fires `asyncio.create_task(run_discovery_crew(slug, run_id))` and returns `202 Accepted` immediately. The crew runs on the FastAPI event loop via CrewAI's `kickoff_async()`. Status updates are written to SQLite and streamed via the existing WebSocket. No new infrastructure required.

### Directory Structure

```
agents/
  tools/
    registry.py               # get_tools_for_agent(agent_name, slug) → [BaseTool, ...]
    document_ingestion.py
    chroma_query.py
    tavily_search.py
    sqlite_state.py
    human_input.py
    mermaid_render.py
  pam.py                      # PAM agent (claude-opus-4-6)
  discovery/
    value_chain_mapper.py
    requirements_capture.py
    requirements_analyst.py
    value_lever_analyst.py
  crews/
    discovery_crew.py         # assembles agents + tasks, returns Crew
api/
  services/
    run_service.py            # asyncio.create_task orchestration (new)
  routers/
    run.py                    # extend existing POST /projects/{slug}/run
tests/
  integration/
    conftest.py               # temp slug, temp DB, temp Chroma collection, haiku config
    test_tools.py             # one test per tool
    test_discovery_crew.py    # full crew run with haiku + auto-respond HITL
```

### Request Flow

1. `POST /projects/{slug}/run` `{"crew": "discovery"}`
2. `run_service.py` creates `crew_runs` record (status: `"running"`)
3. `asyncio.create_task(run_discovery_crew(slug, run_id))`
4. Returns `202 {"run_id": <id>}`
5. Crew runs: agents invoke tools, write outputs to `projects/{slug}/outputs/` and `agent_outputs` table, WS streams events
6. HITL pause: `HumanInputTool` inserts `human_reviews` record (decision: `"pending"`) → POSTs to n8n webhook → polls `asyncio.sleep(5)` → resumes when decision updated
7. Completion: `crew_runs` updated (status: `"completed"`, result_json populated)

---

## PAM (Programme Architecture Manager)

- **Model:** `claude-opus-4-6`
- **Role:** Receives project slug + crew name from the API. Loads project config from `config.yaml`. Instantiates and kicks off the appropriate crew via `crew.kickoff_async()`. Monitors progress and handles HITL escalation. Does no analytical work itself.
- **Tools:** `SQLiteStateTool`, `HumanInputTool`

---

## Crew 1: Discovery

### Agent Sequence (sequential)

| # | Agent | Model | Responsibility | Tools | Output |
|---|---|---|---|---|---|
| 1 | Value Chain Mapper | `claude-sonnet-4-6` | Maps client's value chain from uploaded docs + web search | DocumentIngestionTool, TavilySearchTool, ChromaQueryTool, MermaidRenderTool | `outputs/value_chain.md` (Mermaid) |
| 2 | Requirements Capture | `claude-sonnet-4-6` | Conducts structured multi-turn stakeholder interview using value chain as question frame | HumanInputTool (multi-turn), SQLiteStateTool | Interview transcript stored in SQLite |
| 3 | Requirements Analyst | `claude-sonnet-4-6` | Synthesises interview transcript + ingested docs into structured requirements | DocumentIngestionTool, ChromaQueryTool, SQLiteStateTool | `outputs/requirements.json` |
| 4 | Value Lever Analyst | `claude-sonnet-4-6` | Identifies value levers from value chain + requirements | ChromaQueryTool, TavilySearchTool, SQLiteStateTool | `outputs/value_levers.json` |

### LLM Routing

- Standard mode (`llm_mode: "standard"`): agents use `claude-sonnet-4-6` via LiteLLM proxy
- Sensitive mode (`llm_mode: "sensitive"`): agents use llama.cpp via LiteLLM proxy
- PAM always uses `claude-opus-4-6` direct (never sensitive)

### HITL Pause Points

- After Value Chain Mapper: single pause, human reviews diagram
- During Requirements Capture: multi-turn loop (question → wait → answer → next question), terminates when agent determines sufficient coverage or hits `max_turns` (default: 10, configurable per project via `config.yaml` key `requirements_capture_max_turns`)
- After Requirements Analyst: single pause, human reviews requirements register
- After Value Lever Analyst: single pause, human reviews value levers

If revision notes are provided at a single pause, PAM checks `human_reviews.notes` after the poll resolves. If non-empty, PAM re-dispatches the same CrewAI task with the notes appended to the task description as "Revision requested: {notes}". The agent produces a revised output, and `HumanInputTool` is called again for re-approval. Maximum 3 revision cycles per agent (hardcoded); after that PAM proceeds regardless.

---

## Tool Registry

### Pattern

```python
# agents/tools/registry.py
def get_tools_for_agent(agent_name: str, slug: str) -> list[BaseTool]:
    ...
```

Each tool takes `slug` in its constructor for per-project scoping (SQLite path, ChromaDB collection name).

### Tool Specifications

#### DocumentIngestionTool
- **Inputs:** `slug`, `filename` (optional — if omitted, ingests all files in `projects/{slug}/docs/`)
- **Does:** Reads files from `projects/{slug}/docs/`, chunks text, embeds via ChromaDB into collection `{slug}_docs`
- **Returns:** List of ingested document names

#### ChromaQueryTool
- **Inputs:** `slug`, `query: str`, `collection: Literal["project", "sector"]`, `top_k: int = 5`
- **Does:** Queries `{slug}_docs` (project) or `sector_{sector}` (sector knowledge base) in ChromaDB
- **Returns:** Top-k text chunks as a list of strings

#### TavilySearchTool
- **Inputs:** `query: str`, `max_results: int = 5`
- **Does:** Calls Tavily API (`TAVILY_API_KEY` from config)
- **Returns:** List of result snippets with titles and URLs

#### SQLiteStateTool
- **Inputs:** `slug`, `operation: Literal["read", "write"]`, `key: str`, `value: str | None`
- **Does:** Writes JSON blobs to `projects/{slug}/outputs/{key}.json` and registers the file in `agent_outputs` (output_type: `"state"`). Read operation reads the file directly. Used by agents to pass structured data to downstream agents.
- **Returns:** Stored JSON string (read) or file path (write)

#### HumanInputTool
- **Inputs:** `slug`, `run_id: int`, `prompt: str`, `mode: Literal["single", "multi_turn"]`, `test_auto_respond: str | None = None`
- **Does:**
  - Inserts `human_reviews` record (decision: `"pending"`, prompt stored in `prompt` column)
  - If `N8N_WEBHOOK_URL` set: POSTs `{review_id, prompt, project_slug, run_id}` to n8n
  - Polls `asyncio.sleep(5)` until `decision != "pending"`
  - In multi-turn mode: called in a loop; prior answers retrieved via `crew_run_id` + agent name
  - If `test_auto_respond` set: skips polling, returns canned string immediately
- **Returns:** Reviewer notes/answer string

#### MermaidRenderTool
- **Inputs:** `slug`, `mermaid_md: str`, `filename: str`
- **Does:** Renders Mermaid markdown to SVG, writes to `projects/{slug}/outputs/{filename}.svg`
- **Returns:** Absolute file path

---

## Schema Changes

The `human_reviews` table needs three changes: two new columns (`prompt`, `crew_run_id`) and `output_id` made nullable.

**New schema (used for all new project DBs via `init_db`):**
```sql
CREATE TABLE IF NOT EXISTS human_reviews (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    output_id    INTEGER REFERENCES agent_outputs(id),   -- nullable: not all pauses tie to an output
    crew_run_id  INTEGER REFERENCES crew_runs(id),       -- groups multi-turn interview turns
    reviewer     TEXT,
    decision     TEXT NOT NULL DEFAULT 'pending',
    prompt       TEXT,                                    -- question/instruction shown to human
    notes        TEXT,
    reviewed_at  DATETIME DEFAULT CURRENT_TIMESTAMP
);
```

**Migration for existing project DBs:** SQLite cannot alter column nullability directly. `get_connection()` runs a defensive migration on every open:
```sql
-- These are safe no-ops if columns already exist (caught via try/except)
ALTER TABLE human_reviews ADD COLUMN prompt TEXT;
ALTER TABLE human_reviews ADD COLUMN crew_run_id INTEGER REFERENCES crew_runs(id);
```
The `output_id NOT NULL` constraint on existing DBs is left as-is (no existing rows will conflict — no HITL runs have occurred yet). New rows inserted by SP3a will supply `output_id=NULL`, which SQLite allows even on a `NOT NULL` column only if no CHECK constraint enforces it at the row level. To be safe, the migration also recreates the table if `output_id` is detected as NOT NULL:
```python
# In get_connection(), after adding columns:
async def _migrate_human_reviews_nullable(conn):
    async with conn.execute("PRAGMA table_info(human_reviews)") as cur:
        cols = {row["name"]: row async for row in cur}
    if cols.get("output_id", {}).get("notnull"):
        await conn.executescript("""
            BEGIN;
            ALTER TABLE human_reviews RENAME TO human_reviews_old;
            CREATE TABLE human_reviews ( ... new schema ... );
            INSERT INTO human_reviews SELECT id, output_id, NULL, reviewer, decision, NULL, notes, reviewed_at FROM human_reviews_old;
            DROP TABLE human_reviews_old;
            COMMIT;
        """)
```

---

## n8n / Slack Integration

New config setting: `N8N_WEBHOOK_URL` (optional string, default `None`).

When set, `HumanInputTool` fires a POST to this URL with:
```json
{
  "review_id": 42,
  "prompt": "Please review the value chain diagram and approve or add revision notes.",
  "project_slug": "acme-corp",
  "run_id": 7,
  "review_url": "http://localhost:3000/projects/acme-corp/reviews"
}
```

n8n formats a Slack message and sends it to the configured channel. The user clicks the review URL, responds via `POST /projects/{slug}/review`, which updates `decision` and unblocks the polling loop.

If `N8N_WEBHOOK_URL` is not set, HITL still works — the user must check the React UI manually.

---

## ChromaDB Collections

- `{slug}_docs` — per-project ingested client documents (created on first ingest)
- `sector_{sector}` — shared sector knowledge base, pre-populated separately (read-only in SP3a)

ChromaDB connection: `CHROMA_HOST` / `CHROMA_PORT` from config (defaults: `localhost` / `8002`).

---

## Testing

### Strategy

Integration tests using `claude-haiku-4-5-20251001`. No LLM mocking — real model runs, real tool invocations, isolated infrastructure (temp project slug + temp SQLite DB + temp ChromaDB collection per test session).

Tests tagged `@pytest.mark.integration`, excluded from default `pytest` run. Run via:
```bash
pytest -m integration
```
Requires `ANTHROPIC_API_KEY` and a running ChromaDB instance.

### `conftest.py`

- Creates a temp slug (e.g., `test-sp3a-{uuid4()}`)
- Initialises per-project SQLite DB
- Creates `{slug}_docs` ChromaDB collection
- Seeds `projects/{slug}/docs/` with a fixture PDF
- Configures all agents to use `claude-haiku-4-5-20251001`
- Tears down temp slug, DB, and ChromaDB collection after session

### `test_tools.py`

One test per tool:
1. `DocumentIngestionTool` — ingests fixture PDF, verifies collection has documents
2. `ChromaQueryTool` — queries ingested collection, verifies non-empty results
3. `TavilySearchTool` — searches a known query, verifies result list non-empty
4. `SQLiteStateTool` — writes a value, reads it back, verifies round-trip
5. `HumanInputTool` — runs with `test_auto_respond="approved"`, verifies `human_reviews` record created with decision updated
6. `MermaidRenderTool` — renders a minimal diagram, verifies SVG file written to outputs dir

### `test_discovery_crew.py`

Full Discovery crew run assertions:
1. Crew completes without raising an exception
2. `crew_runs` record transitions `pending → running → completed`
3. `agent_outputs` records exist for all four agents (filter by `output_type != "state"` for primary outputs; at least one per agent)
4. `human_reviews` records created at expected HITL pause points (at minimum: 1 after Value Chain Mapper, N during Requirements Capture, 1 after Requirements Analyst, 1 after Value Lever Analyst)
5. `outputs/value_chain.md` exists and contains Mermaid syntax
6. `outputs/requirements.json` exists and is valid JSON
7. `outputs/value_levers.json` exists and is valid JSON

All HITL pauses use `test_auto_respond="approved"` to run end-to-end without manual intervention.

---

## Sub-Plan Boundaries

| Sub-plan | Scope |
|---|---|
| **SP3a (this spec)** | Tool registry (6 tools), PAM, Crew 1 Discovery (4 agents), HITL, integration tests |
| SP3b | Crew 2 Value Design (Value Proposition Generator, Portfolio Manager) + additional tools (ExcelOutputTool, WordOutputTool) |
| SP3c | Crew 3 Architecture (Enterprise Architect, Initiative Identifier) |
| SP3d | Crew 4 Delivery Planning (Roadmap Generator, Business Plan Generator) + PowerPointOutputTool |
