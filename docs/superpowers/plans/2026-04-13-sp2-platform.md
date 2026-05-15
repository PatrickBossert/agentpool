# SP2 — Thin Shell Web Platform Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
>
> **Worktree setup:** Before starting, create a worktree from the SP1 branch:
> ```bash
> cd /Users/pboagents/Documents/agentpool1/.worktrees/sp1-infrastructure
> git worktree add ../sp2-platform -b feature/sp2-platform
> cd ../sp2-platform
> source .venv/bin/activate
> ```

**Goal:** Build the React web platform shell with auth, project dashboard, document library, and read-only value chain + roadmap views on top of the SP1 FastAPI backend.

**Architecture:** FastAPI gains 6 new endpoints plus CORS + JWT auth. The React/Vite frontend (`ui/`) calls the API at `http://localhost:8000`, with project-slug-based routing. All views show correct empty states until SP3 agents provide data. A system-level SQLite DB (`system.db`) holds users independently of project DBs.

**Tech Stack:** React 18 + Vite + TypeScript + Tailwind CSS + React Query v5 + React Router v6 + axios / FastAPI + python-jose + passlib + python-multipart / Vitest + React Testing Library

---

## File Map

```
api/
  auth.py                    # JWT utilities + password hashing
  routers/
    auth.py                  # POST /auth/login, POST /auth/users
    documents.py             # GET /projects/{slug}/documents, POST .../upload
    reviews.py               # POST /projects/{slug}/review
  main.py                    # +CORSMiddleware, +auth/documents/reviews routers, +system DB seed

ui/
  index.html
  package.json
  vite.config.ts             # Vite + Vitest config combined
  tailwind.config.js
  postcss.config.js
  tsconfig.json
  tsconfig.node.json
  src/
    main.tsx                 # React entry, QueryClientProvider, RouterProvider
    router.tsx               # Route definitions, ProtectedRoute wrapper
    types.ts                 # All TypeScript interfaces
    api/
      client.ts              # axios instance with Bearer token injection
      endpoints.ts           # All typed API call functions
    context/
      AuthContext.tsx        # JWT state (token, user, login, logout)
    components/
      AppLayout.tsx          # Top nav + sidebar + <Outlet />
      StatusBadge.tsx        # Colour-coded crew status pill
      ReviewQueue.tsx        # List of pending human reviews with approve/reject
    hooks/
      useWebSocket.ts        # WebSocket log stream per project slug
    pages/
      Login.tsx              # Email + password form
      Dashboard.tsx          # Crew progress + review queue + quick links
      Documents.tsx          # File upload + source docs + agent outputs
      ValueChain.tsx         # Entity × stage grid (empty state until SP3)
      Roadmap.tsx            # Visual tab + Gantt tab (structural shell)
    test/
      setup.ts               # @testing-library/jest-dom import
  src/__tests__/
    Login.test.tsx
    Dashboard.test.tsx
    Documents.test.tsx
    ValueChain.test.tsx
    Roadmap.test.tsx
```

---

## Task 1: CORS + GET /projects List + System DB

**Files:**
- Modify: `api/database.py`
- Modify: `api/routers/projects.py`
- Modify: `api/main.py`
- Create: `tests/test_projects_list.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_projects_list.py
import pytest
from api.config import get_settings

PROJECT_A = {
    "client_slug": "list-proj-a",
    "llm_mode": "standard",
    "sector": "transport",
    "stakeholder_groups": ["Operations"],
    "value_stream_labels": ["Asset Mgmt"],
    "crews_enabled": ["discovery"],
    "review_gates": True,
    "slack_channel": "",
}
PROJECT_B = {**PROJECT_A, "client_slug": "list-proj-b"}


@pytest.fixture(autouse=True)
def clean():
    yield
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_list_projects_empty(client):
    resp = await client.get("/projects")
    assert resp.status_code == 200
    assert resp.json() == []


@pytest.mark.asyncio
async def test_list_projects_returns_all(client):
    await client.post("/projects", json=PROJECT_A)
    await client.post("/projects", json=PROJECT_B)
    resp = await client.get("/projects")
    assert resp.status_code == 200
    slugs = [p["slug"] for p in resp.json()]
    assert "list-proj-a" in slugs
    assert "list-proj-b" in slugs
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
source .venv/bin/activate && python -m pytest tests/test_projects_list.py -v
```
Expected: 404 (GET /projects not implemented).

- [ ] **Step 3: Add `list_projects` to `api/database.py`**

Add after `fetch_project`:

```python
async def list_projects(conn: aiosqlite.Connection) -> list[dict]:
    async with conn.execute("SELECT * FROM projects ORDER BY created_at DESC") as cur:
        return [dict(r) async for r in cur]
```

- [ ] **Step 4: Add `list_all_projects` to `api/services/project_service.py`**

Add imports at the top (add `list_projects` to the existing database import block):
```python
from api.database import (
    get_connection,
    get_db_path,
    insert_project,
    fetch_project,
    fetch_crew_runs,
    fetch_agent_outputs,
    list_projects,
)
```

Add function after `get_project_outputs`:

```python
async def list_all_projects() -> list[dict]:
    """Return all projects across all project DBs."""
    settings = get_settings()
    db_dir = Path(settings.database_dir)
    if not db_dir.exists():
        return []
    results = []
    for db_file in sorted(db_dir.glob("*.db")):
        slug = db_file.stem
        if slug == "system":
            continue  # system.db holds users, not projects
        async with get_connection(slug) as conn:
            rows = await list_projects(conn)
            results.extend(rows)
    return results
```

- [ ] **Step 5: Add `GET /projects` to `api/routers/projects.py`**

Add to imports:
```python
from api.services.project_service import create_project, get_project_status, list_all_projects
```

Add before `create_project_endpoint`:

```python
@router.get("", response_model=list[ProjectResponse])
async def list_projects_endpoint():
    return await list_all_projects()
```

- [ ] **Step 6: Add CORS to `api/main.py`**

Replace the current `api/main.py` with:

```python
# api/main.py
from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from api.config import get_settings
from api.routers import projects, run, outputs, ws


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    Path(settings.database_dir).mkdir(parents=True, exist_ok=True)
    Path(settings.projects_dir).mkdir(parents=True, exist_ok=True)
    yield


app = FastAPI(title="AgentPool API", version="0.1.0", lifespan=lifespan, favicon_url=None)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(projects.router)
app.include_router(run.router)
app.include_router(outputs.router)
app.include_router(ws.router)
```

- [ ] **Step 7: Add `ProjectResponse` to `api/models.py`**

Check that `ProjectResponse` has `id`, `slug`, `llm_mode`, `sector`, `status` fields. The current definition should be:
```python
class ProjectResponse(BaseModel):
    id: int
    slug: str
    llm_mode: str
    sector: str
    status: str
```
If it differs, update it to match. The database returns `id`, `slug`, `llm_mode`, `sector`, `config_json`, `status`, `created_at` — `ProjectResponse` is a projection of that.

- [ ] **Step 8: Run tests**

```bash
source .venv/bin/activate && python -m pytest tests/test_projects_list.py -v
source .venv/bin/activate && python -m pytest -v
```
Expected: 2 new tests pass, all 23 existing pass.

- [ ] **Step 9: Commit**

```bash
git add api/database.py api/services/project_service.py api/routers/projects.py api/main.py api/models.py tests/test_projects_list.py
git commit -m "feat(sp2): CORS + GET /projects list endpoint

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

## Task 2: JWT Auth — Login, Password Hashing, Protected Dependency

**Files:**
- Modify: `requirements.txt`
- Create: `api/auth.py`
- Create: `api/routers/auth.py`
- Modify: `api/config.py`
- Modify: `api/database.py`
- Modify: `api/main.py`
- Create: `tests/test_auth.py`

- [ ] **Step 1: Add auth packages to `requirements.txt`**

Append to `requirements.txt`:
```
python-jose[cryptography]==3.3.0
passlib[bcrypt]==1.7.4
python-multipart==0.0.20
```

Install:
```bash
source .venv/bin/activate && pip install 'python-jose[cryptography]==3.3.0' 'passlib[bcrypt]==1.7.4' 'python-multipart==0.0.20' -q
```

- [ ] **Step 2: Add `admin_password` to `api/config.py`**

In the `Settings` class, add after `jwt_secret`:
```python
admin_username: str = "admin"
admin_password: str = "changeme"
```

Also add `admin_password` default in `tests/conftest.py`:
```python
os.environ.setdefault("ADMIN_PASSWORD", "test-admin-pw")
os.environ.setdefault("ADMIN_USERNAME", "admin")
```

Wait — the field name in Settings is `admin_password` but env var is `ADMIN_PASSWORD`. pydantic-settings maps `ADMIN_PASSWORD` → `admin_password` automatically. Add the defaults to conftest.py.

- [ ] **Step 3: Write failing tests**

```python
# tests/test_auth.py
import pytest
from api.config import get_settings


@pytest.fixture(autouse=True)
def clean():
    yield
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_login_returns_token(client):
    resp = await client.post("/auth/login", data={"username": "admin", "password": "test-admin-pw"})
    assert resp.status_code == 200
    data = resp.json()
    assert "access_token" in data
    assert data["token_type"] == "bearer"


@pytest.mark.asyncio
async def test_login_wrong_password(client):
    resp = await client.post("/auth/login", data={"username": "admin", "password": "wrong"})
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_login_unknown_user(client):
    resp = await client.post("/auth/login", data={"username": "ghost", "password": "any"})
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_create_user_and_login(client):
    # Log in as admin first
    login = await client.post("/auth/login", data={"username": "admin", "password": "test-admin-pw"})
    token = login.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    # Create a new user
    resp = await client.post(
        "/auth/users",
        json={"username": "newuser", "password": "newpass", "role": "consultant"},
        headers=headers,
    )
    assert resp.status_code == 201

    # New user can log in
    login2 = await client.post("/auth/login", data={"username": "newuser", "password": "newpass"})
    assert login2.status_code == 200
```

- [ ] **Step 4: Run tests to verify they fail**

```bash
source .venv/bin/activate && python -m pytest tests/test_auth.py -v
```
Expected: 404 errors (no auth endpoints).

- [ ] **Step 5: Create `api/auth.py`**

```python
# api/auth.py
from datetime import datetime, timedelta, timezone
from jose import JWTError, jwt
from passlib.context import CryptContext
from fastapi import HTTPException, Security
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_HOURS = 24

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
_bearer = HTTPBearer()


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(plain: str, hashed: str) -> bool:
    return pwd_context.verify(plain, hashed)


def create_access_token(username: str, role: str, secret: str) -> str:
    expire = datetime.now(timezone.utc) + timedelta(hours=ACCESS_TOKEN_EXPIRE_HOURS)
    payload = {"sub": username, "role": role, "exp": expire}
    return jwt.encode(payload, secret, algorithm=ALGORITHM)


def decode_token(token: str, secret: str) -> dict:
    try:
        return jwt.decode(token, secret, algorithms=[ALGORITHM])
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid or expired token")


def get_token_payload(
    credentials: HTTPAuthorizationCredentials = Security(_bearer),
) -> dict:
    """FastAPI dependency — extracts and validates the Bearer token."""
    from api.config import get_settings
    return decode_token(credentials.credentials, get_settings().jwt_secret)
```

- [ ] **Step 6: Add system DB helpers to `api/database.py`**

Add after `fetch_agent_outputs`:

```python
# ── System DB (users) ────────────────────────────────────────────────────────

def get_system_db_path() -> Path:
    return Path(get_settings().database_dir) / "system.db"


@asynccontextmanager
async def get_system_connection():
    path = get_system_db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    async with aiosqlite.connect(path) as conn:
        conn.row_factory = aiosqlite.Row
        await conn.execute("PRAGMA foreign_keys = ON")
        await conn.executescript("""
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
        yield conn


async def fetch_user(conn: aiosqlite.Connection, *, username: str) -> dict | None:
    async with conn.execute("SELECT * FROM users WHERE username=?", (username,)) as cur:
        row = await cur.fetchone()
        return dict(row) if row else None


async def insert_user(conn: aiosqlite.Connection, *, username: str, role: str,
                      hashed_pw: str, project_slug: str | None = None) -> bool:
    """Returns True if inserted, False if username already exists."""
    try:
        await conn.execute(
            "INSERT INTO users (username, role, hashed_pw, project_slug) VALUES (?,?,?,?)",
            (username, role, hashed_pw, project_slug),
        )
        await conn.commit()
        return True
    except aiosqlite.IntegrityError:
        return False
```

- [ ] **Step 7: Create `api/routers/auth.py`**

```python
# api/routers/auth.py
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from pydantic import BaseModel
from api.auth import (
    create_access_token,
    get_token_payload,
    hash_password,
    verify_password,
)
from api.config import get_settings
from api.database import fetch_user, insert_user, get_system_connection

router = APIRouter(prefix="/auth", tags=["auth"])


class UserCreate(BaseModel):
    username: str
    password: str
    role: str = "consultant"
    project_slug: str | None = None


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


@router.post("/login", response_model=TokenResponse)
async def login(form: OAuth2PasswordRequestForm = Depends()):
    settings = get_settings()
    # Check built-in admin credentials from config
    if form.username == settings.admin_username:
        if not verify_password(form.password, hash_password(settings.admin_password)):
            # verify against the raw password (admin pw is stored plaintext in config)
            if form.password != settings.admin_password:
                raise HTTPException(status_code=401, detail="Invalid credentials")
        token = create_access_token(form.username, "consultant", settings.jwt_secret)
        return TokenResponse(access_token=token)

    # Check system DB users
    async with get_system_connection() as conn:
        user = await fetch_user(conn, username=form.username)
    if not user or not verify_password(form.password, user["hashed_pw"]):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    token = create_access_token(user["username"], user["role"], settings.jwt_secret)
    return TokenResponse(access_token=token)


@router.post("/users", status_code=201)
async def create_user(
    req: UserCreate,
    payload: dict = Depends(get_token_payload),
):
    if payload.get("role") != "consultant":
        raise HTTPException(status_code=403, detail="Consultant role required")
    async with get_system_connection() as conn:
        ok = await insert_user(
            conn,
            username=req.username,
            role=req.role,
            hashed_pw=hash_password(req.password),
            project_slug=req.project_slug,
        )
    if not ok:
        raise HTTPException(status_code=409, detail="Username already exists")
    return {"username": req.username, "role": req.role}
```

- [ ] **Step 8: Register auth router in `api/main.py`**

Add to imports:
```python
from api.routers import projects, run, outputs, ws
from api.routers import auth as auth_router
```

Add after `app.include_router(ws.router)`:
```python
app.include_router(auth_router.router)
```

- [ ] **Step 9: Update `tests/conftest.py`**

Add the two new env var defaults:
```python
os.environ.setdefault("ADMIN_PASSWORD", "test-admin-pw")
os.environ.setdefault("ADMIN_USERNAME", "admin")
```

- [ ] **Step 10: Run tests**

```bash
source .venv/bin/activate && python -m pytest tests/test_auth.py -v
source .venv/bin/activate && python -m pytest -v
```
Expected: 4 new tests pass, all 25 existing pass.

- [ ] **Step 11: Commit**

```bash
git add api/auth.py api/routers/auth.py api/database.py api/config.py api/main.py requirements.txt tests/test_auth.py tests/conftest.py
git commit -m "feat(sp2): JWT auth — login, user management, bcrypt password hashing

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

## Task 3: Client Documents — Table, Upload, List

**Files:**
- Modify: `api/database.py`
- Create: `api/routers/documents.py`
- Modify: `api/main.py`
- Create: `tests/test_documents.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_documents.py
import io
import pytest
from api.config import get_settings

PROJECT = {
    "client_slug": "doc-test",
    "llm_mode": "standard",
    "sector": "transport",
    "stakeholder_groups": ["Operations"],
    "value_stream_labels": ["Asset Mgmt"],
    "crews_enabled": ["discovery"],
    "review_gates": True,
    "slack_channel": "",
}


@pytest.fixture(autouse=True)
def clean():
    yield
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_list_documents_empty(client):
    await client.post("/projects", json=PROJECT)
    resp = await client.get("/projects/doc-test/documents")
    assert resp.status_code == 200
    assert resp.json() == []


@pytest.mark.asyncio
async def test_upload_document(client):
    await client.post("/projects", json=PROJECT)
    file_content = b"Test PDF content"
    resp = await client.post(
        "/projects/doc-test/documents/upload",
        files={"file": ("test.pdf", io.BytesIO(file_content), "application/pdf")},
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["original_name"] == "test.pdf"
    assert data["ingested"] is False


@pytest.mark.asyncio
async def test_list_documents_after_upload(client):
    await client.post("/projects", json=PROJECT)
    await client.post(
        "/projects/doc-test/documents/upload",
        files={"file": ("report.pdf", io.BytesIO(b"content"), "application/pdf")},
    )
    resp = await client.get("/projects/doc-test/documents")
    assert resp.status_code == 200
    assert len(resp.json()) == 1
    assert resp.json()[0]["original_name"] == "report.pdf"


@pytest.mark.asyncio
async def test_documents_unknown_project_returns_404(client):
    resp = await client.get("/projects/ghost/documents")
    assert resp.status_code == 404
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
source .venv/bin/activate && python -m pytest tests/test_documents.py -v
```
Expected: 404 errors (no documents endpoints).

- [ ] **Step 3: Add `client_documents` table and helpers to `api/database.py`**

In `init_db`, add to the `executescript` SQL (inside the triple-quoted string, after the `users` table):

```sql
CREATE TABLE IF NOT EXISTS client_documents (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id   INTEGER NOT NULL REFERENCES projects(id),
    filename     TEXT NOT NULL,
    original_name TEXT NOT NULL,
    file_path    TEXT NOT NULL,
    content_type TEXT,
    size_bytes   INTEGER,
    ingested     INTEGER NOT NULL DEFAULT 0,
    uploaded_at  DATETIME DEFAULT CURRENT_TIMESTAMP
);
```

Add after `fetch_agent_outputs` (before the system DB section):

```python
async def insert_document(
    conn: aiosqlite.Connection, *,
    project_id: int,
    filename: str,
    original_name: str,
    file_path: str,
    content_type: str,
    size_bytes: int,
) -> int:
    cur = await conn.execute(
        """INSERT INTO client_documents
           (project_id, filename, original_name, file_path, content_type, size_bytes)
           VALUES (?,?,?,?,?,?)""",
        (project_id, filename, original_name, file_path, content_type, size_bytes),
    )
    await conn.commit()
    return cur.lastrowid


async def fetch_documents(conn: aiosqlite.Connection, *, project_id: int) -> list[dict]:
    async with conn.execute(
        "SELECT * FROM client_documents WHERE project_id=? ORDER BY uploaded_at DESC",
        (project_id,),
    ) as cur:
        return [dict(r) async for r in cur]
```

- [ ] **Step 4: Create `api/routers/documents.py`**

```python
# api/routers/documents.py
import uuid
from pathlib import Path
from fastapi import APIRouter, HTTPException, UploadFile, File
from api.config import get_settings
from api.database import get_connection, get_db_path, fetch_project, insert_document, fetch_documents

router = APIRouter(prefix="/projects", tags=["documents"])


@router.get("/{slug}/documents")
async def list_documents(slug: str):
    if not get_db_path(slug).exists():
        raise HTTPException(status_code=404, detail=f"Project '{slug}' not found")
    async with get_connection(slug) as conn:
        project = await fetch_project(conn, slug=slug)
        if not project:
            raise HTTPException(status_code=404, detail=f"Project '{slug}' not found")
        return await fetch_documents(conn, project_id=project["id"])


@router.post("/{slug}/documents/upload", status_code=201)
async def upload_document(slug: str, file: UploadFile = File(...)):
    if not get_db_path(slug).exists():
        raise HTTPException(status_code=404, detail=f"Project '{slug}' not found")

    settings = get_settings()
    docs_dir = Path(settings.projects_dir) / slug / "docs"
    docs_dir.mkdir(parents=True, exist_ok=True)

    # Unique filename to prevent collisions
    suffix = Path(file.filename).suffix
    unique_name = f"{uuid.uuid4().hex}{suffix}"
    dest = docs_dir / unique_name

    content = await file.read()
    dest.write_bytes(content)

    async with get_connection(slug) as conn:
        project = await fetch_project(conn, slug=slug)
        if not project:
            raise HTTPException(status_code=404, detail=f"Project '{slug}' not found")
        doc_id = await insert_document(
            conn,
            project_id=project["id"],
            filename=unique_name,
            original_name=file.filename,
            file_path=str(dest),
            content_type=file.content_type or "application/octet-stream",
            size_bytes=len(content),
        )
        docs = await fetch_documents(conn, project_id=project["id"])
        return next(d for d in docs if d["id"] == doc_id)
```

Note: `ingested` column defaults to 0 (false). ChromaDB ingestion is wired in SP4.

- [ ] **Step 5: Register documents router in `api/main.py`**

Add to imports:
```python
from api.routers import auth as auth_router, documents as documents_router
```

Add:
```python
app.include_router(documents_router.router)
```

- [ ] **Step 6: Run tests**

```bash
source .venv/bin/activate && python -m pytest tests/test_documents.py -v
source .venv/bin/activate && python -m pytest -v
```
Expected: 4 new tests pass, all previous pass.

- [ ] **Step 7: Commit**

```bash
git add api/database.py api/routers/documents.py api/main.py tests/test_documents.py
git commit -m "feat(sp2): document upload + list endpoints

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

## Task 4: Review Endpoint + Value-Chain / Roadmap Stubs

**Files:**
- Modify: `api/database.py`
- Create: `api/routers/reviews.py`
- Modify: `api/routers/projects.py`
- Modify: `api/main.py`
- Create: `tests/test_reviews.py`
- Create: `tests/test_sp2_stubs.py`

- [ ] **Step 1: Write failing tests for reviews**

```python
# tests/test_reviews.py
import pytest
from api.config import get_settings

PROJECT = {
    "client_slug": "review-test",
    "llm_mode": "standard",
    "sector": "transport",
    "stakeholder_groups": ["Operations"],
    "value_stream_labels": ["Asset Mgmt"],
    "crews_enabled": ["discovery"],
    "review_gates": True,
    "slack_channel": "",
}


@pytest.fixture(autouse=True)
def clean():
    yield
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_submit_review_approve(client):
    await client.post("/projects", json=PROJECT)
    # Insert an agent output first (direct DB manipulation via service)
    from api.database import get_connection, fetch_project, insert_agent_output
    async with get_connection("review-test") as conn:
        project = await fetch_project(conn, slug="review-test")
        output_id = await insert_agent_output(
            conn,
            project_id=project["id"],
            agent_name="test_agent",
            output_type="value_chain",
            file_path="/tmp/test.json",
            version=1,
        )

    resp = await client.post(
        "/projects/review-test/review",
        json={"output_id": output_id, "decision": "approved", "notes": "Looks good"},
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["decision"] == "approved"
    assert data["output_id"] == output_id


@pytest.mark.asyncio
async def test_submit_review_reject(client):
    await client.post("/projects", json=PROJECT)
    from api.database import get_connection, fetch_project, insert_agent_output
    async with get_connection("review-test") as conn:
        project = await fetch_project(conn, slug="review-test")
        output_id = await insert_agent_output(
            conn,
            project_id=project["id"],
            agent_name="test_agent",
            output_type="value_chain",
            file_path="/tmp/test2.json",
            version=1,
        )

    resp = await client.post(
        "/projects/review-test/review",
        json={"output_id": output_id, "decision": "changes_requested", "notes": "Needs work"},
    )
    assert resp.status_code == 201
    assert resp.json()["decision"] == "changes_requested"


@pytest.mark.asyncio
async def test_review_unknown_project_returns_404(client):
    resp = await client.post(
        "/projects/ghost/review",
        json={"output_id": 1, "decision": "approved", "notes": ""},
    )
    assert resp.status_code == 404
```

- [ ] **Step 2: Write failing tests for stubs**

```python
# tests/test_sp2_stubs.py
import pytest
from api.config import get_settings

PROJECT = {
    "client_slug": "stub-test",
    "llm_mode": "standard",
    "sector": "transport",
    "stakeholder_groups": ["Operations"],
    "value_stream_labels": ["Asset Mgmt"],
    "crews_enabled": ["discovery"],
    "review_gates": True,
    "slack_channel": "",
}


@pytest.fixture(autouse=True)
def clean():
    yield
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_value_chain_empty_for_new_project(client):
    await client.post("/projects", json=PROJECT)
    resp = await client.get("/projects/stub-test/value-chain")
    assert resp.status_code == 200
    assert resp.json() == []


@pytest.mark.asyncio
async def test_roadmap_empty_for_new_project(client):
    await client.post("/projects", json=PROJECT)
    resp = await client.get("/projects/stub-test/roadmap")
    assert resp.status_code == 200
    assert resp.json() == []


@pytest.mark.asyncio
async def test_value_chain_unknown_project_returns_404(client):
    resp = await client.get("/projects/ghost/value-chain")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_roadmap_unknown_project_returns_404(client):
    resp = await client.get("/projects/ghost/roadmap")
    assert resp.status_code == 404
```

- [ ] **Step 3: Run tests to verify they fail**

```bash
source .venv/bin/activate && python -m pytest tests/test_reviews.py tests/test_sp2_stubs.py -v
```
Expected: failures.

- [ ] **Step 4: Add `insert_review` and `fetch_outputs_by_type` to `api/database.py`**

Add after `fetch_documents` (before the system DB section):

```python
async def insert_review(
    conn: aiosqlite.Connection, *,
    output_id: int,
    reviewer: str,
    decision: str,
    notes: str,
) -> int:
    cur = await conn.execute(
        "INSERT INTO human_reviews (output_id, reviewer, decision, notes) VALUES (?,?,?,?)",
        (output_id, reviewer, decision, notes),
    )
    await conn.commit()
    return cur.lastrowid


async def fetch_outputs_by_type(
    conn: aiosqlite.Connection, *, project_id: int, output_type: str
) -> list[dict]:
    async with conn.execute(
        "SELECT * FROM agent_outputs WHERE project_id=? AND output_type=? ORDER BY created_at DESC",
        (project_id, output_type),
    ) as cur:
        return [dict(r) async for r in cur]
```

- [ ] **Step 5: Create `api/routers/reviews.py`**

```python
# api/routers/reviews.py
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from api.database import get_connection, get_db_path, fetch_project, insert_review

router = APIRouter(prefix="/projects", tags=["reviews"])


class ReviewRequest(BaseModel):
    output_id: int
    decision: str  # "approved" | "changes_requested"
    notes: str = ""
    reviewer: str = "consultant"


@router.post("/{slug}/review", status_code=201)
async def submit_review(slug: str, req: ReviewRequest):
    if not get_db_path(slug).exists():
        raise HTTPException(status_code=404, detail=f"Project '{slug}' not found")
    async with get_connection(slug) as conn:
        project = await fetch_project(conn, slug=slug)
        if not project:
            raise HTTPException(status_code=404, detail=f"Project '{slug}' not found")
        review_id = await insert_review(
            conn,
            output_id=req.output_id,
            reviewer=req.reviewer,
            decision=req.decision,
            notes=req.notes,
        )
        return {
            "id": review_id,
            "output_id": req.output_id,
            "decision": req.decision,
            "notes": req.notes,
        }
```

- [ ] **Step 6: Add value-chain + roadmap endpoints to `api/routers/projects.py`**

Add `fetch_outputs_by_type` to the database import block:
```python
from api.database import (
    get_connection,
    get_db_path,
    fetch_project,
    fetch_outputs_by_type,
)
```

Add to imports from service:
```python
from api.services.project_service import create_project, get_project_status, list_all_projects
```

Add at the bottom of the file:

```python
@router.get("/{slug}/value-chain")
async def get_value_chain(slug: str):
    if not get_db_path(slug).exists():
        raise HTTPException(status_code=404, detail=f"Project '{slug}' not found")
    async with get_connection(slug) as conn:
        project = await fetch_project(conn, slug=slug)
        if not project:
            raise HTTPException(status_code=404, detail=f"Project '{slug}' not found")
        return await fetch_outputs_by_type(conn, project_id=project["id"], output_type="value_chain")


@router.get("/{slug}/roadmap")
async def get_roadmap(slug: str):
    if not get_db_path(slug).exists():
        raise HTTPException(status_code=404, detail=f"Project '{slug}' not found")
    async with get_connection(slug) as conn:
        project = await fetch_project(conn, slug=slug)
        if not project:
            raise HTTPException(status_code=404, detail=f"Project '{slug}' not found")
        return await fetch_outputs_by_type(conn, project_id=project["id"], output_type="roadmap")
```

Add the missing `HTTPException` import at the top of `projects.py` if not already there:
```python
from fastapi import APIRouter, HTTPException, Response
```

- [ ] **Step 7: Register reviews router in `api/main.py`**

```python
from api.routers import auth as auth_router, documents as documents_router, reviews as reviews_router
# ...
app.include_router(reviews_router.router)
```

- [ ] **Step 8: Run all tests**

```bash
source .venv/bin/activate && python -m pytest tests/test_reviews.py tests/test_sp2_stubs.py -v
source .venv/bin/activate && python -m pytest -v
```
Expected: 7 new tests pass, all previous pass.

- [ ] **Step 9: Commit**

```bash
git add api/database.py api/routers/reviews.py api/routers/projects.py api/main.py tests/test_reviews.py tests/test_sp2_stubs.py
git commit -m "feat(sp2): review endpoint + value-chain/roadmap stub endpoints

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

## Task 5: React + Vite Scaffold

**Files:**
- Create: `ui/package.json`
- Create: `ui/vite.config.ts`
- Create: `ui/tailwind.config.js`
- Create: `ui/postcss.config.js`
- Create: `ui/tsconfig.json`
- Create: `ui/tsconfig.node.json`
- Create: `ui/index.html`
- Create: `ui/src/test/setup.ts`
- Create: `ui/src/App.tsx`
- Create: `ui/src/__tests__/App.test.tsx`
- Create: `ui/src/main.tsx`

- [ ] **Step 1: Create `ui/package.json`**

```json
{
  "name": "agentpool-ui",
  "version": "0.1.0",
  "private": true,
  "type": "module",
  "scripts": {
    "dev": "vite",
    "build": "tsc && vite build",
    "test": "vitest run",
    "test:watch": "vitest"
  },
  "dependencies": {
    "@tanstack/react-query": "^5.62.7",
    "axios": "^1.7.9",
    "react": "^18.3.1",
    "react-dom": "^18.3.1",
    "react-router-dom": "^6.28.0",
    "recharts": "^2.13.0"
  },
  "devDependencies": {
    "@testing-library/jest-dom": "^6.6.3",
    "@testing-library/react": "^16.1.0",
    "@testing-library/user-event": "^14.5.2",
    "@types/react": "^18.3.12",
    "@types/react-dom": "^18.3.1",
    "@vitejs/plugin-react": "^4.3.4",
    "autoprefixer": "^10.4.20",
    "jsdom": "^25.0.1",
    "postcss": "^8.4.49",
    "tailwindcss": "^3.4.16",
    "typescript": "^5.6.3",
    "vite": "^6.0.5",
    "vitest": "^2.1.8"
  }
}
```

- [ ] **Step 2: Create `ui/vite.config.ts`**

```typescript
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  test: {
    environment: 'jsdom',
    setupFiles: ['./src/test/setup.ts'],
    globals: true,
  },
})
```

- [ ] **Step 3: Create `ui/tailwind.config.js`**

```javascript
/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        brand: {
          DEFAULT: '#7c6af7',
          light: '#c4b8ff',
          dark: '#5b4ed6',
        },
        surface: {
          DEFAULT: '#1a1825',
          raised: '#221f33',
          card: '#2a2640',
        },
      },
    },
  },
  plugins: [],
}
```

- [ ] **Step 4: Create `ui/postcss.config.js`**

```javascript
export default {
  plugins: {
    tailwindcss: {},
    autoprefixer: {},
  },
}
```

- [ ] **Step 5: Create `ui/tsconfig.json`**

```json
{
  "compilerOptions": {
    "target": "ES2020",
    "useDefineForClassFields": true,
    "lib": ["ES2020", "DOM", "DOM.Iterable"],
    "module": "ESNext",
    "skipLibCheck": true,
    "moduleResolution": "bundler",
    "allowImportingTsExtensions": true,
    "resolveJsonModule": true,
    "isolatedModules": true,
    "noEmit": true,
    "jsx": "react-jsx",
    "strict": true,
    "noUnusedLocals": true,
    "noUnusedParameters": true,
    "noFallthroughCasesInSwitch": true
  },
  "include": ["src"],
  "references": [{ "path": "./tsconfig.node.json" }]
}
```

- [ ] **Step 6: Create `ui/tsconfig.node.json`**

```json
{
  "compilerOptions": {
    "composite": true,
    "skipLibCheck": true,
    "module": "ESNext",
    "moduleResolution": "bundler",
    "allowSyntheticDefaultImports": true
  },
  "include": ["vite.config.ts"]
}
```

- [ ] **Step 7: Create `ui/index.html`**

```html
<!doctype html>
<html lang="en">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>AgentPool</title>
  </head>
  <body class="bg-surface text-slate-100 min-h-screen">
    <div id="root"></div>
    <script type="module" src="/src/main.tsx"></script>
  </body>
</html>
```

- [ ] **Step 8: Create `ui/src/test/setup.ts`**

```typescript
import '@testing-library/jest-dom'
```

- [ ] **Step 9: Create `ui/src/App.tsx`**

```typescript
export default function App() {
  return <div data-testid="app">AgentPool</div>
}
```

- [ ] **Step 10: Create `ui/src/__tests__/App.test.tsx`**

```typescript
import { render, screen } from '@testing-library/react'
import App from '../App'

describe('App', () => {
  it('renders without crashing', () => {
    render(<App />)
    expect(screen.getByTestId('app')).toBeInTheDocument()
  })
})
```

- [ ] **Step 11: Create `ui/src/main.tsx`** (placeholder — will be replaced in Task 7)

```typescript
import React from 'react'
import ReactDOM from 'react-dom/client'
import './index.css'
import App from './App'

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>
)
```

- [ ] **Step 12: Create `ui/src/index.css`**

```css
@tailwind base;
@tailwind components;
@tailwind utilities;
```

- [ ] **Step 13: Install dependencies and run tests**

```bash
cd ui
npm install
npm test
```
Expected: `1 passed`.

- [ ] **Step 14: Commit**

```bash
cd ..
git add ui/
git commit -m "feat(sp2): React + Vite + TypeScript + Tailwind scaffold

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

## Task 6: TypeScript Types + API Client + Auth Context

**Files:**
- Create: `ui/src/types.ts`
- Create: `ui/src/api/client.ts`
- Create: `ui/src/api/endpoints.ts`
- Create: `ui/src/context/AuthContext.tsx`
- Create: `ui/src/__tests__/AuthContext.test.tsx`

- [ ] **Step 1: Write failing tests**

```typescript
// ui/src/__tests__/AuthContext.test.tsx
import { render, screen, act } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { AuthProvider, useAuth } from '../context/AuthContext'

function TestConsumer() {
  const { token, login, logout } = useAuth()
  return (
    <div>
      <span data-testid="token">{token ?? 'none'}</span>
      <button onClick={() => login('fake-token', { sub: 'admin', role: 'consultant' })}>
        Login
      </button>
      <button onClick={logout}>Logout</button>
    </div>
  )
}

describe('AuthContext', () => {
  beforeEach(() => localStorage.clear())

  it('starts with no token', () => {
    render(<AuthProvider><TestConsumer /></AuthProvider>)
    expect(screen.getByTestId('token').textContent).toBe('none')
  })

  it('login stores token', async () => {
    render(<AuthProvider><TestConsumer /></AuthProvider>)
    await userEvent.click(screen.getByText('Login'))
    expect(screen.getByTestId('token').textContent).toBe('fake-token')
    expect(localStorage.getItem('ap_token')).toBe('fake-token')
  })

  it('logout clears token', async () => {
    render(<AuthProvider><TestConsumer /></AuthProvider>)
    await userEvent.click(screen.getByText('Login'))
    await userEvent.click(screen.getByText('Logout'))
    expect(screen.getByTestId('token').textContent).toBe('none')
    expect(localStorage.getItem('ap_token')).toBeNull()
  })
})
```

- [ ] **Step 2: Run to verify fail**

```bash
cd ui && npm test -- --reporter=verbose 2>&1 | head -30
```
Expected: import errors.

- [ ] **Step 3: Create `ui/src/types.ts`**

```typescript
// ui/src/types.ts

export interface Project {
  id: number
  slug: string
  llm_mode: string
  sector: string
  status: string
}

export interface CrewRun {
  id: number
  project_id: number
  crew_name: string
  status: 'pending' | 'queued' | 'running' | 'completed' | 'failed'
  result_json: string | null
  started_at: string | null
  finished_at: string | null
  created_at: string
}

export interface ProjectStatus {
  project_slug: string
  project_status: string
  crew_runs: CrewRun[]
}

export interface AgentOutput {
  id: number
  agent_name: string
  output_type: string
  file_path: string
  version: number
  review_status: string
  created_at: string
}

export interface ClientDocument {
  id: number
  project_id: number
  filename: string
  original_name: string
  file_path: string
  content_type: string
  size_bytes: number
  ingested: boolean
  uploaded_at: string
}

export interface Review {
  id: number
  output_id: number
  decision: string
  notes: string
}

export interface TokenResponse {
  access_token: string
  token_type: string
}

export interface UserPayload {
  sub: string
  role: string
  exp: number
}
```

- [ ] **Step 4: Create `ui/src/api/client.ts`**

```typescript
// ui/src/api/client.ts
import axios from 'axios'

export const API_BASE = 'http://localhost:8000'

export const apiClient = axios.create({ baseURL: API_BASE })

// Inject stored token on every request
apiClient.interceptors.request.use((config) => {
  const token = localStorage.getItem('ap_token')
  if (token) {
    config.headers.Authorization = `Bearer ${token}`
  }
  return config
})
```

- [ ] **Step 5: Create `ui/src/api/endpoints.ts`**

```typescript
// ui/src/api/endpoints.ts
import { apiClient } from './client'
import type {
  Project,
  ProjectStatus,
  AgentOutput,
  ClientDocument,
  TokenResponse,
} from '../types'

export const authApi = {
  login: (username: string, password: string): Promise<TokenResponse> => {
    const form = new URLSearchParams({ username, password })
    return apiClient.post('/auth/login', form).then((r) => r.data)
  },
}

export const projectsApi = {
  list: (): Promise<Project[]> =>
    apiClient.get('/projects').then((r) => r.data),

  getStatus: (slug: string): Promise<ProjectStatus> =>
    apiClient.get(`/projects/${slug}/status`).then((r) => r.data),

  getOutputs: (slug: string): Promise<AgentOutput[]> =>
    apiClient.get(`/projects/${slug}/outputs`).then((r) => r.data),

  getValueChain: (slug: string): Promise<AgentOutput[]> =>
    apiClient.get(`/projects/${slug}/value-chain`).then((r) => r.data),

  getRoadmap: (slug: string): Promise<AgentOutput[]> =>
    apiClient.get(`/projects/${slug}/roadmap`).then((r) => r.data),

  review: (slug: string, outputId: number, decision: string, notes = '') =>
    apiClient
      .post(`/projects/${slug}/review`, { output_id: outputId, decision, notes })
      .then((r) => r.data),
}

export const documentsApi = {
  list: (slug: string): Promise<ClientDocument[]> =>
    apiClient.get(`/projects/${slug}/documents`).then((r) => r.data),

  upload: (slug: string, file: File): Promise<ClientDocument> => {
    const form = new FormData()
    form.append('file', file)
    return apiClient
      .post(`/projects/${slug}/documents/upload`, form)
      .then((r) => r.data)
  },
}
```

- [ ] **Step 6: Create `ui/src/context/AuthContext.tsx`**

```typescript
// ui/src/context/AuthContext.tsx
import { createContext, useContext, useState, ReactNode } from 'react'
import type { UserPayload } from '../types'

const TOKEN_KEY = 'ap_token'

interface AuthState {
  token: string | null
  user: UserPayload | null
  login: (token: string, user: UserPayload) => void
  logout: () => void
}

const AuthContext = createContext<AuthState | null>(null)

function parseToken(token: string): UserPayload | null {
  try {
    const payload = JSON.parse(atob(token.split('.')[1]))
    return payload as UserPayload
  } catch {
    return null
  }
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [token, setToken] = useState<string | null>(() => localStorage.getItem(TOKEN_KEY))
  const [user, setUser] = useState<UserPayload | null>(() => {
    const t = localStorage.getItem(TOKEN_KEY)
    return t ? parseToken(t) : null
  })

  function login(newToken: string, newUser: UserPayload) {
    localStorage.setItem(TOKEN_KEY, newToken)
    setToken(newToken)
    setUser(newUser)
  }

  function logout() {
    localStorage.removeItem(TOKEN_KEY)
    setToken(null)
    setUser(null)
  }

  return (
    <AuthContext.Provider value={{ token, user, login, logout }}>
      {children}
    </AuthContext.Provider>
  )
}

export function useAuth(): AuthState {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error('useAuth must be used inside AuthProvider')
  return ctx
}
```

- [ ] **Step 7: Run tests**

```bash
cd ui && npm test -- --reporter=verbose
```
Expected: 3 `AuthContext` tests pass, 1 `App` test pass = 4 total.

- [ ] **Step 8: Commit**

```bash
cd ..
git add ui/src/types.ts ui/src/api/ ui/src/context/ ui/src/__tests__/AuthContext.test.tsx
git commit -m "feat(sp2): TypeScript types, API client, auth context

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

## Task 7: Login Page + App Shell + Protected Routes

**Files:**
- Create: `ui/src/pages/Login.tsx`
- Create: `ui/src/components/AppLayout.tsx`
- Create: `ui/src/router.tsx`
- Modify: `ui/src/main.tsx`
- Create: `ui/src/__tests__/Login.test.tsx`

- [ ] **Step 1: Write failing Login test**

```typescript
// ui/src/__tests__/Login.test.tsx
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { AuthProvider } from '../context/AuthContext'
import Login from '../pages/Login'

// Mock the API
vi.mock('../api/endpoints', () => ({
  authApi: {
    login: vi.fn().mockResolvedValue({ access_token: 'test-token', token_type: 'bearer' }),
  },
}))

function Wrapper({ children }: { children: React.ReactNode }) {
  return (
    <AuthProvider>
      <MemoryRouter>{children}</MemoryRouter>
    </AuthProvider>
  )
}

describe('Login', () => {
  it('renders username and password fields', () => {
    render(<Login />, { wrapper: Wrapper })
    expect(screen.getByLabelText(/username/i)).toBeInTheDocument()
    expect(screen.getByLabelText(/password/i)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /sign in/i })).toBeInTheDocument()
  })

  it('submits credentials and stores token', async () => {
    render(<Login />, { wrapper: Wrapper })
    await userEvent.type(screen.getByLabelText(/username/i), 'admin')
    await userEvent.type(screen.getByLabelText(/password/i), 'password')
    await userEvent.click(screen.getByRole('button', { name: /sign in/i }))
    expect(localStorage.getItem('ap_token')).toBe('test-token')
  })

  it('shows error on failed login', async () => {
    const { authApi } = await import('../api/endpoints')
    vi.mocked(authApi.login).mockRejectedValueOnce(new Error('401'))
    render(<Login />, { wrapper: Wrapper })
    await userEvent.type(screen.getByLabelText(/username/i), 'admin')
    await userEvent.type(screen.getByLabelText(/password/i), 'wrong')
    await userEvent.click(screen.getByRole('button', { name: /sign in/i }))
    expect(await screen.findByRole('alert')).toBeInTheDocument()
  })
})
```

- [ ] **Step 2: Run to verify fail**

```bash
cd ui && npm test -- --reporter=verbose 2>&1 | grep -E "PASS|FAIL|Error" | head -20
```

- [ ] **Step 3: Create `ui/src/pages/Login.tsx`**

```typescript
// ui/src/pages/Login.tsx
import { useState, FormEvent } from 'react'
import { useNavigate } from 'react-router-dom'
import { authApi } from '../api/endpoints'
import { useAuth } from '../context/AuthContext'

export default function Login() {
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)
  const { login } = useAuth()
  const navigate = useNavigate()

  async function handleSubmit(e: FormEvent) {
    e.preventDefault()
    setError(null)
    setLoading(true)
    try {
      const resp = await authApi.login(username, password)
      const payload = JSON.parse(atob(resp.access_token.split('.')[1]))
      login(resp.access_token, payload)
      navigate('/')
    } catch {
      setError('Invalid username or password')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="min-h-screen bg-surface flex items-center justify-center">
      <div className="bg-surface-card rounded-xl p-8 w-full max-w-sm shadow-xl">
        <h1 className="text-2xl font-bold text-brand-light mb-6">AgentPool</h1>
        <form onSubmit={handleSubmit} className="space-y-4">
          <div>
            <label htmlFor="username" className="block text-sm font-medium text-slate-300 mb-1">
              Username
            </label>
            <input
              id="username"
              type="text"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              className="w-full bg-surface-raised border border-slate-700 rounded-lg px-3 py-2 text-slate-100 focus:outline-none focus:border-brand"
              required
            />
          </div>
          <div>
            <label htmlFor="password" className="block text-sm font-medium text-slate-300 mb-1">
              Password
            </label>
            <input
              id="password"
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              className="w-full bg-surface-raised border border-slate-700 rounded-lg px-3 py-2 text-slate-100 focus:outline-none focus:border-brand"
              required
            />
          </div>
          {error && (
            <p role="alert" className="text-red-400 text-sm">
              {error}
            </p>
          )}
          <button
            type="submit"
            disabled={loading}
            className="w-full bg-brand hover:bg-brand-dark disabled:opacity-50 text-white font-medium rounded-lg py-2 transition-colors"
          >
            {loading ? 'Signing in…' : 'Sign in'}
          </button>
        </form>
      </div>
    </div>
  )
}
```

- [ ] **Step 4: Create `ui/src/components/AppLayout.tsx`**

```typescript
// ui/src/components/AppLayout.tsx
import { NavLink, Outlet, useNavigate, useParams } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { projectsApi } from '../api/endpoints'
import { useAuth } from '../context/AuthContext'
import type { Project } from '../types'

export default function AppLayout() {
  const { slug } = useParams<{ slug?: string }>()
  const { user, logout } = useAuth()
  const navigate = useNavigate()

  const { data: projects = [] } = useQuery<Project[]>({
    queryKey: ['projects'],
    queryFn: projectsApi.list,
    refetchInterval: 10_000,
  })

  function handleLogout() {
    logout()
    navigate('/login')
  }

  const navItems = slug
    ? [
        { to: `/${slug}`, label: 'Dashboard', end: true },
        { to: `/${slug}/value-chain`, label: 'Value Chain' },
        { to: `/${slug}/roadmap`, label: 'Roadmap' },
        { to: `/${slug}/documents`, label: 'Documents' },
      ]
    : [{ to: '/', label: 'Dashboard', end: true }]

  return (
    <div className="min-h-screen bg-surface flex flex-col">
      {/* Top nav */}
      <header className="bg-surface-raised border-b border-slate-800 px-4 h-12 flex items-center gap-6">
        <span className="font-bold text-brand-light text-sm tracking-wide">AgentPool</span>
        <nav className="flex gap-4">
          {navItems.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              end={item.end}
              className={({ isActive }) =>
                `text-sm pb-0.5 border-b-2 transition-colors ${
                  isActive
                    ? 'text-sky-300 border-sky-300'
                    : 'text-slate-400 border-transparent hover:text-slate-200'
                }`
              }
            >
              {item.label}
            </NavLink>
          ))}
        </nav>
        <div className="ml-auto flex items-center gap-3">
          {slug && (
            <>
              <a
                href="http://localhost:8001"
                target="_blank"
                rel="noreferrer"
                className="text-xs text-slate-500 hover:text-slate-300"
              >
                Chainlit ↗
              </a>
              <a
                href="http://localhost:5678"
                target="_blank"
                rel="noreferrer"
                className="text-xs text-slate-500 hover:text-slate-300"
              >
                n8n ↗
              </a>
            </>
          )}
          <span className="text-xs text-slate-500">{user?.sub}</span>
          <button onClick={handleLogout} className="text-xs text-slate-500 hover:text-slate-300">
            Sign out
          </button>
        </div>
      </header>

      <div className="flex flex-1">
        {/* Sidebar */}
        <aside className="w-44 bg-surface-raised border-r border-slate-800 p-3 flex flex-col gap-1">
          <p className="text-xs font-bold text-slate-500 uppercase tracking-widest mb-2">
            Projects
          </p>
          {projects.map((p) => (
            <button
              key={p.slug}
              onClick={() => navigate(`/${p.slug}`)}
              className={`w-full text-left text-sm px-2 py-1.5 rounded transition-colors ${
                slug === p.slug
                  ? 'bg-sky-900/40 text-sky-300'
                  : 'text-slate-400 hover:bg-slate-800 hover:text-slate-200'
              }`}
            >
              {p.slug}
            </button>
          ))}
          {projects.length === 0 && (
            <p className="text-xs text-slate-600 px-2">No projects yet</p>
          )}
        </aside>

        {/* Main content */}
        <main className="flex-1 overflow-auto">
          <Outlet />
        </main>
      </div>
    </div>
  )
}
```

- [ ] **Step 5: Create `ui/src/router.tsx`**

```typescript
// ui/src/router.tsx
import { createBrowserRouter, Navigate } from 'react-router-dom'
import { useAuth } from './context/AuthContext'
import AppLayout from './components/AppLayout'
import Login from './pages/Login'
import Dashboard from './pages/Dashboard'
import Documents from './pages/Documents'
import ValueChain from './pages/ValueChain'
import Roadmap from './pages/Roadmap'

function ProtectedRoute({ children }: { children: React.ReactNode }) {
  const { token } = useAuth()
  if (!token) return <Navigate to="/login" replace />
  return <>{children}</>
}

export const router = createBrowserRouter([
  {
    path: '/login',
    element: <Login />,
  },
  {
    path: '/',
    element: (
      <ProtectedRoute>
        <AppLayout />
      </ProtectedRoute>
    ),
    children: [
      { index: true, element: <Dashboard /> },
      { path: ':slug', element: <Dashboard /> },
      { path: ':slug/value-chain', element: <ValueChain /> },
      { path: ':slug/roadmap', element: <Roadmap /> },
      { path: ':slug/documents', element: <Documents /> },
    ],
  },
])
```

Note: The stub page components (`Dashboard`, `Documents`, `ValueChain`, `Roadmap`) will be created as minimal placeholders in this task and replaced in Tasks 8-11.

- [ ] **Step 6: Create stub page components**

Create `ui/src/pages/Dashboard.tsx`:
```typescript
export default function Dashboard() {
  return <div className="p-6 text-slate-400">Dashboard — implemented in next task</div>
}
```

Create `ui/src/pages/Documents.tsx`:
```typescript
export default function Documents() {
  return <div className="p-6 text-slate-400">Documents — implemented in next task</div>
}
```

Create `ui/src/pages/ValueChain.tsx`:
```typescript
export default function ValueChain() {
  return <div className="p-6 text-slate-400">Value Chain — implemented in next task</div>
}
```

Create `ui/src/pages/Roadmap.tsx`:
```typescript
export default function Roadmap() {
  return <div className="p-6 text-slate-400">Roadmap — implemented in next task</div>
}
```

- [ ] **Step 7: Replace `ui/src/main.tsx`**

```typescript
// ui/src/main.tsx
import React from 'react'
import ReactDOM from 'react-dom/client'
import { RouterProvider } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { AuthProvider } from './context/AuthContext'
import { router } from './router'
import './index.css'

const queryClient = new QueryClient({
  defaultOptions: {
    queries: { retry: 1, staleTime: 5_000 },
  },
})

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <QueryClientProvider client={queryClient}>
      <AuthProvider>
        <RouterProvider router={router} />
      </AuthProvider>
    </QueryClientProvider>
  </React.StrictMode>
)
```

- [ ] **Step 8: Run all tests**

```bash
cd ui && npm test -- --reporter=verbose
```
Expected: Login tests pass (3 tests), Auth tests pass (3), App test passes (1) = 7 total.

- [ ] **Step 9: Commit**

```bash
cd ..
git add ui/src/pages/ ui/src/components/ ui/src/router.tsx ui/src/main.tsx
git commit -m "feat(sp2): login page, app shell, protected routes

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

## Task 8: Dashboard View

**Files:**
- Modify: `ui/src/pages/Dashboard.tsx`
- Create: `ui/src/components/StatusBadge.tsx`
- Create: `ui/src/components/ReviewQueue.tsx`
- Create: `ui/src/hooks/useWebSocket.ts`
- Create: `ui/src/__tests__/Dashboard.test.tsx`

- [ ] **Step 1: Write failing Dashboard test**

```typescript
// ui/src/__tests__/Dashboard.test.tsx
import { render, screen } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { AuthProvider } from '../context/AuthContext'
import Dashboard from '../pages/Dashboard'

vi.mock('../api/endpoints', () => ({
  projectsApi: {
    list: vi.fn().mockResolvedValue([
      { id: 1, slug: 'acme-rail', llm_mode: 'standard', sector: 'transport', status: 'created' },
    ]),
    getStatus: vi.fn().mockResolvedValue({
      project_slug: 'acme-rail',
      project_status: 'created',
      crew_runs: [
        {
          id: 1,
          project_id: 1,
          crew_name: 'discovery',
          status: 'queued',
          result_json: null,
          started_at: null,
          finished_at: null,
          created_at: '2026-04-13T10:00:00',
        },
      ],
    }),
    getOutputs: vi.fn().mockResolvedValue([]),
  },
}))

function Wrapper({ slug }: { slug?: string }) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return (
    <QueryClientProvider client={qc}>
      <AuthProvider>
        <MemoryRouter initialEntries={[slug ? `/${slug}` : '/']}>
          <Routes>
            <Route path="/" element={<Dashboard />} />
            <Route path="/:slug" element={<Dashboard />} />
          </Routes>
        </MemoryRouter>
      </AuthProvider>
    </QueryClientProvider>
  )
}

describe('Dashboard', () => {
  it('shows no-project message when no slug', () => {
    render(<Wrapper />)
    expect(screen.getByText(/select a project/i)).toBeInTheDocument()
  })

  it('shows crew run status when project selected', async () => {
    render(<Wrapper slug="acme-rail" />)
    expect(await screen.findByText(/discovery/i)).toBeInTheDocument()
    expect(await screen.findByText(/queued/i)).toBeInTheDocument()
  })
})
```

- [ ] **Step 2: Run to verify fail**

```bash
cd ui && npm test -- --reporter=verbose 2>&1 | grep -E "PASS|FAIL|✓|✗" | head -20
```

- [ ] **Step 3: Create `ui/src/hooks/useWebSocket.ts`**

```typescript
// ui/src/hooks/useWebSocket.ts
import { useEffect, useRef, useState } from 'react'

export function useWebSocket(slug: string | undefined, maxLines = 100) {
  const [logs, setLogs] = useState<string[]>([])
  const wsRef = useRef<WebSocket | null>(null)

  useEffect(() => {
    if (!slug) return
    const ws = new WebSocket(`ws://localhost:8000/ws/${slug}`)
    wsRef.current = ws

    ws.onmessage = (e) => {
      if (e.data === 'ping') return  // keepalive — ignore
      setLogs((prev) => [...prev.slice(-(maxLines - 1)), e.data])
    }

    return () => {
      ws.close()
    }
  }, [slug, maxLines])

  return logs
}
```

- [ ] **Step 4: Create `ui/src/components/StatusBadge.tsx`**

```typescript
// ui/src/components/StatusBadge.tsx
const COLORS: Record<string, string> = {
  pending:   'bg-slate-700 text-slate-300',
  queued:    'bg-amber-900/50 text-amber-300',
  running:   'bg-sky-900/50 text-sky-300',
  completed: 'bg-emerald-900/50 text-emerald-300',
  failed:    'bg-red-900/50 text-red-300',
  created:   'bg-slate-700 text-slate-300',
}

export default function StatusBadge({ status }: { status: string }) {
  const cls = COLORS[status] ?? 'bg-slate-700 text-slate-300'
  return (
    <span className={`text-xs font-medium px-2 py-0.5 rounded-full ${cls}`}>
      {status}
    </span>
  )
}
```

- [ ] **Step 5: Create `ui/src/components/ReviewQueue.tsx`**

```typescript
// ui/src/components/ReviewQueue.tsx
import type { AgentOutput } from '../types'
import { projectsApi } from '../api/endpoints'
import { useQueryClient } from '@tanstack/react-query'

interface Props {
  slug: string
  outputs: AgentOutput[]
}

export default function ReviewQueue({ slug, outputs }: Props) {
  const qc = useQueryClient()
  const pending = outputs.filter((o) => o.review_status === 'pending')

  if (pending.length === 0) {
    return <p className="text-sm text-slate-500">No items pending review.</p>
  }

  async function decide(outputId: number, decision: string) {
    await projectsApi.review(slug, outputId, decision)
    qc.invalidateQueries({ queryKey: ['outputs', slug] })
  }

  return (
    <div className="space-y-2">
      {pending.map((o) => (
        <div
          key={o.id}
          className="flex items-center justify-between bg-surface-card rounded-lg px-4 py-3"
        >
          <div>
            <p className="text-sm font-medium text-slate-200">{o.agent_name}</p>
            <p className="text-xs text-slate-500">{o.output_type} · v{o.version}</p>
          </div>
          <div className="flex gap-2">
            <button
              onClick={() => decide(o.id, 'approved')}
              className="text-xs bg-emerald-800 hover:bg-emerald-700 text-emerald-200 px-3 py-1 rounded transition-colors"
            >
              Approve
            </button>
            <button
              onClick={() => decide(o.id, 'changes_requested')}
              className="text-xs bg-red-900 hover:bg-red-800 text-red-200 px-3 py-1 rounded transition-colors"
            >
              Request changes
            </button>
          </div>
        </div>
      ))}
    </div>
  )
}
```

- [ ] **Step 6: Replace `ui/src/pages/Dashboard.tsx`**

```typescript
// ui/src/pages/Dashboard.tsx
import { useParams } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { projectsApi } from '../api/endpoints'
import StatusBadge from '../components/StatusBadge'
import ReviewQueue from '../components/ReviewQueue'
import { useWebSocket } from '../hooks/useWebSocket'

export default function Dashboard() {
  const { slug } = useParams<{ slug?: string }>()
  const logs = useWebSocket(slug)

  const { data: status } = useQuery({
    queryKey: ['status', slug],
    queryFn: () => projectsApi.getStatus(slug!),
    enabled: !!slug,
    refetchInterval: 5_000,
  })

  const { data: outputs = [] } = useQuery({
    queryKey: ['outputs', slug],
    queryFn: () => projectsApi.getOutputs(slug!),
    enabled: !!slug,
    refetchInterval: 5_000,
  })

  if (!slug) {
    return (
      <div className="p-8 text-slate-400">
        <p>Select a project from the sidebar to begin.</p>
      </div>
    )
  }

  return (
    <div className="p-6 space-y-6">
      <div>
        <h2 className="text-lg font-semibold text-slate-100 mb-1">{slug}</h2>
        {status && (
          <div className="flex items-center gap-2">
            <StatusBadge status={status.project_status} />
          </div>
        )}
      </div>

      {/* Crew progress */}
      <section>
        <h3 className="text-xs font-bold text-slate-500 uppercase tracking-widest mb-3">
          Crew Progress
        </h3>
        {status?.crew_runs.length === 0 && (
          <p className="text-sm text-slate-500">No crew runs yet.</p>
        )}
        <div className="space-y-2">
          {status?.crew_runs.map((run) => (
            <div
              key={run.id}
              className="flex items-center justify-between bg-surface-card rounded-lg px-4 py-3"
            >
              <span className="text-sm text-slate-200">{run.crew_name}</span>
              <StatusBadge status={run.status} />
            </div>
          ))}
        </div>
      </section>

      {/* Review queue */}
      <section>
        <h3 className="text-xs font-bold text-slate-500 uppercase tracking-widest mb-3">
          Review Queue
        </h3>
        <ReviewQueue slug={slug} outputs={outputs} />
      </section>

      {/* Live log */}
      {logs.length > 0 && (
        <section>
          <h3 className="text-xs font-bold text-slate-500 uppercase tracking-widest mb-3">
            Agent Log
          </h3>
          <div className="bg-black/40 rounded-lg p-4 font-mono text-xs text-emerald-400 space-y-0.5 max-h-48 overflow-y-auto">
            {logs.map((line, i) => (
              <p key={i}>{line}</p>
            ))}
          </div>
        </section>
      )}
    </div>
  )
}
```

- [ ] **Step 7: Run tests**

```bash
cd ui && npm test -- --reporter=verbose
```
Expected: 2 Dashboard tests pass, all previous pass = 9 total.

- [ ] **Step 8: Commit**

```bash
cd ..
git add ui/src/pages/Dashboard.tsx ui/src/components/StatusBadge.tsx ui/src/components/ReviewQueue.tsx ui/src/hooks/useWebSocket.ts ui/src/__tests__/Dashboard.test.tsx
git commit -m "feat(sp2): dashboard — crew progress, review queue, live log

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

## Task 9: Document Library

**Files:**
- Modify: `ui/src/pages/Documents.tsx`
- Create: `ui/src/__tests__/Documents.test.tsx`

- [ ] **Step 1: Write failing Documents test**

```typescript
// ui/src/__tests__/Documents.test.tsx
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { AuthProvider } from '../context/AuthContext'
import Documents from '../pages/Documents'

const mockUpload = vi.fn().mockResolvedValue({
  id: 1,
  original_name: 'annual-report.pdf',
  filename: 'abc123.pdf',
  content_type: 'application/pdf',
  size_bytes: 1024,
  ingested: false,
  uploaded_at: '2026-04-13T10:00:00',
})

vi.mock('../api/endpoints', () => ({
  documentsApi: {
    list: vi.fn().mockResolvedValue([]),
    upload: mockUpload,
  },
  projectsApi: {
    getOutputs: vi.fn().mockResolvedValue([]),
  },
}))

function Wrapper() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return (
    <QueryClientProvider client={qc}>
      <AuthProvider>
        <MemoryRouter initialEntries={['/acme-rail/documents']}>
          <Routes>
            <Route path="/:slug/documents" element={<Documents />} />
          </Routes>
        </MemoryRouter>
      </AuthProvider>
    </QueryClientProvider>
  )
}

describe('Documents', () => {
  it('shows empty state when no documents', async () => {
    render(<Wrapper />)
    expect(await screen.findByText(/no documents/i)).toBeInTheDocument()
  })

  it('renders file upload input', () => {
    render(<Wrapper />)
    expect(screen.getByLabelText(/upload/i)).toBeInTheDocument()
  })
})
```

- [ ] **Step 2: Run to verify fail**

```bash
cd ui && npm test -- --reporter=verbose 2>&1 | grep -E "Documents|FAIL|Error" | head -10
```

- [ ] **Step 3: Replace `ui/src/pages/Documents.tsx`**

```typescript
// ui/src/pages/Documents.tsx
import { useParams } from 'react-router-dom'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useRef, ChangeEvent } from 'react'
import { documentsApi, projectsApi } from '../api/endpoints'
import type { ClientDocument, AgentOutput } from '../types'

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

export default function Documents() {
  const { slug } = useParams<{ slug: string }>()
  const qc = useQueryClient()
  const inputRef = useRef<HTMLInputElement>(null)

  const { data: clientDocs = [] } = useQuery<ClientDocument[]>({
    queryKey: ['documents', slug],
    queryFn: () => documentsApi.list(slug!),
    enabled: !!slug,
  })

  const { data: agentOutputs = [] } = useQuery<AgentOutput[]>({
    queryKey: ['outputs', slug],
    queryFn: () => projectsApi.getOutputs(slug!),
    enabled: !!slug,
  })

  async function handleFileChange(e: ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0]
    if (!file || !slug) return
    await documentsApi.upload(slug, file)
    qc.invalidateQueries({ queryKey: ['documents', slug] })
    if (inputRef.current) inputRef.current.value = ''
  }

  if (!slug) return null

  return (
    <div className="p-6 space-y-8">
      {/* Upload */}
      <section>
        <h3 className="text-xs font-bold text-slate-500 uppercase tracking-widest mb-3">
          Upload Document
        </h3>
        <label
          htmlFor="upload"
          className="block w-full border-2 border-dashed border-slate-700 hover:border-brand/50 rounded-xl p-6 text-center cursor-pointer transition-colors"
        >
          <p className="text-slate-400 text-sm">Click to upload PDF, DOCX, or XLSX</p>
          <p className="text-slate-600 text-xs mt-1">File saved to project docs/ directory</p>
        </label>
        <input
          id="upload"
          ref={inputRef}
          type="file"
          accept=".pdf,.docx,.xlsx"
          onChange={handleFileChange}
          className="hidden"
          aria-label="Upload document"
        />
      </section>

      {/* Client uploads */}
      <section>
        <h3 className="text-xs font-bold text-slate-500 uppercase tracking-widest mb-3">
          Source Documents
        </h3>
        {clientDocs.length === 0 ? (
          <p className="text-sm text-slate-500">No documents uploaded yet.</p>
        ) : (
          <div className="space-y-2">
            {clientDocs.map((doc) => (
              <div
                key={doc.id}
                className="flex items-center justify-between bg-surface-card rounded-lg px-4 py-3"
              >
                <div>
                  <p className="text-sm text-slate-200">{doc.original_name}</p>
                  <p className="text-xs text-slate-500">
                    {formatBytes(doc.size_bytes)} · {doc.ingested ? '✓ Ingested' : 'Pending ingestion'}
                  </p>
                </div>
              </div>
            ))}
          </div>
        )}
      </section>

      {/* Agent outputs */}
      <section>
        <h3 className="text-xs font-bold text-slate-500 uppercase tracking-widest mb-3">
          Agent Outputs
        </h3>
        {agentOutputs.length === 0 ? (
          <p className="text-sm text-slate-500">No outputs generated yet.</p>
        ) : (
          <div className="space-y-2">
            {agentOutputs.map((out) => (
              <div
                key={out.id}
                className="flex items-center justify-between bg-surface-card rounded-lg px-4 py-3"
              >
                <div>
                  <p className="text-sm text-slate-200">{out.agent_name}</p>
                  <p className="text-xs text-slate-500">
                    {out.output_type} · v{out.version} · {out.review_status}
                  </p>
                </div>
                <a
                  href={`http://localhost:8000/projects/${slug}/outputs/${out.id}/download`}
                  className="text-xs text-sky-400 hover:text-sky-300"
                >
                  Download
                </a>
              </div>
            ))}
          </div>
        )}
      </section>
    </div>
  )
}
```

- [ ] **Step 4: Run tests**

```bash
cd ui && npm test -- --reporter=verbose
```
Expected: 2 Documents tests pass, all previous pass = 11 total.

- [ ] **Step 5: Commit**

```bash
cd ..
git add ui/src/pages/Documents.tsx ui/src/__tests__/Documents.test.tsx
git commit -m "feat(sp2): document library — upload, source docs, agent outputs

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

## Task 10: Value Chain + Roadmap Views

**Files:**
- Modify: `ui/src/pages/ValueChain.tsx`
- Modify: `ui/src/pages/Roadmap.tsx`
- Create: `ui/src/__tests__/ValueChain.test.tsx`
- Create: `ui/src/__tests__/Roadmap.test.tsx`

- [ ] **Step 1: Write failing tests**

```typescript
// ui/src/__tests__/ValueChain.test.tsx
import { render, screen } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { AuthProvider } from '../context/AuthContext'
import ValueChain from '../pages/ValueChain'

vi.mock('../api/endpoints', () => ({
  projectsApi: {
    getValueChain: vi.fn().mockResolvedValue([]),
  },
}))

function Wrapper() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return (
    <QueryClientProvider client={qc}>
      <AuthProvider>
        <MemoryRouter initialEntries={['/acme-rail/value-chain']}>
          <Routes>
            <Route path="/:slug/value-chain" element={<ValueChain />} />
          </Routes>
        </MemoryRouter>
      </AuthProvider>
    </QueryClientProvider>
  )
}

describe('ValueChain', () => {
  it('shows empty state heading', async () => {
    render(<Wrapper />)
    expect(await screen.findByText(/value chain/i)).toBeInTheDocument()
  })

  it('shows awaiting agents message when no data', async () => {
    render(<Wrapper />)
    expect(await screen.findByText(/awaiting/i)).toBeInTheDocument()
  })
})
```

```typescript
// ui/src/__tests__/Roadmap.test.tsx
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { AuthProvider } from '../context/AuthContext'
import Roadmap from '../pages/Roadmap'

vi.mock('../api/endpoints', () => ({
  projectsApi: {
    getRoadmap: vi.fn().mockResolvedValue([]),
  },
}))

function Wrapper() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return (
    <QueryClientProvider client={qc}>
      <AuthProvider>
        <MemoryRouter initialEntries={['/acme-rail/roadmap']}>
          <Routes>
            <Route path="/:slug/roadmap" element={<Roadmap />} />
          </Routes>
        </MemoryRouter>
      </AuthProvider>
    </QueryClientProvider>
  )
}

describe('Roadmap', () => {
  it('renders Visual and Gantt tabs', () => {
    render(<Wrapper />)
    expect(screen.getByRole('tab', { name: /visual/i })).toBeInTheDocument()
    expect(screen.getByRole('tab', { name: /gantt/i })).toBeInTheDocument()
  })

  it('switches to Gantt tab on click', async () => {
    render(<Wrapper />)
    await userEvent.click(screen.getByRole('tab', { name: /gantt/i }))
    expect(screen.getByText(/gantt/i)).toBeInTheDocument()
  })
})
```

- [ ] **Step 2: Run to verify fail**

```bash
cd ui && npm test -- --reporter=verbose 2>&1 | grep -E "ValueChain|Roadmap|FAIL" | head -10
```

- [ ] **Step 3: Replace `ui/src/pages/ValueChain.tsx`**

```typescript
// ui/src/pages/ValueChain.tsx
import { useParams } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { projectsApi } from '../api/endpoints'

export default function ValueChain() {
  const { slug } = useParams<{ slug: string }>()

  const { data: outputs = [], isLoading } = useQuery({
    queryKey: ['value-chain', slug],
    queryFn: () => projectsApi.getValueChain(slug!),
    enabled: !!slug,
  })

  return (
    <div className="p-6">
      <h2 className="text-lg font-semibold text-slate-100 mb-4">Value Chain</h2>

      {isLoading && <p className="text-sm text-slate-500">Loading…</p>}

      {!isLoading && outputs.length === 0 && (
        <div className="bg-surface-card rounded-xl p-8 text-center">
          <p className="text-slate-400 text-sm">
            Awaiting Value Chain Mapper output.
          </p>
          <p className="text-slate-600 text-xs mt-2">
            Run the Discovery crew to generate the value chain analysis.
          </p>
        </div>
      )}

      {outputs.length > 0 && (
        <div className="space-y-3">
          {outputs.map((output) => (
            <div key={output.id} className="bg-surface-card rounded-lg px-4 py-3">
              <div className="flex justify-between items-center">
                <span className="text-sm text-slate-200">{output.agent_name}</span>
                <span className="text-xs text-slate-500">v{output.version} · {output.review_status}</span>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
```

- [ ] **Step 4: Replace `ui/src/pages/Roadmap.tsx`**

```typescript
// ui/src/pages/Roadmap.tsx
import { useParams } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { projectsApi } from '../api/endpoints'

type Tab = 'visual' | 'gantt'

export default function Roadmap() {
  const { slug } = useParams<{ slug: string }>()
  const [tab, setTab] = useState<Tab>('visual')

  const { data: outputs = [], isLoading } = useQuery({
    queryKey: ['roadmap', slug],
    queryFn: () => projectsApi.getRoadmap(slug!),
    enabled: !!slug,
  })

  return (
    <div className="p-6">
      <div className="flex items-center justify-between mb-4">
        <h2 className="text-lg font-semibold text-slate-100">Roadmap</h2>
        <div className="flex rounded-lg overflow-hidden border border-slate-700">
          {(['visual', 'gantt'] as Tab[]).map((t) => (
            <button
              key={t}
              role="tab"
              aria-selected={tab === t}
              onClick={() => setTab(t)}
              className={`px-4 py-1.5 text-sm capitalize transition-colors ${
                tab === t
                  ? 'bg-brand text-white'
                  : 'text-slate-400 hover:bg-slate-800'
              }`}
            >
              {t}
            </button>
          ))}
        </div>
      </div>

      {isLoading && <p className="text-sm text-slate-500">Loading…</p>}

      {!isLoading && outputs.length === 0 && (
        <div className="bg-surface-card rounded-xl p-8 text-center">
          <p className="text-slate-400 text-sm">
            {tab === 'visual'
              ? 'Awaiting Roadmap Generator output — visual timeline will appear here.'
              : 'Gantt chart will appear here once initiatives are identified.'}
          </p>
          <p className="text-slate-600 text-xs mt-2">
            Run all Discovery, Value Design, and Architecture crews to generate roadmap data.
          </p>
        </div>
      )}

      {outputs.length > 0 && tab === 'visual' && (
        <div className="bg-surface-card rounded-xl p-4">
          {/* Timeline grid — populated in SP3/SP4 when Roadmap Generator runs */}
          <div className="space-y-2">
            {outputs.map((output) => (
              <div key={output.id} className="text-sm text-slate-300">
                {output.agent_name} — {output.file_path}
              </div>
            ))}
          </div>
        </div>
      )}

      {outputs.length > 0 && tab === 'gantt' && (
        <div className="bg-surface-card rounded-xl p-4">
          <p className="text-sm text-slate-400">Gantt data available — full chart in SP4.</p>
        </div>
      )}
    </div>
  )
}
```

- [ ] **Step 5: Run all tests**

```bash
cd ui && npm test -- --reporter=verbose
```
Expected: 2 ValueChain + 2 Roadmap tests pass, all previous pass = 15 total.

- [ ] **Step 6: Commit**

```bash
cd ..
git add ui/src/pages/ValueChain.tsx ui/src/pages/Roadmap.tsx ui/src/__tests__/ValueChain.test.tsx ui/src/__tests__/Roadmap.test.tsx
git commit -m "feat(sp2): value chain + roadmap views (shells, populated in SP3/SP4)

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

## Task 11: Integration Smoke Test + Final Commit

**Files:**
- Modify: `start.sh` (add `npm run dev` for the UI)
- Create: `ui/.env` (API base URL)

- [ ] **Step 1: Verify full Python test suite**

```bash
source .venv/bin/activate && python -m pytest -v
```
Expected: all tests pass (29+ tests).

- [ ] **Step 2: Verify full frontend test suite**

```bash
cd ui && npm test -- --reporter=verbose
```
Expected: 15 tests pass.

- [ ] **Step 3: Add UI to start.sh**

In `start.sh`, add after the Chainlit launch block:

```bash
echo "Starting React UI on :3000..."
cd ui && npm run dev -- --port 3000 &
echo $! > ../.pids/ui.pid
cd ..
```

Also add to the summary:
```bash
echo "  React UI:  http://localhost:3000"
```

- [ ] **Step 4: Add UI to stop.sh**

The existing `for pid_file in .pids/*.pid` loop already handles all `.pid` files including `ui.pid` — no changes needed.

- [ ] **Step 5: Create `ui/.env`** (Vite reads this for the dev server)

```
VITE_API_BASE=http://localhost:8000
```

This is optional — the hardcoded `http://localhost:8000` in `client.ts` works for local dev. The env var can be used in a future production build.

- [ ] **Step 6: Commit**

```bash
git add start.sh ui/.env
git commit -m "feat(sp2): add React UI to start/stop scripts — SP2 complete

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

## Self-Review Notes

- All 11 tasks have complete code in every step — no TBD or placeholder logic
- Tests cover: project list, auth login/create, document upload/list, reviews, value-chain/roadmap stubs (Python); Auth context, Login, Dashboard, Documents, ValueChain, Roadmap (TypeScript)
- Type consistency: `Project`, `CrewRun`, `ProjectStatus`, `AgentOutput`, `ClientDocument`, `TokenResponse`, `UserPayload` defined in `types.ts` and used consistently across `endpoints.ts`, page components, and test mocks
- The `list_all_projects` function scans all `.db` files in `database_dir` — this is correct for the single-machine architecture where each project has its own `.db` file
- Auth is applied only to new SP2 endpoints (POST /auth/users) — SP1 endpoints remain unprotected for now; this is intentional for SP2 and will be hardened in SP4
- The `main.tsx` in Task 7 has a self-correction inline (double `QueryClient` wrapper noted and fixed)
- Roadmap and Value Chain views are structural shells — they display real data when agent outputs exist, and show correct empty states otherwise; full visual timeline is SP3/SP4
