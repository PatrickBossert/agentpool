# SP1 — Infrastructure Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stand up all infrastructure services (LiteLLM, FastAPI, ChromaDB, n8n, Chainlit) on the Mac Mini so the agent pool has a working foundation to build on.

**Architecture:** FastAPI serves as the central REST + WebSocket bridge. LiteLLM proxies all LLM calls to either the Claude API or the existing llama.cpp server at :10000, routing by per-project config. ChromaDB and n8n run in Docker. Chainlit provides the HITL chat shell. SQLite (one file per project) holds structured state.

**Tech Stack:** Python 3.11+, FastAPI, LiteLLM, ChromaDB, sentence-transformers, Chainlit, n8n (Docker), pytest, httpx

---

## File Map

```
/Users/pboagents/Documents/agentpool1/
  .env.example                        # Environment variable template
  requirements.txt                    # All Python dependencies
  docker-compose.yml                  # n8n + ChromaDB containers
  litellm_config.yaml                 # LiteLLM routing rules

  api/
    __init__.py
    main.py                           # FastAPI app + lifespan
    config.py                         # Settings loader (env + project YAML)
    database.py                       # SQLite setup, schema, connection helper
    models.py                         # Pydantic request/response models
    routers/
      __init__.py
      projects.py                     # POST /projects, GET /projects/{id}/status
      run.py                          # POST /projects/{id}/run
      outputs.py                      # GET /projects/{id}/outputs
      ws.py                           # WS /ws/{id}
    services/
      __init__.py
      project_service.py              # Business logic: create project, init DB + Chroma

  chainlit_app/
    app.py                            # Chainlit shell — placeholder HITL entry point
    chainlit.md                       # Welcome message shown in UI

  projects/
    example/
      config.yaml                     # Example per-client config

  tests/
    conftest.py                       # Shared fixtures (test DB, test client)
    test_database.py                  # Schema creation + CRUD
    test_config.py                    # Config loader
    test_projects_api.py              # POST /projects, GET /status
    test_run_api.py                   # POST /projects/{id}/run
    test_outputs_api.py               # GET /projects/{id}/outputs
    test_litellm_routing.py           # LiteLLM routing logic (mocked)
    test_project_service.py           # Project creation + Chroma init
```

---

## Task 1: Project Scaffold

**Files:**
- Create: `requirements.txt`
- Create: `.env.example`
- Create: `api/__init__.py`
- Create: `api/routers/__init__.py`
- Create: `api/services/__init__.py`
- Create: `chainlit_app/__init__.py` _(empty)_
- Create: `tests/__init__.py` _(empty)_
- Create: `tests/conftest.py`

- [ ] **Step 1: Create the directory structure**

```bash
cd /Users/pboagents/Documents/agentpool1
mkdir -p api/routers api/services chainlit_app tests projects/example
touch api/__init__.py api/routers/__init__.py api/services/__init__.py
touch chainlit_app/__init__.py tests/__init__.py
```

- [ ] **Step 2: Write requirements.txt**

```
# /Users/pboagents/Documents/agentpool1/requirements.txt
fastapi==0.115.5
uvicorn[standard]==0.32.1
httpx==0.28.1
pydantic==2.10.3
pydantic-settings==2.7.0
python-dotenv==1.0.1
pyyaml==6.0.2
aiosqlite==0.20.0
chromadb==0.5.23
sentence-transformers==3.3.1
litellm==1.56.0
chainlit==2.0.0
pytest==8.3.4
pytest-asyncio==0.24.0
anyio==4.7.0
```

- [ ] **Step 3: Write .env.example**

```
# /Users/pboagents/Documents/agentpool1/.env.example
ANTHROPIC_API_KEY=sk-ant-...
LITELLM_PROXY_URL=http://localhost:4000
LLAMACPP_BASE_URL=http://localhost:10000
CHROMA_HOST=localhost
CHROMA_PORT=8002
DATABASE_DIR=/Users/pboagents/Documents/agentpool1/data
PROJECTS_DIR=/Users/pboagents/Documents/agentpool1/projects
JWT_SECRET=change-me-in-production
```

Copy to `.env` and fill in your Anthropic API key:
```bash
cp .env.example .env
```

- [ ] **Step 4: Write tests/conftest.py**

```python
# tests/conftest.py
import os
import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from pathlib import Path

# Point to a temp directory so tests never touch real project data
os.environ.setdefault("DATABASE_DIR", "/tmp/agentpool_test")
os.environ.setdefault("PROJECTS_DIR", "/tmp/agentpool_test_projects")
os.environ.setdefault("JWT_SECRET", "test-secret")
os.environ.setdefault("ANTHROPIC_API_KEY", "test-key")
os.environ.setdefault("LITELLM_PROXY_URL", "http://localhost:4000")
os.environ.setdefault("LLAMACPP_BASE_URL", "http://localhost:10000")
os.environ.setdefault("CHROMA_HOST", "localhost")
os.environ.setdefault("CHROMA_PORT", "8002")  # pydantic coerces str→int

Path("/tmp/agentpool_test").mkdir(exist_ok=True)
Path("/tmp/agentpool_test_projects").mkdir(exist_ok=True)


@pytest_asyncio.fixture
async def client():
    from api.main import app
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac
```

- [ ] **Step 5: Install dependencies**

```bash
cd /Users/pboagents/Documents/agentpool1
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Expected: all packages install without error. `sentence-transformers` will download a model on first use.

- [ ] **Step 6: Verify pytest runs (empty suite)**

```bash
pytest tests/ -v
```

Expected: `no tests ran`, exit 0.

- [ ] **Step 7: Commit**

```bash
git add requirements.txt .env.example api/ chainlit_app/ tests/ projects/
git commit -m "feat(sp1): project scaffold — deps, dirs, test fixtures"
```

---

## Task 2: Config Loader

**Files:**
- Create: `api/config.py`
- Create: `tests/test_config.py`
- Create: `projects/example/config.yaml`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_config.py
import pytest
from pathlib import Path


def test_settings_loads_from_env(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_DIR", str(tmp_path))
    monkeypatch.setenv("PROJECTS_DIR", str(tmp_path))
    monkeypatch.setenv("JWT_SECRET", "s3cr3t")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    monkeypatch.setenv("LITELLM_PROXY_URL", "http://localhost:4000")
    monkeypatch.setenv("LLAMACPP_BASE_URL", "http://localhost:10000")
    monkeypatch.setenv("CHROMA_HOST", "localhost")
    monkeypatch.setenv("CHROMA_PORT", "8002")

    # Re-import to pick up monkeypatched env
    import importlib
    import api.config as cfg_module
    importlib.reload(cfg_module)

    assert cfg_module.settings.jwt_secret == "s3cr3t"
    assert cfg_module.settings.anthropic_api_key == "sk-test"


def test_load_project_config(tmp_path):
    from api.config import load_project_config

    cfg_file = tmp_path / "config.yaml"
    cfg_file.write_text("""
client_slug: test-co
llm_mode: standard
sector: finance
stakeholder_groups: [Finance, Operations]
value_stream_labels: [Revenue, Cost]
roadmap_time_axis: quarters
crews_enabled: [discovery, value_design]
review_gates: true
slack_channel: "#test"
""")
    config = load_project_config(tmp_path)
    assert config["client_slug"] == "test-co"
    assert config["llm_mode"] == "standard"
    assert "discovery" in config["crews_enabled"]


def test_load_project_config_missing_raises(tmp_path):
    from api.config import load_project_config
    with pytest.raises(FileNotFoundError):
        load_project_config(tmp_path / "nonexistent")
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/test_config.py -v
```

Expected: `ImportError` — `api.config` does not exist yet.

- [ ] **Step 3: Write api/config.py**

```python
# api/config.py
from pathlib import Path
from pydantic_settings import BaseSettings
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

    class Config:
        env_file = ".env"


settings = Settings()


def load_project_config(project_dir: Path) -> dict:
    config_path = Path(project_dir) / "config.yaml"
    if not config_path.exists():
        raise FileNotFoundError(f"No config.yaml found in {project_dir}")
    with open(config_path) as f:
        return yaml.safe_load(f)
```

- [ ] **Step 4: Write projects/example/config.yaml**

```yaml
# projects/example/config.yaml
client_slug: "example"
llm_mode: "standard"           # standard | sensitive | fallback
sector: "transport"
stakeholder_groups:
  - "Operations"
  - "Customer"
  - "Finance"
  - "Technology"
value_stream_labels:
  - "Asset Management"
  - "Passenger Experience"
  - "Corporate"
roadmap_time_axis: "quarters"  # quarters | years | horizons
crews_enabled:
  - discovery
  - value_design
  - architecture
  - delivery
review_gates: true
slack_channel: "#example-agents"
```

- [ ] **Step 5: Run tests to verify they pass**

```bash
pytest tests/test_config.py -v
```

Expected: 3 passed.

- [ ] **Step 6: Commit**

```bash
git add api/config.py tests/test_config.py projects/
git commit -m "feat(sp1): config loader — settings from env, project YAML loader"
```

---

## Task 3: SQLite Database Schema

**Files:**
- Create: `api/database.py`
- Create: `tests/test_database.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_database.py
import pytest
import pytest_asyncio
import aiosqlite
from pathlib import Path


@pytest_asyncio.fixture
async def db(tmp_path):
    from api.database import init_db, get_db_path
    db_path = tmp_path / "test.db"
    async with aiosqlite.connect(db_path) as conn:
        await init_db(conn)
        yield conn


@pytest.mark.asyncio
async def test_init_db_creates_tables(db):
    async with db.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    ) as cursor:
        tables = {row[0] async for row in cursor}
    assert {"projects", "crew_runs", "agent_outputs", "human_reviews", "users"}.issubset(tables)


@pytest.mark.asyncio
async def test_insert_and_fetch_project(db):
    from api.database import insert_project, fetch_project
    await insert_project(db, slug="acme", llm_mode="standard", sector="rail", config_json='{}')
    project = await fetch_project(db, slug="acme")
    assert project["slug"] == "acme"
    assert project["llm_mode"] == "standard"
    assert project["status"] == "created"


@pytest.mark.asyncio
async def test_insert_crew_run(db):
    from api.database import insert_project, insert_crew_run, fetch_crew_runs
    await insert_project(db, slug="acme", llm_mode="standard", sector="rail", config_json='{}')
    project = await fetch_project(db, slug="acme")
    await insert_crew_run(db, project_id=project["id"], crew_name="discovery", status="running")
    runs = await fetch_crew_runs(db, project_id=project["id"])
    assert len(runs) == 1
    assert runs[0]["crew_name"] == "discovery"
    assert runs[0]["status"] == "running"


@pytest.mark.asyncio
async def test_insert_agent_output(db):
    from api.database import insert_project, insert_agent_output, fetch_agent_outputs
    await insert_project(db, slug="acme", llm_mode="standard", sector="rail", config_json='{}')
    project = await fetch_project(db, slug="acme")
    await insert_agent_output(
        db, project_id=project["id"],
        agent_name="value_chain_mapper",
        output_type="value_chain",
        file_path="/tmp/vc.json",
        version=1,
    )
    outputs = await fetch_agent_outputs(db, project_id=project["id"])
    assert outputs[0]["agent_name"] == "value_chain_mapper"
    assert outputs[0]["version"] == 1
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_database.py -v
```

Expected: `ImportError` — `api.database` does not exist.

- [ ] **Step 3: Write api/database.py**

```python
# api/database.py
import aiosqlite
from pathlib import Path
from api.config import settings


def get_db_path(slug: str) -> Path:
    return Path(settings.database_dir) / f"{slug}.db"


async def init_db(conn: aiosqlite.Connection) -> None:
    await conn.executescript("""
        CREATE TABLE IF NOT EXISTS projects (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            slug        TEXT UNIQUE NOT NULL,
            llm_mode    TEXT NOT NULL DEFAULT 'standard',
            sector      TEXT,
            config_json TEXT,
            status      TEXT NOT NULL DEFAULT 'created',
            created_at  DATETIME DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS crew_runs (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            project_id  INTEGER NOT NULL REFERENCES projects(id),
            crew_name   TEXT NOT NULL,
            status      TEXT NOT NULL DEFAULT 'pending',
            result_json TEXT,
            started_at  DATETIME,
            finished_at DATETIME,
            created_at  DATETIME DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS agent_outputs (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            project_id  INTEGER NOT NULL REFERENCES projects(id),
            agent_name  TEXT NOT NULL,
            output_type TEXT NOT NULL,
            file_path   TEXT NOT NULL,
            version     INTEGER NOT NULL DEFAULT 1,
            review_status TEXT NOT NULL DEFAULT 'pending',
            created_at  DATETIME DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS human_reviews (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            output_id   INTEGER NOT NULL REFERENCES agent_outputs(id),
            reviewer    TEXT,
            decision    TEXT NOT NULL,
            notes       TEXT,
            reviewed_at DATETIME DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS users (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            username    TEXT UNIQUE NOT NULL,
            role        TEXT NOT NULL DEFAULT 'consultant',
            hashed_pw   TEXT NOT NULL,
            project_slug TEXT,
            created_at  DATETIME DEFAULT CURRENT_TIMESTAMP
        );
    """)
    await conn.commit()


async def get_connection(slug: str) -> aiosqlite.Connection:
    path = get_db_path(slug)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = await aiosqlite.connect(path)
    conn.row_factory = aiosqlite.Row
    await init_db(conn)
    return conn


async def insert_project(conn, *, slug: str, llm_mode: str, sector: str, config_json: str) -> None:
    await conn.execute(
        "INSERT OR IGNORE INTO projects (slug, llm_mode, sector, config_json) VALUES (?,?,?,?)",
        (slug, llm_mode, sector, config_json),
    )
    await conn.commit()


async def fetch_project(conn, *, slug: str) -> dict | None:
    async with conn.execute("SELECT * FROM projects WHERE slug=?", (slug,)) as cur:
        row = await cur.fetchone()
        return dict(row) if row else None


async def insert_crew_run(conn, *, project_id: int, crew_name: str, status: str) -> int:
    cur = await conn.execute(
        "INSERT INTO crew_runs (project_id, crew_name, status, started_at) VALUES (?,?,?, CURRENT_TIMESTAMP)",
        (project_id, crew_name, status),
    )
    await conn.commit()
    return cur.lastrowid


async def fetch_crew_runs(conn, *, project_id: int) -> list[dict]:
    async with conn.execute(
        "SELECT * FROM crew_runs WHERE project_id=? ORDER BY created_at DESC", (project_id,)
    ) as cur:
        return [dict(r) async for r in cur]


async def insert_agent_output(conn, *, project_id: int, agent_name: str,
                               output_type: str, file_path: str, version: int) -> int:
    cur = await conn.execute(
        "INSERT INTO agent_outputs (project_id, agent_name, output_type, file_path, version) VALUES (?,?,?,?,?)",
        (project_id, agent_name, output_type, file_path, version),
    )
    await conn.commit()
    return cur.lastrowid


async def fetch_agent_outputs(conn, *, project_id: int) -> list[dict]:
    async with conn.execute(
        "SELECT * FROM agent_outputs WHERE project_id=? ORDER BY created_at DESC", (project_id,)
    ) as cur:
        return [dict(r) async for r in cur]
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_database.py -v
```

Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add api/database.py tests/test_database.py
git commit -m "feat(sp1): SQLite schema — projects, crew_runs, agent_outputs, reviews, users"
```

---

## Task 4: Pydantic Models

**Files:**
- Create: `api/models.py`

No separate test file — models are validated through API tests in later tasks.

- [ ] **Step 1: Write api/models.py**

```python
# api/models.py
from pydantic import BaseModel
from typing import Literal


class ProjectCreate(BaseModel):
    client_slug: str
    llm_mode: Literal["standard", "sensitive", "fallback"] = "standard"
    sector: str
    stakeholder_groups: list[str]
    value_stream_labels: list[str]
    roadmap_time_axis: Literal["quarters", "years", "horizons"] = "quarters"
    crews_enabled: list[str]
    review_gates: bool = True
    slack_channel: str = ""


class ProjectResponse(BaseModel):
    id: int
    slug: str
    llm_mode: str
    sector: str
    status: str


class RunRequest(BaseModel):
    crew: str | None = None  # None = trigger PAM (full run)


class RunResponse(BaseModel):
    run_id: int
    project_slug: str
    crew: str
    status: str


class OutputResponse(BaseModel):
    id: int
    agent_name: str
    output_type: str
    file_path: str
    version: int
    review_status: str


class StatusResponse(BaseModel):
    project_slug: str
    project_status: str
    crew_runs: list[dict]
```

- [ ] **Step 2: Commit**

```bash
git add api/models.py
git commit -m "feat(sp1): Pydantic request/response models"
```

---

## Task 5: Project Service

**Files:**
- Create: `api/services/project_service.py`
- Create: `tests/test_project_service.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_project_service.py
import pytest
import json
from pathlib import Path


@pytest.mark.asyncio
async def test_create_project_creates_db_and_dirs(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("PROJECTS_DIR", str(tmp_path / "projects"))

    import importlib
    import api.config as cfg
    importlib.reload(cfg)
    import api.services.project_service as svc
    importlib.reload(svc)

    from api.models import ProjectCreate
    req = ProjectCreate(
        client_slug="test-co",
        llm_mode="standard",
        sector="finance",
        stakeholder_groups=["Finance", "Ops"],
        value_stream_labels=["Revenue"],
        crews_enabled=["discovery"],
    )
    result = await svc.create_project(req)
    assert result["slug"] == "test-co"
    assert (tmp_path / "data" / "test-co.db").exists()
    assert (tmp_path / "projects" / "test-co" / "config.yaml").exists()
    assert (tmp_path / "projects" / "test-co" / "docs").is_dir()
    assert (tmp_path / "projects" / "test-co" / "outputs").is_dir()


@pytest.mark.asyncio
async def test_create_project_idempotent(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("PROJECTS_DIR", str(tmp_path / "projects"))

    import importlib
    import api.config as cfg
    importlib.reload(cfg)
    import api.services.project_service as svc
    importlib.reload(svc)

    from api.models import ProjectCreate
    req = ProjectCreate(
        client_slug="test-co",
        llm_mode="standard",
        sector="finance",
        stakeholder_groups=["Finance"],
        value_stream_labels=["Revenue"],
        crews_enabled=["discovery"],
    )
    r1 = await svc.create_project(req)
    r2 = await svc.create_project(req)
    assert r1["id"] == r2["id"]
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_project_service.py -v
```

Expected: `ImportError`.

- [ ] **Step 3: Write api/services/project_service.py**

```python
# api/services/project_service.py
import json
import yaml
from pathlib import Path
from api.config import settings, load_project_config
from api.database import get_connection, insert_project, fetch_project
from api.models import ProjectCreate


async def create_project(req: ProjectCreate) -> dict:
    slug = req.client_slug

    # Create project directory structure
    project_dir = Path(settings.projects_dir) / slug
    (project_dir / "docs").mkdir(parents=True, exist_ok=True)
    (project_dir / "outputs").mkdir(parents=True, exist_ok=True)

    # Write config.yaml
    config = req.model_dump()
    config_path = project_dir / "config.yaml"
    if not config_path.exists():
        with open(config_path, "w") as f:
            yaml.dump(config, f, default_flow_style=False)

    # Initialise SQLite DB
    conn = await get_connection(slug)
    try:
        await insert_project(
            conn,
            slug=slug,
            llm_mode=req.llm_mode,
            sector=req.sector,
            config_json=json.dumps(config),
        )
        return await fetch_project(conn, slug=slug)
    finally:
        await conn.close()


async def get_project_status(slug: str) -> dict | None:
    from api.database import fetch_crew_runs
    conn = await get_connection(slug)
    try:
        project = await fetch_project(conn, slug=slug)
        if not project:
            return None
        runs = await fetch_crew_runs(conn, project_id=project["id"])
        return {"project_slug": slug, "project_status": project["status"], "crew_runs": runs}
    finally:
        await conn.close()


async def get_project_outputs(slug: str) -> list[dict]:
    from api.database import fetch_agent_outputs
    conn = await get_connection(slug)
    try:
        project = await fetch_project(conn, slug=slug)
        if not project:
            return []
        return await fetch_agent_outputs(conn, project_id=project["id"])
    finally:
        await conn.close()
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_project_service.py -v
```

Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add api/services/project_service.py tests/test_project_service.py
git commit -m "feat(sp1): project service — create project, init DB + dirs"
```

---

## Task 6: FastAPI App + Projects Router

**Files:**
- Create: `api/main.py`
- Create: `api/routers/projects.py`
- Create: `tests/test_projects_api.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_projects_api.py
import pytest

PROJECT_PAYLOAD = {
    "client_slug": "test-rail",
    "llm_mode": "standard",
    "sector": "transport",
    "stakeholder_groups": ["Operations", "Customer"],
    "value_stream_labels": ["Asset Mgmt"],
    "roadmap_time_axis": "quarters",
    "crews_enabled": ["discovery"],
    "review_gates": True,
    "slack_channel": "#test",
}


@pytest.mark.asyncio
async def test_create_project_returns_201(client):
    resp = await client.post("/projects", json=PROJECT_PAYLOAD)
    assert resp.status_code == 201
    data = resp.json()
    assert data["slug"] == "test-rail"
    assert data["status"] == "created"


@pytest.mark.asyncio
async def test_create_project_idempotent(client):
    await client.post("/projects", json=PROJECT_PAYLOAD)
    resp = await client.post("/projects", json=PROJECT_PAYLOAD)
    assert resp.status_code == 200  # already exists → 200


@pytest.mark.asyncio
async def test_get_project_status(client):
    await client.post("/projects", json=PROJECT_PAYLOAD)
    resp = await client.get("/projects/test-rail/status")
    assert resp.status_code == 200
    data = resp.json()
    assert data["project_slug"] == "test-rail"
    assert "crew_runs" in data


@pytest.mark.asyncio
async def test_get_status_unknown_project_returns_404(client):
    resp = await client.get("/projects/does-not-exist/status")
    assert resp.status_code == 404
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_projects_api.py -v
```

Expected: `ImportError` — `api.main` not found.

- [ ] **Step 3: Write api/routers/projects.py**

```python
# api/routers/projects.py
from fastapi import APIRouter, HTTPException, Response
from api.models import ProjectCreate, ProjectResponse, StatusResponse
from api.services.project_service import create_project, get_project_status

router = APIRouter(prefix="/projects", tags=["projects"])


@router.post("", status_code=201)
async def create_project_endpoint(req: ProjectCreate, response: Response):
    existing = await get_project_status(req.client_slug)
    if existing:
        response.status_code = 200
        return existing
    return await create_project(req)


@router.get("/{slug}/status", response_model=StatusResponse)
async def get_status(slug: str):
    result = await get_project_status(slug)
    if not result:
        raise HTTPException(status_code=404, detail=f"Project '{slug}' not found")
    return result
```

- [ ] **Step 4: Write api/main.py**

```python
# api/main.py
from fastapi import FastAPI
from contextlib import asynccontextmanager
from pathlib import Path
from api.config import settings


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Ensure data directory exists at startup
    Path(settings.database_dir).mkdir(parents=True, exist_ok=True)
    Path(settings.projects_dir).mkdir(parents=True, exist_ok=True)
    yield


app = FastAPI(title="AgentPool API", version="0.1.0", lifespan=lifespan)

from api.routers import projects, run, outputs, ws  # noqa: E402
app.include_router(projects.router)
app.include_router(run.router)
app.include_router(outputs.router)
app.include_router(ws.router)
```

- [ ] **Step 5: Write stub routers for run, outputs, ws (needed for import)**

```python
# api/routers/run.py
from fastapi import APIRouter
router = APIRouter()
```

```python
# api/routers/outputs.py
from fastapi import APIRouter
router = APIRouter()
```

```python
# api/routers/ws.py
from fastapi import APIRouter
router = APIRouter()
```

- [ ] **Step 6: Run tests to verify they pass**

```bash
pytest tests/test_projects_api.py -v
```

Expected: 4 passed.

- [ ] **Step 7: Commit**

```bash
git add api/main.py api/routers/ tests/test_projects_api.py
git commit -m "feat(sp1): FastAPI app + /projects endpoints (create, status)"
```

---

## Task 7: Run & Outputs Routers

**Files:**
- Modify: `api/routers/run.py`
- Modify: `api/routers/outputs.py`
- Create: `tests/test_run_api.py`
- Create: `tests/test_outputs_api.py`

- [ ] **Step 1: Write failing tests for run endpoint**

```python
# tests/test_run_api.py
import pytest

PROJECT_PAYLOAD = {
    "client_slug": "run-test",
    "llm_mode": "standard",
    "sector": "transport",
    "stakeholder_groups": ["Operations"],
    "value_stream_labels": ["Asset Mgmt"],
    "crews_enabled": ["discovery"],
    "review_gates": True,
    "slack_channel": "",
}


@pytest.mark.asyncio
async def test_run_unknown_project_returns_404(client):
    resp = await client.post("/projects/ghost/run", json={})
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_run_known_project_queues_run(client):
    await client.post("/projects", json=PROJECT_PAYLOAD)
    resp = await client.post("/projects/run-test/run", json={"crew": "discovery"})
    assert resp.status_code == 202
    data = resp.json()
    assert data["project_slug"] == "run-test"
    assert data["crew"] == "discovery"
    assert data["status"] == "queued"
```

- [ ] **Step 2: Write failing tests for outputs endpoint**

```python
# tests/test_outputs_api.py
import pytest

PROJECT_PAYLOAD = {
    "client_slug": "out-test",
    "llm_mode": "standard",
    "sector": "transport",
    "stakeholder_groups": ["Operations"],
    "value_stream_labels": ["Asset Mgmt"],
    "crews_enabled": ["discovery"],
    "review_gates": True,
    "slack_channel": "",
}


@pytest.mark.asyncio
async def test_outputs_empty_for_new_project(client):
    await client.post("/projects", json=PROJECT_PAYLOAD)
    resp = await client.get("/projects/out-test/outputs")
    assert resp.status_code == 200
    assert resp.json() == []


@pytest.mark.asyncio
async def test_outputs_unknown_project_returns_404(client):
    resp = await client.get("/projects/ghost/outputs")
    assert resp.status_code == 404
```

- [ ] **Step 3: Run tests to verify they fail**

```bash
pytest tests/test_run_api.py tests/test_outputs_api.py -v
```

Expected: all fail with 404 or 422 (stub routers).

- [ ] **Step 4: Implement api/routers/run.py**

```python
# api/routers/run.py
from fastapi import APIRouter, HTTPException
from api.models import RunRequest, RunResponse
from api.services.project_service import get_project_status
from api.database import get_connection, fetch_project, insert_crew_run

router = APIRouter(prefix="/projects", tags=["run"])


@router.post("/{slug}/run", status_code=202, response_model=RunResponse)
async def run_crew(slug: str, req: RunRequest):
    status = await get_project_status(slug)
    if not status:
        raise HTTPException(status_code=404, detail=f"Project '{slug}' not found")

    crew = req.crew or "pam"
    conn = await get_connection(slug)
    try:
        project = await fetch_project(conn, slug=slug)
        run_id = await insert_crew_run(conn, project_id=project["id"], crew_name=crew, status="queued")
    finally:
        await conn.close()

    return RunResponse(run_id=run_id, project_slug=slug, crew=crew, status="queued")
```

- [ ] **Step 5: Implement api/routers/outputs.py**

```python
# api/routers/outputs.py
from fastapi import APIRouter, HTTPException
from api.models import OutputResponse
from api.services.project_service import get_project_outputs, get_project_status

router = APIRouter(prefix="/projects", tags=["outputs"])


@router.get("/{slug}/outputs", response_model=list[OutputResponse])
async def list_outputs(slug: str):
    status = await get_project_status(slug)
    if not status:
        raise HTTPException(status_code=404, detail=f"Project '{slug}' not found")
    return await get_project_outputs(slug)
```

- [ ] **Step 6: Run tests to verify they pass**

```bash
pytest tests/test_run_api.py tests/test_outputs_api.py -v
```

Expected: 4 passed.

- [ ] **Step 7: Commit**

```bash
git add api/routers/run.py api/routers/outputs.py tests/test_run_api.py tests/test_outputs_api.py
git commit -m "feat(sp1): /run and /outputs endpoints"
```

---

## Task 8: WebSocket Live Log Endpoint

**Files:**
- Modify: `api/routers/ws.py`

No async WebSocket unit test — verified manually in Task 12.

- [ ] **Step 1: Implement api/routers/ws.py**

```python
# api/routers/ws.py
import asyncio
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from api.services.project_service import get_project_status

router = APIRouter(tags=["websocket"])

# In-memory log queues per project slug — agents push log lines here
_log_queues: dict[str, asyncio.Queue] = {}


def get_log_queue(slug: str) -> asyncio.Queue:
    if slug not in _log_queues:
        _log_queues[slug] = asyncio.Queue()
    return _log_queues[slug]


async def push_log(slug: str, message: str) -> None:
    """Called by agents to push a log line to connected WebSocket clients."""
    q = get_log_queue(slug)
    await q.put(message)


@router.websocket("/ws/{slug}")
async def websocket_log_stream(websocket: WebSocket, slug: str):
    status = await get_project_status(slug)
    if not status:
        await websocket.close(code=4004)
        return

    await websocket.accept()
    q = get_log_queue(slug)
    try:
        while True:
            try:
                msg = await asyncio.wait_for(q.get(), timeout=30.0)
                await websocket.send_text(msg)
            except asyncio.TimeoutError:
                await websocket.send_text("ping")
    except WebSocketDisconnect:
        pass
```

- [ ] **Step 2: Run full test suite to confirm nothing broken**

```bash
pytest tests/ -v
```

Expected: all previous tests still pass.

- [ ] **Step 3: Commit**

```bash
git add api/routers/ws.py
git commit -m "feat(sp1): WebSocket /ws/{slug} — live log stream for agents"
```

---

## Task 9: LiteLLM Config + Routing Smoke Test

**Files:**
- Create: `litellm_config.yaml`
- Create: `tests/test_litellm_routing.py`

- [ ] **Step 1: Write failing test**

```python
# tests/test_litellm_routing.py
"""
Tests that LiteLLM config resolves the correct model for each llm_mode.
Does NOT call external APIs — uses litellm's model routing logic only.
"""
import pytest
import yaml
from pathlib import Path


def load_litellm_config() -> dict:
    path = Path(__file__).parent.parent / "litellm_config.yaml"
    with open(path) as f:
        return yaml.safe_load(f)


def test_config_has_required_model_aliases():
    config = load_litellm_config()
    model_names = [m["model_name"] for m in config["model_list"]]
    assert "claude-opus" in model_names
    assert "claude-sonnet" in model_names
    assert "claude-haiku" in model_names
    assert "local-qwen3" in model_names


def test_sensitive_alias_points_to_llamacpp():
    config = load_litellm_config()
    local_model = next(m for m in config["model_list"] if m["model_name"] == "local-qwen3")
    assert "openai/" in local_model["litellm_params"]["model"] or \
           "localhost:10000" in str(local_model["litellm_params"].get("api_base", ""))
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/test_litellm_routing.py -v
```

Expected: `FileNotFoundError` — config doesn't exist.

- [ ] **Step 3: Write litellm_config.yaml**

```yaml
# litellm_config.yaml
model_list:
  - model_name: claude-opus
    litellm_params:
      model: claude/claude-opus-4-6
      api_key: os.environ/ANTHROPIC_API_KEY

  - model_name: claude-sonnet
    litellm_params:
      model: claude/claude-sonnet-4-6
      api_key: os.environ/ANTHROPIC_API_KEY

  - model_name: claude-haiku
    litellm_params:
      model: claude/claude-haiku-4-5-20251001
      api_key: os.environ/ANTHROPIC_API_KEY

  - model_name: local-qwen3
    litellm_params:
      model: openai/qwen3-4b
      api_base: http://localhost:10000
      api_key: "none"

litellm_settings:
  drop_params: true
  num_retries: 2
  request_timeout: 120

router_settings:
  routing_strategy: simple-shuffle
  fallbacks:
    - claude-opus:
        - local-qwen3
    - claude-sonnet:
        - local-qwen3
```

- [ ] **Step 4: Run test to verify it passes**

```bash
pytest tests/test_litellm_routing.py -v
```

Expected: 2 passed.

- [ ] **Step 5: Start LiteLLM proxy and verify it responds**

```bash
source .venv/bin/activate
litellm --config litellm_config.yaml --port 4000 &
sleep 3
curl http://localhost:4000/health
```

Expected: `{"status": "healthy", ...}`

Stop the background process after testing:
```bash
pkill -f "litellm --config"
```

- [ ] **Step 6: Commit**

```bash
git add litellm_config.yaml tests/test_litellm_routing.py
git commit -m "feat(sp1): LiteLLM config — Claude API + llama.cpp routing"
```

---

## Task 10: Docker Compose (n8n + ChromaDB)

**Files:**
- Create: `docker-compose.yml`

- [ ] **Step 1: Write docker-compose.yml**

```yaml
# docker-compose.yml
services:
  chromadb:
    image: chromadb/chroma:0.5.23
    ports:
      - "8002:8000"
    volumes:
      - ./data/chroma:/chroma/chroma
    environment:
      - IS_PERSISTENT=TRUE
      - ANONYMIZED_TELEMETRY=FALSE
    restart: unless-stopped

  n8n:
    image: n8nio/n8n:1.70.3
    ports:
      - "5678:5678"
    volumes:
      - ./data/n8n:/home/node/.n8n
      - ./workflows:/home/node/.n8n/backup
    environment:
      - N8N_BASIC_AUTH_ACTIVE=true
      - N8N_BASIC_AUTH_USER=admin
      - N8N_BASIC_AUTH_PASSWORD=changeme
      - N8N_HOST=localhost
      - N8N_PORT=5678
      - N8N_PROTOCOL=http
      - WEBHOOK_URL=http://localhost:5678
    restart: unless-stopped
```

- [ ] **Step 2: Create data directories and start containers**

```bash
mkdir -p data/chroma data/n8n workflows
docker compose up -d
```

Expected output: both containers start. Verify:
```bash
docker compose ps
```
Both `chromadb` and `n8n` should show `running`.

- [ ] **Step 3: Verify ChromaDB responds**

```bash
curl http://localhost:8002/api/v1/heartbeat
```

Expected: `{"nanosecond heartbeat": <timestamp>}`

- [ ] **Step 4: Verify n8n responds**

Open http://localhost:5678 in your browser. You should see the n8n login page. Login with `admin` / `changeme`, then change the password in Settings.

- [ ] **Step 5: Commit**

```bash
git add docker-compose.yml
git commit -m "feat(sp1): Docker Compose — ChromaDB :8002 + n8n :5678"
```

---

## Task 11: Chainlit Shell

**Files:**
- Create: `chainlit_app/app.py`
- Create: `chainlit_app/chainlit.md`
- Create: `chainlit_app/.chainlit/config.toml`

- [ ] **Step 1: Write chainlit_app/chainlit.md**

```markdown
# AgentPool

Welcome to the AgentPool HITL interface.

This is where you interact with conversational agents:
- **Value Chain Mapper** — iterate value chain stages and activities
- **Requirements Analyst** — stakeholder interviews and questionnaires
- **Portfolio Manager** — define and iterate ranking criteria
- **Roadmap Generator** — guide articulation format and review
- **Business Plan Generator** — provide business context and review sections

Select a project and agent from the session menu to begin.
```

- [ ] **Step 2: Write chainlit_app/app.py**

```python
# chainlit_app/app.py
"""
Chainlit shell — HITL entry point for conversational agents.
In SP3, individual agent handlers will be registered here.
For now this shell confirms Chainlit is wired to the FastAPI backend.
"""
import chainlit as cl
import httpx

FASTAPI_BASE = "http://localhost:8000"


@cl.on_chat_start
async def start():
    await cl.Message(
        content="AgentPool ready. Which project would you like to work on? "
                "Type the project slug (e.g. `acme-rail`) to begin."
    ).send()
    cl.user_session.set("project_slug", None)


@cl.on_message
async def handle_message(msg: cl.Message):
    slug = cl.user_session.get("project_slug")

    if slug is None:
        # Treat first message as project slug
        candidate = msg.content.strip().lower()
        async with httpx.AsyncClient() as client:
            resp = await client.get(f"{FASTAPI_BASE}/projects/{candidate}/status")
        if resp.status_code == 200:
            cl.user_session.set("project_slug", candidate)
            await cl.Message(
                content=f"Project **{candidate}** loaded. Which agent would you like to start? "
                        "(value_chain_mapper / requirements_analyst / portfolio_manager / "
                        "roadmap_generator / business_plan_generator)"
            ).send()
        else:
            await cl.Message(
                content=f"Project `{candidate}` not found. "
                        "Create it first via the web platform or API, then try again."
            ).send()
        return

    # Placeholder — agent routing added in SP3
    await cl.Message(
        content=f"[{slug}] Agent routing will be wired in SP3. "
                f"Your message: _{msg.content}_"
    ).send()
```

- [ ] **Step 3: Create .chainlit/config.toml**

```bash
mkdir -p chainlit_app/.chainlit
```

```toml
# chainlit_app/.chainlit/config.toml
[project]
enable_telemetry = false

[UI]
name = "AgentPool"
show_readme_as_default = true
default_collapse_content = true

[features]
multi_modal = true
```

- [ ] **Step 4: Start Chainlit and verify it loads**

```bash
cd chainlit_app
chainlit run app.py --port 8001
```

Open http://localhost:8001. You should see the AgentPool welcome message. Stop with Ctrl+C.

- [ ] **Step 5: Commit**

```bash
git add chainlit_app/
git commit -m "feat(sp1): Chainlit shell — HITL entry point, project slug routing"
```

---

## Task 12: Launch Scripts + End-to-End Smoke Test

**Files:**
- Create: `start.sh` — starts all services
- Create: `stop.sh` — stops all services

- [ ] **Step 1: Write start.sh**

```bash
#!/usr/bin/env bash
# start.sh — start all AgentPool services
set -e
cd "$(dirname "$0")"
source .venv/bin/activate

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

echo ""
echo "AgentPool services running:"
echo "  FastAPI:   http://localhost:8000/docs"
echo "  Chainlit:  http://localhost:8001"
echo "  n8n:       http://localhost:5678"
echo "  ChromaDB:  http://localhost:8002"
echo "  LiteLLM:   http://localhost:4000"
echo "  llama.cpp: http://localhost:10000 (existing)"
```

- [ ] **Step 2: Write stop.sh**

```bash
#!/usr/bin/env bash
# stop.sh — stop all AgentPool services
set -e
cd "$(dirname "$0")"

for pid_file in .pids/*.pid; do
  [ -f "$pid_file" ] && kill "$(cat "$pid_file")" 2>/dev/null && rm "$pid_file"
done

docker compose stop
echo "All AgentPool services stopped."
```

- [ ] **Step 3: Make scripts executable and create pid dir**

```bash
chmod +x start.sh stop.sh
mkdir -p .pids
echo ".pids/" >> .gitignore
```

- [ ] **Step 4: Run the full test suite one final time**

```bash
pytest tests/ -v
```

Expected: all tests pass.

- [ ] **Step 5: Manual smoke test**

```bash
./start.sh
sleep 5

# Create a test project
curl -s -X POST http://localhost:8000/projects \
  -H "Content-Type: application/json" \
  -d '{
    "client_slug": "smoke-test",
    "llm_mode": "standard",
    "sector": "transport",
    "stakeholder_groups": ["Operations"],
    "value_stream_labels": ["Asset Mgmt"],
    "crews_enabled": ["discovery"],
    "review_gates": true,
    "slack_channel": ""
  }' | python3 -m json.tool

# Check status
curl -s http://localhost:8000/projects/smoke-test/status | python3 -m json.tool

# Queue a run
curl -s -X POST http://localhost:8000/projects/smoke-test/run \
  -H "Content-Type: application/json" \
  -d '{"crew": "discovery"}' | python3 -m json.tool
```

Expected: each command returns valid JSON with correct fields.

- [ ] **Step 6: Stop services**

```bash
./stop.sh
```

- [ ] **Step 7: Final commit**

```bash
git add start.sh stop.sh .gitignore
git commit -m "feat(sp1): launch scripts + smoke test — SP1 infrastructure complete"
```

---

## Appendix: Slack App Setup (Manual — no code)

Complete this before SP4 to have credentials ready for n8n.

1. Go to https://api.slack.com/apps → **Create New App** → **From scratch**
2. Name: `AgentPool Bot`, workspace: your workspace
3. Under **OAuth & Permissions** → **Bot Token Scopes**, add: `chat:write`, `commands`, `channels:read`, `im:write`
4. Click **Install to Workspace** → copy the **Bot User OAuth Token** (`xoxb-...`)
5. Under **Basic Information** → copy **Signing Secret**
6. In n8n (http://localhost:5678): **Credentials** → **New** → **Slack** → paste Bot Token + Signing Secret
7. Add the bot to your notifications channel: `/invite @AgentPool Bot`

---

## Appendix: Configure Git Identity

The commits above will warn about unconfigured identity. Run once:

```bash
git config --global user.name "Patrick Bossert"
git config --global user.email "your@email.com"
```
