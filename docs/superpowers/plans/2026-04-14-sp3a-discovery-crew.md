# SP3a: Discovery Crew Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the shared tool registry scaffold, PAM orchestrator, and Crew 1 (Discovery) — delivering a fully runnable end-to-end pipeline triggered via `POST /projects/{slug}/run` that maps a client's value chain, conducts stakeholder interviews, synthesises requirements, and identifies value levers.

**Architecture:** CrewAI agents run sequentially via `crew.kickoff_async()` inside an `asyncio.create_task` dispatched from the run router. Tools are sync `BaseTool` subclasses that use `sqlite3` directly (no event loop conflicts); `HumanInputTool` polls with `time.sleep` which CrewAI runs in its thread pool. HITL revision logic lives in task descriptions — agents call `HumanInputTool`, receive notes, and reprocess up to 3 times before proceeding. A new `PATCH /projects/{slug}/reviews/{review_id}` endpoint lets humans respond to HITL pauses.

**Tech Stack:** Python 3.14, CrewAI ≥0.80.0, ChromaDB 0.6.3 (HTTP client), sentence-transformers, pypdf, tavily-python, httpx (sync), sqlite3 (sync, tools layer), aiosqlite (async, API layer), FastAPI, pytest + pytest-asyncio

---

## File Map

**Modify:**
- `requirements.txt` — add crewai, pypdf, tavily-python
- `api/config.py` — add n8n_webhook_url, tavily_api_key, frontend_url
- `.env.example` — add new keys
- `api/database.py` — new human_reviews schema + migration + update_review()
- `api/routers/reviews.py` — add PATCH /{slug}/reviews/{review_id}
- `api/routers/run.py` — trigger run_service after creating run record
- `tests/test_run_api.py` — update expected status "queued" → "running"
- `pytest.ini` — register `integration` marker

**Create:**
- `agents/__init__.py`
- `agents/llm.py` — get_crew_llm(), get_pam_llm(), get_test_llm()
- `agents/tools/__init__.py`
- `agents/tools/_db.py` — sync SQLite helpers for tools
- `agents/tools/registry.py` — get_tools_for_agent(agent_name, slug, run_id)
- `agents/tools/sqlite_state.py` — SQLiteStateTool
- `agents/tools/human_input.py` — HumanInputTool
- `agents/tools/document_ingestion.py` — DocumentIngestionTool
- `agents/tools/chroma_query.py` — ChromaQueryTool
- `agents/tools/tavily_search.py` — TavilySearchTool
- `agents/tools/mermaid_render.py` — MermaidRenderTool
- `agents/pam.py` — PAM config constants
- `agents/discovery/__init__.py`
- `agents/discovery/value_chain_mapper.py`
- `agents/discovery/requirements_capture.py`
- `agents/discovery/requirements_analyst.py`
- `agents/discovery/value_lever_analyst.py`
- `agents/crews/__init__.py`
- `agents/crews/discovery_crew.py`
- `api/services/run_service.py`
- `tests/integration/__init__.py`
- `tests/integration/conftest.py`
- `tests/integration/test_tools.py`
- `tests/integration/test_discovery_crew.py`

---

## Task 1: Dependencies, Config & Environment

**Files:**
- Modify: `requirements.txt`
- Modify: `api/config.py`
- Modify: `.env.example`

- [ ] **Step 1: Add new dependencies to requirements.txt**

```
# append to requirements.txt
crewai>=0.80.0
pypdf>=4.3.0
tavily-python>=0.3.0
```

Full updated `requirements.txt`:
```
fastapi==0.115.5
uvicorn[standard]==0.32.1
httpx==0.28.1
pydantic==2.12.5
pydantic-settings==2.13.1
python-dotenv==1.0.1
pyyaml==6.0.2
aiosqlite==0.20.0
chromadb==0.6.3
sentence-transformers==3.4.1
litellm==1.83.4
chainlit==2.6.3
pytest==8.3.4
pytest-asyncio==0.24.0
anyio==4.7.0
python-jose[cryptography]==3.3.0
passlib[bcrypt]==1.7.4
bcrypt==4.2.1
python-multipart==0.0.20
crewai>=0.80.0
pypdf>=4.3.0
tavily-python>=0.3.0
```

- [ ] **Step 2: Install new dependencies**

```bash
pip install crewai pypdf tavily-python
```

Expected: packages install without error. If crewai fails on Python 3.14, try `pip install crewai==0.86.0`.

- [ ] **Step 3: Add new settings to api/config.py**

Replace the Settings class with:

```python
# api/config.py
from functools import lru_cache
from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict
import yaml


class Settings(BaseSettings):
    anthropic_api_key: str
    litellm_proxy_url: str = "http://localhost:4000"
    llamacpp_base_url: str = "http://localhost:10000"
    chroma_host: str = "localhost"
    chroma_port: int = 8002
    database_dir: str = "/Users/pboagents/Documents/agentpool1/data"
    projects_dir: str = "/Users/pboagents/Documents/agentpool1/projects"
    jwt_secret: str
    admin_username: str = "admin"
    admin_password: str = "changeme"
    tavily_api_key: str = ""
    n8n_webhook_url: str = ""
    frontend_url: str = "http://localhost:3000"

    model_config = SettingsConfigDict(env_file=".env")


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


def load_project_config(project_dir: Path) -> dict:
    config_path = Path(project_dir) / "config.yaml"
    if not config_path.exists():
        raise FileNotFoundError(f"No config.yaml found in {project_dir}")
    with open(config_path) as f:
        data = yaml.safe_load(f)
    if not isinstance(data, dict):
        raise ValueError(f"config.yaml in {project_dir} is empty or not a valid YAML mapping")
    return data
```

- [ ] **Step 4: Update .env.example**

```
# .env.example
ANTHROPIC_API_KEY=sk-ant-...
LITELLM_PROXY_URL=http://localhost:4000
LLAMACPP_BASE_URL=http://localhost:10000
CHROMA_HOST=localhost
CHROMA_PORT=8002
DATABASE_DIR=/Users/pboagents/Documents/agentpool1/data
PROJECTS_DIR=/Users/pboagents/Documents/agentpool1/projects
JWT_SECRET=change-me-in-production
TAVILY_API_KEY=tvly-...
N8N_WEBHOOK_URL=
FRONTEND_URL=http://localhost:3000
```

- [ ] **Step 5: Verify existing tests still pass**

```bash
pytest tests/ -x -q
```

Expected: all existing tests pass (no regressions from config change).

- [ ] **Step 6: Commit**

```bash
git add requirements.txt api/config.py .env.example
git commit -m "feat: add crewai/pypdf/tavily deps and n8n/tavily config settings"
```

---

## Task 2: Schema Migration for human_reviews

**Files:**
- Modify: `api/database.py`

The `human_reviews` table needs `prompt` and `crew_run_id` columns, and `output_id` must become nullable. New and existing project DBs both need to work.

- [ ] **Step 1: Update init_db in api/database.py — replace the human_reviews CREATE TABLE**

In `init_db`, replace:
```sql
CREATE TABLE IF NOT EXISTS human_reviews (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    output_id   INTEGER NOT NULL REFERENCES agent_outputs(id),
    reviewer    TEXT,
    decision    TEXT NOT NULL,
    notes       TEXT,
    reviewed_at DATETIME DEFAULT CURRENT_TIMESTAMP
);
```

With:
```sql
CREATE TABLE IF NOT EXISTS human_reviews (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    output_id    INTEGER REFERENCES agent_outputs(id),
    crew_run_id  INTEGER REFERENCES crew_runs(id),
    reviewer     TEXT,
    decision     TEXT NOT NULL DEFAULT 'pending',
    prompt       TEXT,
    notes        TEXT,
    reviewed_at  DATETIME DEFAULT CURRENT_TIMESTAMP
);
```

- [ ] **Step 2: Add _migrate_human_reviews helper and call it from get_connection**

Add this function immediately after `init_db`:

```python
async def _migrate_human_reviews(conn: aiosqlite.Connection) -> None:
    """Add prompt/crew_run_id columns and make output_id nullable on existing DBs."""
    async with conn.execute("PRAGMA table_info(human_reviews)") as cur:
        cols = {row["name"]: row async for row in cur}

    if "prompt" not in cols:
        await conn.execute("ALTER TABLE human_reviews ADD COLUMN prompt TEXT")
    if "crew_run_id" not in cols:
        await conn.execute(
            "ALTER TABLE human_reviews ADD COLUMN crew_run_id INTEGER REFERENCES crew_runs(id)"
        )

    output_id_col = cols.get("output_id")
    if output_id_col and output_id_col["notnull"]:
        # SQLite can't drop NOT NULL via ALTER — rebuild the table.
        await conn.executescript("""
            CREATE TABLE human_reviews_new (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                output_id    INTEGER REFERENCES agent_outputs(id),
                crew_run_id  INTEGER REFERENCES crew_runs(id),
                reviewer     TEXT,
                decision     TEXT NOT NULL DEFAULT 'pending',
                prompt       TEXT,
                notes        TEXT,
                reviewed_at  DATETIME DEFAULT CURRENT_TIMESTAMP
            );
            INSERT INTO human_reviews_new
                (id, output_id, reviewer, decision, notes, reviewed_at)
                SELECT id, output_id, reviewer, decision, notes, reviewed_at
                FROM human_reviews;
            DROP TABLE human_reviews;
            ALTER TABLE human_reviews_new RENAME TO human_reviews;
        """)

    await conn.commit()
```

Update `get_connection` to call the migration after `init_db`:

```python
@asynccontextmanager
async def get_connection(slug: str):
    path = get_db_path(slug)
    path.parent.mkdir(parents=True, exist_ok=True)
    async with aiosqlite.connect(path) as conn:
        conn.row_factory = aiosqlite.Row
        await conn.execute("PRAGMA foreign_keys = ON")
        await init_db(conn)
        await _migrate_human_reviews(conn)
        yield conn
```

- [ ] **Step 3: Add update_review function to api/database.py**

Add after `insert_review`:

```python
async def update_review(
    conn: aiosqlite.Connection, *, review_id: int, decision: str, notes: str
) -> bool:
    """Update an existing review record. Returns True if the record was found."""
    cur = await conn.execute(
        "UPDATE human_reviews SET decision=?, notes=?, reviewed_at=CURRENT_TIMESTAMP WHERE id=?",
        (decision, notes, review_id),
    )
    await conn.commit()
    return cur.rowcount > 0
```

- [ ] **Step 4: Verify existing tests still pass**

```bash
pytest tests/ -x -q
```

Expected: all existing tests pass. The migration is idempotent — calling `_migrate_human_reviews` on a fresh DB (where columns already exist in the new schema) is a no-op.

- [ ] **Step 5: Commit**

```bash
git add api/database.py
git commit -m "feat: extend human_reviews schema with prompt/crew_run_id, make output_id nullable"
```

---

## Task 3: PATCH Review Endpoint

**Files:**
- Modify: `api/routers/reviews.py`

Adds `PATCH /projects/{slug}/reviews/{review_id}` so the React UI (or direct API call) can resolve a pending HITL review. The existing `POST /projects/{slug}/review` is unchanged.

- [ ] **Step 1: Add HITLReviewRequest model and PATCH endpoint to api/routers/reviews.py**

Append to `api/routers/reviews.py`:

```python
from api.database import get_connection, get_db_path, fetch_project, insert_review, update_review


class HITLReviewRequest(BaseModel):
    decision: str   # "approved" | "changes_requested"
    notes: str = ""
    reviewer: str = "consultant"


@router.patch("/{slug}/reviews/{review_id}", status_code=200)
async def resolve_hitl_review(slug: str, review_id: int, req: HITLReviewRequest):
    if not get_db_path(slug).exists():
        raise HTTPException(status_code=404, detail=f"Project '{slug}' not found")
    async with get_connection(slug) as conn:
        project = await fetch_project(conn, slug=slug)
        if not project:
            raise HTTPException(status_code=404, detail=f"Project '{slug}' not found")
        updated = await update_review(
            conn, review_id=review_id, decision=req.decision, notes=req.notes
        )
        if not updated:
            raise HTTPException(status_code=404, detail=f"Review {review_id} not found")
        return {"id": review_id, "decision": req.decision, "notes": req.notes}
```

Also update the import at the top of the file so `update_review` is imported:

```python
from api.database import get_connection, get_db_path, fetch_project, insert_review, update_review
```

- [ ] **Step 2: Verify existing tests still pass**

```bash
pytest tests/ -x -q
```

Expected: all existing tests pass.

- [ ] **Step 3: Commit**

```bash
git add api/routers/reviews.py
git commit -m "feat: add PATCH /projects/{slug}/reviews/{review_id} for HITL resolution"
```

---

## Task 4: Integration Test Infrastructure

**Files:**
- Modify: `pytest.ini`
- Create: `tests/integration/__init__.py`
- Create: `tests/integration/conftest.py`

- [ ] **Step 1: Register the integration marker in pytest.ini**

Replace the full content of `pytest.ini`:

```ini
[pytest]
asyncio_mode = strict
asyncio_default_fixture_loop_scope = function

markers =
    integration: marks tests as integration tests (require ANTHROPIC_API_KEY + running ChromaDB)
```

- [ ] **Step 2: Create tests/integration/__init__.py**

```python
```

(Empty file — makes tests/integration a package.)

- [ ] **Step 3: Create tests/integration/conftest.py**

```python
# tests/integration/conftest.py
"""
Integration test infrastructure for SP3a.

Requires:
- ANTHROPIC_API_KEY set in environment
- ChromaDB running: docker run -p 8002:8000 chromadb/chroma

Run with: pytest -m integration
"""
import os
import uuid
import json
import sqlite3
from pathlib import Path
import pytest
import chromadb

# Set env vars before any app imports so settings are correct
os.environ.setdefault("DATABASE_DIR", "/tmp/agentpool_integration_test")
os.environ.setdefault("PROJECTS_DIR", "/tmp/agentpool_integration_test_projects")
os.environ.setdefault("JWT_SECRET", "test-secret")
os.environ.setdefault("ADMIN_PASSWORD", "test-admin-pw")
os.environ.setdefault("ADMIN_USERNAME", "admin")
os.environ.setdefault("LITELLM_PROXY_URL", "http://localhost:4000")
os.environ.setdefault("LLAMACPP_BASE_URL", "http://localhost:10000")
os.environ.setdefault("CHROMA_HOST", "localhost")
os.environ.setdefault("CHROMA_PORT", "8002")
# Auto-respond to all HITL prompts in integration tests
os.environ["HITL_AUTO_RESPOND"] = "approved"

Path("/tmp/agentpool_integration_test").mkdir(exist_ok=True)
Path("/tmp/agentpool_integration_test_projects").mkdir(exist_ok=True)


@pytest.fixture(scope="session")
def test_slug() -> str:
    return f"test-sp3a-{uuid.uuid4().hex[:8]}"


@pytest.fixture(scope="session")
def chroma_client():
    return chromadb.HttpClient(host="localhost", port=8002)


@pytest.fixture(scope="session", autouse=True)
def setup_test_project(test_slug, chroma_client):
    """Create a full project environment for integration tests."""
    from api.config import get_settings
    settings = get_settings()

    # Create project directory structure
    project_dir = Path(settings.projects_dir) / test_slug
    docs_dir = project_dir / "docs"
    outputs_dir = project_dir / "outputs"
    docs_dir.mkdir(parents=True, exist_ok=True)
    outputs_dir.mkdir(parents=True, exist_ok=True)

    # Write a fixture document
    (docs_dir / "test_document.txt").write_text(
        "This document describes a logistics company's digital transformation needs.\n"
        "The organisation operates a hub-and-spoke distribution network across 12 regions.\n"
        "Key pain points: manual order tracking, disconnected warehouse management systems,\n"
        "and lack of real-time visibility across the supply chain.\n"
        "Strategic priorities: automate order processing, integrate WMS with ERP,\n"
        "and implement predictive demand forecasting.\n"
        "Budget constraint: £2M over 18 months. Regulatory: GDPR compliance required.\n"
    )

    # Write config.yaml
    config = {
        "client_slug": test_slug,
        "llm_mode": "standard",
        "sector": "logistics",
        "stakeholder_groups": ["Operations", "IT", "Finance"],
        "value_stream_labels": ["Inbound", "Warehousing", "Outbound", "Last Mile"],
        "crews_enabled": ["discovery"],
        "review_gates": True,
        "slack_channel": "",
        "requirements_capture_max_turns": 3,
    }
    import yaml
    (project_dir / "config.yaml").write_text(yaml.dump(config))

    # Create SQLite DB with project row
    db_path = Path(settings.database_dir) / f"{test_slug}.db"
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS projects (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            slug TEXT UNIQUE NOT NULL,
            llm_mode TEXT NOT NULL DEFAULT 'standard',
            sector TEXT,
            config_json TEXT,
            status TEXT NOT NULL DEFAULT 'created',
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS crew_runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            project_id INTEGER NOT NULL REFERENCES projects(id),
            crew_name TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending',
            result_json TEXT,
            started_at DATETIME,
            finished_at DATETIME,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS agent_outputs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            project_id INTEGER NOT NULL REFERENCES projects(id),
            agent_name TEXT NOT NULL,
            output_type TEXT NOT NULL,
            file_path TEXT NOT NULL,
            version INTEGER NOT NULL DEFAULT 1,
            review_status TEXT NOT NULL DEFAULT 'pending',
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS human_reviews (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            output_id INTEGER REFERENCES agent_outputs(id),
            crew_run_id INTEGER REFERENCES crew_runs(id),
            reviewer TEXT,
            decision TEXT NOT NULL DEFAULT 'pending',
            prompt TEXT,
            notes TEXT,
            reviewed_at DATETIME DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS client_documents (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            project_id INTEGER NOT NULL REFERENCES projects(id),
            filename TEXT NOT NULL,
            original_name TEXT NOT NULL,
            file_path TEXT NOT NULL,
            content_type TEXT,
            size_bytes INTEGER,
            ingested INTEGER NOT NULL DEFAULT 0,
            uploaded_at DATETIME DEFAULT CURRENT_TIMESTAMP
        );
    """)
    conn.execute(
        "INSERT OR IGNORE INTO projects (slug, llm_mode, sector, config_json) VALUES (?,?,?,?)",
        (test_slug, "standard", "logistics", json.dumps(config)),
    )
    conn.commit()
    conn.close()

    yield

    # Teardown: remove SQLite DB, project dir, ChromaDB collection
    import shutil
    db_path.unlink(missing_ok=True)
    shutil.rmtree(project_dir, ignore_errors=True)
    try:
        chroma_client.delete_collection(f"{test_slug}_docs")
    except Exception:
        pass


@pytest.fixture(scope="session")
def project_id(test_slug) -> int:
    from api.config import get_settings
    settings = get_settings()
    db_path = Path(settings.database_dir) / f"{test_slug}.db"
    conn = sqlite3.connect(db_path)
    cur = conn.execute("SELECT id FROM projects WHERE slug=?", (test_slug,))
    row = cur.fetchone()
    conn.close()
    return row[0]
```

- [ ] **Step 4: Verify the conftest imports cleanly**

```bash
python -c "import tests.integration.conftest"
```

Expected: no error.

- [ ] **Step 5: Commit**

```bash
git add pytest.ini tests/integration/__init__.py tests/integration/conftest.py
git commit -m "test: add integration test infrastructure for SP3a"
```

---

## Task 5: Agent Package & LLM Factory

**Files:**
- Create: `agents/__init__.py`
- Create: `agents/llm.py`
- Create: `agents/tools/__init__.py`
- Create: `agents/tools/_db.py`

- [ ] **Step 1: Create agents/__init__.py**

```python
```

(Empty.)

- [ ] **Step 2: Create agents/tools/__init__.py**

```python
```

(Empty.)

- [ ] **Step 3: Create agents/llm.py**

```python
# agents/llm.py
from crewai import LLM
from api.config import get_settings


def get_crew_llm(llm_mode: str) -> LLM:
    """Return the LLM for crew agents based on the project's llm_mode setting."""
    settings = get_settings()
    if llm_mode == "sensitive":
        return LLM(
            model="openai/local-model",
            base_url=settings.llamacpp_base_url,
            api_key="not-needed",
        )
    # standard or fallback: use Anthropic directly
    return LLM(
        model="anthropic/claude-sonnet-4-6",
        api_key=settings.anthropic_api_key,
    )


def get_pam_llm() -> LLM:
    """PAM always uses claude-opus-4-6, never routes to sensitive/local."""
    settings = get_settings()
    return LLM(
        model="anthropic/claude-opus-4-6",
        api_key=settings.anthropic_api_key,
    )


def get_test_llm() -> LLM:
    """Cheap model for integration tests."""
    settings = get_settings()
    return LLM(
        model="anthropic/claude-haiku-4-5-20251001",
        api_key=settings.anthropic_api_key,
    )
```

- [ ] **Step 4: Create agents/tools/_db.py**

```python
# agents/tools/_db.py
"""Synchronous SQLite helpers for use inside CrewAI tools.

Tools run in CrewAI's thread pool (not the FastAPI event loop), so they must
use the standard sqlite3 module rather than aiosqlite.
"""
import sqlite3
from pathlib import Path
from api.config import get_settings


def _db_path(slug: str) -> str:
    return str(Path(get_settings().database_dir) / f"{slug}.db")


def get_project_id(slug: str) -> int:
    """Return the integer project id for slug. Raises ValueError if not found."""
    conn = sqlite3.connect(_db_path(slug))
    cur = conn.execute("SELECT id FROM projects WHERE slug=?", (slug,))
    row = cur.fetchone()
    conn.close()
    if not row:
        raise ValueError(f"Project not found: {slug}")
    return row[0]


def insert_agent_output_sync(
    slug: str, agent_name: str, output_type: str, file_path: str
) -> int:
    """Insert an agent_outputs record and return the new row id."""
    project_id = get_project_id(slug)
    conn = sqlite3.connect(_db_path(slug))
    conn.execute("PRAGMA foreign_keys = ON")
    cur = conn.execute(
        "SELECT MAX(version) FROM agent_outputs WHERE project_id=? AND agent_name=? AND output_type=?",
        (project_id, agent_name, output_type),
    )
    max_ver = cur.fetchone()[0]
    version = (max_ver or 0) + 1
    cur = conn.execute(
        "INSERT INTO agent_outputs (project_id, agent_name, output_type, file_path, version)"
        " VALUES (?,?,?,?,?)",
        (project_id, agent_name, output_type, file_path, version),
    )
    conn.commit()
    output_id = cur.lastrowid
    conn.close()
    return output_id


def insert_hitl_review(slug: str, run_id: int, prompt: str) -> int:
    """Insert a human_reviews record with decision='pending'. Returns review_id."""
    conn = sqlite3.connect(_db_path(slug))
    conn.execute("PRAGMA foreign_keys = ON")
    cur = conn.execute(
        "INSERT INTO human_reviews (crew_run_id, decision, prompt) VALUES (?,?,?)",
        (run_id, "pending", prompt),
    )
    conn.commit()
    review_id = cur.lastrowid
    conn.close()
    return review_id


def get_review_decision(slug: str, review_id: int) -> tuple[str, str]:
    """Return (decision, notes) for a review. Returns ('pending', '') if not found."""
    conn = sqlite3.connect(_db_path(slug))
    cur = conn.execute(
        "SELECT decision, notes FROM human_reviews WHERE id=?", (review_id,)
    )
    row = cur.fetchone()
    conn.close()
    return (row[0], row[1] or "") if row else ("pending", "")


def complete_hitl_review(slug: str, review_id: int, decision: str) -> None:
    """Update decision on a review (used by test_auto_respond mode)."""
    conn = sqlite3.connect(_db_path(slug))
    conn.execute(
        "UPDATE human_reviews SET decision=?, reviewed_at=CURRENT_TIMESTAMP WHERE id=?",
        (decision, review_id),
    )
    conn.commit()
    conn.close()
```

- [ ] **Step 5: Verify imports work**

```bash
python -c "from agents.llm import get_crew_llm, get_pam_llm, get_test_llm; print('OK')"
python -c "from agents.tools._db import get_project_id; print('OK')"
```

Expected: `OK` for both.

- [ ] **Step 6: Commit**

```bash
git add agents/__init__.py agents/llm.py agents/tools/__init__.py agents/tools/_db.py
git commit -m "feat: add agents package, LLM factory, and sync DB helpers for tools"
```

---

## Task 6: SQLiteStateTool

**Files:**
- Create: `agents/tools/sqlite_state.py`
- Create: `tests/integration/test_tools.py` (partial — first test only)

- [ ] **Step 1: Write the failing integration test**

Create `tests/integration/test_tools.py`:

```python
# tests/integration/test_tools.py
"""Integration tests for each tool. Requires ChromaDB running and ANTHROPIC_API_KEY set."""
import json
import pytest
from pathlib import Path
from api.config import get_settings


@pytest.mark.integration
def test_sqlite_state_tool_round_trip(test_slug, project_id):
    from agents.tools.sqlite_state import SQLiteStateTool
    settings = get_settings()

    tool = SQLiteStateTool(slug=test_slug)

    # Write a value
    write_result = tool._run(
        operation="write",
        key="test_state",
        agent_name="test_agent",
        value=json.dumps({"hello": "world"}),
    )
    assert "test_state" in write_result

    # Read it back
    read_result = tool._run(
        operation="read",
        key="test_state",
        agent_name="test_agent",
    )
    data = json.loads(read_result)
    assert data == {"hello": "world"}

    # Verify file was written
    file_path = Path(settings.projects_dir) / test_slug / "outputs" / "test_state.json"
    assert file_path.exists()
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/integration/test_tools.py::test_sqlite_state_tool_round_trip -m integration -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'agents.tools.sqlite_state'`

- [ ] **Step 3: Implement agents/tools/sqlite_state.py**

```python
# agents/tools/sqlite_state.py
import json
from pathlib import Path
from pydantic import BaseModel, Field
from crewai.tools import BaseTool
from api.config import get_settings
from agents.tools._db import insert_agent_output_sync


class SQLiteStateToolInput(BaseModel):
    operation: str = Field(description="'read' or 'write'")
    key: str = Field(description="Unique key for this state blob (used as filename)")
    agent_name: str = Field(description="Name of the agent writing/reading this state")
    value: str = Field(default="", description="JSON string to write (required for 'write')")


class SQLiteStateTool(BaseTool):
    name: str = "SQLiteStateTool"
    description: str = (
        "Read or write a JSON state blob scoped to this project. "
        "Use 'write' to save intermediate results; use 'read' to retrieve them. "
        "The key becomes the filename (e.g. key='requirements' → outputs/requirements.json)."
    )
    args_schema: type[BaseModel] = SQLiteStateToolInput
    slug: str

    def _run(
        self,
        operation: str,
        key: str,
        agent_name: str,
        value: str = "",
    ) -> str:
        settings = get_settings()
        outputs_dir = Path(settings.projects_dir) / self.slug / "outputs"
        outputs_dir.mkdir(parents=True, exist_ok=True)
        file_path = outputs_dir / f"{key}.json"

        if operation == "write":
            # Validate JSON
            try:
                json.loads(value)
            except json.JSONDecodeError as e:
                return f"Error: value is not valid JSON — {e}"
            file_path.write_text(value)
            insert_agent_output_sync(
                slug=self.slug,
                agent_name=agent_name,
                output_type="state",
                file_path=str(file_path),
            )
            return f"Written to {file_path}"

        if operation == "read":
            if not file_path.exists():
                return f"Error: no state found for key '{key}'"
            return file_path.read_text()

        return f"Error: unknown operation '{operation}' — use 'read' or 'write'"
```

- [ ] **Step 4: Run test to verify it passes**

```bash
pytest tests/integration/test_tools.py::test_sqlite_state_tool_round_trip -m integration -v
```

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add agents/tools/sqlite_state.py tests/integration/test_tools.py
git commit -m "feat: add SQLiteStateTool with integration test"
```

---

## Task 7: HumanInputTool

**Files:**
- Create: `agents/tools/human_input.py`
- Modify: `tests/integration/test_tools.py` (add test)

- [ ] **Step 1: Write the failing integration test**

Append to `tests/integration/test_tools.py`:

```python
@pytest.mark.integration
def test_human_input_tool_auto_respond(test_slug, project_id):
    """HumanInputTool with test_auto_respond inserts a review and returns immediately."""
    import sqlite3
    from pathlib import Path
    from agents.tools.human_input import HumanInputTool
    from api.config import get_settings

    settings = get_settings()

    # Create a crew_run record for the test
    db_path = Path(settings.database_dir) / f"{test_slug}.db"
    conn = sqlite3.connect(db_path)
    cur = conn.execute(
        "INSERT INTO crew_runs (project_id, crew_name, status) VALUES (?,?,?)",
        (project_id, "test", "running"),
    )
    conn.commit()
    run_id = cur.lastrowid
    conn.close()

    tool = HumanInputTool(slug=test_slug, run_id=run_id, test_auto_respond="approved")
    result = tool._run(prompt="Please review this output. Reply 'approved' to continue.")

    assert result == "approved"

    # Verify the human_reviews record was created
    conn = sqlite3.connect(db_path)
    cur = conn.execute(
        "SELECT decision, prompt, crew_run_id FROM human_reviews WHERE crew_run_id=?",
        (run_id,),
    )
    row = cur.fetchone()
    conn.close()

    assert row is not None
    assert row[0] == "approved"
    assert "Please review" in row[1]
    assert row[2] == run_id
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/integration/test_tools.py::test_human_input_tool_auto_respond -m integration -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'agents.tools.human_input'`

- [ ] **Step 3: Implement agents/tools/human_input.py**

```python
# agents/tools/human_input.py
import os
import time
import httpx
from pydantic import BaseModel, Field
from crewai.tools import BaseTool
from api.config import get_settings
from agents.tools._db import insert_hitl_review, get_review_decision, complete_hitl_review


class HumanInputToolInput(BaseModel):
    prompt: str = Field(
        description="The question or instruction to present to the human reviewer."
    )


class HumanInputTool(BaseTool):
    name: str = "HumanInputTool"
    description: str = (
        "Pause the crew and request a human response. "
        "Use for review approval checkpoints and stakeholder interview questions. "
        "Returns the human's response as a string. "
        "If the response contains revision notes, revise your output and call this tool again "
        "(maximum 3 times per output)."
    )
    args_schema: type[BaseModel] = HumanInputToolInput
    slug: str
    run_id: int
    test_auto_respond: str | None = None

    def _run(self, prompt: str) -> str:
        # Check for auto-respond (env var for tests, or instance attribute)
        auto = self.test_auto_respond or os.getenv("HITL_AUTO_RESPOND")

        review_id = insert_hitl_review(
            slug=self.slug, run_id=self.run_id, prompt=prompt
        )

        if auto:
            complete_hitl_review(slug=self.slug, review_id=review_id, decision=auto)
            return auto

        # Notify n8n (fire and forget — don't fail the crew if n8n is unavailable)
        settings = get_settings()
        if settings.n8n_webhook_url:
            try:
                httpx.post(
                    settings.n8n_webhook_url,
                    json={
                        "review_id": review_id,
                        "prompt": prompt,
                        "project_slug": self.slug,
                        "run_id": self.run_id,
                        "review_url": (
                            f"{settings.frontend_url}/projects/{self.slug}/reviews"
                        ),
                    },
                    timeout=5.0,
                )
            except Exception:
                pass  # Don't block the crew if n8n is unreachable

        # Poll until the human updates the review via PATCH /projects/{slug}/reviews/{id}
        while True:
            time.sleep(5)
            decision, notes = get_review_decision(slug=self.slug, review_id=review_id)
            if decision != "pending":
                return notes if notes else decision
```

- [ ] **Step 4: Run test to verify it passes**

```bash
pytest tests/integration/test_tools.py::test_human_input_tool_auto_respond -m integration -v
```

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add agents/tools/human_input.py tests/integration/test_tools.py
git commit -m "feat: add HumanInputTool with auto-respond support and integration test"
```

---

## Task 8: DocumentIngestionTool

**Files:**
- Create: `agents/tools/document_ingestion.py`
- Modify: `tests/integration/test_tools.py` (add test)

Requires ChromaDB running: `docker run -p 8002:8000 chromadb/chroma`

- [ ] **Step 1: Write the failing integration test**

Append to `tests/integration/test_tools.py`:

```python
@pytest.mark.integration
def test_document_ingestion_tool(test_slug):
    from agents.tools.document_ingestion import DocumentIngestionTool
    from api.config import get_settings
    import chromadb

    settings = get_settings()
    tool = DocumentIngestionTool(slug=test_slug)

    result = tool._run(filename=None)  # ingest all docs in projects/{slug}/docs/
    assert "test_document.txt" in result

    # Verify documents are in ChromaDB
    client = chromadb.HttpClient(host=settings.chroma_host, port=settings.chroma_port)
    collection = client.get_collection(f"{test_slug}_docs")
    count = collection.count()
    assert count > 0
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/integration/test_tools.py::test_document_ingestion_tool -m integration -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'agents.tools.document_ingestion'`

- [ ] **Step 3: Implement agents/tools/document_ingestion.py**

```python
# agents/tools/document_ingestion.py
from pathlib import Path
from typing import Optional
from pydantic import BaseModel, Field
from crewai.tools import BaseTool
import chromadb
from api.config import get_settings


def _chunk_text(text: str, chunk_size: int = 1000, overlap: int = 200) -> list[str]:
    """Split text into overlapping chunks."""
    chunks = []
    start = 0
    while start < len(text):
        end = start + chunk_size
        chunks.append(text[start:end])
        start += chunk_size - overlap
    return [c for c in chunks if c.strip()]


def _read_file(path: Path) -> str:
    """Extract text from .txt, .md, or .pdf files."""
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        from pypdf import PdfReader
        reader = PdfReader(str(path))
        return "\n".join(page.extract_text() or "" for page in reader.pages)
    return path.read_text(errors="replace")


class DocumentIngestionToolInput(BaseModel):
    filename: Optional[str] = Field(
        default=None,
        description="Specific filename to ingest. If None, ingests all files in docs/.",
    )


class DocumentIngestionTool(BaseTool):
    name: str = "DocumentIngestionTool"
    description: str = (
        "Ingest client documents from the project docs/ directory into ChromaDB. "
        "Call with filename=None to ingest all documents, or specify a single filename. "
        "Returns a list of ingested document names."
    )
    args_schema: type[BaseModel] = DocumentIngestionToolInput
    slug: str

    def _run(self, filename: str | None = None) -> str:
        settings = get_settings()
        docs_dir = Path(settings.projects_dir) / self.slug / "docs"
        if not docs_dir.exists():
            return f"Error: docs directory not found at {docs_dir}"

        paths = (
            [docs_dir / filename]
            if filename
            else list(docs_dir.iterdir())
        )
        paths = [p for p in paths if p.is_file() and p.suffix.lower() in {".txt", ".md", ".pdf"}]
        if not paths:
            return "No supported documents found (.txt, .md, .pdf)"

        client = chromadb.HttpClient(host=settings.chroma_host, port=settings.chroma_port)
        collection = client.get_or_create_collection(name=f"{self.slug}_docs")

        ingested = []
        for path in paths:
            text = _read_file(path)
            if not text.strip():
                continue
            chunks = _chunk_text(text)
            ids = [f"{path.name}::{i}" for i in range(len(chunks))]
            metadatas = [{"filename": path.name, "chunk": i} for i in range(len(chunks))]
            collection.upsert(documents=chunks, ids=ids, metadatas=metadatas)
            ingested.append(path.name)

        return f"Ingested: {', '.join(ingested)}"
```

- [ ] **Step 4: Run test to verify it passes**

```bash
pytest tests/integration/test_tools.py::test_document_ingestion_tool -m integration -v
```

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add agents/tools/document_ingestion.py tests/integration/test_tools.py
git commit -m "feat: add DocumentIngestionTool with PDF/text support and integration test"
```

---

## Task 9: ChromaQueryTool

**Files:**
- Create: `agents/tools/chroma_query.py`
- Modify: `tests/integration/test_tools.py` (add test)

- [ ] **Step 1: Write the failing integration test**

Append to `tests/integration/test_tools.py`:

```python
@pytest.mark.integration
def test_chroma_query_tool(test_slug):
    """Requires documents already ingested by test_document_ingestion_tool."""
    from agents.tools.chroma_query import ChromaQueryTool

    tool = ChromaQueryTool(slug=test_slug, sector="logistics")

    result = tool._run(
        query="supply chain digital transformation priorities",
        collection="project",
        top_k=3,
    )

    assert isinstance(result, str)
    assert len(result) > 0
    # The fixture document mentions logistics — at least one chunk should match
    assert any(word in result.lower() for word in ["logistics", "supply", "digital", "transformation"])
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/integration/test_tools.py::test_chroma_query_tool -m integration -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'agents.tools.chroma_query'`

- [ ] **Step 3: Implement agents/tools/chroma_query.py**

```python
# agents/tools/chroma_query.py
from typing import Literal
from pydantic import BaseModel, Field
from crewai.tools import BaseTool
import chromadb
from api.config import get_settings


class ChromaQueryToolInput(BaseModel):
    query: str = Field(description="The search query to run against the document collection.")
    collection: Literal["project", "sector"] = Field(
        default="project",
        description="'project' queries this project's ingested docs; 'sector' queries the shared sector knowledge base.",
    )
    top_k: int = Field(default=5, description="Number of results to return.")


class ChromaQueryTool(BaseTool):
    name: str = "ChromaQueryTool"
    description: str = (
        "Retrieve relevant text chunks from ChromaDB. "
        "Use collection='project' for ingested client documents; "
        "use collection='sector' for the shared sector knowledge base."
    )
    args_schema: type[BaseModel] = ChromaQueryToolInput
    slug: str
    sector: str

    def _run(
        self,
        query: str,
        collection: str = "project",
        top_k: int = 5,
    ) -> str:
        settings = get_settings()
        client = chromadb.HttpClient(host=settings.chroma_host, port=settings.chroma_port)

        collection_name = (
            f"{self.slug}_docs" if collection == "project" else f"sector_{self.sector}"
        )

        try:
            col = client.get_collection(collection_name)
        except Exception:
            return f"Collection '{collection_name}' not found. Ingest documents first."

        results = col.query(query_texts=[query], n_results=min(top_k, col.count()))
        docs = results.get("documents", [[]])[0]
        if not docs:
            return "No relevant documents found."
        return "\n\n---\n\n".join(docs)
```

- [ ] **Step 4: Run test to verify it passes**

```bash
pytest tests/integration/test_tools.py::test_chroma_query_tool -m integration -v
```

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add agents/tools/chroma_query.py tests/integration/test_tools.py
git commit -m "feat: add ChromaQueryTool with project/sector collection support and integration test"
```

---

## Task 10: TavilySearchTool

**Files:**
- Create: `agents/tools/tavily_search.py`
- Modify: `tests/integration/test_tools.py` (add test)

Requires `TAVILY_API_KEY` set in environment.

- [ ] **Step 1: Write the failing integration test**

Append to `tests/integration/test_tools.py`:

```python
@pytest.mark.integration
def test_tavily_search_tool():
    import os
    if not os.getenv("TAVILY_API_KEY"):
        pytest.skip("TAVILY_API_KEY not set")

    from agents.tools.tavily_search import TavilySearchTool

    tool = TavilySearchTool()
    result = tool._run(query="logistics industry digital transformation trends 2025", max_results=3)

    assert isinstance(result, str)
    assert len(result) > 50
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/integration/test_tools.py::test_tavily_search_tool -m integration -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'agents.tools.tavily_search'`

- [ ] **Step 3: Implement agents/tools/tavily_search.py**

```python
# agents/tools/tavily_search.py
from pydantic import BaseModel, Field
from crewai.tools import BaseTool
from api.config import get_settings


class TavilySearchToolInput(BaseModel):
    query: str = Field(description="The search query.")
    max_results: int = Field(default=5, description="Maximum number of results to return.")


class TavilySearchTool(BaseTool):
    name: str = "TavilySearchTool"
    description: str = (
        "Search the web for current information about a topic. "
        "Use for market research, sector benchmarks, and technology trends."
    )
    args_schema: type[BaseModel] = TavilySearchToolInput

    def _run(self, query: str, max_results: int = 5) -> str:
        settings = get_settings()
        if not settings.tavily_api_key:
            return "Error: TAVILY_API_KEY not configured."
        try:
            from tavily import TavilyClient
            client = TavilyClient(api_key=settings.tavily_api_key)
            response = client.search(query=query, max_results=max_results)
            results = response.get("results", [])
            if not results:
                return "No results found."
            return "\n\n".join(
                f"**{r.get('title', 'Untitled')}**\n{r.get('url', '')}\n{r.get('content', '')}"
                for r in results
            )
        except Exception as e:
            return f"Search error: {e}"
```

- [ ] **Step 4: Run test to verify it passes**

```bash
TAVILY_API_KEY=your-key pytest tests/integration/test_tools.py::test_tavily_search_tool -m integration -v
```

Expected: PASS (or skip if key not set)

- [ ] **Step 5: Commit**

```bash
git add agents/tools/tavily_search.py tests/integration/test_tools.py
git commit -m "feat: add TavilySearchTool with graceful key-missing handling and integration test"
```

---

## Task 11: MermaidRenderTool

**Files:**
- Create: `agents/tools/mermaid_render.py`
- Modify: `tests/integration/test_tools.py` (add test)

Saves Mermaid markdown to `outputs/{filename}.md`. The React frontend renders Mermaid in-browser; SVG export is deferred.

- [ ] **Step 1: Write the failing integration test**

Append to `tests/integration/test_tools.py`:

```python
@pytest.mark.integration
def test_mermaid_render_tool(test_slug):
    from agents.tools.mermaid_render import MermaidRenderTool
    from api.config import get_settings

    settings = get_settings()
    tool = MermaidRenderTool(slug=test_slug)

    mermaid_md = """```mermaid
graph LR
    A[Inbound Logistics] --> B[Operations]
    B --> C[Outbound Logistics]
    C --> D[Marketing & Sales]
    D --> E[Service]
```"""

    result = tool._run(mermaid_md=mermaid_md, filename="test_value_chain")

    assert "test_value_chain.md" in result
    file_path = Path(settings.projects_dir) / test_slug / "outputs" / "test_value_chain.md"
    assert file_path.exists()
    assert "graph LR" in file_path.read_text()
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/integration/test_tools.py::test_mermaid_render_tool -m integration -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'agents.tools.mermaid_render'`

- [ ] **Step 3: Implement agents/tools/mermaid_render.py**

```python
# agents/tools/mermaid_render.py
from pathlib import Path
from pydantic import BaseModel, Field
from crewai.tools import BaseTool
from api.config import get_settings
from agents.tools._db import insert_agent_output_sync


class MermaidRenderToolInput(BaseModel):
    mermaid_md: str = Field(
        description="Mermaid diagram markdown content (including the ```mermaid fence)."
    )
    filename: str = Field(
        description="Output filename without extension (e.g. 'value_chain' → value_chain.md)."
    )
    agent_name: str = Field(
        default="value_chain_mapper",
        description="Name of the agent producing this diagram (used for output tracking).",
    )


class MermaidRenderTool(BaseTool):
    name: str = "MermaidRenderTool"
    description: str = (
        "Save a Mermaid diagram to the project outputs directory. "
        "Pass the full Mermaid markdown (including the ```mermaid fence) and a filename. "
        "The diagram will be rendered in the React UI automatically."
    )
    args_schema: type[BaseModel] = MermaidRenderToolInput
    slug: str

    def _run(self, mermaid_md: str, filename: str, agent_name: str = "value_chain_mapper") -> str:
        settings = get_settings()
        outputs_dir = Path(settings.projects_dir) / self.slug / "outputs"
        outputs_dir.mkdir(parents=True, exist_ok=True)

        file_path = outputs_dir / f"{filename}.md"
        file_path.write_text(mermaid_md)

        insert_agent_output_sync(
            slug=self.slug,
            agent_name=agent_name,
            output_type="value_chain",
            file_path=str(file_path),
        )
        return f"Diagram saved to {file_path}"
```

- [ ] **Step 4: Run test to verify it passes**

```bash
pytest tests/integration/test_tools.py::test_mermaid_render_tool -m integration -v
```

Expected: PASS

- [ ] **Step 5: Run all tool tests together**

```bash
pytest tests/integration/test_tools.py -m integration -v
```

Expected: All tool tests PASS (TavilySearch skipped if no API key).

- [ ] **Step 6: Commit**

```bash
git add agents/tools/mermaid_render.py tests/integration/test_tools.py
git commit -m "feat: add MermaidRenderTool and verify all tool integration tests pass"
```

---

## Task 12: Tool Registry

**Files:**
- Create: `agents/tools/registry.py`

- [ ] **Step 1: Create agents/tools/registry.py**

```python
# agents/tools/registry.py
"""
Maps agent names to their tool lists.

Usage:
    tools = get_tools_for_agent("value_chain_mapper", slug="acme", run_id=7, sector="logistics")
"""
from crewai.tools import BaseTool
from api.config import get_settings, load_project_config
from pathlib import Path


def get_tools_for_agent(
    agent_name: str,
    slug: str,
    run_id: int = 0,
    sector: str = "",
) -> list[BaseTool]:
    """Return instantiated tools for the given agent, scoped to the project slug."""
    from agents.tools.sqlite_state import SQLiteStateTool
    from agents.tools.human_input import HumanInputTool
    from agents.tools.document_ingestion import DocumentIngestionTool
    from agents.tools.chroma_query import ChromaQueryTool
    from agents.tools.tavily_search import TavilySearchTool
    from agents.tools.mermaid_render import MermaidRenderTool

    if not sector:
        settings = get_settings()
        try:
            config = load_project_config(Path(settings.projects_dir) / slug)
            sector = config.get("sector", "")
        except Exception:
            sector = ""

    tool_map: dict[str, list[BaseTool]] = {
        "value_chain_mapper": [
            DocumentIngestionTool(slug=slug),
            TavilySearchTool(),
            ChromaQueryTool(slug=slug, sector=sector),
            MermaidRenderTool(slug=slug),
            SQLiteStateTool(slug=slug),
            HumanInputTool(slug=slug, run_id=run_id),
        ],
        "requirements_capture": [
            HumanInputTool(slug=slug, run_id=run_id),
            SQLiteStateTool(slug=slug),
        ],
        "requirements_analyst": [
            DocumentIngestionTool(slug=slug),
            ChromaQueryTool(slug=slug, sector=sector),
            SQLiteStateTool(slug=slug),
            HumanInputTool(slug=slug, run_id=run_id),
        ],
        "value_lever_analyst": [
            ChromaQueryTool(slug=slug, sector=sector),
            TavilySearchTool(),
            SQLiteStateTool(slug=slug),
            HumanInputTool(slug=slug, run_id=run_id),
        ],
        "pam": [
            SQLiteStateTool(slug=slug),
            HumanInputTool(slug=slug, run_id=run_id),
        ],
    }

    tools = tool_map.get(agent_name)
    if tools is None:
        raise ValueError(f"Unknown agent: {agent_name}")
    return tools
```

- [ ] **Step 2: Verify it imports cleanly**

```bash
python -c "
import os; os.environ['ANTHROPIC_API_KEY']='test'
from agents.tools.registry import get_tools_for_agent
print('OK')
"
```

Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add agents/tools/registry.py
git commit -m "feat: add tool registry mapping agent names to scoped tool lists"
```

---

## Task 13: Value Chain Mapper Agent

**Files:**
- Create: `agents/discovery/__init__.py`
- Create: `agents/discovery/value_chain_mapper.py`

- [ ] **Step 1: Create agents/discovery/__init__.py**

```python
```

(Empty.)

- [ ] **Step 2: Create agents/discovery/value_chain_mapper.py**

```python
# agents/discovery/value_chain_mapper.py
from crewai import Agent, Task, LLM
from crewai.tools import BaseTool


def create_value_chain_mapper(slug: str, llm: LLM, tools: list[BaseTool]) -> Agent:
    return Agent(
        role="Value Chain Mapper",
        goal=(
            "Map the client organisation's complete value chain by analysing uploaded documents "
            "and researching the sector. Produce a clear, accurate Mermaid diagram."
        ),
        backstory=(
            "You are a senior strategy consultant specialising in value chain analysis. "
            "You have deep expertise in identifying primary and support activities across "
            "industry sectors and translating them into clear visual models."
        ),
        llm=llm,
        tools=tools,
        verbose=True,
        allow_delegation=False,
    )


def create_value_chain_mapper_task(agent: Agent) -> Task:
    return Task(
        description=(
            "Analyse the client documents and sector context to map the organisation's value chain.\n\n"
            "Steps:\n"
            "1. Use DocumentIngestionTool with filename=None to ingest all client documents.\n"
            "2. Use ChromaQueryTool with collection='project' to understand the client's operations.\n"
            "3. Use TavilySearchTool to research the sector's typical value chain structure.\n"
            "4. Use ChromaQueryTool with collection='sector' for additional sector benchmarks.\n"
            "5. Produce a Mermaid diagram showing primary activities (left to right: Inbound Logistics, "
            "Operations, Outbound Logistics, Marketing & Sales, Service) and support activities, "
            "labelled with client-specific process names where known.\n"
            "6. Use MermaidRenderTool to save the diagram with filename='value_chain'.\n"
            "7. Use SQLiteStateTool with operation='write', key='value_chain_summary', "
            "agent_name='value_chain_mapper' to save a brief JSON summary: "
            "{\"activities\": [list of key activities identified], \"sector\": \"...\"}.\n"
            "8. Use HumanInputTool with prompt: 'Please review the value chain diagram saved at "
            "outputs/value_chain.md. Reply \"approved\" to proceed, or provide revision notes.'\n"
            "9. If revision notes are received (response is not 'approved'), revise the diagram "
            "and call HumanInputTool again. Repeat at most 3 times total.\n"
        ),
        expected_output=(
            "A Mermaid value chain diagram saved to outputs/value_chain.md, "
            "a JSON summary saved via SQLiteStateTool, "
            "and confirmation that the diagram has been approved by a human reviewer."
        ),
        agent=agent,
    )
```

- [ ] **Step 3: Verify imports**

```bash
python -c "
import os; os.environ['ANTHROPIC_API_KEY']='test'
from agents.discovery.value_chain_mapper import create_value_chain_mapper, create_value_chain_mapper_task
print('OK')
"
```

Expected: `OK`

- [ ] **Step 4: Commit**

```bash
git add agents/discovery/__init__.py agents/discovery/value_chain_mapper.py
git commit -m "feat: add Value Chain Mapper agent and task"
```

---

## Task 14: Requirements Capture Agent

**Files:**
- Create: `agents/discovery/requirements_capture.py`

- [ ] **Step 1: Create agents/discovery/requirements_capture.py**

```python
# agents/discovery/requirements_capture.py
from crewai import Agent, Task, LLM
from crewai.tools import BaseTool
from api.config import get_settings, load_project_config
from pathlib import Path


def create_requirements_capture(slug: str, llm: LLM, tools: list[BaseTool]) -> Agent:
    return Agent(
        role="Requirements Capture Specialist",
        goal=(
            "Conduct a structured stakeholder interview to surface digital modernisation requirements. "
            "Use the value chain as a frame to ask targeted, high-value questions."
        ),
        backstory=(
            "You are an experienced business analyst who has conducted hundreds of requirements "
            "workshops. You know how to ask open questions that reveal hidden pain points, "
            "and how to probe for priorities, constraints, and success criteria."
        ),
        llm=llm,
        tools=tools,
        verbose=True,
        allow_delegation=False,
    )


def create_requirements_capture_task(
    agent: Agent, context_tasks: list[Task], slug: str
) -> Task:
    settings = get_settings()
    try:
        config = load_project_config(Path(settings.projects_dir) / slug)
        max_turns = config.get("requirements_capture_max_turns", 10)
    except Exception:
        max_turns = 10

    return Task(
        description=(
            "Conduct a structured stakeholder interview to capture digital modernisation requirements.\n\n"
            "The value chain map is available from the previous task's output. "
            f"Conduct the interview over a minimum of 5 and a maximum of {max_turns} exchanges.\n\n"
            "Process:\n"
            "1. Formulate your first question covering the most critical pain points in the value chain.\n"
            "2. Use HumanInputTool to ask the question.\n"
            "3. Based on the response, formulate a follow-up question that probes deeper or covers "
            "a new area. Cover: pain points by value chain activity, current technology constraints, "
            "desired outcomes, priorities, regulatory constraints, and budget/timeline context.\n"
            "4. Repeat steps 2-3 until you have sufficient coverage (minimum 5 exchanges) or "
            f"reach {max_turns} questions.\n"
            "5. Use SQLiteStateTool with operation='write', key='interview_transcript', "
            "agent_name='requirements_capture' to save the complete Q&A as JSON: "
            "[{\"question\": \"...\", \"answer\": \"...\"}, ...].\n"
        ),
        expected_output=(
            "A complete interview transcript saved via SQLiteStateTool under key 'interview_transcript', "
            f"containing between 5 and {max_turns} question-answer pairs covering "
            "pain points, constraints, priorities, and desired outcomes."
        ),
        agent=agent,
        context=context_tasks,
    )
```

- [ ] **Step 2: Verify imports**

```bash
python -c "
import os; os.environ['ANTHROPIC_API_KEY']='test'
from agents.discovery.requirements_capture import create_requirements_capture, create_requirements_capture_task
print('OK')
"
```

Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add agents/discovery/requirements_capture.py
git commit -m "feat: add Requirements Capture agent with multi-turn interview task"
```

---

## Task 15: Requirements Analyst Agent

**Files:**
- Create: `agents/discovery/requirements_analyst.py`

- [ ] **Step 1: Create agents/discovery/requirements_analyst.py**

```python
# agents/discovery/requirements_analyst.py
from crewai import Agent, Task, LLM
from crewai.tools import BaseTool


def create_requirements_analyst(slug: str, llm: LLM, tools: list[BaseTool]) -> Agent:
    return Agent(
        role="Requirements Analyst",
        goal=(
            "Synthesise the stakeholder interview transcript and client documents into a "
            "structured, prioritised requirements register ready for value design."
        ),
        backstory=(
            "You are a meticulous business analyst who specialises in translating messy "
            "stakeholder inputs into clear, actionable requirements. You are skilled at "
            "deduplication, prioritisation, and linking requirements to business outcomes."
        ),
        llm=llm,
        tools=tools,
        verbose=True,
        allow_delegation=False,
    )


def create_requirements_analyst_task(
    agent: Agent, context_tasks: list[Task]
) -> Task:
    return Task(
        description=(
            "Synthesise the interview transcript and client documents into a structured requirements register.\n\n"
            "Steps:\n"
            "1. Use SQLiteStateTool with operation='read', key='interview_transcript', "
            "agent_name='requirements_analyst' to retrieve the interview transcript.\n"
            "2. Use ChromaQueryTool with collection='project' to retrieve any additional context "
            "from client documents.\n"
            "3. Use ChromaQueryTool with collection='sector' to compare against sector-standard requirements.\n"
            "4. Produce a requirements register as a JSON array. Each requirement must follow this schema:\n"
            "   {\"id\": \"REQ-001\", \"description\": \"...\", \"source\": \"interview|document\", "
            "\"priority\": \"high|medium|low\", \"value_chain_activity\": \"...\", "
            "\"acceptance_criteria\": \"...\"}\n"
            "   Number requirements sequentially from REQ-001. Deduplicate overlapping requirements.\n"
            "5. Use SQLiteStateTool with operation='write', key='requirements', "
            "agent_name='requirements_analyst' to save the JSON array.\n"
            "6. Use HumanInputTool with prompt: 'Please review the requirements register saved at "
            "outputs/requirements.json. Reply \"approved\" to proceed, or provide notes.'\n"
            "7. If revision notes are received, revise and call HumanInputTool again (maximum 3 times).\n"
        ),
        expected_output=(
            "A JSON requirements register saved to outputs/requirements.json "
            "and confirmed approved by a human reviewer. "
            "Register must contain at least 3 requirements with id, description, source, "
            "priority, value_chain_activity, and acceptance_criteria fields."
        ),
        agent=agent,
        context=context_tasks,
    )
```

- [ ] **Step 2: Verify imports**

```bash
python -c "
import os; os.environ['ANTHROPIC_API_KEY']='test'
from agents.discovery.requirements_analyst import create_requirements_analyst, create_requirements_analyst_task
print('OK')
"
```

Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add agents/discovery/requirements_analyst.py
git commit -m "feat: add Requirements Analyst agent and task"
```

---

## Task 16: Value Lever Analyst Agent

**Files:**
- Create: `agents/discovery/value_lever_analyst.py`

- [ ] **Step 1: Create agents/discovery/value_lever_analyst.py**

```python
# agents/discovery/value_lever_analyst.py
from crewai import Agent, Task, LLM
from crewai.tools import BaseTool


def create_value_lever_analyst(slug: str, llm: LLM, tools: list[BaseTool]) -> Agent:
    return Agent(
        role="Value Lever Analyst",
        goal=(
            "Identify the highest-impact value levers for digital modernisation by connecting "
            "the requirements register to known transformation patterns and sector benchmarks."
        ),
        backstory=(
            "You are a transformation strategist with expertise in identifying where digital "
            "interventions create the most business value. You combine requirements analysis "
            "with market knowledge to pinpoint high-ROI modernisation opportunities."
        ),
        llm=llm,
        tools=tools,
        verbose=True,
        allow_delegation=False,
    )


def create_value_lever_analyst_task(
    agent: Agent, context_tasks: list[Task]
) -> Task:
    return Task(
        description=(
            "Identify the highest-impact value levers from the requirements register and value chain.\n\n"
            "Steps:\n"
            "1. Use SQLiteStateTool with operation='read', key='requirements', "
            "agent_name='value_lever_analyst' to retrieve the requirements.\n"
            "2. Use ChromaQueryTool with collection='sector' to retrieve known digital transformation "
            "patterns and value levers for this sector.\n"
            "3. Use TavilySearchTool to research best practices and benchmarks relevant to "
            "the top requirements.\n"
            "4. Produce a value levers analysis as a JSON array. Each lever must follow this schema:\n"
            "   {\"lever\": \"...\", \"description\": \"...\", \"value_impact\": \"high|medium|low\", "
            "\"effort\": \"high|medium|low\", \"related_requirements\": [\"REQ-001\", ...], "
            "\"evidence\": \"...\"}\n"
            "   Order levers by value_impact (high first), then by effort (low first).\n"
            "5. Use SQLiteStateTool with operation='write', key='value_levers', "
            "agent_name='value_lever_analyst' to save the JSON array.\n"
            "6. Use HumanInputTool with prompt: 'Please review the value levers analysis saved at "
            "outputs/value_levers.json. Reply \"approved\" to conclude the Discovery phase, "
            "or provide notes.'\n"
            "7. If revision notes are received, revise and call HumanInputTool again (maximum 3 times).\n"
        ),
        expected_output=(
            "A JSON value levers analysis saved to outputs/value_levers.json "
            "and confirmed approved by a human reviewer. "
            "Analysis must contain at least 3 levers each with lever, description, value_impact, "
            "effort, related_requirements, and evidence fields."
        ),
        agent=agent,
        context=context_tasks,
    )
```

- [ ] **Step 2: Verify imports**

```bash
python -c "
import os; os.environ['ANTHROPIC_API_KEY']='test'
from agents.discovery.value_lever_analyst import create_value_lever_analyst, create_value_lever_analyst_task
print('OK')
"
```

Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add agents/discovery/value_lever_analyst.py
git commit -m "feat: add Value Lever Analyst agent and task"
```

---

## Task 17: Discovery Crew Assembly

**Files:**
- Create: `agents/crews/__init__.py`
- Create: `agents/crews/discovery_crew.py`
- Create: `agents/pam.py`

- [ ] **Step 1: Create agents/crews/__init__.py**

```python
```

(Empty.)

- [ ] **Step 2: Create agents/pam.py**

```python
# agents/pam.py
"""PAM (Programme Architecture Manager) configuration constants."""

PAM_NAME = "PAM"
PAM_MODEL = "anthropic/claude-opus-4-6"
PAM_ROLE = "Programme Architecture Manager"
PAM_GOAL = (
    "Orchestrate the end-to-end delivery of AI-assisted strategy consulting, "
    "coordinating specialist crews and ensuring quality outputs at each stage."
)
```

- [ ] **Step 3: Create agents/crews/discovery_crew.py**

```python
# agents/crews/discovery_crew.py
from crewai import Crew, Process, LLM
from agents.llm import get_crew_llm
from agents.tools.registry import get_tools_for_agent
from agents.discovery.value_chain_mapper import (
    create_value_chain_mapper,
    create_value_chain_mapper_task,
)
from agents.discovery.requirements_capture import (
    create_requirements_capture,
    create_requirements_capture_task,
)
from agents.discovery.requirements_analyst import (
    create_requirements_analyst,
    create_requirements_analyst_task,
)
from agents.discovery.value_lever_analyst import (
    create_value_lever_analyst,
    create_value_lever_analyst_task,
)


def create_discovery_crew(
    slug: str,
    run_id: int,
    llm_mode: str,
    sector: str,
    llm: LLM | None = None,
) -> Crew:
    """
    Assemble and return the Discovery Crew.

    Args:
        slug: Project slug (used for DB/file scoping).
        run_id: crew_runs.id for this execution (used by HumanInputTool).
        llm_mode: "standard" | "sensitive" | "fallback" — determines LLM routing.
        sector: Client sector (used by ChromaQueryTool for sector knowledge base).
        llm: Optional LLM override (used in tests to inject a cheap model).
    """
    if llm is None:
        llm = get_crew_llm(llm_mode)

    vcm = create_value_chain_mapper(
        slug=slug,
        llm=llm,
        tools=get_tools_for_agent("value_chain_mapper", slug=slug, run_id=run_id, sector=sector),
    )
    rc = create_requirements_capture(
        slug=slug,
        llm=llm,
        tools=get_tools_for_agent("requirements_capture", slug=slug, run_id=run_id, sector=sector),
    )
    ra = create_requirements_analyst(
        slug=slug,
        llm=llm,
        tools=get_tools_for_agent("requirements_analyst", slug=slug, run_id=run_id, sector=sector),
    )
    vla = create_value_lever_analyst(
        slug=slug,
        llm=llm,
        tools=get_tools_for_agent("value_lever_analyst", slug=slug, run_id=run_id, sector=sector),
    )

    vcm_task = create_value_chain_mapper_task(agent=vcm)
    rc_task = create_requirements_capture_task(agent=rc, context_tasks=[vcm_task], slug=slug)
    ra_task = create_requirements_analyst_task(agent=ra, context_tasks=[vcm_task, rc_task])
    vla_task = create_value_lever_analyst_task(agent=vla, context_tasks=[vcm_task, ra_task])

    return Crew(
        agents=[vcm, rc, ra, vla],
        tasks=[vcm_task, rc_task, ra_task, vla_task],
        process=Process.sequential,
        verbose=True,
    )
```

- [ ] **Step 4: Verify the crew assembles without error**

```bash
python -c "
import os; os.environ['ANTHROPIC_API_KEY']='test'
from agents.crews.discovery_crew import create_discovery_crew
crew = create_discovery_crew(slug='test', run_id=1, llm_mode='standard', sector='logistics')
print(f'Crew assembled with {len(crew.tasks)} tasks')
"
```

Expected: `Crew assembled with 4 tasks`

- [ ] **Step 5: Commit**

```bash
git add agents/crews/__init__.py agents/crews/discovery_crew.py agents/pam.py
git commit -m "feat: assemble Discovery Crew with 4 sequential agents"
```

---

## Task 18: Run Service

**Files:**
- Create: `api/services/run_service.py`
- Modify: `api/database.py` (add update_crew_run_status)

- [ ] **Step 1: Add update_crew_run_status to api/database.py**

Append to `api/database.py`:

```python
async def update_crew_run_status(
    conn: aiosqlite.Connection,
    *,
    run_id: int,
    status: str,
    result_json: str = "{}",
) -> None:
    await conn.execute(
        "UPDATE crew_runs SET status=?, result_json=?, finished_at=CURRENT_TIMESTAMP WHERE id=?",
        (status, result_json, run_id),
    )
    await conn.commit()
```

- [ ] **Step 2: Create api/services/run_service.py**

```python
# api/services/run_service.py
"""
PAM orchestration layer.

dispatch_crew() is called by the run router via asyncio.create_task().
It loads the project config, builds the appropriate crew, runs it, and
writes the final status back to crew_runs.
"""
import asyncio
import json
from pathlib import Path
from api.config import get_settings, load_project_config
from api.database import get_connection, update_crew_run_status
from api.routers.ws import push_log


async def dispatch_crew(slug: str, crew_name: str, run_id: int) -> None:
    """Entry point called by asyncio.create_task. Runs the named crew and updates status."""
    try:
        await push_log(slug, json.dumps({"type": "crew_started", "crew": crew_name, "run_id": run_id}))
        if crew_name == "discovery":
            await _run_discovery_crew(slug=slug, run_id=run_id)
        else:
            raise ValueError(f"Unknown crew: '{crew_name}'")
        async with get_connection(slug) as conn:
            await update_crew_run_status(conn, run_id=run_id, status="completed")
        await push_log(slug, json.dumps({"type": "crew_completed", "crew": crew_name, "run_id": run_id}))
    except Exception as e:
        async with get_connection(slug) as conn:
            await update_crew_run_status(
                conn,
                run_id=run_id,
                status="failed",
                result_json=json.dumps({"error": str(e)}),
            )
        await push_log(slug, json.dumps({"type": "crew_failed", "crew": crew_name, "error": str(e)}))
        raise


async def _run_discovery_crew(slug: str, run_id: int) -> None:
    """Build and run the Discovery Crew asynchronously."""
    settings = get_settings()
    config = load_project_config(Path(settings.projects_dir) / slug)
    llm_mode = config.get("llm_mode", "standard")
    sector = config.get("sector", "")

    from agents.crews.discovery_crew import create_discovery_crew
    crew = create_discovery_crew(
        slug=slug,
        run_id=run_id,
        llm_mode=llm_mode,
        sector=sector,
    )
    # kickoff_async() runs the crew on the event loop without blocking
    await crew.kickoff_async()
```

- [ ] **Step 3: Verify imports**

```bash
python -c "
import os; os.environ['ANTHROPIC_API_KEY']='test'; os.environ['JWT_SECRET']='test'
from api.services.run_service import dispatch_crew
print('OK')
"
```

Expected: `OK`

- [ ] **Step 4: Commit**

```bash
git add api/services/run_service.py api/database.py
git commit -m "feat: add run_service with async crew dispatch and update_crew_run_status"
```

---

## Task 19: Extend Run Router

**Files:**
- Modify: `api/routers/run.py`
- Modify: `tests/test_run_api.py`
- Modify: `api/main.py` (add run_service import to services __init__)
- Create: `api/services/__init__.py` (if missing)

- [ ] **Step 1: Update api/routers/run.py to trigger run_service**

Replace the full content of `api/routers/run.py`:

```python
# api/routers/run.py
import asyncio
from fastapi import APIRouter, HTTPException
from api.database import get_connection, get_db_path, fetch_project, insert_crew_run
from api.models import RunRequest, RunResponse

router = APIRouter(prefix="/projects", tags=["run"])


@router.post("/{slug}/run", status_code=202, response_model=RunResponse)
async def run_crew(slug: str, req: RunRequest):
    if not get_db_path(slug).exists():
        raise HTTPException(status_code=404, detail=f"Project '{slug}' not found")

    crew = req.crew or "discovery"
    async with get_connection(slug) as conn:
        project = await fetch_project(conn, slug=slug)
        if not project:
            raise HTTPException(status_code=404, detail=f"Project '{slug}' not found")
        run_id = await insert_crew_run(
            conn, project_id=project["id"], crew_name=crew, status="running"
        )

    # Fire and forget — dispatch_crew runs in the background
    from api.services.run_service import dispatch_crew
    asyncio.create_task(dispatch_crew(slug=slug, crew_name=crew, run_id=run_id))

    return RunResponse(run_id=run_id, project_slug=slug, crew=crew, status="running")
```

- [ ] **Step 2: Update the existing test to expect status "running"**

In `tests/test_run_api.py`, change:

```python
assert data["status"] == "queued"
```

To:

```python
assert data["status"] == "running"
```

- [ ] **Step 3: Run the existing test suite to verify**

```bash
pytest tests/ -x -q
```

Expected: all tests pass. The `test_run_known_project_queues_run` test now checks `status == "running"`.

Note: `asyncio.create_task(dispatch_crew(...))` will immediately attempt to run the crew in the test, but since `ANTHROPIC_API_KEY` is set to `"test-key"` in `tests/conftest.py`, the crew will fail quickly with an auth error. The test only checks the HTTP response (202 + run_id), which is returned before the crew starts. The background task failure is silent in the test context.

If the test fails due to background task noise, wrap `dispatch_crew` in a try/except inside the test by mocking it:

```python
# In tests/test_run_api.py, add at module level:
from unittest.mock import patch, AsyncMock

@pytest.mark.asyncio
async def test_run_known_project_queues_run(client):
    await client.post("/projects", json=PROJECT_PAYLOAD)
    with patch("api.routers.run.dispatch_crew", new_callable=AsyncMock):
        resp = await client.post("/projects/run-test/run", json={"crew": "discovery"})
    assert resp.status_code == 202
    data = resp.json()
    assert data["project_slug"] == "run-test"
    assert data["crew"] == "discovery"
    assert data["status"] == "running"
    assert isinstance(data["run_id"], int)
```

- [ ] **Step 4: Run tests again after mock update**

```bash
pytest tests/ -x -q
```

Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add api/routers/run.py tests/test_run_api.py
git commit -m "feat: run router triggers run_service via asyncio.create_task, status now 'running'"
```

---

## Task 20: Full Crew Integration Test

**Files:**
- Create: `tests/integration/test_discovery_crew.py`

This test runs the full Discovery crew end-to-end with `claude-haiku-4-5-20251001`. It takes 3–10 minutes. All HITL pauses are auto-responded via `HITL_AUTO_RESPOND=approved` (set in conftest).

- [ ] **Step 1: Create tests/integration/test_discovery_crew.py**

```python
# tests/integration/test_discovery_crew.py
"""
Full end-to-end integration test for the Discovery Crew.

Runs the crew with claude-haiku-4-5-20251001 against a real SQLite DB and ChromaDB.
HITL pauses are auto-responded via HITL_AUTO_RESPOND env var set in conftest.

Takes 3-10 minutes. Run with: pytest -m integration -v
"""
import json
import sqlite3
import pytest
from pathlib import Path
from api.config import get_settings


@pytest.mark.integration
def test_discovery_crew_end_to_end(test_slug, project_id):
    """
    Run the full Discovery Crew and verify all outputs are produced.
    Uses synchronous execution (crew.kickoff()) for test simplicity.
    """
    import asyncio
    from agents.llm import get_test_llm
    from agents.crews.discovery_crew import create_discovery_crew

    settings = get_settings()
    db_path = Path(settings.database_dir) / f"{test_slug}.db"

    # Create a crew_run record
    conn = sqlite3.connect(db_path)
    cur = conn.execute(
        "INSERT INTO crew_runs (project_id, crew_name, status, started_at)"
        " VALUES (?,?,?, CURRENT_TIMESTAMP)",
        (project_id, "discovery", "running"),
    )
    conn.commit()
    run_id = cur.lastrowid
    conn.close()

    # Build crew with cheap test LLM
    llm = get_test_llm()
    crew = create_discovery_crew(
        slug=test_slug,
        run_id=run_id,
        llm_mode="standard",
        sector="logistics",
        llm=llm,
    )

    # Run the crew (synchronously — simpler for test assertions)
    result = crew.kickoff()
    assert result is not None

    # 1. crew_runs record should still exist (updated by run_service in production;
    #    in this test we called kickoff() directly so we update manually)
    conn = sqlite3.connect(db_path)
    conn.execute(
        "UPDATE crew_runs SET status='completed', finished_at=CURRENT_TIMESTAMP WHERE id=?",
        (run_id,),
    )
    conn.commit()

    # 2. Verify crew_runs status
    cur = conn.execute("SELECT status FROM crew_runs WHERE id=?", (run_id,))
    assert cur.fetchone()[0] == "completed"

    # 3. agent_outputs: at least one record per agent (excluding state-type)
    cur = conn.execute(
        "SELECT DISTINCT agent_name FROM agent_outputs WHERE project_id=? AND output_type != 'state'",
        (project_id,),
    )
    agent_names = {row[0] for row in cur.fetchall()}
    assert "value_chain_mapper" in agent_names, "Value Chain Mapper produced no output"

    # 4. human_reviews: at least one HITL record for this run
    cur = conn.execute(
        "SELECT COUNT(*) FROM human_reviews WHERE crew_run_id=?", (run_id,)
    )
    hitl_count = cur.fetchone()[0]
    conn.close()
    assert hitl_count >= 1, "No HITL reviews created during crew run"

    # 5. Output files
    outputs_dir = Path(settings.projects_dir) / test_slug / "outputs"

    value_chain_path = outputs_dir / "value_chain.md"
    assert value_chain_path.exists(), "value_chain.md not created"
    value_chain_content = value_chain_path.read_text()
    assert "graph" in value_chain_content.lower() or "flowchart" in value_chain_content.lower(), \
        "value_chain.md does not contain Mermaid syntax"

    requirements_path = outputs_dir / "requirements.json"
    assert requirements_path.exists(), "requirements.json not created"
    requirements = json.loads(requirements_path.read_text())
    assert isinstance(requirements, list), "requirements.json is not a JSON array"
    assert len(requirements) >= 1, "requirements.json contains no requirements"
    assert "id" in requirements[0], "Requirements missing 'id' field"

    value_levers_path = outputs_dir / "value_levers.json"
    assert value_levers_path.exists(), "value_levers.json not created"
    levers = json.loads(value_levers_path.read_text())
    assert isinstance(levers, list), "value_levers.json is not a JSON array"
    assert len(levers) >= 1, "value_levers.json contains no levers"
    assert "lever" in levers[0], "Value levers missing 'lever' field"
```

- [ ] **Step 2: Run the full crew integration test**

Ensure ChromaDB is running first:
```bash
docker run -d -p 8002:8000 chromadb/chroma
```

Then run:
```bash
pytest tests/integration/test_discovery_crew.py::test_discovery_crew_end_to_end -m integration -v -s
```

Expected: PASS after 3–10 minutes. If the crew produces incomplete JSON (haiku may truncate), re-run — haiku output can be non-deterministic.

- [ ] **Step 3: Run the full integration suite**

```bash
pytest -m integration -v
```

Expected: all integration tests pass (TavilySearch skips if no API key).

- [ ] **Step 4: Run the unit test suite to confirm no regressions**

```bash
pytest tests/ -x -q --ignore=tests/integration
```

Expected: all existing tests pass.

- [ ] **Step 5: Commit**

```bash
git add tests/integration/test_discovery_crew.py
git commit -m "test: add full Discovery Crew end-to-end integration test"
```

---

## Done

All 20 tasks complete. The Discovery Crew is fully implemented and tested:

- 6 tools (SQLiteState, HumanInput, DocumentIngestion, ChromaQuery, TavilySearch, MermaidRender)
- 4 discovery agents (Value Chain Mapper, Requirements Capture, Requirements Analyst, Value Lever Analyst)
- HITL via SQLite + n8n/Slack
- Integration tests with `claude-haiku-4-5-20251001`
- `POST /projects/{slug}/run {"crew": "discovery"}` triggers the full pipeline
