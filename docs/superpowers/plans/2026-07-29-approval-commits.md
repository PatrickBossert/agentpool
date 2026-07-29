# Committing Output and Releasing It Downstream - Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A finished crew's outputs are committed by an approver, and committing arms the crews downstream - replacing a 24-hour blocking sleep with a row in a table.

**Architecture:** Three new per-project tables record what was committed, which output versions it froze, and every change asked of an output. A Python dependency graph replaces the frontend-only display map and computes readiness from commit history rather than storing a flag. The end-of-phase gating that made crews block is removed from the agent skills, so a crew's last act becomes finishing.

**Tech Stack:** FastAPI, aiosqlite, pytest / pytest-asyncio; React 18, TypeScript, Tailwind CSS v3, vitest, @testing-library/react.

## Global Constraints

- **British English** throughout - `-ise` (organise, prioritise), `-our` (behaviour, colour), `-re` (centre).
- **Spaced hyphen ` - `** in prose, comments, and copy. Never an em dash (`—`). Hyphenated compound adjectives keep their tight hyphen ("per-minute").
- **No emoji** in rendered web content. Lucide React icons only.
- **Oxford comma** in lists of three or more.
- Backend: async `aiosqlite` throughout; all raw SQL lives in `api/database.py`; no ORM. Routers live in `api/routers/<resource>.py`, services in `api/services/<feature>_service.py`.
- Frontend: brand tokens only - `bg-brand`, `text-brand`, `brand-dark`. Never `sky-*` or `blue-*`.
- Backend tests run with `./venv/bin/pytest` - **not** bare `pytest`.
- **Baseline: 548 backend tests, 66 frontend tests, both green, `tsc --noEmit` clean.** Any failure you see is yours.
- **Readiness is computed, never stored.** A stored flag would need invalidating on every commit, and a stale one would arm a crew whose inputs had been withdrawn.
- **A commit is never undone and a committed version is never edited.** Later projects' differential depends on both.

---

## File Structure

| File | Responsibility |
|------|----------------|
| `api/database.py` (modify) | The three new tables in `init_db`, plus their helpers. All SQL |
| `api/services/crew_graph.py` (create) | `CREW_DEPENDENCIES`, inversion, and readiness computed from commits |
| `api/services/commit_service.py` (create) | Who may commit; performing a commit; the change log for a crew |
| `api/routers/commits.py` (create) | The four endpoints |
| `api/main.py` (modify) | Register the router |
| `api/services/skills_service.py` (modify) | Remove end-of-phase gating from two skills |
| `api/services/run_service.py` (modify) | Notify reviewers and approvers when a run completes |
| `ui/src/api/endpoints.ts` (modify) | `commitsApi` |
| `ui/src/components/CrewCarousel.tsx` (modify) | The Ready state |
| `ui/src/components/ReviewQueue.tsx` (modify) | Crews awaiting commit, with a commit control |

---

## Task 1: The three tables and their helpers

**Files:**
- Modify: `api/database.py` - tables in `init_db`'s `executescript` (after `human_reviews`, which ends at line 77); helpers after `update_review` (ends line 930)
- Test: `tests/test_approval_commits.py`

**Interfaces:**
- Consumes: `get_connection(slug)`, `fetch_project(conn, slug=)`, `insert_agent_output(conn, ...)` - all existing
- Produces:
  - `async def insert_approval_commit(conn, *, crew_name: str, committed_by: str, notes: str = "") -> int`
  - `async def link_commit_outputs(conn, *, commit_id: int, output_ids: list[int]) -> None`
  - `async def fetch_approval_commits(conn, *, crew_name: str | None = None) -> list[dict]`
  - `async def crew_has_commit(conn, *, crew_name: str) -> bool`
  - `async def insert_output_change(conn, *, output_id: int, requested_by: str, source: str, request: str, summary: str = "") -> int`
  - `async def fetch_output_changes(conn, *, output_ids: list[int]) -> list[dict]`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_approval_commits.py`:

```python
# tests/test_approval_commits.py
"""Commits freeze output versions; changes record what was asked of an output.

A commit is the only act that is not a change - it fixes a version and releases it,
and later projects diff consecutive commits to find what moved.
"""
import pytest

from api.config import get_settings

PROJECT = {
    "client_slug": "commit-test",
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


async def _make_output(slug: str, agent_name: str = "value_chain_mapper") -> int:
    from api.database import get_connection, fetch_project, insert_agent_output
    async with get_connection(slug) as conn:
        project = await fetch_project(conn, slug=slug)
        return await insert_agent_output(
            conn,
            project_id=project["id"],
            agent_name=agent_name,
            output_type="value_chain",
            file_path="/tmp/vc.json",
            version=1,
        )


@pytest.mark.asyncio
async def test_a_commit_records_who_and_freezes_the_outputs_it_names(client):
    await client.post("/projects", json=PROJECT)
    output_id = await _make_output("commit-test")

    from api.database import (
        get_connection, insert_approval_commit, link_commit_outputs,
        fetch_approval_commits,
    )
    async with get_connection("commit-test") as conn:
        commit_id = await insert_approval_commit(
            conn, crew_name="discovery_mapping", committed_by="admin", notes="looks right"
        )
        await link_commit_outputs(conn, commit_id=commit_id, output_ids=[output_id])
        commits = await fetch_approval_commits(conn)

    assert len(commits) == 1
    assert commits[0]["crew_name"] == "discovery_mapping"
    assert commits[0]["committed_by"] == "admin"
    assert commits[0]["notes"] == "looks right"


@pytest.mark.asyncio
async def test_crew_has_commit_distinguishes_committed_crews(client):
    await client.post("/projects", json=PROJECT)

    from api.database import get_connection, insert_approval_commit, crew_has_commit
    async with get_connection("commit-test") as conn:
        assert await crew_has_commit(conn, crew_name="discovery_mapping") is False
        await insert_approval_commit(
            conn, crew_name="discovery_mapping", committed_by="admin"
        )
        assert await crew_has_commit(conn, crew_name="discovery_mapping") is True
        # Committing one crew says nothing about another.
        assert await crew_has_commit(conn, crew_name="assessment_design") is False


@pytest.mark.asyncio
async def test_a_crew_with_no_outputs_can_still_be_committed(client):
    """Some crews produce no artefact, and readiness asks only whether a commit exists."""
    await client.post("/projects", json=PROJECT)

    from api.database import get_connection, insert_approval_commit, link_commit_outputs, crew_has_commit
    async with get_connection("commit-test") as conn:
        commit_id = await insert_approval_commit(
            conn, crew_name="stakeholder_management", committed_by="admin"
        )
        await link_commit_outputs(conn, commit_id=commit_id, output_ids=[])
        assert await crew_has_commit(conn, crew_name="stakeholder_management") is True


@pytest.mark.asyncio
async def test_changes_record_who_asked_and_what_the_agent_did(client):
    await client.post("/projects", json=PROJECT)
    output_id = await _make_output("commit-test")

    from api.database import get_connection, insert_output_change, fetch_output_changes
    async with get_connection("commit-test") as conn:
        await insert_output_change(
            conn,
            output_id=output_id,
            requested_by="patrick",
            source="note",
            request="Add an L3 for asset tagging",
            summary="",
        )
        changes = await fetch_output_changes(conn, output_ids=[output_id])

    assert len(changes) == 1
    assert changes[0]["requested_by"] == "patrick"
    assert changes[0]["source"] == "note"
    assert changes[0]["request"] == "Add an L3 for asset tagging"


@pytest.mark.asyncio
async def test_fetching_changes_for_no_outputs_returns_nothing_rather_than_everything(client):
    """An empty id list must not degenerate into an unfiltered query."""
    await client.post("/projects", json=PROJECT)
    output_id = await _make_output("commit-test")

    from api.database import get_connection, insert_output_change, fetch_output_changes
    async with get_connection("commit-test") as conn:
        await insert_output_change(
            conn, output_id=output_id, requested_by="p", source="note", request="x"
        )
        assert await fetch_output_changes(conn, output_ids=[]) == []
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `./venv/bin/pytest tests/test_approval_commits.py -v`
Expected: FAIL - `ImportError: cannot import name 'insert_approval_commit' from 'api.database'`

- [ ] **Step 3: Add the tables**

In `api/database.py`, inside `init_db`'s `executescript`, immediately after the
`human_reviews` table (which ends at line 77 with `);`), add:

```sql
        -- One row per act of committing: what a governing role signed off, and when.
        CREATE TABLE IF NOT EXISTS approval_commits (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            crew_name     TEXT NOT NULL,
            committed_by  TEXT NOT NULL,
            committed_at  TEXT NOT NULL DEFAULT (datetime('now')),
            notes         TEXT NOT NULL DEFAULT ''
        );

        -- Exactly which output versions a commit froze. Later projects diff
        -- consecutive commits through this table.
        CREATE TABLE IF NOT EXISTS approval_commit_outputs (
            commit_id  INTEGER NOT NULL REFERENCES approval_commits(id),
            output_id  INTEGER NOT NULL REFERENCES agent_outputs(id),
            PRIMARY KEY (commit_id, output_id)
        );

        -- Every change asked of an output, however it was asked for.
        CREATE TABLE IF NOT EXISTS output_changes (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            output_id     INTEGER NOT NULL REFERENCES agent_outputs(id),
            requested_by  TEXT NOT NULL,
            source        TEXT NOT NULL,
            request       TEXT NOT NULL,
            summary       TEXT NOT NULL DEFAULT '',
            created_at    TEXT NOT NULL DEFAULT (datetime('now'))
        );
```

`source` is `'note'` in this project; `'chat'` and `'edit'` arrive with the later doors,
which is why the column exists from the start.

- [ ] **Step 4: Add the helpers**

In `api/database.py`, after `update_review` (ends line 930), add:

```python
async def insert_approval_commit(
    conn: aiosqlite.Connection, *, crew_name: str, committed_by: str, notes: str = ""
) -> int:
    """Record that a crew's outputs were committed. Never undone - a later commit
    supersedes it, and the history is the audit trail."""
    cur = await conn.execute(
        "INSERT INTO approval_commits (crew_name, committed_by, notes) VALUES (?,?,?)",
        (crew_name, committed_by, notes),
    )
    await conn.commit()
    return cur.lastrowid


async def link_commit_outputs(
    conn: aiosqlite.Connection, *, commit_id: int, output_ids: list[int]
) -> None:
    """Freeze these output versions against a commit. An empty list is valid - some
    crews produce no artefact."""
    for output_id in output_ids:
        await conn.execute(
            "INSERT OR IGNORE INTO approval_commit_outputs (commit_id, output_id) VALUES (?,?)",
            (commit_id, output_id),
        )
    await conn.commit()


async def fetch_approval_commits(
    conn: aiosqlite.Connection, *, crew_name: str | None = None
) -> list[dict]:
    """Commit history, newest first. Filtered to one crew when named."""
    if crew_name is None:
        sql, params = "SELECT * FROM approval_commits ORDER BY id DESC", ()
    else:
        sql, params = (
            "SELECT * FROM approval_commits WHERE crew_name=? ORDER BY id DESC",
            (crew_name,),
        )
    async with conn.execute(sql, params) as cur:
        return [dict(row) for row in await cur.fetchall()]


async def crew_has_commit(conn: aiosqlite.Connection, *, crew_name: str) -> bool:
    """Whether this crew has ever been committed - the unit readiness is computed from."""
    async with conn.execute(
        "SELECT 1 FROM approval_commits WHERE crew_name=? LIMIT 1", (crew_name,)
    ) as cur:
        return await cur.fetchone() is not None


async def insert_output_change(
    conn: aiosqlite.Connection,
    *,
    output_id: int,
    requested_by: str,
    source: str,
    request: str,
    summary: str = "",
) -> int:
    """Record a change asked of an output: who asked, through which door, for what."""
    cur = await conn.execute(
        "INSERT INTO output_changes (output_id, requested_by, source, request, summary) "
        "VALUES (?,?,?,?,?)",
        (output_id, requested_by, source, request, summary),
    )
    await conn.commit()
    return cur.lastrowid


async def fetch_output_changes(
    conn: aiosqlite.Connection, *, output_ids: list[int]
) -> list[dict]:
    """Changes against these outputs, newest first.

    An empty id list returns nothing rather than everything - the alternative is an
    unfiltered query that silently reports the whole project's history.
    """
    if not output_ids:
        return []
    placeholders = ",".join("?" for _ in output_ids)
    async with conn.execute(
        f"SELECT * FROM output_changes WHERE output_id IN ({placeholders}) ORDER BY id DESC",
        tuple(output_ids),
    ) as cur:
        return [dict(row) for row in await cur.fetchall()]
```

The `IN (...)` list is built from placeholders, never from interpolated values - the ids
come from a query rather than a request body, but the habit is what keeps it true.

- [ ] **Step 5: Run the tests to verify they pass**

Run: `./venv/bin/pytest tests/test_approval_commits.py -v`
Expected: 5 passed

- [ ] **Step 6: Run the full backend suite**

Run: `./venv/bin/pytest -q --ignore=tests/integration`
Expected: 553 passed (548 baseline + 5). No new warnings.

- [ ] **Step 7: Commit**

```bash
git add api/database.py tests/test_approval_commits.py
git commit -m "feat: record commits, the versions they freeze, and changes asked of outputs"
```

---

## Task 2: The dependency graph and computed readiness

**Files:**
- Create: `api/services/crew_graph.py`
- Test: `tests/test_crew_graph.py`

**Interfaces:**
- Consumes: `crew_has_commit(conn, *, crew_name)` from Task 1; `_CREW_AGENT_NAMES` from `api/services/run_service.py:18`
- Produces:
  - `CREW_DEPENDENCIES: dict[str, list[str]]`
  - `def downstream_of(crew_name: str) -> list[str]`
  - `async def is_crew_ready(conn, *, crew_name: str) -> bool`
  - `async def readiness_report(conn) -> dict[str, dict]` - `{crew: {"ready": bool, "waiting_on": [str]}}`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_crew_graph.py`:

```python
# tests/test_crew_graph.py
"""Which crews may run, derived from what has been committed.

Readiness is computed rather than stored: a stored flag would need invalidating on
every commit, and a stale one would arm a crew whose inputs had been withdrawn.
"""
import pytest

from api.config import get_settings
from api.services.crew_graph import (
    CREW_DEPENDENCIES,
    downstream_of,
    is_crew_ready,
    readiness_report,
)

PROJECT = {
    "client_slug": "graph-test",
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


def test_every_dispatchable_crew_appears_in_the_graph():
    """A crew missing from the graph would be permanently unready with no signal."""
    from api.services.run_service import _CREW_AGENT_NAMES
    assert set(CREW_DEPENDENCIES) == set(_CREW_AGENT_NAMES)


def test_every_named_dependency_is_itself_a_crew():
    for crew, upstreams in CREW_DEPENDENCIES.items():
        for upstream in upstreams:
            assert upstream in CREW_DEPENDENCIES, f"{crew} depends on unknown {upstream}"


def test_the_graph_is_acyclic():
    """A cycle would make both crews permanently unready and is invisible by eye."""
    visiting, done = set(), set()

    def visit(crew: str, trail: list[str]) -> None:
        if crew in done:
            return
        assert crew not in visiting, f"cycle: {' -> '.join(trail + [crew])}"
        visiting.add(crew)
        for upstream in CREW_DEPENDENCIES[crew]:
            visit(upstream, trail + [crew])
        visiting.discard(crew)
        done.add(crew)

    for crew in CREW_DEPENDENCIES:
        visit(crew, [])


def test_jordan_now_follows_maya():
    """The reordering: stakeholder_management depends on assessment_design."""
    assert "assessment_design" in CREW_DEPENDENCIES["stakeholder_management"]


def test_downstream_is_the_inverse_of_dependencies():
    assert "assessment_design" in downstream_of("discovery_mapping")
    assert downstream_of("business_plan") == []


@pytest.mark.asyncio
async def test_a_crew_with_no_dependencies_is_always_ready(client):
    await client.post("/projects", json=PROJECT)
    from api.database import get_connection
    async with get_connection("graph-test") as conn:
        assert await is_crew_ready(conn, crew_name="discovery_mapping") is True


@pytest.mark.asyncio
async def test_a_crew_waits_until_every_upstream_is_committed(client):
    await client.post("/projects", json=PROJECT)
    from api.database import get_connection, insert_approval_commit

    async with get_connection("graph-test") as conn:
        # discovery_interviews needs assessment_design AND stakeholder_management.
        assert await is_crew_ready(conn, crew_name="discovery_interviews") is False

        await insert_approval_commit(
            conn, crew_name="assessment_design", committed_by="admin"
        )
        assert await is_crew_ready(conn, crew_name="discovery_interviews") is False

        await insert_approval_commit(
            conn, crew_name="stakeholder_management", committed_by="admin"
        )
        assert await is_crew_ready(conn, crew_name="discovery_interviews") is True


@pytest.mark.asyncio
async def test_the_report_names_what_each_crew_is_waiting_on(client):
    await client.post("/projects", json=PROJECT)
    from api.database import get_connection, insert_approval_commit

    async with get_connection("graph-test") as conn:
        await insert_approval_commit(
            conn, crew_name="assessment_design", committed_by="admin"
        )
        report = await readiness_report(conn)

    assert report["discovery_mapping"]["ready"] is True
    assert report["discovery_interviews"]["ready"] is False
    assert report["discovery_interviews"]["waiting_on"] == ["stakeholder_management"]
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `./venv/bin/pytest tests/test_crew_graph.py -v`
Expected: FAIL - `ModuleNotFoundError: No module named 'api.services.crew_graph'`

- [ ] **Step 3: Implement**

Create `api/services/crew_graph.py`:

```python
# api/services/crew_graph.py
"""Which crews may run, and what they are waiting for.

The frontend has carried a CREW_DOWNSTREAM map for display since long before anything
could act on it. This is the authoritative form: upstream dependencies, because that is
what readiness is computed from. Downstream targets are derived by inversion.
"""
from __future__ import annotations

import aiosqlite

from api.database import crew_has_commit

# Each crew maps to the crews that must be committed before it may run.
# Alex -> Maya -> Jordan: stakeholder_management follows assessment_design, because
# Jordan's coming role is to report which steps and roles have no interview covering
# them, which he can only do once Maya's interviews exist.
CREW_DEPENDENCIES: dict[str, list[str]] = {
    "discovery_mapping":      [],
    "assessment_design":      ["discovery_mapping"],
    "stakeholder_management": ["assessment_design"],
    "discovery":              [],
    "discovery_interviews":   ["assessment_design", "stakeholder_management"],
    "value_design":           ["discovery", "discovery_interviews"],
    "architecture":           ["value_design"],
    "delivery":               ["architecture"],
    "business_plan":          ["delivery"],
}


def downstream_of(crew_name: str) -> list[str]:
    """The crews a commit to this one could release."""
    return [
        crew for crew, upstreams in CREW_DEPENDENCIES.items() if crew_name in upstreams
    ]


async def is_crew_ready(conn: aiosqlite.Connection, *, crew_name: str) -> bool:
    """True when every upstream crew has been committed at least once.

    Later uncommitted changes upstream do not un-arm a crew: readiness was released by
    a commit, and that release stands. The next upstream commit releases the next
    increment.
    """
    for upstream in CREW_DEPENDENCIES.get(crew_name, []):
        if not await crew_has_commit(conn, crew_name=upstream):
            return False
    return True


async def readiness_report(conn: aiosqlite.Connection) -> dict[str, dict]:
    """Per crew: whether it is ready, and which upstream crews it is still waiting on."""
    committed = {
        crew: await crew_has_commit(conn, crew_name=crew) for crew in CREW_DEPENDENCIES
    }
    return {
        crew: {
            "ready": all(committed[u] for u in upstreams),
            "waiting_on": [u for u in upstreams if not committed[u]],
        }
        for crew, upstreams in CREW_DEPENDENCIES.items()
    }
```

`readiness_report` queries each crew once and reuses the result, rather than calling
`is_crew_ready` per crew and re-querying shared upstreams.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `./venv/bin/pytest tests/test_crew_graph.py -v`
Expected: 8 passed

- [ ] **Step 5: Run the full backend suite**

Run: `./venv/bin/pytest -q --ignore=tests/integration`
Expected: 561 passed. No new warnings.

- [ ] **Step 6: Commit**

```bash
git add api/services/crew_graph.py tests/test_crew_graph.py
git commit -m "feat: add the crew dependency graph and compute readiness from commits"
```

---

## Task 3: Committing, and who may do it

**Files:**
- Create: `api/services/commit_service.py`
- Create: `api/routers/commits.py`
- Modify: `api/main.py` - import beside the other routers, `include_router` beside its neighbours
- Test: `tests/test_commit_endpoint.py`

**Interfaces:**
- Consumes: Task 1's helpers; `CREW_DEPENDENCIES`, `downstream_of`, `is_crew_ready`, `readiness_report` from Task 2; `fetch_user` (`api/database.py:1714`), `fetch_stakeholders(conn, *, project_id)` (`api/database.py:1134`), `_CREW_AGENT_NAMES` (`api/services/run_service.py:18`)
- Produces:
  - `async def caller_may_commit(slug: str, payload: dict) -> bool`
  - `async def commit_crew(slug: str, *, crew_name: str, committed_by: str, notes: str) -> dict` returning `{"commit_id": int, "output_ids": [int], "released": [str]}`
  - `GET /projects/{slug}/crew-readiness`, `POST /projects/{slug}/commits`, `GET /projects/{slug}/commits`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_commit_endpoint.py`:

```python
# tests/test_commit_endpoint.py
"""Committing a crew's outputs, and who is allowed to.

The identity model cannot yet express "only approvers commit": the users table is
empty and every login is sysadmin. The rule is written so it is correct now and
tightens by itself once per-user accounts exist.
"""
import pytest

from api.config import get_settings

PROJECT = {
    "client_slug": "commit-api-test",
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


async def _make_output(slug: str, agent_name: str) -> int:
    from api.database import get_connection, fetch_project, insert_agent_output
    async with get_connection(slug) as conn:
        project = await fetch_project(conn, slug=slug)
        return await insert_agent_output(
            conn,
            project_id=project["id"],
            agent_name=agent_name,
            output_type="value_chain",
            file_path="/tmp/vc.json",
            version=1,
        )


@pytest.mark.asyncio
async def test_committing_freezes_only_that_crews_outputs(client):
    await client.post("/projects", json=PROJECT)
    mine = await _make_output("commit-api-test", "value_chain_mapper")   # discovery_mapping
    theirs = await _make_output("commit-api-test", "interaction_designer")  # assessment_design

    resp = await client.post(
        "/projects/commit-api-test/commits",
        json={"crew_name": "discovery_mapping", "notes": "signed off"},
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["output_ids"] == [mine]
    assert theirs not in body["output_ids"]


@pytest.mark.asyncio
async def test_committing_reports_the_crews_it_released(client):
    await client.post("/projects", json=PROJECT)
    resp = await client.post(
        "/projects/commit-api-test/commits",
        json={"crew_name": "discovery_mapping", "notes": ""},
    )
    assert resp.json()["released"] == ["assessment_design"]


@pytest.mark.asyncio
async def test_a_crew_released_only_when_its_last_upstream_lands(client):
    """discovery_interviews needs both assessment_design and stakeholder_management."""
    await client.post("/projects", json=PROJECT)
    first = await client.post(
        "/projects/commit-api-test/commits",
        json={"crew_name": "assessment_design", "notes": ""},
    )
    assert "discovery_interviews" not in first.json()["released"]

    second = await client.post(
        "/projects/commit-api-test/commits",
        json={"crew_name": "stakeholder_management", "notes": ""},
    )
    assert "discovery_interviews" in second.json()["released"]


@pytest.mark.asyncio
async def test_an_unknown_crew_is_rejected(client):
    await client.post("/projects", json=PROJECT)
    resp = await client.post(
        "/projects/commit-api-test/commits",
        json={"crew_name": "not_a_crew", "notes": ""},
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_readiness_endpoint_reflects_commits(client):
    await client.post("/projects", json=PROJECT)
    before = (await client.get("/projects/commit-api-test/crew-readiness")).json()
    assert before["assessment_design"]["ready"] is False
    assert before["assessment_design"]["waiting_on"] == ["discovery_mapping"]

    await client.post(
        "/projects/commit-api-test/commits",
        json={"crew_name": "discovery_mapping", "notes": ""},
    )
    after = (await client.get("/projects/commit-api-test/crew-readiness")).json()
    assert after["assessment_design"]["ready"] is True
    assert after["assessment_design"]["waiting_on"] == []


@pytest.mark.asyncio
async def test_commit_history_is_returned_newest_first(client):
    await client.post("/projects", json=PROJECT)
    for crew in ("discovery_mapping", "discovery"):
        await client.post(
            "/projects/commit-api-test/commits", json={"crew_name": crew, "notes": ""}
        )
    history = (await client.get("/projects/commit-api-test/commits")).json()
    assert [c["crew_name"] for c in history] == ["discovery", "discovery_mapping"]
    assert history[0]["committed_by"] == "admin"


@pytest.mark.asyncio
async def test_a_non_sysadmin_without_a_matching_approver_is_refused():
    """The rule that will bite once real accounts exist."""
    from httpx import ASGITransport, AsyncClient

    from api.auth import create_access_token
    from api.main import app

    token = create_access_token("nobody", "consultant", "test-secret")
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        headers={"Authorization": f"Bearer {token}"},
    ) as ac:
        resp = await ac.post(
            "/projects/commit-api-test/commits",
            json={"crew_name": "discovery_mapping", "notes": ""},
        )
    assert resp.status_code == 403
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `./venv/bin/pytest tests/test_commit_endpoint.py -v`
Expected: FAIL - every request returns 404, the routes do not exist.

- [ ] **Step 3: Write the service**

Create `api/services/commit_service.py`:

```python
# api/services/commit_service.py
"""Committing a crew's outputs, and deciding who may.

Committing is the one act that is not a change: it does not mutate an output, it fixes
the current version, attributes it, and releases the crews downstream.
"""
from __future__ import annotations

import logging

from api.database import (
    crew_has_commit,
    fetch_agent_outputs,
    fetch_project,
    fetch_stakeholders,
    fetch_user,
    get_connection,
    get_system_connection,
    insert_approval_commit,
    link_commit_outputs,
)
from api.services.crew_graph import CREW_DEPENDENCIES, downstream_of, is_crew_ready
from api.services.run_service import _CREW_AGENT_NAMES

log = logging.getLogger(__name__)


async def caller_may_commit(slug: str, payload: dict) -> bool:
    """Whether this caller may commit in this project.

    The intent is that only governing roles commit, but nothing links a login to a
    stakeholder record: the users table is empty and every login is sysadmin. So the
    rule permits the platform operator, and otherwise matches the caller's account
    email against a stakeholder flagged is_approver. Today the first branch always
    fires; the restriction becomes real when accounts exist, with no code change.
    """
    if payload.get("role") == "sysadmin":
        return True

    async with get_system_connection() as sys_conn:
        user = await fetch_user(sys_conn, username=payload.get("sub", ""))
    email = ((user or {}).get("email") or "").strip().lower()
    if not email:
        # A stakeholder with no email can never be matched either - the join needs
        # both sides to have one.
        return False

    async with get_connection(slug) as conn:
        project = await fetch_project(conn, slug=slug)
        if not project:
            return False
        stakeholders = await fetch_stakeholders(conn, project_id=project["id"])

    return any(
        ((s.get("email") or "").strip().lower() == email) and s.get("is_approver")
        for s in stakeholders
    )


async def commit_crew(
    slug: str, *, crew_name: str, committed_by: str, notes: str
) -> dict:
    """Freeze this crew's current outputs and report the crews it released.

    "Released" means newly ready: a crew that was already ready before this commit is
    not reported, so the caller can react to what actually changed.
    """
    agents = set(_CREW_AGENT_NAMES.get(crew_name, []))

    async with get_connection(slug) as conn:
        project = await fetch_project(conn, slug=slug)
        outputs = await fetch_agent_outputs(conn, project_id=project["id"])
        output_ids = [
            o["id"]
            for o in outputs
            if o["agent_name"] in agents and o.get("is_current")
        ]

        candidates = downstream_of(crew_name)
        was_ready = {
            c: await is_crew_ready(conn, crew_name=c) for c in candidates
        }

        commit_id = await insert_approval_commit(
            conn, crew_name=crew_name, committed_by=committed_by, notes=notes
        )
        await link_commit_outputs(conn, commit_id=commit_id, output_ids=output_ids)

        released = [
            c
            for c in candidates
            if not was_ready[c] and await is_crew_ready(conn, crew_name=c)
        ]

    return {"commit_id": commit_id, "output_ids": output_ids, "released": released}
```

- [ ] **Step 4: Write the router**

Create `api/routers/commits.py`:

```python
# api/routers/commits.py
"""Committing crew output, and reading what that released."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from api.auth import check_project_access, require_any_auth
from api.database import fetch_approval_commits, get_connection, get_db_path
from api.services.commit_service import caller_may_commit, commit_crew
from api.services.crew_graph import CREW_DEPENDENCIES, readiness_report

router = APIRouter(prefix="/projects", tags=["commits"])


class CommitRequest(BaseModel):
    crew_name: str
    notes: str = ""


def _require_project(slug: str) -> None:
    if not get_db_path(slug).exists():
        raise HTTPException(status_code=404, detail=f"Project '{slug}' not found")


@router.post("/{slug}/commits", status_code=201)
async def create_commit(
    slug: str, req: CommitRequest, payload: dict = Depends(require_any_auth)
):
    await check_project_access(slug, payload)
    _require_project(slug)

    if req.crew_name not in CREW_DEPENDENCIES:
        raise HTTPException(status_code=422, detail=f"Unknown crew '{req.crew_name}'")

    if not await caller_may_commit(slug, payload):
        raise HTTPException(
            status_code=403, detail="Only an approver may commit this crew's output"
        )

    return await commit_crew(
        slug,
        crew_name=req.crew_name,
        committed_by=payload.get("sub", ""),
        notes=req.notes,
    )


@router.get("/{slug}/commits")
async def list_commits(slug: str, payload: dict = Depends(require_any_auth)):
    await check_project_access(slug, payload)
    _require_project(slug)
    async with get_connection(slug) as conn:
        return await fetch_approval_commits(conn)


@router.get("/{slug}/crew-readiness")
async def get_crew_readiness(slug: str, payload: dict = Depends(require_any_auth)):
    await check_project_access(slug, payload)
    _require_project(slug)
    async with get_connection(slug) as conn:
        return await readiness_report(conn)
```

- [ ] **Step 5: Register the router**

In `api/main.py`, add beside the other router imports:

```python
from api.routers import commits as commits_router
```

and beside the `include_router` calls:

```python
app.include_router(commits_router.router)
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `./venv/bin/pytest tests/test_commit_endpoint.py -v`
Expected: 7 passed

- [ ] **Step 7: Run the full backend suite**

Run: `./venv/bin/pytest -q --ignore=tests/integration`
Expected: 568 passed. No new warnings.

- [ ] **Step 8: Commit**

```bash
git add api/services/commit_service.py api/routers/commits.py api/main.py tests/test_commit_endpoint.py
git commit -m "feat: commit a crew's outputs and report the crews it released"
```

---

## Task 4: The change log

**Files:**
- Modify: `api/services/commit_service.py` - add `changes_for_crew`
- Modify: `api/routers/commits.py` - add two routes
- Test: `tests/test_output_changes.py`

**Interfaces:**
- Consumes: `insert_output_change`, `fetch_output_changes` from Task 1; `_CREW_AGENT_NAMES`
- Produces:
  - `async def changes_for_crew(slug: str, *, crew_name: str) -> list[dict]`
  - `POST /projects/{slug}/changes`, `GET /projects/{slug}/changes?crew_name=`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_output_changes.py`:

```python
# tests/test_output_changes.py
"""A change asked of an output, recorded with who asked.

In this project the only door is a reviewer's note. Chat and inline editing arrive
later and write the same rows with a different source.
"""
import pytest

from api.config import get_settings

PROJECT = {
    "client_slug": "changes-test",
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


async def _make_output(slug: str, agent_name: str) -> int:
    from api.database import get_connection, fetch_project, insert_agent_output
    async with get_connection(slug) as conn:
        project = await fetch_project(conn, slug=slug)
        return await insert_agent_output(
            conn,
            project_id=project["id"],
            agent_name=agent_name,
            output_type="value_chain",
            file_path="/tmp/vc.json",
            version=1,
        )


@pytest.mark.asyncio
async def test_a_note_is_recorded_against_the_caller(client):
    await client.post("/projects", json=PROJECT)
    output_id = await _make_output("changes-test", "value_chain_mapper")

    resp = await client.post(
        "/projects/changes-test/changes",
        json={"output_id": output_id, "request": "Add an L3 for asset tagging"},
    )
    assert resp.status_code == 201
    assert resp.json()["requested_by"] == "admin"
    assert resp.json()["source"] == "note"


@pytest.mark.asyncio
async def test_changes_are_listed_for_the_crew_that_owns_the_output(client):
    await client.post("/projects", json=PROJECT)
    mine = await _make_output("changes-test", "value_chain_mapper")     # discovery_mapping
    theirs = await _make_output("changes-test", "interaction_designer")  # assessment_design

    for output_id, text in ((mine, "mine"), (theirs, "theirs")):
        await client.post(
            "/projects/changes-test/changes",
            json={"output_id": output_id, "request": text},
        )

    listed = (
        await client.get("/projects/changes-test/changes?crew_name=discovery_mapping")
    ).json()
    assert [c["request"] for c in listed] == ["mine"]


@pytest.mark.asyncio
async def test_a_note_leaves_committed_versions_untouched(client):
    """The invariant later projects' differential depends on."""
    await client.post("/projects", json=PROJECT)
    output_id = await _make_output("changes-test", "value_chain_mapper")

    await client.post(
        "/projects/changes-test/commits",
        json={"crew_name": "discovery_mapping", "notes": ""},
    )
    await client.post(
        "/projects/changes-test/changes",
        json={"output_id": output_id, "request": "later thought"},
    )

    from api.database import get_connection
    async with get_connection("changes-test") as conn:
        async with conn.execute(
            "SELECT output_id FROM approval_commit_outputs"
        ) as cur:
            frozen = [r["output_id"] for r in await cur.fetchall()]
    assert frozen == [output_id]


@pytest.mark.asyncio
async def test_a_change_against_an_unknown_output_is_rejected(client):
    await client.post("/projects", json=PROJECT)
    resp = await client.post(
        "/projects/changes-test/changes",
        json={"output_id": 999999, "request": "nothing to change"},
    )
    assert resp.status_code == 422
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `./venv/bin/pytest tests/test_output_changes.py -v`
Expected: FAIL - the `/changes` routes return 404.

- [ ] **Step 3: Add the service function**

Append to `api/services/commit_service.py`:

```python
async def changes_for_crew(slug: str, *, crew_name: str) -> list[dict]:
    """Every change asked of this crew's current outputs, newest first."""
    agents = set(_CREW_AGENT_NAMES.get(crew_name, []))
    async with get_connection(slug) as conn:
        project = await fetch_project(conn, slug=slug)
        outputs = await fetch_agent_outputs(conn, project_id=project["id"])
        output_ids = [
            o["id"] for o in outputs if o["agent_name"] in agents and o.get("is_current")
        ]
        return await fetch_output_changes(conn, output_ids=output_ids)
```

and add `fetch_output_changes` and `insert_output_change` to the module's existing
`from api.database import (...)` block.

- [ ] **Step 4: Add the routes**

In `api/routers/commits.py`, add the request model beside `CommitRequest`:

```python
class ChangeRequest(BaseModel):
    output_id: int
    request: str
```

and the two routes:

```python
@router.post("/{slug}/changes", status_code=201)
async def create_change(
    slug: str, req: ChangeRequest, payload: dict = Depends(require_any_auth)
):
    """Record a change asked of an output. The only door in this project is a note."""
    await check_project_access(slug, payload)
    _require_project(slug)

    async with get_connection(slug) as conn:
        async with conn.execute(
            "SELECT 1 FROM agent_outputs WHERE id=?", (req.output_id,)
        ) as cur:
            if await cur.fetchone() is None:
                raise HTTPException(
                    status_code=422, detail=f"output_id {req.output_id} does not exist"
                )
        change_id = await insert_output_change(
            conn,
            output_id=req.output_id,
            requested_by=payload.get("sub", ""),
            source="note",
            request=req.request,
        )

    return {
        "id": change_id,
        "output_id": req.output_id,
        "requested_by": payload.get("sub", ""),
        "source": "note",
        "request": req.request,
    }


@router.get("/{slug}/changes")
async def list_changes(
    slug: str, crew_name: str, payload: dict = Depends(require_any_auth)
):
    await check_project_access(slug, payload)
    _require_project(slug)
    if crew_name not in CREW_DEPENDENCIES:
        raise HTTPException(status_code=422, detail=f"Unknown crew '{crew_name}'")
    return await changes_for_crew(slug, crew_name=crew_name)
```

Add `insert_output_change` to the router's `api.database` import and `changes_for_crew`
to its `api.services.commit_service` import.

- [ ] **Step 5: Run the tests to verify they pass**

Run: `./venv/bin/pytest tests/test_output_changes.py -v`
Expected: 4 passed

- [ ] **Step 6: Run the full backend suite**

Run: `./venv/bin/pytest -q --ignore=tests/integration`
Expected: 572 passed. No new warnings.

- [ ] **Step 7: Commit**

```bash
git add api/services/commit_service.py api/routers/commits.py tests/test_output_changes.py
git commit -m "feat: record changes asked of an output, attributed to who asked"
```

---

## Task 5: Stop the agents gating phases

**Files:**
- Modify: `api/services/skills_service.py` - the `Phase Gating` entry (line 110) and the `Human Review Gate` entry (line 131)
- Test: `tests/test_skills_no_phase_gating.py`

**Interfaces:**
- Consumes: nothing
- Produces: nothing. The skill *names* stay; their descriptions stop instructing agents to block.

**Why this matters:** eleven agents carry `HumanInputTool`, whose `_run` blocks on
`time.sleep(5)` against a 24-hour deadline (`agents/tools/human_input.py:69-90`). While
the skills tell agents to pause at the end of every phase, crews keep blocking and a
commit achieves nothing. The tool itself stays - an interviewer asking a clarifying
question mid-session is a real use.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_skills_no_phase_gating.py`:

```python
# tests/test_skills_no_phase_gating.py
"""A crew's last act is finishing.

Gating used to live in the agents' instructions, backed by a blocking 24-hour poll.
It now lives in approval_commits, so the instructions must stop telling agents to wait.
"""
import pytest

from api.services.skills_service import BASELINE_SKILLS


def _skill(name: str) -> dict:
    for skill in BASELINE_SKILLS:
        if skill["name"] == name:
            return skill
    raise AssertionError(f"skill {name!r} not found")


@pytest.mark.parametrize("skill_name", ["Phase Gating", "Human Review Gate"])
def test_the_skill_no_longer_tells_agents_to_block(skill_name):
    description = _skill(skill_name)["description"].lower()
    for phrase in ("halt", "do not allow downstream", "block every downstream",
                   "never proceed", "pause and request human review"):
        assert phrase not in description, (
            f"{skill_name} still instructs the agent to wait: {phrase!r}"
        )


@pytest.mark.parametrize("skill_name", ["Phase Gating", "Human Review Gate"])
def test_the_skill_still_asks_for_a_reviewable_summary(skill_name):
    """Removing the block must not remove the reason a reviewer can act at all."""
    description = _skill(skill_name)["description"].lower()
    assert "summar" in description or "review" in description
```

`BASELINE_SKILLS` is the list at `api/services/skills_service.py:107` - verified, not
guessed.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `./venv/bin/pytest tests/test_skills_no_phase_gating.py -v`
Expected: FAIL - both descriptions still contain blocking instructions.

- [ ] **Step 3: Rewrite the two descriptions**

In `api/services/skills_service.py`, replace the `Phase Gating` description with:

```
Produce a clear, self-contained summary at the end of each phase naming what was
produced and what a reviewer needs to validate. Do not wait for a response - the
platform records the output for review and releases downstream work when an approver
commits it.
```

and the `Human Review Gate` description with:

```
At the end of every work phase, write a summary of what was produced and what the
reviewer needs to validate, then finish. Approval is recorded outside the run, so
there is nothing to wait for.
```

Leave both skill *names* and their agent lists unchanged: the skills still exist and
still shape behaviour, they just no longer instruct the agent to block.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `./venv/bin/pytest tests/test_skills_no_phase_gating.py -v`
Expected: 4 passed

- [ ] **Step 5: Run the full backend suite**

Run: `./venv/bin/pytest -q --ignore=tests/integration`
Expected: 576 passed. If a pre-existing test asserts on either description's old wording,
update that assertion to the new text rather than reverting the change - and say so in
your report.

- [ ] **Step 6: Commit**

```bash
git add api/services/skills_service.py tests/test_skills_no_phase_gating.py
git commit -m "feat: stop the agent skills instructing crews to block for review"
```

---

## Task 6: Pamela tells the reviewers and approvers

**Files:**
- Modify: `api/services/run_service.py` - `dispatch_crew` (after line 387) and `dispatch_agent` (after line 558)
- Create: `api/services/commit_notify_service.py`
- Test: `tests/test_commit_notification.py`

**Interfaces:**
- Consumes: `resolve_recipients(stakeholders, dev_mode)` and the Resend dispatch from `api/services/pam_report_job.py`; `fetch_stakeholders`, `fetch_project`
- Produces: `async def notify_crew_awaiting_commit(slug: str, crew_name: str) -> None` - never raises

- [ ] **Step 1: Write the failing tests**

Create `tests/test_commit_notification.py`:

```python
# tests/test_commit_notification.py
"""Pamela's audience is governance - reviewers and approvers. Jordan's is the actors,
and he says nothing here.
"""
from unittest.mock import AsyncMock, patch

import pytest

from api.config import get_settings

PROJECT = {
    "client_slug": "notify-test",
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


async def _set_dev_mode(slug: str, value: bool) -> None:
    """dev_mode lives inside config_json, not as a column on projects."""
    import json
    from api.database import get_connection, fetch_project
    async with get_connection(slug) as conn:
        project = await fetch_project(conn, slug=slug)
        config = json.loads(project.get("config_json") or "{}")
        config["dev_mode"] = value
        await conn.execute(
            "UPDATE projects SET config_json=? WHERE slug=?", (json.dumps(config), slug)
        )
        await conn.commit()


async def _add_stakeholder(slug: str, name: str, email: str, *, approver: bool) -> None:
    """Set the review flags directly.

    `StakeholderIn` (`api/routers/stakeholders.py:23`) has no is_reviewer or is_approver
    fields, so posting them to the endpoint would silently drop them and every
    stakeholder would arrive with the column default of 0 - making the assertion below
    pass for the wrong reason.
    """
    from api.database import get_connection, fetch_project
    async with get_connection(slug) as conn:
        project = await fetch_project(conn, slug=slug)
        await conn.execute(
            "INSERT INTO stakeholders (project_id, name, email, project_role, "
            "is_reviewer, is_approver) VALUES (?,?,?,?,?,?)",
            (project["id"], name, email, "governing" if approver else "actor",
             int(approver), int(approver)),
        )
        await conn.commit()


@pytest.mark.asyncio
async def test_notification_goes_to_reviewers_and_approvers_only(client, monkeypatch):
    await client.post("/projects", json=PROJECT)
    await _add_stakeholder("notify-test", "Gov", "gov@example.com", approver=True)
    await _add_stakeholder("notify-test", "Actor", "actor@example.com", approver=False)
    # dev_mode defaults to on, which would redirect everything to one address and hide
    # the very filtering this test exists to check.
    await _set_dev_mode("notify-test", False)

    from api.services.commit_notify_service import notify_crew_awaiting_commit

    with patch(
        "api.services.commit_notify_service._send_email", AsyncMock()
    ) as send:
        await notify_crew_awaiting_commit("notify-test", "discovery_mapping")

    assert send.await_count == 1
    recipients = send.await_args.kwargs["to"]
    assert "actor@example.com" not in recipients


@pytest.mark.asyncio
async def test_a_failing_send_does_not_raise(client):
    """The outputs are the durable record; the email is a notification."""
    await client.post("/projects", json=PROJECT)

    from api.services.commit_notify_service import notify_crew_awaiting_commit

    with patch(
        "api.services.commit_notify_service._send_email",
        AsyncMock(side_effect=RuntimeError("resend is down")),
    ):
        await notify_crew_awaiting_commit("notify-test", "discovery_mapping")


@pytest.mark.asyncio
async def test_no_recipients_sends_nothing(client):
    await client.post("/projects", json=PROJECT)

    from api.services.commit_notify_service import notify_crew_awaiting_commit

    with patch(
        "api.services.commit_notify_service._send_email", AsyncMock()
    ) as send:
        await notify_crew_awaiting_commit("notify-test", "discovery_mapping")

    assert send.await_count == 0
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `./venv/bin/pytest tests/test_commit_notification.py -v`
Expected: FAIL - `ModuleNotFoundError: No module named 'api.services.commit_notify_service'`

- [ ] **Step 3: Implement the service**

Create `api/services/commit_notify_service.py`:

```python
# api/services/commit_notify_service.py
"""Tell the people who can act that a crew's output is waiting.

Pamela's remit is project governance - reviewers and approvers. Jordan speaks to the
actors in the organisation, and not from here.
"""
from __future__ import annotations

import json
import logging

import httpx

from api.config import get_settings
from api.database import fetch_project, fetch_stakeholders, get_connection
from api.services.pam_report_job import DEV_MODE_ADDRESS, resolve_recipients

log = logging.getLogger(__name__)


async def _send_email(*, to: list[str], subject: str, body: str) -> None:
    settings = get_settings()
    if not settings.resend_api_key:
        raise RuntimeError("RESEND_API_KEY is not configured")
    async with httpx.AsyncClient(timeout=15.0) as http:
        resp = await http.post(
            "https://api.resend.com/emails",
            json={"from": settings.from_email, "to": to, "subject": subject, "text": body},
            headers={"Authorization": f"Bearer {settings.resend_api_key}"},
        )
    if resp.status_code not in (200, 201):
        raise RuntimeError(f"Resend returned {resp.status_code}: {resp.text[:200]}")


async def notify_crew_awaiting_commit(slug: str, crew_name: str) -> None:
    """Never raises. A failed notification must not fail a completed run."""
    try:
        async with get_connection(slug) as conn:
            project = await fetch_project(conn, slug=slug)
            if not project:
                return
            stakeholders = await fetch_stakeholders(conn, project_id=project["id"])
            # dev_mode lives inside config_json, not as a column - the same read
            # pam_report_job.py:129 performs.
            config = json.loads(project.get("config_json") or "{}")
            dev_mode = bool(config.get("dev_mode", True))

        actual, intended = resolve_recipients(stakeholders, dev_mode)
        if not actual:
            return

        settings = get_settings()
        link = f"{settings.public_url.rstrip('/')}/dashboard/{slug}/reviews"
        lines = [
            f"{crew_name} has finished and its output is waiting to be committed.",
            "",
            f"Review it here: {link}",
        ]
        if dev_mode:
            lines += [
                "",
                f"Development mode - this would have gone to: {', '.join(intended) or 'nobody'}",
            ]

        await _send_email(
            to=actual,
            subject=f"{slug}: {crew_name} is ready for review",
            body="\n".join(lines),
        )
    except Exception:
        log.exception("could not notify reviewers that %s is awaiting commit", crew_name)
```

`resolve_recipients` (`api/services/pam_report_job.py:35`) and `DEV_MODE_ADDRESS`
(line 29) are verified to exist under those names. Do not duplicate their logic.

- [ ] **Step 4: Call it when a run completes**

In `api/services/run_service.py`, in `dispatch_crew`, immediately after
`await update_crew_run_status(conn, run_id=run_id, status="completed")` (line 387) and
outside the `async with` block:

```python
        from api.services.commit_notify_service import notify_crew_awaiting_commit
        await notify_crew_awaiting_commit(slug, crew_name)
```

and the same in `dispatch_agent` after line 558, using `crew_label` as the crew name.

The import is function-local to avoid a circular import: `commit_notify_service` imports
from `pam_report_job`, which imports from `run_service`.

- [ ] **Step 5: Run the tests to verify they pass**

Run: `./venv/bin/pytest tests/test_commit_notification.py -v`
Expected: 3 passed

- [ ] **Step 6: Run the full backend suite**

Run: `./venv/bin/pytest -q --ignore=tests/integration`
Expected: 579 passed. No new warnings.

- [ ] **Step 7: Commit**

```bash
git add api/services/commit_notify_service.py api/services/run_service.py tests/test_commit_notification.py
git commit -m "feat: tell reviewers and approvers when a crew is waiting to be committed"
```

---

## Task 7: The Ready state on the crew card

**Files:**
- Modify: `ui/src/api/endpoints.ts` - add `commitsApi` after `systemApi`
- Modify: `ui/src/components/CrewCarousel.tsx` - `CrewCard`'s status chip, border, and button
- Modify: `ui/src/pages/Dashboard.tsx` - fetch readiness and pass it down
- Test: `ui/src/__tests__/CrewReadyState.test.tsx`

**Interfaces:**
- Consumes: `GET /projects/{slug}/crew-readiness` returning `{ [crew]: { ready: boolean, waiting_on: string[] } }`
- Produces: `CrewCarousel` accepts `readiness?: Record<string, { ready: boolean; waiting_on: string[] }>`

**Precedence:** Ready is a *resting* state, so it ranks below running, waiting, and
failed, and above idle. A crew that is running shows Running even if it is also ready.

- [ ] **Step 1: Write the failing test**

Create `ui/src/__tests__/CrewReadyState.test.tsx`:

```tsx
import { render, screen } from '@testing-library/react'
import { describe, it, expect } from 'vitest'

import { crewStatusLabel } from '../components/agentStatus'

describe('crewStatusLabel', () => {
  it('says Ready when the crew is armed and resting', () => {
    expect(crewStatusLabel('idle', true)).toBe('Ready to run')
  })

  it('says nothing special when the crew is not ready', () => {
    expect(crewStatusLabel('idle', false)).toBeNull()
  })

  it('does not override a running crew', () => {
    expect(crewStatusLabel('running', true)).toBeNull()
  })

  it('does not override a failed crew - a fault outranks readiness', () => {
    expect(crewStatusLabel('failed', true)).toBeNull()
  })
})
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd ui && npx vitest run src/__tests__/CrewReadyState.test.tsx`
Expected: FAIL - `crewStatusLabel is not a function`

- [ ] **Step 3: Add the helper**

In `ui/src/components/agentStatus.ts`, after `getRotatedIdleStatus`, add:

```ts
/**
 * The Ready label, or null when the crew's own status should speak instead.
 *
 * Ready is a resting state, so anything actually happening - or anything broken -
 * outranks it. A running crew that is also ready is simply running.
 */
export function crewStatusLabel(status: AgentStatus | CrewStatus, ready: boolean): string | null {
  if (!ready) return null
  return status === 'idle' ? 'Ready to run' : null
}
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `cd ui && npx vitest run src/__tests__/CrewReadyState.test.tsx`
Expected: 4 passed

- [ ] **Step 5: Add the API client call**

In `ui/src/api/endpoints.ts`, after the `systemApi` block:

```ts
export interface CrewReadiness {
  ready: boolean
  waiting_on: string[]
}

export const commitsApi = {
  readiness: (slug: string): Promise<Record<string, CrewReadiness>> =>
    apiClient.get<Record<string, CrewReadiness>>(`/projects/${slug}/crew-readiness`)
      .then((r) => r.data),
  create: (slug: string, crewName: string, notes = ''): Promise<{ released: string[] }> =>
    apiClient.post<{ released: string[] }>(`/projects/${slug}/commits`, {
      crew_name: crewName, notes,
    }).then((r) => r.data),
}
```

- [ ] **Step 6: Render it**

In `ui/src/pages/Dashboard.tsx`, fetch readiness alongside the existing project status
query, following the file's existing `useQuery` style, and pass the result to
`<CrewCarousel readiness={readiness} />` at both render sites (currently lines 297 and
320, where `isPipelineActive` is passed).

In `ui/src/components/CrewCarousel.tsx`, add `readiness` to `CrewCarouselProps` and to
`CrewCardProps`, then in `CrewCard` replace the fall-through arm of `statusLabel` - the
`FadingText` branch - with:

```tsx
                             crewStatusLabel(status, isReady)
                               ? <span className="text-[10px] font-semibold text-brand">
                                   {crewStatusLabel(status, isReady)}
                                 </span>
                               : <FadingText
                                   className="text-[10px] font-medium text-gray-300"
                                   text={getRotatedIdleStatus(crewKey, crewRun?.id ?? 0, rotation)}
                                   delayKey={crewKey}
                                 />
```

where `const isReady = readiness?.[crewKey]?.ready ?? false`. Add `crewStatusLabel` to
the existing import from `./agentStatus`.

A ready card also takes an emphasised border - add `isReady` to the `borderClass` chain
immediately above the default arm:

```tsx
          : isReady
            ? 'border-brand/40'
```

- [ ] **Step 7: Run the whole frontend suite and typecheck**

Run: `cd ui && npx vitest run && npx tsc --noEmit`
Expected: 70 passed (66 baseline + 4), no type errors. Existing `CrewCarousel` renders
that pass no `readiness` prop must still work - it is optional and defaults to not ready.

- [ ] **Step 8: Commit**

```bash
git add ui/src/api/endpoints.ts ui/src/components/agentStatus.ts ui/src/components/CrewCarousel.tsx ui/src/pages/Dashboard.tsx ui/src/__tests__/CrewReadyState.test.tsx
git commit -m "feat: show a crew as ready once its upstream work is committed"
```

---

## Task 8: Committing from the review queue

**Files:**
- Modify: `ui/src/components/ReviewQueue.tsx`
- Test: `ui/src/__tests__/ReviewQueueCommit.test.tsx`

**Interfaces:**
- Consumes: `commitsApi.create(slug, crewName, notes)` and `commitsApi.readiness(slug)` from Task 7; `GET /projects/{slug}/changes?crew_name=`
- Produces: nothing

- [ ] **Step 1: Write the failing test**

Create `ui/src/__tests__/ReviewQueueCommit.test.tsx`:

```tsx
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, it, expect, vi, beforeEach } from 'vitest'

import CommitControl from '../components/CommitControl'

const onCommit = vi.fn()

beforeEach(() => onCommit.mockReset())

describe('CommitControl', () => {
  it('names how many changes it is committing over', () => {
    render(<CommitControl crewName="discovery_mapping" changeCount={3} onCommit={onCommit} />)
    expect(screen.getByRole('button', { name: /commit/i }).textContent).toContain('3')
  })

  it('does not mention changes when there are none', () => {
    render(<CommitControl crewName="discovery_mapping" changeCount={0} onCommit={onCommit} />)
    expect(screen.getByRole('button', { name: /commit/i }).textContent).not.toContain('0 change')
  })

  it('commits the crew it was given', async () => {
    render(<CommitControl crewName="discovery_mapping" changeCount={0} onCommit={onCommit} />)
    await userEvent.click(screen.getByRole('button', { name: /commit/i }))
    expect(onCommit).toHaveBeenCalledWith('discovery_mapping')
  })

  it('cannot be clicked twice while a commit is in flight', async () => {
    let release: () => void = () => {}
    onCommit.mockReturnValue(new Promise<void>((r) => { release = r }))
    render(<CommitControl crewName="discovery_mapping" changeCount={0} onCommit={onCommit} />)
    const button = screen.getByRole('button', { name: /commit/i })
    await userEvent.click(button)
    expect(button).toBeDisabled()
    release()
  })
})
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd ui && npx vitest run src/__tests__/ReviewQueueCommit.test.tsx`
Expected: FAIL - cannot resolve `../components/CommitControl`

- [ ] **Step 3: Create the control**

Create `ui/src/components/CommitControl.tsx`:

```tsx
// ui/src/components/CommitControl.tsx
import { useState } from 'react'

/**
 * Commit a crew's outputs.
 *
 * The count of outstanding changes is shown rather than blocking on it: an approver
 * holds the governing authority, so they may commit over unaddressed requests - but
 * they should be able to see what they are committing over.
 */
export default function CommitControl({
  crewName,
  changeCount,
  onCommit,
}: {
  crewName: string
  changeCount: number
  onCommit: (crewName: string) => void | Promise<void>
}) {
  const [busy, setBusy] = useState(false)

  async function commit() {
    setBusy(true)
    try {
      await onCommit(crewName)
    } finally {
      setBusy(false)
    }
  }

  return (
    <button
      type="button"
      onClick={() => void commit()}
      disabled={busy}
      className="text-xs font-semibold text-white bg-brand hover:bg-brand-dark px-3 py-1.5 rounded-lg transition-colors disabled:opacity-50"
    >
      {busy
        ? 'Committing…'
        : changeCount > 0
          ? `Commit over ${changeCount} change${changeCount === 1 ? '' : 's'}`
          : 'Commit'}
    </button>
  )
}
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `cd ui && npx vitest run src/__tests__/ReviewQueueCommit.test.tsx`
Expected: 4 passed

- [ ] **Step 5: Use it in the review queue**

`ui/src/components/ReviewQueue.tsx` is 53 lines: `export default function ReviewQueue({
slug, outputs }: Props)` with a `useQueryClient` and a `pending` filter on
`review_status`. Read it, then add a section beneath the existing pending-review list.

Add to `ui/src/api/endpoints.ts`, inside the `commitsApi` object created in Task 7:

```ts
  committedCrews: (slug: string): Promise<string[]> =>
    apiClient.get<{ crew_name: string }[]>(`/projects/${slug}/commits`)
      .then((r) => [...new Set(r.data.map((c) => c.crew_name))]),
  changeCount: (slug: string, crewName: string): Promise<number> =>
    apiClient.get<unknown[]>(`/projects/${slug}/changes`, { params: { crew_name: crewName } })
      .then((r) => r.data.length),
```

In `ReviewQueue`, fetch readiness and the committed set, and render a commit row per
crew that is ready but not yet committed - those are the crews whose turn it is:

```tsx
  const { data: readiness = {} } = useQuery({
    queryKey: ['crew-readiness', slug],
    queryFn: () => commitsApi.readiness(slug),
  })
  const { data: committed = [] } = useQuery({
    queryKey: ['committed-crews', slug],
    queryFn: () => commitsApi.committedCrews(slug),
  })

  const awaitingCommit = Object.entries(readiness)
    .filter(([crew, r]) => r.ready && !committed.includes(crew))
    .map(([crew]) => crew)

  async function commit(crewName: string) {
    await commitsApi.create(slug, crewName)
    // Both the board's Ready states and this list derive from these two queries.
    await qc.invalidateQueries({ queryKey: ['crew-readiness', slug] })
    await qc.invalidateQueries({ queryKey: ['committed-crews', slug] })
  }
```

Render each entry of `awaitingCommit` with `CREW_LABELS[crew]` from `./agentStatus` and a
`<CommitControl crewName={crew} changeCount={...} onCommit={commit} />`, matching the
markup of the pending-review rows above it rather than inventing a new style. Fetch each
crew's `changeCount` with its own query keyed `['crew-changes', slug, crew]`.

Add `useQuery` to the existing `@tanstack/react-query` import.

- [ ] **Step 6: Run the whole frontend suite and typecheck**

Run: `cd ui && npx vitest run && npx tsc --noEmit`
Expected: 74 passed, no type errors.

- [ ] **Step 7: Run the backend suite**

Run: `./venv/bin/pytest -q --ignore=tests/integration`
Expected: 579 passed, unchanged by this task.

- [ ] **Step 8: Commit**

```bash
git add ui/src/components/CommitControl.tsx ui/src/components/ReviewQueue.tsx ui/src/__tests__/ReviewQueueCommit.test.tsx
git commit -m "feat: commit a crew's outputs from the review queue"
```

---

## Manual verification

Automated tests cannot see the board change. With the API and UI running:

1. Open a project. Crews with uncommitted upstreams show their breathing idle activity;
   `discovery_mapping` and `discovery`, which have no dependencies, show "Ready to run".
2. Commit `discovery_mapping` from the review queue. `assessment_design` should turn
   Ready without a page reload.
3. Add a note against one of that crew's outputs, then reopen the review queue - the
   commit control should read "Commit over 1 change".
4. Confirm no crew card shows "Ready to run" while it is running or failed.
5. Run a crew and confirm it finishes rather than hanging - the run should reach
   `completed` without a 24-hour wait, and the reviewers should receive an email (or the
   dev-mode address, if `dev_mode` is on).
