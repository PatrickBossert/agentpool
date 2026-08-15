# User Administration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make a person's rights live on the record that holds their name, so authority is read rather than inferred by matching email text.

**Architecture:** `stakeholders` becomes the project person and carries five role flags. `users` shrinks to identity, credentials, and a global `is_sys_admin`. `project_memberships` gains `stakeholder_id` and becomes the link, so authority is a walk - JWT, user, membership for this slug, stakeholder row, flag - with no text comparison anywhere. An invite and reset loop shares one token table, and every gate reads one authority function.

**Tech Stack:** Python 3.13, FastAPI, aiosqlite (raw SQL, no ORM), python-jose JWT, bcrypt direct, React 18 + TypeScript + Vite + Tailwind v3, pytest, Vitest.

## Global Constraints

- British English throughout: `-ise` not `-ize`, `-our` not `-or` - organise, behaviour, artefact, favour, centre.
- Short en dash ` - ` with spaces in prose. Never an em dash (`—`).
- Oxford comma in lists of three or more items.
- **No emoji in rendered web content** - stylised Lucide React icons only.
- Tailwind `brand` / `surface` / `text-*` tokens. **Never `sky-*` or `blue-*`.**
- Python 3.13 only: `./venv/bin/pytest`, `./venv/bin/python`. Never system python.
- Frontend commands run from `ui/`: `npx vitest run`, `npx tsc --noEmit`.
- **bcrypt direct, never passlib** - passlib is incompatible with bcrypt 5.x on this Python. Use `hash_password` / `verify_password` from `api/auth.py`.
- **Never run `pytest -m integration`** - it calls the real Anthropic API and costs money.
- **Run the backend suite twice** and confirm identical counts. `tests/conftest.py` points `DATABASE_DIR` at a fixed path that persists between runs, so a test writing a hardcoded row id passes once and fails ever after.
- Adding a `_migrate_*` function to a **project** database requires bumping `_SCHEMA_VERSION` in `api/database.py` in the same change and adding the call to the migration block in `get_connection`. `_SCHEMA_VERSION` is currently **5**. The **system** database is initialised by `init_system_db`, which is idempotent and carries no version gate.
- **Never write to `data/sp-gs-am.db`** - it holds a live engagement. Read-only checks are fine.
- Do not restart the API server while a crew run is in flight. Do not run a crew.

---

## File Structure

| File | Responsibility |
|---|---|
| `api/database.py` | `_migrate_stakeholder_roles`, `_SCHEMA_VERSION` bump, `init_system_db` gains `is_sys_admin`, `project_memberships.stakeholder_id`, and `auth_tokens` |
| `api/services/authority_service.py` | new - `caller_roles`, the single authority walk |
| `api/services/invite_service.py` | new - issue, re-issue, accept, and reset, over one token table |
| `api/routers/invites.py` | new - accept and reset endpoints, unauthenticated by design |
| `api/routers/stakeholders.py` | role flags on create and update; issuing an invite is a consequence of a role change |
| `api/services/commit_service.py` | `_caller_matches_stakeholder_flag` removed |
| `api/routers/script_reviews.py`, `api/routers/projects.py`, `api/routers/permissions.py` | switched onto `caller_roles` |
| `api/services/script_review_service.py` | forced approval recorded as such |
| `ui/src/pages/AcceptInvite.tsx` | new - set a password from an invite or reset link |
| `ui/src/context/AuthContext.tsx` | rolling token, and the post-login return destination |

---

### Task 1: Roles live on the person

**Files:**
- Modify: `api/database.py` (`_migrate_stakeholder_roles`, `_SCHEMA_VERSION`, the `stakeholders` CREATE, `insert_stakeholder`, `_row_to_stakeholder`)
- Test: `tests/test_stakeholder_roles.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `stakeholders.is_project_admin` and `stakeholders.is_governor`, both `INTEGER NOT NULL DEFAULT 0`, joining the existing `is_participant`, `is_reviewer`, and `is_approver`. `insert_stakeholder` gains `is_project_admin: bool = False` and `is_governor: bool = False`; `_row_to_stakeholder` coerces both to `bool`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_stakeholder_roles.py
"""A person's rights live on the record that holds their name.

The five flags are one set, not two systems: is_participant already existed alongside
is_reviewer and is_approver, and project_admin and governor join them rather than living
somewhere else. Boolean columns rather than a JSON list because resolve_recipients already
filters on exactly these columns, and the role set is fixed and small.
"""
import pytest
from api.database import get_connection, insert_stakeholder, fetch_stakeholders


@pytest.mark.asyncio
async def test_all_five_roles_round_trip_as_booleans(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_DIR", str(tmp_path))
    from api.config import get_settings
    get_settings.cache_clear()
    try:
        async with get_connection("roles-test") as conn:
            await conn.execute("INSERT INTO projects (slug) VALUES ('roles-test')")
            await conn.commit()
            await insert_stakeholder(
                conn, project_id=1, name="Dougie McCrone", email="dougie@example.com",
                is_participant=True, is_reviewer=True, is_approver=True,
                is_project_admin=True, is_governor=True,
            )
            rows = await fetch_stakeholders(conn, project_id=1)
        assert len(rows) == 1
        r = rows[0]
        for flag in ("is_participant", "is_reviewer", "is_approver",
                     "is_project_admin", "is_governor"):
            assert r[flag] is True, f"{flag} did not round-trip as a bool"


@pytest.mark.asyncio
async def test_the_new_flags_default_to_false(tmp_path, monkeypatch):
    """A person added with no roles is nobody yet - adding a stakeholder must not
    accidentally confer administration."""
    monkeypatch.setenv("DATABASE_DIR", str(tmp_path))
    from api.config import get_settings
    get_settings.cache_clear()
    try:
        async with get_connection("roles-default") as conn:
            await conn.execute("INSERT INTO projects (slug) VALUES ('roles-default')")
            await conn.commit()
            await insert_stakeholder(conn, project_id=1, name="Nobody", email="n@example.com")
            rows = await fetch_stakeholders(conn, project_id=1)
        assert rows[0]["is_project_admin"] is False
        assert rows[0]["is_governor"] is False
    finally:
        get_settings.cache_clear()
```

Note the first test is missing its `finally: get_settings.cache_clear()` - add it, matching the
second. Read `insert_stakeholder`'s real signature and `fetch_stakeholders`' real name before
writing; both are in `api/database.py` and the brief may have them wrong.

- [ ] **Step 2: Run to verify it fails**

Run: `./venv/bin/pytest tests/test_stakeholder_roles.py -v`
Expected: FAIL - `insert_stakeholder() got an unexpected keyword argument 'is_project_admin'`.

- [ ] **Step 3: Add the migration**

In `api/database.py`, following the house style of the neighbouring `_migrate_*` functions:

```python
async def _migrate_stakeholder_roles(conn: aiosqlite.Connection) -> None:
    """The two roles the stakeholder record was missing.

    is_participant, is_reviewer, and is_approver already lived here; project_admin and
    governor complete the set rather than starting a second one. Authority is then read
    from the row that holds the person's name and address, instead of being inferred by
    matching that address against a separate account.
    """
    cur = await conn.execute("PRAGMA table_info(stakeholders)")
    cols = {row[1] for row in await cur.fetchall()}
    for name in ("is_project_admin", "is_governor"):
        if name not in cols:
            await conn.execute(
                f"ALTER TABLE stakeholders ADD COLUMN {name} INTEGER NOT NULL DEFAULT 0")
    await conn.commit()
```

Add both columns to the `CREATE TABLE stakeholders` statement so fresh databases carry them, and
add them to the `("is_reviewer", "INTEGER NOT NULL DEFAULT 0")`-style list nearby if one governs
column upgrades.

- [ ] **Step 4: Bump the version and register the migration**

Change `_SCHEMA_VERSION = 5` (line 1299) to `_SCHEMA_VERSION = 6`, and add to the migration block
in `get_connection`, after `_migrate_interview_sessions_script_id(conn)`:

```python
            await _migrate_stakeholder_roles(conn)
```

Both are required. `get_connection` re-runs the block only when `PRAGMA user_version <
_SCHEMA_VERSION`, so a migration added without the bump silently never runs on any database
already opened at version 5 - which is every existing project.

- [ ] **Step 5: Carry the flags through insert and read**

Add `is_project_admin: bool = False` and `is_governor: bool = False` to `insert_stakeholder`'s
keyword arguments, its INSERT column list, and its values tuple. Add both names to the coercion
loop in `_row_to_stakeholder` that already does `row["is_reviewer"] = bool(...)`, and to the
allowed-field tuple used by the update path.

- [ ] **Step 6: Run the tests to verify they pass**

Run: `./venv/bin/pytest tests/test_stakeholder_roles.py -v`
Expected: 2 passed

- [ ] **Step 7: Power-check the migration on an existing database**

Open a throwaway project, force `PRAGMA user_version = 5` and drop the two columns, reopen through
`get_connection`, and confirm they return with the version at 6. That is the path every existing
project takes, and the failure mode CLAUDE.md names is that it silently does not run. Report the
observed before and after.

- [ ] **Step 8: Run the full suite twice, then commit**

```bash
git add api/database.py tests/test_stakeholder_roles.py
git commit -m "feat(users): the person record carries all five roles"
```

---

### Task 2: One login, many engagements

**Files:**
- Modify: `api/database.py` (`init_system_db` - `users.is_sys_admin`, `project_memberships.stakeholder_id`)
- Test: `tests/test_membership_link.py`

**Interfaces:**
- Consumes: Task 1's role flags.
- Produces: `users.is_sys_admin INTEGER NOT NULL DEFAULT 0`; `project_memberships.stakeholder_id INTEGER`; `link_membership(conn, *, user_id: int, project_slug: str, stakeholder_id: int) -> None` in `api/database.py`, upserting on the existing `UNIQUE(user_id, project_slug)`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_membership_link.py
"""One person, one login, a row per engagement.

project_memberships already meant "this user is on this project". Carrying stakeholder_id
makes it mean "and this is who they are here", which is what removes the email match: the
same login points at a different person record on each project.
"""
import pytest
from api.database import get_system_connection, insert_user, link_membership


@pytest.mark.asyncio
async def test_one_login_links_to_a_different_person_on_each_project(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_DIR", str(tmp_path))
    from api.config import get_settings
    get_settings.cache_clear()
    try:
        async with get_system_connection() as conn:
            await insert_user(conn, username="patrick@arup.com", email="patrick@arup.com",
                              role="reviewer", hashed_pw="x")
            cur = await conn.execute("SELECT id FROM users WHERE username=?",
                                     ("patrick@arup.com",))
            uid = (await cur.fetchone())[0]
            await link_membership(conn, user_id=uid, project_slug="alpha", stakeholder_id=7)
            await link_membership(conn, user_id=uid, project_slug="beta", stakeholder_id=41)
            cur = await conn.execute(
                "SELECT project_slug, stakeholder_id FROM project_memberships "
                "WHERE user_id=? ORDER BY project_slug", (uid,))
            rows = [tuple(r) for r in await cur.fetchall()]
        assert rows == [("alpha", 7), ("beta", 41)]
    finally:
        get_settings.cache_clear()


@pytest.mark.asyncio
async def test_relinking_the_same_project_replaces_rather_than_duplicates(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_DIR", str(tmp_path))
    from api.config import get_settings
    get_settings.cache_clear()
    try:
        async with get_system_connection() as conn:
            await insert_user(conn, username="d@example.com", email="d@example.com",
                              role="reviewer", hashed_pw="x")
            cur = await conn.execute("SELECT id FROM users WHERE username=?", ("d@example.com",))
            uid = (await cur.fetchone())[0]
            await link_membership(conn, user_id=uid, project_slug="alpha", stakeholder_id=7)
            await link_membership(conn, user_id=uid, project_slug="alpha", stakeholder_id=9)
            cur = await conn.execute(
                "SELECT stakeholder_id FROM project_memberships WHERE user_id=?", (uid,))
            rows = [r[0] for r in await cur.fetchall()]
        assert rows == [9], "UNIQUE(user_id, project_slug) means one row, updated not doubled"
    finally:
        get_settings.cache_clear()
```

- [ ] **Step 2: Run to verify they fail**

Run: `./venv/bin/pytest tests/test_membership_link.py -v`
Expected: FAIL - `ImportError: cannot import name 'link_membership'`.

- [ ] **Step 3: Extend the system schema**

In `init_system_db`'s `executescript`, add `is_sys_admin INTEGER NOT NULL DEFAULT 0` to the
`users` CREATE and `stakeholder_id INTEGER` to `project_memberships`. `init_system_db` is
idempotent and has no version gate, so also add an upgrade for existing databases immediately
after the script, in the same style as the project migrations:

```python
    for table, column, decl in (
        ("users", "is_sys_admin", "INTEGER NOT NULL DEFAULT 0"),
        ("project_memberships", "stakeholder_id", "INTEGER"),
    ):
        cur = await conn.execute(f"PRAGMA table_info({table})")
        if column not in {row[1] for row in await cur.fetchall()}:
            await conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {decl}")
    await conn.commit()
```

`stakeholder_id` is deliberately nullable: a membership can exist before the person is linked, and
a `sys_admin` administering a project has no stakeholder row there at all.

- [ ] **Step 4: Add the linking helper**

```python
async def link_membership(
    conn: aiosqlite.Connection, *, user_id: int, project_slug: str, stakeholder_id: int
) -> None:
    """Point a login at the person record it is on this project.

    Upserts on the existing UNIQUE(user_id, project_slug): a person has one membership per
    engagement, and re-linking corrects it rather than creating a second.
    """
    await conn.execute(
        "INSERT INTO project_memberships (user_id, project_slug, stakeholder_id)"
        " VALUES (?,?,?)"
        " ON CONFLICT(user_id, project_slug) DO UPDATE SET stakeholder_id=excluded.stakeholder_id",
        (user_id, project_slug, stakeholder_id),
    )
    await conn.commit()
```

- [ ] **Step 5: Run the tests, then the full suite twice, then commit**

Power-check first: change `DO UPDATE` to `DO NOTHING`, confirm the second test fails, restore.

```bash
git add api/database.py tests/test_membership_link.py
git commit -m "feat(users): a membership names the person it belongs to"
```

---

### Task 3: Authority is a walk, not a match

**Files:**
- Create: `api/services/authority_service.py`
- Test: `tests/test_authority_walk.py`

**Interfaces:**
- Consumes: Tasks 1 and 2.
- Produces: `caller_roles(slug: str, payload: dict) -> set[str]` returning any of `"sys_admin"`, `"project_admin"`, `"governor"`, `"approver"`, `"reviewer"`, `"participant"`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_authority_walk.py
"""Authority is read from the person record, never inferred from an address.

The previous implementation lowercased the caller's account email and looked for a
stakeholder carrying the same string, behind an early `if role == "sysadmin": return True`
that did all the work in practice - granting content rights to whoever could administer
accounts. Both are gone.
"""
import pytest
from api.services.authority_service import caller_roles


@pytest.mark.asyncio
async def test_roles_come_from_the_linked_person(seeded_authority):
    slug, payload, _ = seeded_authority
    assert await caller_roles(slug, payload) == {"reviewer", "approver", "participant"}


@pytest.mark.asyncio
async def test_a_sys_admin_administers_but_cannot_approve(seeded_authority):
    """The distinction the whole design turns on: administration is not content authority.
    sys_admin exists so a new project - which has no stakeholders and therefore no way to
    add one - can be bootstrapped at all."""
    slug, _, sys_payload = seeded_authority
    roles = await caller_roles(slug, sys_payload)
    assert "project_admin" in roles
    assert "sys_admin" in roles
    assert "approver" not in roles, "administering accounts must not confer approval"
    assert "reviewer" not in roles
    assert "governor" not in roles


@pytest.mark.asyncio
async def test_an_unlinked_caller_has_no_roles(seeded_authority):
    """No membership means nothing - not a guess by matching their email."""
    slug, _, _ = seeded_authority
    assert await caller_roles(slug, {"sub": "stranger@example.com", "role": "reviewer"}) == set()


@pytest.mark.asyncio
async def test_a_membership_on_another_project_confers_nothing_here(seeded_authority_two_projects):
    slug_a, slug_b, payload = seeded_authority_two_projects
    assert "approver" in await caller_roles(slug_a, payload)
    assert await caller_roles(slug_b, payload) == set()
```

Write the two fixtures yourself. `seeded_authority` must create a project, a stakeholder carrying
`is_reviewer`, `is_approver`, and `is_participant`, a `users` row, and a membership linking them -
plus a second `users` row with `is_sys_admin` and **no** stakeholder or membership. Insert the
`projects` row before any stakeholder row: `PRAGMA foreign_keys = ON` is set by `get_connection`,
and several briefs on this project have failed on that before reaching what they meant to prove.

- [ ] **Step 2: Run to verify they fail**

Run: `./venv/bin/pytest tests/test_authority_walk.py -v`
Expected: FAIL - `ModuleNotFoundError: No module named 'api.services.authority_service'`.

- [ ] **Step 3: Write the walk**

```python
# api/services/authority_service.py
"""What the calling account may do on one project.

Read, not inferred. The walk is JWT -> users row -> membership for this slug ->
stakeholder row -> flags, so nothing depends on two tables happening to hold the same
email text. The previous implementation matched on exactly that, and could not work at
all: the users table was empty, so an `if role == "sysadmin": return True` was carrying
every call - granting content authority to whoever could administer accounts.

sys_admin implies project_admin on every project and nothing else. Without it a newly
created project has no stakeholders and no way to add one. The line that matters is
administration versus content, not global versus per-project.
"""
from api.database import get_system_connection, get_connection, fetch_project, fetch_user

_FLAG_ROLES = (
    ("is_project_admin", "project_admin"),
    ("is_governor", "governor"),
    ("is_approver", "approver"),
    ("is_reviewer", "reviewer"),
    ("is_participant", "participant"),
)


async def caller_roles(slug: str, payload: dict) -> set[str]:
    """Every role this caller holds on this project. Empty when they hold none."""
    username = (payload or {}).get("sub", "")
    if not username:
        return set()

    async with get_system_connection() as sys_conn:
        user = await fetch_user(sys_conn, username=username)
        if not user:
            return set()
        roles: set[str] = set()
        if user.get("is_sys_admin"):
            roles |= {"sys_admin", "project_admin"}
        cur = await sys_conn.execute(
            "SELECT stakeholder_id FROM project_memberships WHERE user_id=? AND project_slug=?",
            (user["id"], slug),
        )
        row = await cur.fetchone()

    stakeholder_id = row[0] if row else None
    if stakeholder_id is None:
        return roles

    async with get_connection(slug) as conn:
        project = await fetch_project(conn, slug=slug)
        if not project:
            return roles
        conn.row_factory = __import__("aiosqlite").Row
        cur = await conn.execute(
            "SELECT * FROM stakeholders WHERE id=? AND project_id=?",
            (stakeholder_id, project["id"]),
        )
        person = await cur.fetchone()

    if person is not None:
        roles |= {role for flag, role in _FLAG_ROLES if person[flag]}
    return roles
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `./venv/bin/pytest tests/test_authority_walk.py -v`
Expected: 4 passed

- [ ] **Step 5: Power-check the two properties that matter**

Add `roles |= {"approver"}` to the `is_sys_admin` branch and confirm
`test_a_sys_admin_administers_but_cannot_approve` fails. Then make the unlinked case fall back to
matching `user["email"]` against a stakeholder email and confirm
`test_an_unlinked_caller_has_no_roles` fails. Report both verbatim - the second is the defect this
task exists to remove, and a test that passes with the match reinstated is not testing it.

- [ ] **Step 6: Run the full suite twice, then commit**

```bash
git add api/services/authority_service.py tests/test_authority_walk.py
git commit -m "feat(auth): read authority from the person, not from a matching address"
```

---

### Task 4: Every gate reads the walk

**Files:**
- Modify: `api/routers/script_reviews.py`, `api/routers/projects.py`, `api/routers/permissions.py`
- Delete: `_caller_matches_stakeholder_flag` and `caller_may_commit` / `caller_may_submit`'s use of it, in `api/services/commit_service.py`
- Test: `tests/test_authority_call_sites.py`

**Interfaces:**
- Consumes: `caller_roles(slug, payload) -> set[str]`.
- Produces: nothing new. Every authority check in the application reads one function.

- [ ] **Step 1: Establish the call sites before changing any**

Run and record in your report:

```bash
grep -rn "_caller_matches_stakeholder_flag\|caller_may_commit\|caller_may_submit" api/ tests/
```

Anything outside the file list above is a call site this plan did not anticipate. Report it rather
than changing it silently.

- [ ] **Step 2: Write the failing test**

```python
# tests/test_authority_call_sites.py
"""Every gate asks the same question, in the same way.

A rule enforced at one door and not another is this project's documented recurring failure -
CLAUDE.md records the two review doors, where wiring only one turned the other's flows into
no-ops. These assert on the roles each endpoint demands, because the roles are the rule and
the status code is only its shadow.
"""
from unittest.mock import AsyncMock, patch
import pytest


@pytest.mark.asyncio
async def test_reviewing_demands_a_review_role(client, seeded_ledger_script):
    slug, script_id = seeded_ledger_script
    with patch("api.routers.script_reviews.caller_roles",
               new=AsyncMock(return_value=set())) as roles:
        r = await client.post(f"/projects/{slug}/script-ledger/{script_id}/review",
                              json={"decision": "reviewed"})
    assert r.status_code == 403, r.text
    roles.assert_awaited()


@pytest.mark.asyncio
async def test_approving_demands_the_approver_role_specifically(client, seeded_ledger_script):
    """A reviewer may review and may not approve - the two are different rights, and a
    caller holding only the first must be refused the second."""
    slug, script_id = seeded_ledger_script
    with patch("api.routers.script_reviews.caller_roles",
               new=AsyncMock(return_value={"reviewer"})):
        r = await client.post(f"/projects/{slug}/script-ledger/{script_id}/review",
                              json={"decision": "approved"})
    assert r.status_code == 403, r.text


@pytest.mark.asyncio
async def test_editing_a_script_demands_a_review_role(client, seeded_scripts):
    slug = seeded_scripts
    before = (await client.get(f"/projects/{slug}/interview-scripts")).json()
    with patch("api.routers.projects.caller_roles", new=AsyncMock(return_value=set())):
        r = await client.patch(f"/projects/{slug}/interview-scripts/SC-001",
                               json={"script": {**before["SC-001"], "node_label": "Nope"}})
    assert r.status_code == 403, r.text


@pytest.mark.asyncio
async def test_permissions_reports_the_same_roles_the_gates_read(client, seeded_ledger_script):
    slug, _ = seeded_ledger_script
    with patch("api.routers.permissions.caller_roles",
               new=AsyncMock(return_value={"reviewer"})):
        r = await client.get(f"/projects/{slug}/my-permissions")
    assert r.json() == {"can_review": True, "can_approve": False}
```

Patch where each name is **looked up** - `api.routers.script_reviews`, `api.routers.projects`,
`api.routers.permissions` - not where it is defined. Each router binds its own reference with
`from ... import`, and CLAUDE.md records four tests that got this wrong and hid a live production
bug for weeks. Reuse the existing `seeded_ledger_script` and `seeded_scripts` fixtures rather than
writing new ones; read them first.

- [ ] **Step 3: Run to verify they fail**

Run: `./venv/bin/pytest tests/test_authority_call_sites.py -v`
Expected: FAIL - the patch targets do not exist yet, since the routers still import
`_caller_matches_stakeholder_flag`.

- [ ] **Step 4: Switch each router onto the walk**

In `api/routers/script_reviews.py`, replace the flag call with:

```python
    roles = await caller_roles(slug, payload)
    needed = {"approver"} if body.decision == "approved" else {"reviewer", "approver"}
    if not (roles & needed):
        raise HTTPException(status_code=403, detail="Not permitted to review this script")
```

In `api/routers/projects.py`'s `patch_interview_script`, the same with
`needed = {"reviewer", "approver"}`. In `api/routers/permissions.py`:

```python
    roles = await caller_roles(slug, payload)
    return {
        "can_review": bool(roles & {"reviewer", "approver"}),
        "can_approve": "approver" in roles,
    }
```

- [ ] **Step 5: Remove the old authority**

Delete `_caller_matches_stakeholder_flag` from `api/services/commit_service.py` and repoint
`caller_may_commit` and `caller_may_submit` onto `caller_roles` - commit needs `approver`, submit
needs `reviewer` or `approver`. For every test you delete or change, say in your report whether
the behaviour is gone by design or merely inconvenient to keep working.

- [ ] **Step 6: Run the tests, then the full suite twice, then commit**

Power-check: revert the `needed` narrowing for `approved` so any review role suffices, and confirm
`test_approving_demands_the_approver_role_specifically` fails. Report it verbatim.

```bash
git add api/routers/ api/services/commit_service.py tests/
git commit -m "refactor(auth): every gate reads one authority function"
```

---

### Task 5: A forced approval says so

**Files:**
- Modify: `api/services/script_review_service.py`, `api/routers/script_reviews.py`
- Test: `tests/test_forced_approval.py`

**Interfaces:**
- Consumes: `NotYetReviewedError`, `record_script_review`.
- Produces: `record_script_review` gains `forced: bool = False`; `script_reviews` gains `forced INTEGER NOT NULL DEFAULT 0`; `ScriptReviewRequest` gains `forced: bool = False`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_forced_approval.py
"""An approver may override the gate, and the record must show they did.

Without this, approved silently means two different things - "two people looked at this"
and "one person waved it through" - and six months later nobody can tell which. The warning
in the UI is a courtesy; the audit trail is the point.
"""
import pytest


@pytest.mark.asyncio
async def test_an_unforced_approval_on_an_unreviewed_script_is_still_refused(
        client, seeded_ledger_script):
    slug, script_id = seeded_ledger_script
    r = await client.post(f"/projects/{slug}/script-ledger/{script_id}/review",
                          json={"decision": "approved"})
    assert r.status_code == 409, r.text


@pytest.mark.asyncio
async def test_a_forced_approval_is_permitted_and_recorded_as_forced(
        client, seeded_ledger_script):
    slug, script_id = seeded_ledger_script
    r = await client.post(f"/projects/{slug}/script-ledger/{script_id}/review",
                          json={"decision": "approved", "forced": True})
    assert r.status_code == 200, r.text

    from api.database import get_connection
    async with get_connection(slug) as conn:
        cur = await conn.execute(
            "SELECT decision, forced FROM script_reviews WHERE script_id=?", (script_id,))
        rows = [tuple(x) for x in await cur.fetchall()]
    assert rows == [("approved", 1)]


@pytest.mark.asyncio
async def test_a_normal_approval_after_a_review_is_not_marked_forced(
        client, seeded_ledger_script):
    slug, script_id = seeded_ledger_script
    await client.post(f"/projects/{slug}/script-ledger/{script_id}/review",
                      json={"decision": "reviewed"})
    await client.post(f"/projects/{slug}/script-ledger/{script_id}/review",
                      json={"decision": "approved"})
    from api.database import get_connection
    async with get_connection(slug) as conn:
        cur = await conn.execute(
            "SELECT forced FROM script_reviews WHERE decision='approved'")
        assert [r[0] for r in await cur.fetchall()] == [0]
```

- [ ] **Step 2: Run to verify they fail**

Run: `./venv/bin/pytest tests/test_forced_approval.py -v`
Expected: FAIL - the second test gets 409, because `forced` is not accepted.

- [ ] **Step 3: Add the column**

Add `forced INTEGER NOT NULL DEFAULT 0` to the `script_reviews` CREATE in
`_migrate_script_reviews`, and an `ALTER TABLE` upgrade guarded by `PRAGMA table_info` in the same
function. Bump `_SCHEMA_VERSION` from 6 to 7 and confirm `_migrate_script_reviews` is already in
the migration block - it is, so no new registration is needed, only the bump.

- [ ] **Step 4: Let an approver override, and record it**

In `record_script_review`, change the gate:

```python
    if decision == "approved" and not forced:
        if await review_count(conn, project_id=project_id, script_id=script_id) == 0:
            raise NotYetReviewedError(
                f"script {script_id} has no reviews - it must be read before it is approved"
            )
```

and store `forced` on the inserted `script_reviews` row. Add `forced: bool = False` to
`ScriptReviewRequest` and pass it through the router.

- [ ] **Step 5: Run the tests, power-check, then the full suite twice, then commit**

Power-check: make `forced` always store `0` and confirm the second test fails on
`[("approved", 1)]`. Then remove `and not forced` from the gate and confirm the first test fails.
Report both verbatim - one proves the record, the other proves the default is still refusal.

```bash
git add api/services/script_review_service.py api/routers/script_reviews.py api/database.py tests/test_forced_approval.py
git commit -m "feat(review): an approver may override the gate, and the record shows it"
```

---

### Task 6: Invite, accept, and reset

**Files:**
- Modify: `api/database.py` (`auth_tokens` in `init_system_db`)
- Create: `api/services/invite_service.py`, `api/routers/invites.py`
- Modify: `api/main.py` (register the router)
- Test: `tests/test_invite_loop.py`

**Interfaces:**
- Consumes: `link_membership`, `hash_password` / `verify_password` from `api/auth.py`.
- Produces: table `auth_tokens (id, token_hash TEXT UNIQUE, email TEXT, project_slug TEXT, stakeholder_id INTEGER, purpose TEXT, expires_at DATETIME, used_at DATETIME, created_at)`; `issue_invite(email, project_slug, stakeholder_id) -> str` returning the raw token; `reissue_invite(email) -> str | None`; `accept_token(raw_token, password) -> dict | None`; `issue_reset(email) -> str | None`. `POST /auth/accept` and `POST /auth/reset-request` and `POST /auth/reset`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_invite_loop.py
"""One live invite per person, and the same machinery does resets.

The trigger is a role, not a person: adding a stakeholder does nothing, and setting any
flag other than is_participant on somebody with no login issues an invite. A participant
never gets one - they are reached by interview URL and token, as they always were.
"""
import pytest
from api.services.invite_service import (
    issue_invite, reissue_invite, accept_token, issue_reset,
)


@pytest.mark.asyncio
async def test_accepting_an_invite_creates_the_login_and_the_link(seeded_person):
    slug, stakeholder_id, email = seeded_person
    raw = await issue_invite(email=email, project_slug=slug, stakeholder_id=stakeholder_id)
    user = await accept_token(raw, "correct horse battery staple")
    assert user is not None and user["username"] == email

    from api.database import get_system_connection
    async with get_system_connection() as conn:
        cur = await conn.execute(
            "SELECT project_slug, stakeholder_id FROM project_memberships"
            " WHERE user_id=?", (user["id"],))
        assert [tuple(r) for r in await cur.fetchall()] == [(slug, stakeholder_id)]


@pytest.mark.asyncio
async def test_a_token_cannot_be_used_twice(seeded_person):
    slug, stakeholder_id, email = seeded_person
    raw = await issue_invite(email=email, project_slug=slug, stakeholder_id=stakeholder_id)
    assert await accept_token(raw, "first password") is not None
    assert await accept_token(raw, "second password") is None


@pytest.mark.asyncio
async def test_reissuing_returns_the_same_live_invite_rather_than_a_second(seeded_person):
    """One live invite per person. Re-issuing is for a lost email, not a parallel token -
    two live invites means two passwords can be set and only one membership exists."""
    slug, stakeholder_id, email = seeded_person
    first = await issue_invite(email=email, project_slug=slug, stakeholder_id=stakeholder_id)
    second = await reissue_invite(email=email)
    assert second is not None
    assert await accept_token(first, "pw") is None or second == first

    from api.database import get_system_connection
    async with get_system_connection() as conn:
        cur = await conn.execute(
            "SELECT COUNT(*) FROM auth_tokens WHERE email=? AND used_at IS NULL", (email,))
        assert (await cur.fetchone())[0] == 1


@pytest.mark.asyncio
async def test_a_reset_sets_a_new_password_on_an_existing_login(seeded_person):
    slug, stakeholder_id, email = seeded_person
    raw = await issue_invite(email=email, project_slug=slug, stakeholder_id=stakeholder_id)
    await accept_token(raw, "old password")
    reset = await issue_reset(email=email)
    assert reset is not None
    user = await accept_token(reset, "new password")
    assert user is not None

    from api.auth import verify_password
    from api.database import get_system_connection, fetch_user
    async with get_system_connection() as conn:
        row = await fetch_user(conn, username=email)
    assert verify_password("new password", row["hashed_pw"])
    assert not verify_password("old password", row["hashed_pw"])


@pytest.mark.asyncio
async def test_a_reset_for_an_unknown_address_reveals_nothing(seeded_person):
    """Returning None rather than raising keeps the endpoint from confirming which
    addresses have accounts."""
    assert await issue_reset(email="nobody@example.com") is None
```

Write the `seeded_person` fixture yourself: a project, a stakeholder with an email, and no login.
Insert the `projects` row first. **Tokens are stored hashed** - use `hash_password` from
`api/auth.py`, never the raw value, and never log the raw token.

- [ ] **Step 2: Run to verify they fail**

Run: `./venv/bin/pytest tests/test_invite_loop.py -v`
Expected: FAIL - `ModuleNotFoundError: No module named 'api.services.invite_service'`.

- [ ] **Step 3: Add the token table**

In `init_system_db`'s `executescript`:

```sql
        CREATE TABLE IF NOT EXISTS auth_tokens (
            id             INTEGER PRIMARY KEY AUTOINCREMENT,
            token_hash     TEXT    NOT NULL UNIQUE,
            email          TEXT    NOT NULL,
            project_slug   TEXT,
            stakeholder_id INTEGER,
            purpose        TEXT    NOT NULL,
            expires_at     DATETIME NOT NULL,
            used_at        DATETIME,
            created_at     DATETIME DEFAULT CURRENT_TIMESTAMP
        );
```

`purpose` is `'invite'` or `'reset'`. `project_slug` and `stakeholder_id` are null on a reset,
which is for an existing login and creates no membership.

- [ ] **Step 4: Write the service**

Create `api/services/invite_service.py`. The behaviours the tests above pin down:

- `issue_invite` generates a token with `secrets.token_urlsafe(32)`, stores only its hash, sets
  `expires_at` seven days out, and returns the raw value once. If a live unused invite already
  exists for that email, it returns that one refreshed rather than creating a second.
- `reissue_invite` refreshes the live invite's expiry and returns a usable raw token for the same
  row, so the count of unused rows stays at one.
- `accept_token` looks the token up by hash, refuses a used or expired one by returning `None`,
  creates the `users` row with `hash_password(password)` if none exists or updates the password if
  one does, calls `link_membership` when the token carries a `project_slug`, stamps `used_at`, and
  returns the user row.
- `issue_reset` returns `None` for an address with no login, so the endpoint cannot be used to
  discover which addresses have accounts.

- [ ] **Step 5: Add the endpoints**

Create `api/routers/invites.py` with `POST /auth/accept` (`{token, password}`), `POST
/auth/reset-request` (`{email}`), and `POST /auth/reset` (`{token, password}`). **All three are
unauthenticated by design** - somebody accepting an invite has no session yet. `reset-request`
must return 204 whether or not the address is known. Register the router in `api/main.py`.

- [ ] **Step 6: Run the tests, power-check, then the full suite twice, then commit**

Power-check: make `accept_token` ignore `used_at` and confirm the second test fails; make
`issue_reset` return a token for an unknown address and confirm the last test fails. Report both
verbatim.

```bash
git add api/database.py api/services/invite_service.py api/routers/invites.py api/main.py tests/test_invite_loop.py
git commit -m "feat(auth): invite, accept, and reset over one token table"
```

---

### Task 7: Setting a role issues the invite

**Files:**
- Modify: `api/routers/stakeholders.py`
- Test: `tests/test_role_triggers_invite.py`

**Interfaces:**
- Consumes: `issue_invite`, `caller_roles`.
- Produces: nothing new.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_role_triggers_invite.py
"""The trigger is the data, not a step somebody has to remember.

Setting any role other than participant on a person with no login issues an invite -
whether they were typed in or bulk-uploaded, because both paths end at the same write.
"""
from unittest.mock import AsyncMock, patch
import pytest


@pytest.mark.asyncio
async def test_adding_a_participant_issues_no_invite(client, seeded_project_slug):
    slug = seeded_project_slug
    with patch("api.routers.stakeholders.issue_invite", new=AsyncMock()) as invite:
        r = await client.post(f"/projects/{slug}/stakeholders",
                              json={"name": "Ana", "email": "ana@example.com",
                                    "is_participant": True})
    assert r.status_code in (200, 201), r.text
    invite.assert_not_awaited()


@pytest.mark.asyncio
async def test_setting_a_reviewer_role_issues_exactly_one_invite(client, seeded_project_slug):
    slug = seeded_project_slug
    with patch("api.routers.stakeholders.issue_invite", new=AsyncMock()) as invite:
        r = await client.post(f"/projects/{slug}/stakeholders",
                              json={"name": "Bo", "email": "bo@example.com",
                                    "is_reviewer": True})
        assert r.status_code in (200, 201), r.text
        sid = r.json()["id"]
        await client.patch(f"/projects/{slug}/stakeholders/{sid}",
                           json={"is_approver": True})
    assert invite.await_count == 1, "a second role must not issue a second invite"
    assert invite.await_args.kwargs["email"] == "bo@example.com"


@pytest.mark.asyncio
async def test_a_person_with_no_email_cannot_be_invited_and_says_so(client, seeded_project_slug):
    """Dougie McCrone holds full rights on the live project and has no address, so nothing
    can reach him and nothing reports it. A role set on an addressless person must surface
    that rather than silently not sending."""
    slug = seeded_project_slug
    r = await client.post(f"/projects/{slug}/stakeholders",
                          json={"name": "Dougie", "email": "", "is_reviewer": True})
    assert r.status_code == 422, r.text
    assert "email" in r.text.lower()
```

Read `api/routers/stakeholders.py` for the real create and update paths and their response shapes
before writing - the brief may have the route names or the returned body wrong.

- [ ] **Step 2: Run to verify they fail**

Run: `./venv/bin/pytest tests/test_role_triggers_invite.py -v`
Expected: FAIL - `issue_invite` is not imported in that module, so the patch target does not exist.

- [ ] **Step 3: Issue on role change**

In `api/routers/stakeholders.py`, after a successful create or update, compare the flags now set
against `is_participant` alone. When any other flag is set and the person has no linked login,
call `issue_invite`. Refuse with 422 when such a role is set on a person with no email, naming the
field - a role that cannot be delivered is a state somebody must be told about, not one to store
quietly.

- [ ] **Step 4: Run the tests, power-check, then the full suite twice, then commit**

Power-check: remove the "no linked login" condition and confirm the second test fails on
`await_count == 2`. Report it verbatim.

```bash
git add api/routers/stakeholders.py tests/test_role_triggers_invite.py
git commit -m "feat(users): setting a role invites the person to set a password"
```

---

### Task 8: The session rolls, and a link survives the login

**Files:**
- Modify: `api/auth.py`, `api/routers/auth.py`, `ui/src/context/AuthContext.tsx`, `ui/src/router.tsx`
- Create: `ui/src/pages/AcceptInvite.tsx`
- Test: `tests/test_rolling_session.py`, `ui/src/__tests__/LoginReturnTo.test.tsx`

**Interfaces:**
- Consumes: `POST /auth/accept` from Task 6.
- Produces: `ACCESS_TOKEN_EXPIRE_HOURS` becomes 30 days; every authenticated response carries a refreshed token in an `X-Refreshed-Token` header; `/dashboard/accept-invite/:token` renders `AcceptInvite`.

- [ ] **Step 1: Write the failing backend test**

```python
# tests/test_rolling_session.py
"""Thirty days, refreshed on use, so an active reviewer never logs in twice.

PAM's links are ordinary application URLs: they work while a session is live and bounce to
login when it is not. A reviewer who reads three scripts a week should never see the login
page again after the first time.
"""
import pytest
from datetime import datetime, timezone
from jose import jwt
from api.auth import create_access_token, ACCESS_TOKEN_EXPIRE_HOURS
from api.config import get_settings


def test_a_token_lasts_thirty_days():
    assert ACCESS_TOKEN_EXPIRE_HOURS == 24 * 30
    secret = get_settings().jwt_secret
    payload = jwt.decode(create_access_token("ana", "reviewer", secret), secret,
                         algorithms=["HS256"])
    remaining = datetime.fromtimestamp(payload["exp"], tz=timezone.utc) - datetime.now(timezone.utc)
    assert 29 <= remaining.days <= 30


@pytest.mark.asyncio
async def test_an_authenticated_request_returns_a_refreshed_token(client, seeded_project_slug):
    """Rolling means re-issued on use. Without this the thirtieth day is a cliff, and it
    arrives while somebody is mid-review."""
    r = await client.get(f"/projects/{seeded_project_slug}/my-permissions")
    assert r.status_code == 200
    assert r.headers.get("X-Refreshed-Token"), "an authenticated response must roll the session"
```

- [ ] **Step 2: Run to verify it fails**

Run: `./venv/bin/pytest tests/test_rolling_session.py -v`
Expected: FAIL - `ACCESS_TOKEN_EXPIRE_HOURS` is not 720 and no header is set.

- [ ] **Step 3: Roll the token**

Set `ACCESS_TOKEN_EXPIRE_HOURS = 24 * 30` in `api/auth.py`. Add FastAPI middleware in
`api/main.py` that, when a request carried a valid bearer token, re-issues it and sets
`X-Refreshed-Token` on the response. The frontend stores the new value when present.

- [ ] **Step 4: Write the failing frontend test**

```tsx
// ui/src/__tests__/LoginReturnTo.test.tsx
import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { RequireAuth } from '../context/AuthContext'

it('remembers where an unauthenticated visitor was heading', () => {
  // PAM emails a link to one script. A reviewer opens it three weeks later on their phone,
  // logs in, and must land on that script - not on the dashboard, with no idea which of
  // eighty-six they were sent to.
  render(
    <MemoryRouter initialEntries={['/dashboard/projects/sp-gs-am/agents/interaction_designer']}>
      <RequireAuth><div>protected</div></RequireAuth>
    </MemoryRouter>,
  )
  expect(screen.queryByText('protected')).not.toBeInTheDocument()
  expect(sessionStorage.getItem('returnTo'))
    .toBe('/dashboard/projects/sp-gs-am/agents/interaction_designer')
})
```

Read `ui/src/context/AuthContext.tsx` for the real guard component and its export name before
writing this - the brief may have it wrong.

- [ ] **Step 5: Carry the destination, and add the invite page**

Store the attempted path when the guard redirects, and consume it after a successful login.
Create `ui/src/pages/AcceptInvite.tsx` - a password field posting to `POST /auth/accept` with the
token from the route - and add `/accept-invite/:token` to `ui/src/router.tsx`, outside the
authenticated guard.

- [ ] **Step 6: Run both suites, power-check, then commit**

Power-check: drop the `returnTo` write and confirm the frontend test fails; revert the header and
confirm the backend test fails. Report both verbatim.

```bash
git add api/auth.py api/main.py ui/src/context/AuthContext.tsx ui/src/router.tsx ui/src/pages/AcceptInvite.tsx tests/test_rolling_session.py ui/src/__tests__/LoginReturnTo.test.tsx
git commit -m "feat(auth): a rolling session, and a link that survives the login"
```

---

### Task 9: Bootstrap the live project, verify, and record

**Files:**
- Modify: `CLAUDE.md`
- Data: `data/system.db`, `data/sp-gs-am.db`

- [ ] **Step 1: Back up both databases first**

```bash
cp data/system.db "$CLAUDE_JOB_DIR/tmp/system.db.bak"
cp data/sp-gs-am.db "$CLAUDE_JOB_DIR/tmp/sp-gs-am.db.bak"
ls -la "$CLAUDE_JOB_DIR/tmp/"*.bak
```

- [ ] **Step 2: Report the live state before changing anything**

Read-only, and report each number: how many stakeholders on `sp-gs-am` carry each of the five
flags, how many have an email, and how many rows `users` and `project_memberships` hold. Expect
two stakeholders, both `is_reviewer` and `is_approver`, one with an address, and zero users.

- [ ] **Step 3: Create the system administrator and invite the two**

Create one `users` row with `is_sys_admin = 1` for the operator, then issue invites for the
stakeholders that have an address. **Dougie McCrone has no email**: report that he cannot be
invited until one is set, and do not invent one. Report the raw invite tokens to the operator
rather than emailing, since Resend's sender domain is unverified on this project.

- [ ] **Step 4: Verify the walk against the live data, read-only**

Confirm `caller_roles('sp-gs-am', {...})` returns the expected set for the linked person and the
empty set for an unlinked one, and that a `sys_admin` gets `project_admin` and no content roles.
Report each.

- [ ] **Step 5: Run both suites**

`./venv/bin/pytest -q` twice with identical counts, then from `ui/`: `npx vitest run && npx tsc
--noEmit`.

- [ ] **Step 6: Update CLAUDE.md**

Verify every claim against the code before writing it, then add under **API conventions**:

```markdown
Authority on a project is read, never inferred. `caller_roles(slug, payload)` in
`api/services/authority_service.py` walks JWT to `users`, to `project_memberships` for that
slug, to the `stakeholders` row it names, and returns the roles that row carries -
`project_admin`, `governor`, `approver`, `reviewer`, or `participant`. It previously matched
the caller's account email against a stakeholder email, behind an
`if role == "sysadmin": return True` that did all the work in practice because `users` was
empty - granting content authority to whoever could administer accounts.

`is_sys_admin` is global and implies `project_admin` on every project, so a newly created
project - which has no stakeholders and therefore no way to add one - can be bootstrapped. It
implies nothing about content. Administration and content are different axes.

Setting any role other than `is_participant` on a person with no login issues an invite; a
participant never gets one, because they are reached by interview URL and token. One live
invite per person, re-issuable when the email is lost, and the same token table serves password
resets.
```

- [ ] **Step 7: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: record how authority is read, and how somebody gets a login"
```

---

## Self-Review

**Spec coverage**

| Spec requirement | Task |
|---|---|
| Five role flags on the person record | 1 |
| `is_sys_admin` global; `stakeholder_id` on the membership | 2 |
| Authority is a walk, no text match | 3 |
| `sys_admin` implies `project_admin` and nothing else | 3 |
| Every gate reads one function; old authority removed | 4 |
| Forced approval permitted and recorded as forced | 5 |
| Invite issued, one live per person, re-issuable | 6, 7 |
| Password reset over the same machinery | 6 |
| Participant needs no login | 7 |
| Rolling thirty-day session | 8 |
| A deep link survives the login round trip | 8 |
| Bootstrap the live project; Dougie's missing email surfaced | 9 |
| Notifications resolve by role from the person record | none - `resolve_recipients` already filters on these columns, so Tasks 1 and 9 are sufficient and no code change is required |
| Test mode replaces `dev_mode` | none - sub-project D |
| PAM's daily reminders | none - sub-project C |
| Project settings and `crews_enabled` | none - sub-project B |

**Placeholder scan:** none. Six steps direct the implementer to read real code rather than trust
the plan - Task 1 Step 1's signatures, Task 4 Step 1's call-site sweep, Task 4 Step 2's fixtures,
Task 7 Step 1's routes, Task 8 Step 4's guard component, and Task 9 Step 2's live state - stated
explicitly because briefs on this project have been wrong about details repeatedly.

**Type consistency:** `caller_roles(slug: str, payload: dict) -> set[str]` is defined in Task 3
and consumed in Tasks 4 and 9. `link_membership(conn, *, user_id, project_slug, stakeholder_id)`
is defined in Task 2 and consumed in Task 6. `issue_invite(email, project_slug, stakeholder_id)`,
`reissue_invite(email)`, `accept_token(raw_token, password)`, and `issue_reset(email)` are defined
in Task 6 and consumed in Task 7. The five flag names are identical in Tasks 1, 3, 7, and 9.
`_SCHEMA_VERSION` moves 5 → 6 in Task 1 and 6 → 7 in Task 5, and no other task touches it.

**One ordering note:** Task 4 removes `_caller_matches_stakeholder_flag` before Task 6 exists to
create any login, so between those commits nobody can pass an authority check on a real
deployment. That is deliberate and safe here - `users` holds zero rows today, so nobody passes one
now either, and the alternative leaves two authority systems live at once with the email match
still reachable. Task 9 is what makes the deployment usable again, and it is the last task for
that reason.
