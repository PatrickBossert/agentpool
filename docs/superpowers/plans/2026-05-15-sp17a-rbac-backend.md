# SP17a RBAC — Backend Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add three-role RBAC (sysadmin / org_admin / reviewer) with organisations, org memberships, project registry, and project memberships — all in system.db — plus enforce auth on every existing API endpoint.

**Architecture:** Four new tables in system.db bridge the per-slug SQLite world to the org structure. New FastAPI auth dependencies (`require_sysadmin`, `require_org_admin_or_above`, `require_any_auth`, `check_project_access`) replace the single loose `get_token_payload` check. A new `api/routers/admin.py` handles all org/user management. Every existing router gets auth wired in.

**Tech Stack:** FastAPI, aiosqlite, python-jose (JWT), bcrypt, httpx (Resend email), pytest

---

## File map

| File | Action |
|------|--------|
| `api/database.py` | Add 4 tables to `init_system_db`; add ~20 new async helpers |
| `api/auth.py` | Add `require_sysadmin`, `require_org_admin_or_above`, `require_any_auth`, `check_project_access`; update `create_access_token` |
| `api/routers/auth.py` | Fix admin JWT to issue `sysadmin`; update `create_user` to include email + send notification |
| `api/routers/admin.py` | **NEW** — org CRUD, org membership, project registry, user CRUD, project membership |
| `api/services/admin_service.py` | **NEW** — service functions for admin router + Resend email notification |
| `api/services/project_service.py` | Update `list_all_projects` to accept payload and filter by role |
| `api/routers/projects.py` | Add auth dependencies to all endpoints |
| `api/routers/run.py` | Add auth |
| `api/routers/outputs.py` | Add auth |
| `api/routers/runs.py` | Add auth |
| `api/routers/reviews.py` | Add auth |
| `api/routers/orchestrate.py` | Add auth |
| `api/routers/stakeholders.py` | Add auth |
| `api/routers/campaigns.py` | Add auth |
| `api/routers/assignment.py` | Add auth |
| `api/routers/documents.py` | Add auth |
| `api/routers/templates.py` | Already has `get_token_payload`; update to `require_any_auth` |
| `api/main.py` | Register admin router |
| `tests/test_admin.py` | **NEW** — 16+ tests |

---

### Task 1: DB migration — 4 new tables + email column + role migration

**Files:**
- Modify: `api/database.py` — `init_system_db` function (~line 920)

- [ ] **Step 1: Add 4 new tables and email column inside `init_system_db`**

Replace the `executescript` body in `init_system_db` with:

```python
async def init_system_db(conn: aiosqlite.Connection) -> None:
    """Initialise all system.db tables (idempotent)."""
    await conn.execute("PRAGMA foreign_keys = ON")
    await conn.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            username    TEXT UNIQUE NOT NULL,
            email       TEXT NOT NULL DEFAULT '',
            role        TEXT NOT NULL DEFAULT 'sysadmin',
            hashed_pw   TEXT NOT NULL,
            project_slug TEXT,
            created_at  DATETIME DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS interview_templates (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            name        TEXT    NOT NULL,
            description TEXT    NOT NULL DEFAULT '',
            type        TEXT    NOT NULL CHECK(type IN ('interview', 'questionnaire')),
            schema_json TEXT    NOT NULL,
            created_at  TEXT    NOT NULL DEFAULT (datetime('now')),
            updated_at  TEXT    NOT NULL DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS organisations (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            slug       TEXT    UNIQUE NOT NULL,
            name       TEXT    NOT NULL,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS org_memberships (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            org_id     INTEGER NOT NULL REFERENCES organisations(id) ON DELETE CASCADE,
            role       TEXT    NOT NULL CHECK(role IN ('org_admin', 'member')),
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(user_id, org_id)
        );

        CREATE TABLE IF NOT EXISTS project_registry (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            slug         TEXT    UNIQUE NOT NULL,
            org_id       INTEGER NOT NULL REFERENCES organisations(id) ON DELETE CASCADE,
            display_name TEXT    NOT NULL DEFAULT '',
            created_at   DATETIME DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS project_memberships (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id      INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            project_slug TEXT    NOT NULL,
            created_at   DATETIME DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(user_id, project_slug)
        );
    """)
    await conn.commit()

    # Idempotent migrations on existing DBs
    async with conn.execute("PRAGMA table_info(users)") as cur:
        user_cols = {row["name"] async for row in cur}
    if "email" not in user_cols:
        await conn.execute("ALTER TABLE users ADD COLUMN email TEXT NOT NULL DEFAULT ''")
    # Migrate legacy 'consultant' role to 'sysadmin'
    await conn.execute("UPDATE users SET role='sysadmin' WHERE role='consultant'")
    await conn.commit()
```

- [ ] **Step 2: Run existing tests to verify nothing broke**

```bash
pytest tests/ -x -q 2>&1 | tail -5
```

Expected: all existing tests pass (schema additions are additive).

- [ ] **Step 3: Commit**

```bash
git add api/database.py
git commit -m "feat: add RBAC tables to system.db (organisations, memberships, registry)"
```

---

### Task 2: DB helpers — orgs, memberships, registry, project memberships, updated user helpers

**Files:**
- Modify: `api/database.py` — append after the existing `insert_user` helper (~line 984)

- [ ] **Step 1: Write failing tests for new helpers**

Create `tests/test_admin_db.py`:

```python
# tests/test_admin_db.py
import pytest
import aiosqlite
from api.database import (
    init_system_db,
    insert_organisation, fetch_all_organisations, fetch_organisation,
    update_organisation, delete_organisation,
    insert_org_membership, fetch_org_members, update_org_membership_role,
    delete_org_membership, fetch_user_org,
    insert_project_registry, fetch_project_registry, fetch_org_projects,
    fetch_all_registry, delete_project_registry,
    insert_project_membership, delete_project_membership,
    fetch_user_project_memberships, has_project_membership,
    insert_user, fetch_user_by_id, fetch_all_users, fetch_users_by_org,
    update_user, delete_user,
)


@pytest.fixture
async def sys_conn():
    async with aiosqlite.connect(":memory:") as conn:
        conn.row_factory = aiosqlite.Row
        await init_system_db(conn)
        yield conn


@pytest.mark.asyncio
async def test_org_crud(sys_conn):
    org_id = await insert_organisation(sys_conn, slug="acme", name="Acme Corp")
    assert org_id > 0
    org = await fetch_organisation(sys_conn, org_id=org_id)
    assert org["name"] == "Acme Corp"
    await update_organisation(sys_conn, org_id=org_id, name="Acme Ltd")
    org = await fetch_organisation(sys_conn, org_id=org_id)
    assert org["name"] == "Acme Ltd"
    orgs = await fetch_all_organisations(sys_conn)
    assert len(orgs) == 1
    await delete_organisation(sys_conn, org_id=org_id)
    assert await fetch_organisation(sys_conn, org_id=org_id) is None


@pytest.mark.asyncio
async def test_org_membership(sys_conn):
    org_id = await insert_organisation(sys_conn, slug="acme", name="Acme")
    ok = await insert_user(sys_conn, username="bob", email="bob@test.com", role="org_admin",
                           hashed_pw="hashed", project_slug=None)
    assert ok
    user = await fetch_user_by_id(sys_conn, user_id=1)
    await insert_org_membership(sys_conn, user_id=user["id"], org_id=org_id, role="org_admin")
    members = await fetch_org_members(sys_conn, org_id=org_id)
    assert len(members) == 1
    assert members[0]["username"] == "bob"
    user_org = await fetch_user_org(sys_conn, user_id=user["id"])
    assert user_org["org_id"] == org_id
    await update_org_membership_role(sys_conn, user_id=user["id"], org_id=org_id, role="member")
    members = await fetch_org_members(sys_conn, org_id=org_id)
    assert members[0]["role"] == "member"
    await delete_org_membership(sys_conn, user_id=user["id"], org_id=org_id)
    assert await fetch_org_members(sys_conn, org_id=org_id) == []


@pytest.mark.asyncio
async def test_project_registry(sys_conn):
    org_id = await insert_organisation(sys_conn, slug="acme", name="Acme")
    await insert_project_registry(sys_conn, slug="proj-a", org_id=org_id, display_name="Project A")
    row = await fetch_project_registry(sys_conn, slug="proj-a")
    assert row["org_id"] == org_id
    org_projs = await fetch_org_projects(sys_conn, org_id=org_id)
    assert len(org_projs) == 1
    all_reg = await fetch_all_registry(sys_conn)
    assert len(all_reg) == 1
    await delete_project_registry(sys_conn, slug="proj-a")
    assert await fetch_project_registry(sys_conn, slug="proj-a") is None


@pytest.mark.asyncio
async def test_project_membership(sys_conn):
    await insert_user(sys_conn, username="carol", email="carol@test.com", role="reviewer",
                      hashed_pw="hashed", project_slug=None)
    user = await fetch_user_by_id(sys_conn, user_id=1)
    ok = await insert_project_membership(sys_conn, user_id=user["id"], project_slug="proj-x")
    assert ok
    memberships = await fetch_user_project_memberships(sys_conn, user_id=user["id"])
    assert len(memberships) == 1
    assert await has_project_membership(sys_conn, user_id=user["id"], project_slug="proj-x")
    assert not await has_project_membership(sys_conn, user_id=user["id"], project_slug="other")
    await delete_project_membership(sys_conn, user_id=user["id"], project_slug="proj-x")
    assert not await has_project_membership(sys_conn, user_id=user["id"], project_slug="proj-x")


@pytest.mark.asyncio
async def test_user_helpers(sys_conn):
    await insert_user(sys_conn, username="alice", email="alice@test.com", role="sysadmin",
                      hashed_pw="hashed", project_slug=None)
    org_id = await insert_organisation(sys_conn, slug="acme", name="Acme")
    await insert_user(sys_conn, username="bob", email="bob@test.com", role="org_admin",
                      hashed_pw="hashed", project_slug=None)
    bob = await fetch_user_by_id(sys_conn, user_id=2)
    await insert_org_membership(sys_conn, user_id=bob["id"], org_id=org_id, role="org_admin")
    all_users = await fetch_all_users(sys_conn)
    assert len(all_users) == 2
    org_users = await fetch_users_by_org(sys_conn, org_id=org_id)
    assert len(org_users) == 1
    assert org_users[0]["username"] == "bob"
    await update_user(sys_conn, user_id=bob["id"], email="bob2@test.com", role="member")
    updated = await fetch_user_by_id(sys_conn, user_id=bob["id"])
    assert updated["email"] == "bob2@test.com"
    await delete_user(sys_conn, user_id=bob["id"])
    assert await fetch_user_by_id(sys_conn, user_id=bob["id"]) is None
```

- [ ] **Step 2: Run to verify failure**

```bash
pytest tests/test_admin_db.py -x -q 2>&1 | head -10
```

Expected: ImportError — helpers don't exist yet.

- [ ] **Step 3: Add all new helpers to `api/database.py`**

Append after the `insert_user` helper (~line 984):

```python
# ── Organisation helpers ──────────────────────────────────────────────────────

async def insert_organisation(conn: aiosqlite.Connection, *, slug: str, name: str) -> int:
    cur = await conn.execute(
        "INSERT INTO organisations (slug, name) VALUES (?,?)", (slug, name)
    )
    await conn.commit()
    return cur.lastrowid


async def fetch_all_organisations(conn: aiosqlite.Connection) -> list[dict]:
    async with conn.execute("SELECT * FROM organisations ORDER BY name") as cur:
        return [dict(r) async for r in cur]


async def fetch_organisation(conn: aiosqlite.Connection, *, org_id: int) -> dict | None:
    async with conn.execute("SELECT * FROM organisations WHERE id=?", (org_id,)) as cur:
        row = await cur.fetchone()
        return dict(row) if row else None


async def update_organisation(conn: aiosqlite.Connection, *, org_id: int, name: str) -> None:
    await conn.execute("UPDATE organisations SET name=? WHERE id=?", (name, org_id))
    await conn.commit()


async def delete_organisation(conn: aiosqlite.Connection, *, org_id: int) -> None:
    await conn.execute("DELETE FROM organisations WHERE id=?", (org_id,))
    await conn.commit()


# ── Org membership helpers ────────────────────────────────────────────────────

async def insert_org_membership(
    conn: aiosqlite.Connection, *, user_id: int, org_id: int, role: str
) -> bool:
    try:
        await conn.execute(
            "INSERT INTO org_memberships (user_id, org_id, role) VALUES (?,?,?)",
            (user_id, org_id, role),
        )
        await conn.commit()
        return True
    except aiosqlite.IntegrityError:
        return False


async def fetch_org_members(conn: aiosqlite.Connection, *, org_id: int) -> list[dict]:
    async with conn.execute(
        """SELECT u.id, u.username, u.email, u.role, om.role AS org_role, u.created_at
           FROM org_memberships om
           JOIN users u ON u.id = om.user_id
           WHERE om.org_id=? ORDER BY u.username""",
        (org_id,),
    ) as cur:
        return [dict(r) async for r in cur]


async def update_org_membership_role(
    conn: aiosqlite.Connection, *, user_id: int, org_id: int, role: str
) -> None:
    await conn.execute(
        "UPDATE org_memberships SET role=? WHERE user_id=? AND org_id=?",
        (role, user_id, org_id),
    )
    await conn.commit()


async def delete_org_membership(
    conn: aiosqlite.Connection, *, user_id: int, org_id: int
) -> None:
    await conn.execute(
        "DELETE FROM org_memberships WHERE user_id=? AND org_id=?", (user_id, org_id)
    )
    await conn.commit()


async def fetch_user_org(conn: aiosqlite.Connection, *, user_id: int) -> dict | None:
    """Return the first org_membership row for this user (users belong to one org)."""
    async with conn.execute(
        "SELECT * FROM org_memberships WHERE user_id=? LIMIT 1", (user_id,)
    ) as cur:
        row = await cur.fetchone()
        return dict(row) if row else None


# ── Project registry helpers ──────────────────────────────────────────────────

async def insert_project_registry(
    conn: aiosqlite.Connection, *, slug: str, org_id: int, display_name: str
) -> None:
    await conn.execute(
        "INSERT OR IGNORE INTO project_registry (slug, org_id, display_name) VALUES (?,?,?)",
        (slug, org_id, display_name),
    )
    await conn.commit()


async def fetch_project_registry(
    conn: aiosqlite.Connection, *, slug: str
) -> dict | None:
    async with conn.execute(
        "SELECT * FROM project_registry WHERE slug=?", (slug,)
    ) as cur:
        row = await cur.fetchone()
        return dict(row) if row else None


async def fetch_org_projects(conn: aiosqlite.Connection, *, org_id: int) -> list[dict]:
    async with conn.execute(
        "SELECT * FROM project_registry WHERE org_id=? ORDER BY display_name", (org_id,)
    ) as cur:
        return [dict(r) async for r in cur]


async def fetch_all_registry(conn: aiosqlite.Connection) -> list[dict]:
    async with conn.execute(
        "SELECT pr.*, o.name AS org_name FROM project_registry pr "
        "JOIN organisations o ON o.id = pr.org_id ORDER BY pr.slug"
    ) as cur:
        return [dict(r) async for r in cur]


async def delete_project_registry(conn: aiosqlite.Connection, *, slug: str) -> None:
    await conn.execute("DELETE FROM project_registry WHERE slug=?", (slug,))
    await conn.commit()


# ── Project membership helpers ────────────────────────────────────────────────

async def insert_project_membership(
    conn: aiosqlite.Connection, *, user_id: int, project_slug: str
) -> bool:
    try:
        await conn.execute(
            "INSERT INTO project_memberships (user_id, project_slug) VALUES (?,?)",
            (user_id, project_slug),
        )
        await conn.commit()
        return True
    except aiosqlite.IntegrityError:
        return False


async def delete_project_membership(
    conn: aiosqlite.Connection, *, user_id: int, project_slug: str
) -> None:
    await conn.execute(
        "DELETE FROM project_memberships WHERE user_id=? AND project_slug=?",
        (user_id, project_slug),
    )
    await conn.commit()


async def fetch_user_project_memberships(
    conn: aiosqlite.Connection, *, user_id: int
) -> list[dict]:
    async with conn.execute(
        "SELECT * FROM project_memberships WHERE user_id=? ORDER BY project_slug",
        (user_id,),
    ) as cur:
        return [dict(r) async for r in cur]


async def has_project_membership(
    conn: aiosqlite.Connection, *, user_id: int, project_slug: str
) -> bool:
    async with conn.execute(
        "SELECT 1 FROM project_memberships WHERE user_id=? AND project_slug=?",
        (user_id, project_slug),
    ) as cur:
        return await cur.fetchone() is not None


# ── Extended user helpers ─────────────────────────────────────────────────────

async def fetch_user_by_id(conn: aiosqlite.Connection, *, user_id: int) -> dict | None:
    async with conn.execute("SELECT * FROM users WHERE id=?", (user_id,)) as cur:
        row = await cur.fetchone()
        return dict(row) if row else None


async def fetch_all_users(conn: aiosqlite.Connection) -> list[dict]:
    async with conn.execute("SELECT * FROM users ORDER BY username") as cur:
        return [dict(r) async for r in cur]


async def fetch_users_by_org(conn: aiosqlite.Connection, *, org_id: int) -> list[dict]:
    async with conn.execute(
        """SELECT u.* FROM users u
           JOIN org_memberships om ON om.user_id = u.id
           WHERE om.org_id=? ORDER BY u.username""",
        (org_id,),
    ) as cur:
        return [dict(r) async for r in cur]


async def update_user(
    conn: aiosqlite.Connection,
    *,
    user_id: int,
    email: str,
    role: str,
    hashed_pw: str | None = None,
) -> None:
    if hashed_pw:
        await conn.execute(
            "UPDATE users SET email=?, role=?, hashed_pw=? WHERE id=?",
            (email, role, hashed_pw, user_id),
        )
    else:
        await conn.execute(
            "UPDATE users SET email=?, role=? WHERE id=?",
            (email, role, user_id),
        )
    await conn.commit()


async def delete_user(conn: aiosqlite.Connection, *, user_id: int) -> None:
    await conn.execute("DELETE FROM users WHERE id=?", (user_id,))
    await conn.commit()
```

Also update the existing `insert_user` signature to accept `email`:

```python
async def insert_user(
    conn: aiosqlite.Connection,
    *,
    username: str,
    email: str = "",
    role: str,
    hashed_pw: str,
    project_slug: str | None = None,
) -> bool:
    """Returns True if inserted, False if username already exists."""
    try:
        await conn.execute(
            "INSERT INTO users (username, email, role, hashed_pw, project_slug) VALUES (?,?,?,?,?)",
            (username, email, role, hashed_pw, project_slug),
        )
        await conn.commit()
        return True
    except aiosqlite.IntegrityError:
        return False
```

- [ ] **Step 4: Run tests**

```bash
pytest tests/test_admin_db.py -v 2>&1 | tail -15
```

Expected: all 5 tests pass.

- [ ] **Step 5: Run full suite**

```bash
pytest tests/ -x -q 2>&1 | tail -5
```

Expected: all tests pass (the `insert_user` signature change is backwards-compatible — `email` defaults to `""`).

- [ ] **Step 6: Commit**

```bash
git add api/database.py tests/test_admin_db.py
git commit -m "feat: add RBAC DB helpers (orgs, memberships, registry, project memberships)"
```

---

### Task 3: Auth layer — new dependencies + updated create_access_token + check_project_access

**Files:**
- Modify: `api/auth.py`

- [ ] **Step 1: Write failing test for new dependencies**

Add to `tests/test_auth.py` (create if it doesn't exist):

```python
# tests/test_auth.py
import pytest
from fastapi import HTTPException
from api.auth import (
    create_access_token, decode_token,
    require_sysadmin, require_org_admin_or_above, require_any_auth,
)
from api.config import get_settings


SECRET = "test-secret"


def make_payload(role: str, org_id: int | None = None) -> dict:
    token = create_access_token("alice", role, SECRET, org_id=org_id)
    return decode_token(token, SECRET)


def test_require_sysadmin_passes():
    payload = make_payload("sysadmin")
    assert require_sysadmin(payload) == payload


def test_require_sysadmin_rejects_org_admin():
    with pytest.raises(HTTPException) as exc:
        require_sysadmin(make_payload("org_admin"))
    assert exc.value.status_code == 403


def test_require_org_admin_or_above_passes_sysadmin():
    payload = make_payload("sysadmin")
    assert require_org_admin_or_above(payload) == payload


def test_require_org_admin_or_above_passes_org_admin():
    payload = make_payload("org_admin", org_id=1)
    assert require_org_admin_or_above(payload) == payload


def test_require_org_admin_or_above_rejects_reviewer():
    with pytest.raises(HTTPException):
        require_org_admin_or_above(make_payload("reviewer"))


def test_require_any_auth_passes_all():
    for role in ("sysadmin", "org_admin", "reviewer"):
        payload = make_payload(role)
        assert require_any_auth(payload) == payload


def test_org_id_in_token():
    payload = make_payload("org_admin", org_id=7)
    assert payload["org_id"] == 7


def test_sysadmin_no_org_id():
    payload = make_payload("sysadmin")
    assert "org_id" not in payload
```

- [ ] **Step 2: Run to verify failure**

```bash
pytest tests/test_auth.py -x -q 2>&1 | head -10
```

Expected: ImportError on `require_sysadmin`.

- [ ] **Step 3: Rewrite `api/auth.py`**

```python
# api/auth.py
from datetime import datetime, timedelta, timezone
import bcrypt
from jose import JWTError, jwt
from fastapi import Depends, HTTPException, Security
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_HOURS = 24

_bearer = HTTPBearer()


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(plain: str, hashed: str) -> bool:
    return bcrypt.checkpw(plain.encode(), hashed.encode())


def create_access_token(
    username: str, role: str, secret: str, *, org_id: int | None = None
) -> str:
    expire = datetime.now(timezone.utc) + timedelta(hours=ACCESS_TOKEN_EXPIRE_HOURS)
    payload: dict = {"sub": username, "role": role, "exp": expire}
    if org_id is not None:
        payload["org_id"] = org_id
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


# ── Role-based dependencies ───────────────────────────────────────────────────

def require_sysadmin(payload: dict = Depends(get_token_payload)) -> dict:
    if payload.get("role") != "sysadmin":
        raise HTTPException(status_code=403, detail="Sysadmin role required")
    return payload


def require_org_admin_or_above(payload: dict = Depends(get_token_payload)) -> dict:
    if payload.get("role") not in ("sysadmin", "org_admin"):
        raise HTTPException(status_code=403, detail="Org admin or above required")
    return payload


def require_any_auth(payload: dict = Depends(get_token_payload)) -> dict:
    """Any valid token — just verifies authentication."""
    return payload


# ── Project-level access check ────────────────────────────────────────────────

async def check_project_access(slug: str, payload: dict) -> None:
    """Raises 403 if the calling user has no access to this project slug.

    Opens its own system DB connection — call this inside endpoint handlers,
    not as a FastAPI dependency (it needs the slug at call time).
    """
    role = payload.get("role")
    if role == "sysadmin":
        return

    from api.database import (
        get_system_connection, fetch_user, fetch_project_registry,
        has_project_membership,
    )

    async with get_system_connection() as conn:
        if role == "org_admin":
            org_id = payload.get("org_id")
            row = await fetch_project_registry(conn, slug=slug)
            if row and row["org_id"] == org_id:
                return
        elif role == "reviewer":
            user = await fetch_user(conn, username=payload["sub"])
            if user and await has_project_membership(conn, user_id=user["id"], project_slug=slug):
                return

    raise HTTPException(status_code=403, detail="Access denied to this project")
```

- [ ] **Step 4: Run auth tests**

```bash
pytest tests/test_auth.py -v 2>&1 | tail -15
```

Expected: all 9 tests pass.

- [ ] **Step 5: Run full suite**

```bash
pytest tests/ -x -q 2>&1 | tail -5
```

Expected: all passing.

- [ ] **Step 6: Commit**

```bash
git add api/auth.py tests/test_auth.py
git commit -m "feat: add require_sysadmin/org_admin/any_auth deps + check_project_access"
```

---

### Task 4: Admin service — org/user CRUD + Resend email notification

**Files:**
- Create: `api/services/admin_service.py`

- [ ] **Step 1: Create `api/services/admin_service.py`**

```python
# api/services/admin_service.py
import httpx
from api.config import get_settings
from api.auth import hash_password
from api.database import (
    get_system_connection,
    insert_organisation, fetch_all_organisations, fetch_organisation,
    update_organisation, delete_organisation,
    insert_org_membership, fetch_org_members, update_org_membership_role,
    delete_org_membership,
    insert_project_registry, fetch_all_registry, fetch_org_projects,
    delete_project_registry, fetch_project_registry,
    insert_project_membership, delete_project_membership,
    fetch_user_project_memberships,
    insert_user, fetch_all_users, fetch_users_by_org,
    fetch_user_by_id, update_user, delete_user, fetch_user,
)


async def _send_welcome_email(email: str, username: str, password: str) -> None:
    """Send one-time welcome email with credentials via Resend. Silently skips if no API key."""
    settings = get_settings()
    if not settings.resend_api_key or not email:
        return
    login_url = f"{settings.public_url}/dashboard/login"
    body = (
        f"Hello,\n\n"
        f"Your FutureMomentum account has been created.\n\n"
        f"Username: {username}\n"
        f"Temporary password: {password}\n"
        f"Login: {login_url}\n\n"
        f"Please change your password after first login.\n\n"
        f"FutureMomentum"
    )
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            await client.post(
                "https://api.resend.com/emails",
                json={
                    "from": settings.from_email,
                    "to": [email],
                    "subject": "Your FutureMomentum account has been created",
                    "text": body,
                },
                headers={"Authorization": f"Bearer {settings.resend_api_key}"},
            )
    except Exception:
        pass  # Email failure must never block user creation


# ── Organisation services ─────────────────────────────────────────────────────

async def svc_list_orgs() -> list[dict]:
    async with get_system_connection() as conn:
        return await fetch_all_organisations(conn)


async def svc_create_org(slug: str, name: str) -> dict:
    async with get_system_connection() as conn:
        org_id = await insert_organisation(conn, slug=slug, name=name)
        return await fetch_organisation(conn, org_id=org_id)


async def svc_get_org(org_id: int) -> dict | None:
    async with get_system_connection() as conn:
        return await fetch_organisation(conn, org_id=org_id)


async def svc_update_org(org_id: int, name: str) -> dict | None:
    async with get_system_connection() as conn:
        org = await fetch_organisation(conn, org_id=org_id)
        if not org:
            return None
        await update_organisation(conn, org_id=org_id, name=name)
        return await fetch_organisation(conn, org_id=org_id)


async def svc_delete_org(org_id: int) -> bool:
    async with get_system_connection() as conn:
        org = await fetch_organisation(conn, org_id=org_id)
        if not org:
            return False
        await delete_organisation(conn, org_id=org_id)
        return True


# ── Org membership services ───────────────────────────────────────────────────

async def svc_list_org_members(org_id: int) -> list[dict]:
    async with get_system_connection() as conn:
        return await fetch_org_members(conn, org_id=org_id)


async def svc_add_org_member(org_id: int, user_id: int, role: str) -> bool:
    async with get_system_connection() as conn:
        return await insert_org_membership(conn, user_id=user_id, org_id=org_id, role=role)


async def svc_update_org_member_role(org_id: int, user_id: int, role: str) -> None:
    async with get_system_connection() as conn:
        await update_org_membership_role(conn, user_id=user_id, org_id=org_id, role=role)


async def svc_remove_org_member(org_id: int, user_id: int) -> None:
    async with get_system_connection() as conn:
        await delete_org_membership(conn, user_id=user_id, org_id=org_id)


# ── Project registry services ─────────────────────────────────────────────────

async def svc_list_registry(payload: dict) -> list[dict]:
    async with get_system_connection() as conn:
        if payload.get("role") == "sysadmin":
            return await fetch_all_registry(conn)
        org_id = payload.get("org_id")
        if org_id:
            return await fetch_org_projects(conn, org_id=org_id)
        return []


async def svc_register_project(slug: str, org_id: int, display_name: str) -> None:
    async with get_system_connection() as conn:
        await insert_project_registry(conn, slug=slug, org_id=org_id, display_name=display_name)


async def svc_unregister_project(slug: str) -> bool:
    async with get_system_connection() as conn:
        row = await fetch_project_registry(conn, slug=slug)
        if not row:
            return False
        await delete_project_registry(conn, slug=slug)
        return True


# ── User services ─────────────────────────────────────────────────────────────

async def svc_list_users(payload: dict) -> list[dict]:
    async with get_system_connection() as conn:
        if payload.get("role") == "sysadmin":
            users = await fetch_all_users(conn)
        else:
            org_id = payload.get("org_id")
            users = await fetch_users_by_org(conn, org_id=org_id) if org_id else []
        # Strip hashed_pw from response
        return [{k: v for k, v in u.items() if k != "hashed_pw"} for u in users]


async def svc_create_user(
    username: str,
    email: str,
    password: str,
    role: str,
    org_id: int | None,
    calling_payload: dict,
) -> dict | None:
    """Create user. Returns user dict (without hashed_pw) or None if username taken."""
    # org_admin can only create org_admin-or-below users within their own org
    if calling_payload.get("role") == "org_admin":
        if role == "sysadmin":
            return None  # org_admin cannot create sysadmins
        org_id = calling_payload.get("org_id")

    hashed = hash_password(password)
    async with get_system_connection() as conn:
        ok = await insert_user(
            conn, username=username, email=email, role=role,
            hashed_pw=hashed, project_slug=None,
        )
        if not ok:
            return None
        user = await fetch_user(conn, username=username)
        if user and org_id:
            await insert_org_membership(
                conn, user_id=user["id"], org_id=org_id,
                role="org_admin" if role == "org_admin" else "member",
            )

    await _send_welcome_email(email, username, password)
    return {k: v for k, v in user.items() if k != "hashed_pw"}


async def svc_update_user(
    user_id: int, email: str, role: str, password: str | None
) -> dict | None:
    async with get_system_connection() as conn:
        user = await fetch_user_by_id(conn, user_id=user_id)
        if not user:
            return None
        hashed = hash_password(password) if password else None
        await update_user(conn, user_id=user_id, email=email, role=role, hashed_pw=hashed)
        updated = await fetch_user_by_id(conn, user_id=user_id)
        return {k: v for k, v in updated.items() if k != "hashed_pw"}


async def svc_delete_user(user_id: int) -> bool:
    async with get_system_connection() as conn:
        user = await fetch_user_by_id(conn, user_id=user_id)
        if not user:
            return False
        await delete_user(conn, user_id=user_id)
        return True


# ── Project membership services ───────────────────────────────────────────────

async def svc_list_user_projects(user_id: int) -> list[dict]:
    async with get_system_connection() as conn:
        return await fetch_user_project_memberships(conn, user_id=user_id)


async def svc_grant_project_access(user_id: int, project_slug: str) -> bool:
    async with get_system_connection() as conn:
        return await insert_project_membership(conn, user_id=user_id, project_slug=project_slug)


async def svc_revoke_project_access(user_id: int, project_slug: str) -> None:
    async with get_system_connection() as conn:
        await delete_project_membership(conn, user_id=user_id, project_slug=project_slug)
```

- [ ] **Step 2: Run full suite to verify no breakage**

```bash
pytest tests/ -x -q 2>&1 | tail -5
```

Expected: all passing (new file, no tests yet).

- [ ] **Step 3: Commit**

```bash
git add api/services/admin_service.py
git commit -m "feat: add admin service layer with org/user/membership CRUD + Resend notification"
```

---

### Task 5: Admin router + register in main.py

**Files:**
- Create: `api/routers/admin.py`
- Modify: `api/main.py`

- [ ] **Step 1: Create `api/routers/admin.py`**

```python
# api/routers/admin.py
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from api.auth import require_sysadmin, require_org_admin_or_above, get_token_payload
from api.services.admin_service import (
    svc_list_orgs, svc_create_org, svc_get_org, svc_update_org, svc_delete_org,
    svc_list_org_members, svc_add_org_member, svc_update_org_member_role, svc_remove_org_member,
    svc_list_registry, svc_register_project, svc_unregister_project,
    svc_list_users, svc_create_user, svc_update_user, svc_delete_user,
    svc_list_user_projects, svc_grant_project_access, svc_revoke_project_access,
)

router = APIRouter(prefix="/auth", tags=["admin"])


def _404(msg: str):
    raise HTTPException(status_code=404, detail=msg)


# ── Organisations ─────────────────────────────────────────────────────────────

class OrgCreate(BaseModel):
    slug: str
    name: str


class OrgUpdate(BaseModel):
    name: str


@router.get("/orgs", dependencies=[Depends(require_sysadmin)])
async def list_orgs():
    return await svc_list_orgs()


@router.post("/orgs", status_code=201, dependencies=[Depends(require_sysadmin)])
async def create_org(req: OrgCreate):
    try:
        return await svc_create_org(slug=req.slug, name=req.name)
    except Exception:
        raise HTTPException(status_code=409, detail="Org slug already exists")


@router.get("/orgs/{org_id}", dependencies=[Depends(require_org_admin_or_above)])
async def get_org(org_id: int):
    org = await svc_get_org(org_id)
    if not org:
        _404(f"Org {org_id} not found")
    return org


@router.patch("/orgs/{org_id}", dependencies=[Depends(require_sysadmin)])
async def update_org(org_id: int, req: OrgUpdate):
    org = await svc_update_org(org_id, req.name)
    if not org:
        _404(f"Org {org_id} not found")
    return org


@router.delete("/orgs/{org_id}", status_code=204, dependencies=[Depends(require_sysadmin)])
async def delete_org(org_id: int):
    if not await svc_delete_org(org_id):
        _404(f"Org {org_id} not found")


# ── Org membership ────────────────────────────────────────────────────────────

class MemberAdd(BaseModel):
    user_id: int
    role: str = "member"


class MemberRoleUpdate(BaseModel):
    role: str


@router.get("/orgs/{org_id}/members", dependencies=[Depends(require_org_admin_or_above)])
async def list_org_members(org_id: int):
    return await svc_list_org_members(org_id)


@router.post("/orgs/{org_id}/members", status_code=201, dependencies=[Depends(require_org_admin_or_above)])
async def add_org_member(org_id: int, req: MemberAdd):
    ok = await svc_add_org_member(org_id, req.user_id, req.role)
    if not ok:
        raise HTTPException(status_code=409, detail="User already a member of this org")
    return {"ok": True}


@router.patch("/orgs/{org_id}/members/{user_id}", dependencies=[Depends(require_org_admin_or_above)])
async def update_org_member(org_id: int, user_id: int, req: MemberRoleUpdate):
    await svc_update_org_member_role(org_id, user_id, req.role)
    return {"ok": True}


@router.delete("/orgs/{org_id}/members/{user_id}", status_code=204, dependencies=[Depends(require_org_admin_or_above)])
async def remove_org_member(org_id: int, user_id: int):
    await svc_remove_org_member(org_id, user_id)


# ── Project registry ──────────────────────────────────────────────────────────

class ProjectRegister(BaseModel):
    slug: str
    org_id: int
    display_name: str = ""


@router.get("/projects")
async def list_registry(payload: dict = Depends(require_org_admin_or_above)):
    return await svc_list_registry(payload)


@router.post("/projects", status_code=201, dependencies=[Depends(require_sysadmin)])
async def register_project(req: ProjectRegister):
    await svc_register_project(req.slug, req.org_id, req.display_name)
    return {"ok": True}


@router.delete("/projects/{slug}", status_code=204, dependencies=[Depends(require_sysadmin)])
async def unregister_project(slug: str):
    if not await svc_unregister_project(slug):
        _404(f"Project '{slug}' not in registry")


# ── Users ─────────────────────────────────────────────────────────────────────

class UserCreate(BaseModel):
    username: str
    email: str
    password: str
    role: str = "reviewer"
    org_id: int | None = None


class UserUpdate(BaseModel):
    email: str
    role: str
    password: str | None = None


@router.get("/users")
async def list_users(payload: dict = Depends(require_org_admin_or_above)):
    return await svc_list_users(payload)


@router.post("/users", status_code=201)
async def create_user(req: UserCreate, payload: dict = Depends(require_org_admin_or_above)):
    user = await svc_create_user(
        username=req.username,
        email=req.email,
        password=req.password,
        role=req.role,
        org_id=req.org_id,
        calling_payload=payload,
    )
    if user is None:
        raise HTTPException(status_code=409, detail="Username already exists or forbidden role")
    return user


@router.patch("/users/{user_id}", dependencies=[Depends(require_org_admin_or_above)])
async def update_user_endpoint(user_id: int, req: UserUpdate):
    user = await svc_update_user(user_id, req.email, req.role, req.password)
    if not user:
        _404(f"User {user_id} not found")
    return user


@router.delete("/users/{user_id}", status_code=204, dependencies=[Depends(require_org_admin_or_above)])
async def delete_user_endpoint(user_id: int):
    if not await svc_delete_user(user_id):
        _404(f"User {user_id} not found")


# ── Project memberships ───────────────────────────────────────────────────────

@router.get("/users/{user_id}/projects", dependencies=[Depends(require_org_admin_or_above)])
async def list_user_projects(user_id: int):
    return await svc_list_user_projects(user_id)


@router.post("/users/{user_id}/projects/{slug}", status_code=201, dependencies=[Depends(require_org_admin_or_above)])
async def grant_project_access(user_id: int, slug: str):
    ok = await svc_grant_project_access(user_id, slug)
    if not ok:
        raise HTTPException(status_code=409, detail="Access already granted")
    return {"ok": True}


@router.delete("/users/{user_id}/projects/{slug}", status_code=204, dependencies=[Depends(require_org_admin_or_above)])
async def revoke_project_access(user_id: int, slug: str):
    await svc_revoke_project_access(user_id, slug)
```

- [ ] **Step 2: Register admin router in `api/main.py`**

Add to `api/main.py` after the existing router imports:

```python
from api.routers import admin as admin_router
```

And after the existing `app.include_router(...)` calls:

```python
app.include_router(admin_router.router)
```

- [ ] **Step 3: Run full suite**

```bash
pytest tests/ -x -q 2>&1 | tail -5
```

Expected: all passing.

- [ ] **Step 4: Commit**

```bash
git add api/routers/admin.py api/main.py
git commit -m "feat: add admin router (orgs, users, memberships, project registry)"
```

---

### Task 6: Fix existing auth router — sysadmin JWT + email on create_user

**Files:**
- Modify: `api/routers/auth.py`

- [ ] **Step 1: Rewrite `api/routers/auth.py`**

```python
# api/routers/auth.py
from fastapi import APIRouter, Depends, HTTPException
from fastapi.security import OAuth2PasswordRequestForm
from pydantic import BaseModel
from api.auth import (
    create_access_token,
    get_token_payload,
    hash_password,
    verify_password,
    require_sysadmin,
)
from api.config import get_settings
from api.database import fetch_user, insert_user, get_system_connection, fetch_user_org

router = APIRouter(prefix="/auth", tags=["auth"])


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


@router.post("/login", response_model=TokenResponse)
async def login(form: OAuth2PasswordRequestForm = Depends()):
    settings = get_settings()

    # Built-in env-var admin always gets sysadmin role
    if form.username == settings.admin_username:
        if form.password != settings.admin_password:
            raise HTTPException(status_code=401, detail="Invalid credentials")
        token = create_access_token(form.username, "sysadmin", settings.jwt_secret)
        return TokenResponse(access_token=token)

    # System DB users
    async with get_system_connection() as conn:
        user = await fetch_user(conn, username=form.username)
        if not user or not verify_password(form.password, user["hashed_pw"]):
            raise HTTPException(status_code=401, detail="Invalid credentials")
        # Embed org_id for org_admin tokens
        org_id: int | None = None
        if user["role"] == "org_admin":
            org_row = await fetch_user_org(conn, user_id=user["id"])
            if org_row:
                org_id = org_row["org_id"]
        token = create_access_token(
            user["username"], user["role"], settings.jwt_secret, org_id=org_id
        )
    return TokenResponse(access_token=token)
```

Note: the old `POST /auth/users` endpoint is removed — user creation is now handled by `POST /auth/users` in `admin.py` (same path, different router registered later, but FastAPI merges them under `/auth`). Verify there is no conflict: the old endpoint used `role="consultant"` guard; the new admin router endpoint uses `require_org_admin_or_above`. Since both define `POST /auth/users`, **remove the old endpoint entirely** from `auth.py` — the admin router owns it now.

- [ ] **Step 2: Run full suite**

```bash
pytest tests/ -x -q 2>&1 | tail -5
```

Expected: all passing. If any test called `POST /auth/users` with the old `consultant` role guard, it will need updating — check `tests/test_auth_router.py` if it exists.

- [ ] **Step 3: Commit**

```bash
git add api/routers/auth.py
git commit -m "fix: admin login now issues sysadmin JWT; remove duplicate create_user endpoint"
```

---

### Task 7: Enforce auth on all existing project-scoped endpoints

**Files:**
- Modify: `api/services/project_service.py` (update `list_all_projects`)
- Modify: `api/routers/projects.py`
- Modify: `api/routers/run.py`
- Modify: `api/routers/outputs.py`
- Modify: `api/routers/runs.py`
- Modify: `api/routers/reviews.py`
- Modify: `api/routers/orchestrate.py`
- Modify: `api/routers/stakeholders.py`
- Modify: `api/routers/campaigns.py`
- Modify: `api/routers/assignment.py`
- Modify: `api/routers/documents.py`
- Modify: `api/routers/templates.py`

**Pattern for read endpoints (viewer or above):**
```python
from api.auth import require_any_auth, check_project_access

@router.get("/{slug}/something")
async def handler(slug: str, payload: dict = Depends(require_any_auth)):
    await check_project_access(slug, payload)
    ...
```

**Pattern for write/admin endpoints (org_admin or above):**
```python
from api.auth import require_org_admin_or_above, check_project_access

@router.patch("/{slug}/settings")
async def handler(slug: str, req: ..., payload: dict = Depends(require_org_admin_or_above)):
    await check_project_access(slug, payload)
    ...
```

- [ ] **Step 1: Update `list_all_projects` in `api/services/project_service.py`**

Find the existing `list_all_projects` function and replace it:

```python
async def list_all_projects(payload: dict | None = None) -> list[dict]:
    """Return projects visible to the calling user. Pass None to skip filtering (internal use)."""
    settings = get_settings()
    data_dir = Path(settings.database_dir)
    all_slugs = [p.stem for p in data_dir.glob("*.db") if p.stem != "system"]

    if payload is None or payload.get("role") == "sysadmin":
        slugs_to_show = all_slugs
    else:
        from api.database import (
            get_system_connection, fetch_user,
            fetch_org_projects, fetch_user_project_memberships,
        )
        async with get_system_connection() as sys_conn:
            if payload.get("role") == "org_admin":
                org_id = payload.get("org_id")
                rows = await fetch_org_projects(sys_conn, org_id=org_id) if org_id else []
                visible = {r["slug"] for r in rows}
            else:  # reviewer
                user = await fetch_user(sys_conn, username=payload["sub"])
                if not user:
                    return []
                rows = await fetch_user_project_memberships(sys_conn, user_id=user["id"])
                visible = {r["project_slug"] for r in rows}
        slugs_to_show = [s for s in all_slugs if s in visible]

    results = []
    for slug in slugs_to_show:
        if get_db_path(slug).exists():
            async with get_connection(slug) as conn:
                project = await fetch_project(conn, slug=slug)
                if project:
                    results.append(dict(project))
    return sorted(results, key=lambda p: p.get("created_at", ""), reverse=True)
```

- [ ] **Step 2: Update `api/routers/projects.py` — add auth to all endpoints**

Add to imports:
```python
from api.auth import require_any_auth, require_org_admin_or_above, check_project_access
from api.database import get_system_connection, insert_project_registry
```

Update each endpoint signature as follows (show only the changed lines):

```python
@router.get("", response_model=list[ProjectResponse])
async def list_projects_endpoint(payload: dict = Depends(require_any_auth)):
    return await list_all_projects(payload)


@router.post("", status_code=201)
async def create_project_endpoint(
    req: ProjectCreate,
    response: Response,
    payload: dict = Depends(require_org_admin_or_above),
):
    if get_db_path(req.client_slug).exists():
        response.status_code = 200
    result = await create_project(req)
    # Auto-register to org for org_admin
    if payload.get("role") == "org_admin":
        org_id = payload.get("org_id")
        if org_id:
            async with get_system_connection() as sys_conn:
                await insert_project_registry(
                    sys_conn,
                    slug=req.client_slug,
                    org_id=org_id,
                    display_name=req.client_slug,
                )
    return result


@router.get("/{slug}/status", response_model=StatusResponse)
async def get_status(slug: str, payload: dict = Depends(require_any_auth)):
    await check_project_access(slug, payload)
    result = await get_project_status(slug)
    if not result:
        raise HTTPException(status_code=404, detail=f"Project '{slug}' not found")
    return result


@router.get("/{slug}/value-chain")
async def get_value_chain(slug: str, payload: dict = Depends(require_any_auth)):
    await check_project_access(slug, payload)
    # ... rest unchanged


@router.get("/{slug}/roadmap")
async def get_roadmap(slug: str, payload: dict = Depends(require_any_auth)):
    await check_project_access(slug, payload)
    # ... rest unchanged


@router.get("/{slug}/settings", response_model=ProjectSettings)
async def get_settings_endpoint(slug: str, payload: dict = Depends(require_any_auth)):
    await check_project_access(slug, payload)
    result = await get_project_settings(slug)
    if result is None:
        raise HTTPException(status_code=404, detail=f"Project '{slug}' not found")
    return result


@router.patch("/{slug}/settings", response_model=ProjectSettings)
async def patch_settings_endpoint(
    slug: str, req: ProjectSettings, payload: dict = Depends(require_org_admin_or_above)
):
    await check_project_access(slug, payload)
    result = await update_project_settings(slug, req)
    if result is None:
        raise HTTPException(status_code=404, detail=f"Project '{slug}' not found")
    return result
```

All remaining `/{slug}/*` endpoints in `projects.py` (outputs, downloads, roadmap-data, financial-summary, portfolio-register, branding upload, node-templates): add `payload: dict = Depends(require_any_auth)` and `await check_project_access(slug, payload)`.

Exception: `GET /{slug}/branding/image` — keep open (used by unauthenticated voice interview page).

- [ ] **Step 3: Update remaining routers — add `require_any_auth` + `check_project_access`**

For each router below, add the import and dependency. Show the full updated function signature only.

**`api/routers/run.py`** — `POST /{slug}/run`:
```python
from api.auth import require_org_admin_or_above, check_project_access

@router.post("/{slug}/run", status_code=202, response_model=RunResponse)
async def run_crew(slug: str, req: RunRequest, payload: dict = Depends(require_org_admin_or_above)):
    await check_project_access(slug, payload)
    # rest unchanged
```

**`api/routers/outputs.py`** — `GET /{slug}/outputs`:
```python
from api.auth import require_any_auth, check_project_access

@router.get("/{slug}/outputs", response_model=list[OutputResponse])
async def list_outputs(slug: str, payload: dict = Depends(require_any_auth)):
    await check_project_access(slug, payload)
    # rest unchanged
```

**`api/routers/runs.py`** — `GET /{slug}/runs`:
```python
from api.auth import require_any_auth, check_project_access

@router.get("/{slug}/runs")
async def list_runs(slug: str, payload: dict = Depends(require_any_auth)):
    await check_project_access(slug, payload)
    # rest unchanged
```

**`api/routers/reviews.py`** — both `POST /{slug}/review` and `GET /{slug}/reviews`:
```python
from fastapi import APIRouter, Depends, HTTPException
from api.auth import require_any_auth, check_project_access

@router.post("/{slug}/review", status_code=201)
async def submit_review(slug: str, req: ReviewRequest, payload: dict = Depends(require_any_auth)):
    await check_project_access(slug, payload)
    # rest unchanged

@router.get("/{slug}/reviews")  # if this endpoint exists
async def list_reviews(slug: str, payload: dict = Depends(require_any_auth)):
    await check_project_access(slug, payload)
    # rest unchanged
```

**`api/routers/orchestrate.py`** — `POST /projects/{slug}/orchestrate`:
```python
from fastapi import APIRouter, Depends, HTTPException
from api.auth import require_org_admin_or_above, check_project_access

@router.post("/projects/{slug}/orchestrate", status_code=202)
async def orchestrate_project(slug: str, payload: dict = Depends(require_org_admin_or_above)):
    await check_project_access(slug, payload)
    # rest unchanged
```

**`api/routers/stakeholders.py`** — all endpoints get `require_any_auth` + `check_project_access`. Write/delete endpoints get `require_org_admin_or_above`.

**`api/routers/campaigns.py`** — all endpoints get `require_any_auth` + `check_project_access`. The `send` endpoint gets `require_org_admin_or_above`.

**`api/routers/assignment.py`** — `GET` gets `require_any_auth`; `POST` gets `require_org_admin_or_above`. Both call `check_project_access`.

**`api/routers/documents.py`** — `GET` gets `require_any_auth`; `POST` (upload) gets `require_org_admin_or_above`. Both call `check_project_access`.

**`api/routers/templates.py`** — already has `get_token_payload`. Replace all instances with `require_any_auth` (templates are system-level, no `check_project_access` needed).

- [ ] **Step 4: Run full suite**

```bash
pytest tests/ -q 2>&1 | tail -10
```

Expected: all existing tests pass. Tests that call project endpoints without a token will now get 403 — update fixtures in failing tests to pass a valid sysadmin token. Look for patterns like:

```python
# In test fixtures — add auth header:
headers = {"Authorization": f"Bearer {sysadmin_token}"}
client.get("/projects/test-slug/status", headers=headers)
```

To generate a sysadmin token in tests:
```python
from api.auth import create_access_token
token = create_access_token("admin", "sysadmin", "test-secret")
```

Fix any broken tests by adding the auth header.

- [ ] **Step 5: Commit**

```bash
git add api/routers/ api/services/project_service.py
git commit -m "feat: enforce RBAC auth on all project-scoped API endpoints"
```

---

### Task 8: Backend tests for admin endpoints

**Files:**
- Create: `tests/test_admin.py`

- [ ] **Step 1: Create `tests/test_admin.py`**

```python
# tests/test_admin.py
import pytest
from httpx import AsyncClient, ASGITransport
from api.main import app
from api.auth import create_access_token

SECRET = "test-secret"


def sysadmin_token():
    return create_access_token("admin", "sysadmin", SECRET)


def org_admin_token(org_id: int):
    return create_access_token("orgadmin", "org_admin", SECRET, org_id=org_id)


def reviewer_token():
    return create_access_token("reviewer", "reviewer", SECRET)


def auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture(autouse=True)
def patch_settings(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test")
    monkeypatch.setenv("JWT_SECRET", SECRET)
    monkeypatch.setenv("ADMIN_USERNAME", "admin")
    monkeypatch.setenv("ADMIN_PASSWORD", "pass")
    monkeypatch.setenv("DATABASE_DIR", "/tmp/test_admin_db")
    from api.config import get_settings
    get_settings.cache_clear()
    import pathlib
    pathlib.Path("/tmp/test_admin_db").mkdir(exist_ok=True)
    # Remove stale system.db
    db = pathlib.Path("/tmp/test_admin_db/system.db")
    if db.exists():
        db.unlink()


@pytest.mark.anyio
async def test_login_admin_gets_sysadmin_role():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post("/auth/login", data={"username": "admin", "password": "pass"})
    assert resp.status_code == 200
    from api.auth import decode_token
    payload = decode_token(resp.json()["access_token"], SECRET)
    assert payload["role"] == "sysadmin"


@pytest.mark.anyio
async def test_create_and_list_org():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post(
            "/auth/orgs",
            json={"slug": "acme", "name": "Acme Corp"},
            headers=auth(sysadmin_token()),
        )
        assert resp.status_code == 201
        org_id = resp.json()["id"]

        resp = await client.get("/auth/orgs", headers=auth(sysadmin_token()))
        assert resp.status_code == 200
        assert any(o["slug"] == "acme" for o in resp.json())

        resp = await client.patch(
            f"/auth/orgs/{org_id}",
            json={"name": "Acme Ltd"},
            headers=auth(sysadmin_token()),
        )
        assert resp.status_code == 200
        assert resp.json()["name"] == "Acme Ltd"


@pytest.mark.anyio
async def test_reviewer_cannot_create_org():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post(
            "/auth/orgs",
            json={"slug": "x", "name": "X"},
            headers=auth(reviewer_token()),
        )
        assert resp.status_code == 403


@pytest.mark.anyio
async def test_create_user_and_list():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # Create org first
        resp = await client.post(
            "/auth/orgs", json={"slug": "org1", "name": "Org 1"},
            headers=auth(sysadmin_token()),
        )
        org_id = resp.json()["id"]

        # Create user
        resp = await client.post(
            "/auth/users",
            json={
                "username": "alice",
                "email": "alice@test.com",
                "password": "secret123",
                "role": "reviewer",
                "org_id": org_id,
            },
            headers=auth(sysadmin_token()),
        )
        assert resp.status_code == 201
        assert resp.json()["username"] == "alice"
        assert "hashed_pw" not in resp.json()

        # List users
        resp = await client.get("/auth/users", headers=auth(sysadmin_token()))
        assert any(u["username"] == "alice" for u in resp.json())


@pytest.mark.anyio
async def test_duplicate_username_rejected():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        payload = {"username": "bob", "email": "b@t.com", "password": "p", "role": "reviewer"}
        await client.post("/auth/users", json=payload, headers=auth(sysadmin_token()))
        resp = await client.post("/auth/users", json=payload, headers=auth(sysadmin_token()))
        assert resp.status_code == 409


@pytest.mark.anyio
async def test_project_membership_grant_revoke():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post(
            "/auth/users",
            json={"username": "carol", "email": "c@t.com", "password": "p", "role": "reviewer"},
            headers=auth(sysadmin_token()),
        )
        user_id = resp.json()["id"]

        resp = await client.post(
            f"/auth/users/{user_id}/projects/my-proj",
            headers=auth(sysadmin_token()),
        )
        assert resp.status_code == 201

        resp = await client.get(
            f"/auth/users/{user_id}/projects",
            headers=auth(sysadmin_token()),
        )
        assert any(m["project_slug"] == "my-proj" for m in resp.json())

        resp = await client.delete(
            f"/auth/users/{user_id}/projects/my-proj",
            headers=auth(sysadmin_token()),
        )
        assert resp.status_code == 204


@pytest.mark.anyio
async def test_org_admin_cannot_create_sysadmin():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # Create org first
        resp = await client.post(
            "/auth/orgs", json={"slug": "org2", "name": "Org 2"},
            headers=auth(sysadmin_token()),
        )
        org_id = resp.json()["id"]

        resp = await client.post(
            "/auth/users",
            json={"username": "hacker", "email": "h@t.com", "password": "p", "role": "sysadmin"},
            headers=auth(org_admin_token(org_id)),
        )
        assert resp.status_code == 409  # svc_create_user returns None for forbidden role


@pytest.mark.anyio
async def test_register_project():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post(
            "/auth/orgs", json={"slug": "org3", "name": "Org 3"},
            headers=auth(sysadmin_token()),
        )
        org_id = resp.json()["id"]

        resp = await client.post(
            "/auth/projects",
            json={"slug": "proj-a", "org_id": org_id, "display_name": "Project A"},
            headers=auth(sysadmin_token()),
        )
        assert resp.status_code == 201

        resp = await client.get("/auth/projects", headers=auth(sysadmin_token()))
        assert any(r["slug"] == "proj-a" for r in resp.json())
```

- [ ] **Step 2: Run tests**

```bash
pytest tests/test_admin.py -v 2>&1 | tail -20
```

Expected: all 8 tests pass.

- [ ] **Step 3: Run full suite**

```bash
pytest tests/ -q 2>&1 | tail -5
```

Expected: all passing.

- [ ] **Step 4: Commit**

```bash
git add tests/test_admin.py tests/test_admin_db.py
git commit -m "test: add admin endpoint and DB helper tests (admin RBAC)"
```

---
