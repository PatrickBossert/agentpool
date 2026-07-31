# Auto-start on Approval Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** When an approver commits a crew's output, every crew directly downstream of it that is ready starts automatically.

**Architecture:** A new `api/services/autostart_service.py` classifies each downstream crew as ready, already running, or waiting, then dispatches the ready ones the same way the REST path does - `insert_crew_run` followed by `asyncio.create_task(dispatch_crew(...))`. `api/routers/commits.py` calls it **after** `commit_crew` returns, so an approval that was recorded stays recorded whatever happens next. `dispatch_crew` gains a `triggered_by` argument so a failed run can tell the person whose approval started it.

**Tech Stack:** FastAPI, aiosqlite, pytest + pytest-asyncio, React 18 + TypeScript + Vitest.

**Spec:** `docs/superpowers/specs/2026-07-31-auto-start-on-approval-design.md`

## Global Constraints

- **British English** (`-ise`, `-our`, `-re`) in all prose, comments, docstrings, test names, and UI copy.
- **Spaced hyphen ` - ` in prose, never an em dash `—`.** Applies to prose, not hyphenated compound adjectives. Do not alter pre-existing em dashes on lines you are not otherwise changing.
- **Lucide React SVG icons only. No emoji in rendered content.**
- **Never `sky-*` or `blue-*` Tailwind classes.** Brand tokens preferred: `text-brand`, `bg-brand`, `bg-surface`, `bg-surface-raised`, `bg-surface-card`, `text-primary`, `text-secondary`, `text-muted`. `text-red-400` for error text is accepted. The existing activate banner uses `amber-*`, which is established for warnings and stays.
- **All raw SQL lives in `api/database.py`** - none in service or router modules.
- **`agents/tools/human_input.py` must not be modified.**
- Backend tests: `./venv/bin/pytest -q --ignore=tests/integration` - **not** bare `pytest`.
- Frontend tests: `npx vitest run` from `ui/`, plus `npx tsc --noEmit` which must be clean.
- **Baselines: 741 backend, 208 frontend.** Report actual counts; predicted figures in this plan are estimates to reconcile, not gates.
- **Stage files explicitly by name. Never `git add -A` or `git add .`** - the working tree holds unrelated untracked files (screenshots, `.docx`) that must not be swept in.

## File Structure

| File | Responsibility |
|---|---|
| `api/services/crew_graph.py` | **Modify.** Gains `classify_downstream` - the decision, read-only, no dispatch. |
| `api/services/autostart_service.py` | **Create.** Reads the project's status, dispatches the ready crews, returns the report. |
| `api/routers/commits.py` | **Modify.** Calls the service after `commit_crew`; response gains the new fields. |
| `api/services/run_service.py` | **Modify.** `dispatch_crew` gains `triggered_by`; its failure path notifies. |
| `api/services/commit_notify_service.py` | **Modify.** Gains `notify_crew_failed`. |
| `ui/src/api/endpoints.ts` | **Modify.** The commit response type. |
| `ui/src/pages/Reviews.tsx` | **Modify.** The activate banner's copy, which currently states something untrue. |

**Why the classification is separate from the dispatch.** The risky logic is "ready, not newly ready" - it is where the behaviour changes and where a wrong answer starts crews that should not run. Keeping it read-only means it is tested without anything being dispatched, and a reviewer can reject the decision while approving the plumbing or vice versa.

---

## Task 1: Classify each downstream crew

**Files:**
- Modify: `api/services/crew_graph.py`
- Test: `tests/test_crew_graph.py`

**Interfaces:**
- Consumes: `CREW_DEPENDENCIES`, `downstream_of`, `is_crew_ready` - all already in that module.
- Produces: `async def classify_downstream(conn, *, crew_name: str) -> dict[str, list]` returning `{"ready": [...], "running": [...], "waiting": [{"crew": str, "waiting_on": [str]}]}`. Every crew in `downstream_of(crew_name)` appears in exactly one list.

**Background you need.** `is_crew_ready(conn, crew_name=...)` returns True when every upstream crew has at least one commit. `crew_has_commit(conn, crew_name=...)` and `crew_is_running(conn, crew_name=...)` are in `api/database.py`. The existing `commit_crew` computes a `released` list meaning "crews this commit made ready **for the first time**"; this task deliberately does **not** use that idea - a crew that was already ready must still be classified ready, because the whole point is that re-approving upstream re-runs downstream.

- [ ] **Step 1: Write the failing tests**

If `tests/test_crew_graph.py` does not exist, create it. Follow the connection fixture used by `tests/test_approval_commits.py` in the same directory - it opens a per-test project database; copy its fixture rather than inventing one, and make sure it unlinks the database before and after, since tests in this repo share slugs.

```python
# tests/test_crew_graph.py additions
import pytest

from api.services.crew_graph import classify_downstream


@pytest.mark.asyncio
async def test_a_downstream_crew_with_all_upstreams_committed_is_ready(conn):
    """discovery_mapping is assessment_design's only upstream, so committing it arms Maya."""
    await insert_approval_commit(conn, crew_name="discovery_mapping", committed_by="a", notes="")

    result = await classify_downstream(conn, crew_name="discovery_mapping")

    assert "assessment_design" in result["ready"]


@pytest.mark.asyncio
async def test_a_crew_stays_ready_on_a_second_commit_upstream(conn):
    """The behaviour this whole project turns on. The old 'released' idea reported a crew
    only the first time it became ready, so a revision approved later started nothing.
    Readiness is a state, not a transition."""
    await insert_approval_commit(conn, crew_name="discovery_mapping", committed_by="a", notes="")
    first = await classify_downstream(conn, crew_name="discovery_mapping")

    await insert_approval_commit(conn, crew_name="discovery_mapping", committed_by="a", notes="")
    second = await classify_downstream(conn, crew_name="discovery_mapping")

    assert "assessment_design" in first["ready"]
    assert "assessment_design" in second["ready"]


@pytest.mark.asyncio
async def test_a_crew_with_an_uncommitted_upstream_is_waiting_and_names_it(conn):
    """discovery_interviews needs BOTH assessment_design and stakeholder_management. A
    single-upstream crew cannot discriminate 'ready' from 'its one upstream just landed',
    so this case must be built on a two-upstream crew or it proves nothing."""
    await insert_approval_commit(conn, crew_name="assessment_design", committed_by="a", notes="")

    result = await classify_downstream(conn, crew_name="assessment_design")

    waiting = {w["crew"]: w["waiting_on"] for w in result["waiting"]}
    assert "discovery_interviews" in waiting
    assert waiting["discovery_interviews"] == ["stakeholder_management"]
    assert "discovery_interviews" not in result["ready"]


@pytest.mark.asyncio
async def test_a_crew_becomes_ready_once_its_last_upstream_lands(conn):
    await insert_approval_commit(conn, crew_name="assessment_design", committed_by="a", notes="")
    await insert_approval_commit(conn, crew_name="stakeholder_management", committed_by="a", notes="")

    result = await classify_downstream(conn, crew_name="stakeholder_management")

    assert "discovery_interviews" in result["ready"]


@pytest.mark.asyncio
async def test_a_ready_crew_that_is_running_is_classified_running_not_ready(conn):
    """Two concurrent runs of one crew both writing versioned outputs is the failure this
    avoids. A running crew must not also appear in ready, or the caller starts it twice."""
    await insert_approval_commit(conn, crew_name="discovery_mapping", committed_by="a", notes="")
    await insert_crew_run(
        conn, project_id=1, crew_name="assessment_design", status="running"
    )

    result = await classify_downstream(conn, crew_name="discovery_mapping")

    assert "assessment_design" in result["running"]
    assert "assessment_design" not in result["ready"]


@pytest.mark.asyncio
async def test_every_downstream_crew_appears_exactly_once(conn):
    """A crew silently in no list is a crew nobody can see is stuck."""
    await insert_approval_commit(conn, crew_name="assessment_design", committed_by="a", notes="")

    result = await classify_downstream(conn, crew_name="assessment_design")

    seen = result["ready"] + result["running"] + [w["crew"] for w in result["waiting"]]
    assert sorted(seen) == sorted(downstream_of("assessment_design"))
    assert len(seen) == len(set(seen))


@pytest.mark.asyncio
async def test_a_crew_with_no_downstream_classifies_to_three_empty_lists(conn):
    """business_plan is the end of the chain. Committing it must not error."""
    result = await classify_downstream(conn, crew_name="business_plan")

    assert result == {"ready": [], "running": [], "waiting": []}
```

Import `insert_approval_commit`, `insert_crew_run` from `api.database` and `downstream_of` from `api.services.crew_graph` at the top of the file.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `./venv/bin/pytest tests/test_crew_graph.py -v`
Expected: FAIL with `ImportError: cannot import name 'classify_downstream'`.

- [ ] **Step 3: Implement `classify_downstream`**

Append to `api/services/crew_graph.py`:

```python
async def classify_downstream(
    conn: aiosqlite.Connection, *, crew_name: str
) -> dict[str, list]:
    """Sort every crew directly downstream of this one into ready, running, or waiting.

    Readiness is a state, not a transition. `commit_crew`'s older `released` list reported
    a crew only the first time it became ready, which meant a revision approved later
    started nothing - the first pass through the pipeline ran itself and every subsequent
    change was manual. Asking "is it ready" rather than "did it just become ready" is what
    makes re-approval re-run the crew below.

    A ready crew that is already running is reported as running, never as both: the caller
    starts everything in `ready`, and two concurrent runs of one crew would both write
    versioned outputs.
    """
    ready: list[str] = []
    running: list[str] = []
    waiting: list[dict] = []

    for crew in downstream_of(crew_name):
        blocking = [
            upstream
            for upstream in CREW_DEPENDENCIES.get(crew, [])
            if not await crew_has_commit(conn, crew_name=upstream)
        ]
        if blocking:
            waiting.append({"crew": crew, "waiting_on": blocking})
        elif await crew_is_running(conn, crew_name=crew):
            running.append(crew)
        else:
            ready.append(crew)

    return {"ready": ready, "running": running, "waiting": waiting}
```

Add `crew_is_running` to the existing `from api.database import crew_has_commit` line.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `./venv/bin/pytest tests/test_crew_graph.py -v`
Expected: PASS.

- [ ] **Step 5: Run the full backend suite**

Run: `./venv/bin/pytest -q --ignore=tests/integration`
Expected: 741 + the new tests. Nothing existing changes - this task only adds a function.

- [ ] **Step 6: Commit**

```bash
git add api/services/crew_graph.py tests/test_crew_graph.py
git commit -m "feat: classify each downstream crew as ready, running or waiting"
```

---

## Task 2: Start the ready crews

**Files:**
- Create: `api/services/autostart_service.py`
- Test: `tests/test_autostart_service.py`

**Interfaces:**
- Consumes: `classify_downstream(conn, crew_name=...)` from Task 1; `fetch_project`, `insert_crew_run`, `get_connection` from `api.database`; `dispatch_crew(slug, crew_name, run_id)` from `api.services.run_service`.
- Produces: `async def start_ready_downstream(slug: str, crew_name: str, *, committed_by: str) -> dict` returning `{"started": [{"crew": str, "run_id": int}], "skipped": [str], "waiting": [{"crew": str, "waiting_on": [str]}], "inactive": bool}`.

**Two things to get right.**

**The inactive gate lives here, not in the router.** `projects.status` is set by `POST /projects/{slug}/activate` and is already read by `api/services/pam_report_job.py:133`, which skips the daily report for a project that is not active; auto-start becomes its second reader. (An earlier draft of this plan said the column was read by nothing - that came from a grep for `!= 'active'` in single quotes against a line written with double quotes.) Reading it inside this function means every caller gets the gate, and a second caller added later cannot forget it. When the project is not `'active'`, return `{"started": [], "skipped": [], "waiting": [], "inactive": True}` - **do not** report the ready crews as `waiting`. They are not waiting on an upstream; they are waiting on the project being activated, which is a different problem with a different fix, and mislabelling it would send someone hunting for a missing approval that does not exist.

**Dispatch mirrors the REST path exactly** - `api/routers/run.py:33-39` does `insert_crew_run(...)` then `asyncio.create_task(dispatch_crew(...))`. Use the same two steps so there is one way a crew starts.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_autostart_service.py`. Use the same project-creating fixture as `tests/test_commit_endpoint.py`, and unlink both the project database and its `projects/<slug>` directory before and after each test - tests in this repo share slugs.

```python
# tests/test_autostart_service.py
"""Auto-start turns an approval into the next crew running.

dispatch_crew is patched throughout: these tests are about which crews are started and
what is reported, not about running CrewAI. Assertions are on the returned report and on
the crew_runs rows, both of which are deterministic - asserting on the patched
coroutine having been awaited is not, because asyncio.create_task does not guarantee the
task has run before the test ends.
"""
from unittest.mock import AsyncMock, patch

import pytest

from api.database import (
    fetch_crew_runs,
    fetch_project,
    get_connection,
    insert_approval_commit,
    insert_crew_run,
    set_project_status,
)
from api.services.autostart_service import start_ready_downstream

SLUG = "autostart-test"


async def _activate(slug: str) -> None:
    async with get_connection(slug) as conn:
        await set_project_status(conn, slug=slug, status="active")


@pytest.mark.asyncio
async def test_a_ready_crew_is_started_and_reported_with_its_run_id(project):
    await _activate(SLUG)
    async with get_connection(SLUG) as conn:
        await insert_approval_commit(
            conn, crew_name="discovery_mapping", committed_by="a", notes=""
        )

    with patch("api.services.autostart_service.dispatch_crew", AsyncMock()):
        result = await start_ready_downstream(
            SLUG, "discovery_mapping", committed_by="approver@example.com"
        )

    started = {s["crew"]: s["run_id"] for s in result["started"]}
    assert "assessment_design" in started
    assert isinstance(started["assessment_design"], int)


@pytest.mark.asyncio
async def test_starting_a_crew_records_a_running_crew_run(project):
    await _activate(SLUG)
    async with get_connection(SLUG) as conn:
        await insert_approval_commit(
            conn, crew_name="discovery_mapping", committed_by="a", notes=""
        )

    with patch("api.services.autostart_service.dispatch_crew", AsyncMock()):
        await start_ready_downstream(SLUG, "discovery_mapping", committed_by="a")

    async with get_connection(SLUG) as conn:
        project_row = await fetch_project(conn, slug=SLUG)
        runs = await fetch_crew_runs(conn, project_id=project_row["id"])
    assert any(
        r["crew_name"] == "assessment_design" and r["status"] == "running" for r in runs
    )


@pytest.mark.asyncio
async def test_a_crew_with_an_uncommitted_upstream_is_waiting_not_started(project):
    """discovery_interviews needs both assessment_design and stakeholder_management."""
    await _activate(SLUG)
    async with get_connection(SLUG) as conn:
        await insert_approval_commit(
            conn, crew_name="assessment_design", committed_by="a", notes=""
        )

    with patch("api.services.autostart_service.dispatch_crew", AsyncMock()):
        result = await start_ready_downstream(SLUG, "assessment_design", committed_by="a")

    waiting = {w["crew"]: w["waiting_on"] for w in result["waiting"]}
    assert waiting["discovery_interviews"] == ["stakeholder_management"]
    assert not any(s["crew"] == "discovery_interviews" for s in result["started"])


@pytest.mark.asyncio
async def test_a_running_crew_is_skipped_and_named(project):
    await _activate(SLUG)
    async with get_connection(SLUG) as conn:
        project_row = await fetch_project(conn, slug=SLUG)
        await insert_approval_commit(
            conn, crew_name="discovery_mapping", committed_by="a", notes=""
        )
        await insert_crew_run(
            conn,
            project_id=project_row["id"],
            crew_name="assessment_design",
            status="running",
        )

    with patch("api.services.autostart_service.dispatch_crew", AsyncMock()):
        result = await start_ready_downstream(SLUG, "discovery_mapping", committed_by="a")

    assert result["skipped"] == ["assessment_design"]
    assert result["started"] == []


@pytest.mark.asyncio
async def test_an_inactive_project_starts_nothing_and_says_why(project):
    """Every project in this codebase is 'created' until an approver activates it, so this
    is the state auto-start meets first. The ready crew must NOT be reported as waiting -
    it is not waiting on an upstream."""
    async with get_connection(SLUG) as conn:
        await insert_approval_commit(
            conn, crew_name="discovery_mapping", committed_by="a", notes=""
        )

    with patch("api.services.autostart_service.dispatch_crew", AsyncMock()):
        result = await start_ready_downstream(SLUG, "discovery_mapping", committed_by="a")

    assert result == {"started": [], "skipped": [], "waiting": [], "inactive": True}


@pytest.mark.asyncio
async def test_an_inactive_project_records_no_crew_run(project):
    async with get_connection(SLUG) as conn:
        await insert_approval_commit(
            conn, crew_name="discovery_mapping", committed_by="a", notes=""
        )

    with patch("api.services.autostart_service.dispatch_crew", AsyncMock()):
        await start_ready_downstream(SLUG, "discovery_mapping", committed_by="a")

    async with get_connection(SLUG) as conn:
        project_row = await fetch_project(conn, slug=SLUG)
        runs = await fetch_crew_runs(conn, project_id=project_row["id"])
    assert runs == []


@pytest.mark.asyncio
async def test_an_active_project_reports_inactive_false(project):
    await _activate(SLUG)
    with patch("api.services.autostart_service.dispatch_crew", AsyncMock()):
        result = await start_ready_downstream(SLUG, "business_plan", committed_by="a")

    assert result["inactive"] is False


@pytest.mark.asyncio
async def test_a_crew_finishing_starts_nothing_further(project):
    """Cascade safety, as a test rather than an argument. A crew completing does not
    commit anything, so a single approval can start at most the crews directly below it
    and can never chain onwards on its own. Here: start assessment_design by committing
    its upstream, mark it completed as a finished run would, and assert that nothing
    downstream of it - stakeholder_management - was started by that completion."""
    await _activate(SLUG)
    async with get_connection(SLUG) as conn:
        await insert_approval_commit(
            conn, crew_name="discovery_mapping", committed_by="a", notes=""
        )

    with patch("api.services.autostart_service.dispatch_crew", AsyncMock()):
        await start_ready_downstream(SLUG, "discovery_mapping", committed_by="a")

    async with get_connection(SLUG) as conn:
        await conn.execute(
            "UPDATE crew_runs SET status='completed' WHERE crew_name='assessment_design'"
        )
        await conn.commit()
        project_row = await fetch_project(conn, slug=SLUG)
        runs = await fetch_crew_runs(conn, project_id=project_row["id"])

    assert [r["crew_name"] for r in runs] == ["assessment_design"]
    assert not any(r["crew_name"] == "stakeholder_management" for r in runs)
```

`fetch_crew_runs(conn, *, project_id: int) -> list[dict]` is at `api/database.py:764`.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `./venv/bin/pytest tests/test_autostart_service.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'api.services.autostart_service'`.

- [ ] **Step 3: Implement the service**

Create `api/services/autostart_service.py`:

```python
# api/services/autostart_service.py
"""Turning an approval into the next crew running.

Called after a commit has already been recorded, never before: an approval that landed
stays landed whatever happens here. Cascade safety is structural rather than enforced -
a crew completing does not commit anything, so nothing in this module is reachable from a
run finishing, and one approval can start at most the crews directly below it.
"""
from __future__ import annotations

import asyncio

from api.database import fetch_project, get_connection, insert_crew_run
from api.services.crew_graph import classify_downstream
from api.services.run_service import dispatch_crew


async def start_ready_downstream(
    slug: str, crew_name: str, *, committed_by: str
) -> dict:
    """Start every crew directly downstream of `crew_name` that is ready to run.

    Returns a complete account of every downstream crew: `started` with its run id,
    `skipped` because it was already running, or `waiting` with the upstream crews it
    still needs. `inactive` is True when the project has not been activated, in which
    case nothing is started and the other three lists are empty - the ready crews are
    deliberately not reported as waiting, because they are not waiting on an upstream.
    """
    async with get_connection(slug) as conn:
        project = await fetch_project(conn, slug=slug)
        if not project:
            return {"started": [], "skipped": [], "waiting": [], "inactive": False}

        if project.get("status") != "active":
            return {"started": [], "skipped": [], "waiting": [], "inactive": True}

        classified = await classify_downstream(conn, crew_name=crew_name)

        started = []
        for crew in classified["ready"]:
            run_id = await insert_crew_run(
                conn, project_id=project["id"], crew_name=crew, status="running"
            )
            started.append({"crew": crew, "run_id": run_id})

    # Dispatch outside the connection: a crew run is minutes of work, and holding the
    # project's connection open for it would block every other write to this project.
    for entry in started:
        asyncio.create_task(
            dispatch_crew(
                slug=slug,
                crew_name=entry["crew"],
                run_id=entry["run_id"],
                triggered_by=committed_by,
            )
        )

    return {
        "started": started,
        "skipped": classified["running"],
        "waiting": classified["waiting"],
        "inactive": False,
    }
```

**`triggered_by` does not exist on `dispatch_crew` yet - Task 4 adds it.** Until then these tests pass because `dispatch_crew` is patched. Task 4's step order accounts for this; if you are running the plan out of order, do Task 4 first.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `./venv/bin/pytest tests/test_autostart_service.py -v`
Expected: PASS.

- [ ] **Step 5: Run the full backend suite**

Run: `./venv/bin/pytest -q --ignore=tests/integration`
Expected: no existing test changes - nothing calls this service yet.

- [ ] **Step 6: Commit**

```bash
git add api/services/autostart_service.py tests/test_autostart_service.py
git commit -m "feat: start the ready downstream crews when an approval lands"
```

---

## Task 3: Wire it into the commit endpoint, and correct the banner

**Files:**
- Modify: `api/services/commit_service.py` - remove the `released` computation
- Modify: `api/routers/commits.py` - call the service, merge the report
- Modify: `tests/test_commit_endpoint.py` - the two tests asserting `released`
- Modify: `ui/src/api/endpoints.ts` - the commit response type
- Modify: `ui/src/pages/Reviews.tsx` - the activate banner's copy

**Interfaces:**
- Consumes: `start_ready_downstream(slug, crew_name, *, committed_by)` from Task 2.
- Produces: `POST /projects/{slug}/commits` returns `{commit_id, output_ids, started, skipped, waiting, inactive}`.

**`released` is replaced, not supplemented.** It reports crews made ready for the first time, is returned by the endpoint, is typed in the frontend client, and is consumed by nothing. Two overlapping fields where one is dead is a trap for the next reader. `commit_crew` keeps `commit_id` and `output_ids` and loses `released`, along with the `candidates` / `was_ready` computation that fed it.

**The banner names one consequence and must name two.** `ui/src/pages/Reviews.tsx:113-114` and its rendered copy say Pamela's daily report will not run until the project is activated. **That is true** - `api/services/pam_report_job.py:133` returns early from `run_pam_daily_report` when `project.get("status") != "active"`, and it predates this branch. (An earlier draft of this plan claimed no such gate existed; that came from a grep for `!= 'active'` in single quotes, while the line uses double quotes.) Keep the daily report clause and **add** the consequence this project makes real: an inactive project's approvals do not start the next crew either.

- [ ] **Step 1: Write the failing tests**

Replace the two `released` tests in `tests/test_commit_endpoint.py`. The fixture there creates the project; it must also be activated, because an inactive project starts nothing.

```python
@pytest.mark.asyncio
async def test_committing_starts_the_crew_it_released(client):
    await client.post("/projects", json=PROJECT)
    await client.post("/projects/commit-api-test/activate")

    with patch("api.services.autostart_service.dispatch_crew", AsyncMock()):
        resp = await client.post(
            "/projects/commit-api-test/commits",
            json={"crew_name": "discovery_mapping", "notes": ""},
        )

    started = [s["crew"] for s in resp.json()["started"]]
    assert started == ["assessment_design"]


@pytest.mark.asyncio
async def test_a_second_commit_starts_the_downstream_crew_again(client):
    """The behaviour this project exists for. The old `released` field reported a crew
    only the first time it became ready, so approving a revision started nothing."""
    await client.post("/projects", json=PROJECT)
    await client.post("/projects/commit-api-test/activate")

    with patch("api.services.autostart_service.dispatch_crew", AsyncMock()):
        first = await client.post(
            "/projects/commit-api-test/commits",
            json={"crew_name": "discovery_mapping", "notes": ""},
        )
        # The first start leaves assessment_design running, which would mask the second
        # commit as a skip rather than a start. Clear it, as a finished run would.
        async with get_connection("commit-api-test") as conn:
            await conn.execute(
                "UPDATE crew_runs SET status='completed' WHERE crew_name='assessment_design'"
            )
            await conn.commit()
        second = await client.post(
            "/projects/commit-api-test/commits",
            json={"crew_name": "discovery_mapping", "notes": ""},
        )

    assert [s["crew"] for s in first.json()["started"]] == ["assessment_design"]
    assert [s["crew"] for s in second.json()["started"]] == ["assessment_design"]


@pytest.mark.asyncio
async def test_a_crew_waiting_on_another_upstream_is_reported_not_started(client):
    """discovery_interviews needs both assessment_design and stakeholder_management."""
    await client.post("/projects", json=PROJECT)
    await client.post("/projects/commit-api-test/activate")

    with patch("api.services.autostart_service.dispatch_crew", AsyncMock()):
        resp = await client.post(
            "/projects/commit-api-test/commits",
            json={"crew_name": "assessment_design", "notes": ""},
        )

    waiting = {w["crew"]: w["waiting_on"] for w in resp.json()["waiting"]}
    assert waiting["discovery_interviews"] == ["stakeholder_management"]


@pytest.mark.asyncio
async def test_an_inactive_project_commits_without_starting_anything(client):
    """The commit must still land - only the start is suppressed."""
    await client.post("/projects", json=PROJECT)

    with patch("api.services.autostart_service.dispatch_crew", AsyncMock()):
        resp = await client.post(
            "/projects/commit-api-test/commits",
            json={"crew_name": "discovery_mapping", "notes": ""},
        )

    body = resp.json()
    assert resp.status_code == 201
    assert body["inactive"] is True
    assert body["started"] == []
    assert isinstance(body["commit_id"], int)


@pytest.mark.asyncio
async def test_the_commit_lands_even_when_starting_raises(client):
    """An approval that was recorded stays recorded whatever happens next."""
    await client.post("/projects", json=PROJECT)
    await client.post("/projects/commit-api-test/activate")

    with patch(
        "api.routers.commits.start_ready_downstream",
        AsyncMock(side_effect=RuntimeError("boom")),
    ):
        resp = await client.post(
            "/projects/commit-api-test/commits",
            json={"crew_name": "discovery_mapping", "notes": ""},
        )

    assert resp.status_code == 201
    commits = await client.get("/projects/commit-api-test/commits")
    assert len(commits.json()) == 1
```

Add `from unittest.mock import AsyncMock, patch` and `from api.database import get_connection` to that file's imports if absent.

The last test decides a real question: **a failure to start must not fail the request**, because the commit already happened. Implement that by catching around the call in the router.

Then in `ui/src/__tests__/Reviews.test.tsx`, add:

```tsx
  it('names both consequences of leaving a project inactive', async () => {
    // Two gates read projects.status - the daily report's, in pam_report_job.py, and the
    // auto-start's - and the banner is the only place either is explained.
    render(<Wrapper />)
    const banner = await screen.findByText(/not active/i)
    expect(banner).toHaveTextContent(/next crew/i)
    expect(banner).toHaveTextContent(/daily report/i)
  })
```

Match the existing file's render helper and mocks rather than introducing a new pattern; it already has an `activateMock` and a status mock.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `./venv/bin/pytest tests/test_commit_endpoint.py -v`
Expected: FAIL - `KeyError: 'started'`.

Run: `cd ui && npx vitest run src/__tests__/Reviews.test.tsx`
Expected: FAIL - the banner still mentions the daily report.

- [ ] **Step 3: Drop `released` from the service**

In `api/services/commit_service.py`'s `commit_crew`, delete the `candidates`, `was_ready` and `released` lines and the `downstream_of` / `is_crew_ready` imports if they become unused, and change the return to:

```python
    return {"commit_id": commit_id, "output_ids": output_ids}
```

Update the docstring: it currently says "and report the crews it released". It now freezes the outputs; what happens next is the router's business.

- [ ] **Step 4: Call the service from the router**

In `api/routers/commits.py`, replace the `return await commit_crew(...)` block:

```python
    try:
        result = await commit_crew(
            slug,
            crew_name=req.crew_name,
            committed_by=payload.get("sub", ""),
            notes=req.notes,
        )
    except CrewRunInProgress as e:
        raise HTTPException(status_code=409, detail=str(e))

    # After the commit, never before. The approval is recorded; a failure to start the
    # next crew must not unwind it, so this cannot raise into the response.
    try:
        started = await start_ready_downstream(
            slug, req.crew_name, committed_by=payload.get("sub", "")
        )
    except Exception:
        _log.exception("Auto-start after committing %s on %s failed", req.crew_name, slug)
        started = {"started": [], "skipped": [], "waiting": [], "inactive": False}

    return {**result, **started}
```

Add `from api.services.autostart_service import start_ready_downstream`, and a module logger (`_log = logging.getLogger(__name__)`) if the file has none.

- [ ] **Step 5: Update the frontend type and the banner**

In `ui/src/api/endpoints.ts`, replace the commit response type:

```ts
  create: (
    slug: string,
    crewName: string,
    notes = '',
  ): Promise<{
    commit_id: number
    started: { crew: string; run_id: number }[]
    skipped: string[]
    waiting: { crew: string; waiting_on: string[] }[]
    inactive: boolean
  }> =>
```

In `ui/src/pages/Reviews.tsx`, extend the banner copy and the comment above `ActivateProjectControl`. The rendered sentence becomes:

```tsx
          This project is not active yet - approving output will not start the next crew,
          and Pamela's daily report will not run, until it is.
```

and the comment names both readers of `projects.status`: `pam_report_job.py` for the daily report, `autostart_service.py` for the start.

- [ ] **Step 6: Run both suites and the type check**

Run: `./venv/bin/pytest -q --ignore=tests/integration`
Run: `cd ui && npx vitest run && npx tsc --noEmit`
Expected: all passing, `tsc` clean.

- [ ] **Step 7: Commit**

```bash
git add api/services/commit_service.py api/routers/commits.py tests/test_commit_endpoint.py ui/src/api/endpoints.ts ui/src/pages/Reviews.tsx ui/src/__tests__/Reviews.test.tsx
git commit -m "feat: an approval starts the next crew, and says so when it cannot"
```

---

## Task 4: Tell someone when an auto-started run fails

**Files:**
- Modify: `api/services/commit_notify_service.py`
- Modify: `api/services/run_service.py` - `dispatch_crew`
- Test: `tests/test_commit_notification.py`

**Interfaces:**
- Produces: `async def notify_crew_failed(slug: str, crew_name: str, *, triggered_by: str | None) -> None`; `dispatch_crew(slug, crew_name, run_id, *, triggered_by: str | None = None)`.

**The hole this closes.** `dispatch_crew`'s success path calls `notify_crew_awaiting_commit`; its failure path writes a log line and re-raises. Nobody is told. Combined with a commit that notifies nobody by design - project 1 chose that on the grounds that "the next crew starting is the signal" - auto-start would otherwise produce: approve, crew starts, crew fails, silence, with the approver believing work is in flight.

Reviewers are notified always. The person named in `triggered_by` is notified additionally, when set. A manually started run has no `triggered_by`, so it notifies reviewers only - which is still an improvement on today's nobody.

`_notify` in that module already resolves the audience from stakeholder flags, applies `dev_mode` routing, and never raises. Follow its shape; `notify_crew_failed` needs one thing `_notify` does not currently do, which is to add a specific address alongside a flag-resolved audience. Extend `_notify` with an `extra_recipient: str | None = None` parameter rather than writing a second sender - the `dev_mode` routing and the never-raises guarantee must apply identically, and duplicating them is how they drift.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_commit_notification.py`, following its existing pattern of patching `api.services.commit_notify_service._send_email` with an `AsyncMock`:

That file already has everything the setup needs: `SLUG = "notify-test"`, an autouse `clean` fixture, `_add_stakeholder(slug, name, email, *, approver: bool)`, and `_set_dev_mode(slug, value)`. Its existing tests use `gov@example.com` as the approver and `actor@example.com` as the non-approver. **`_set_dev_mode(SLUG, False)` is essential** - dev_mode defaults to on and redirects everything to one address, which would hide the very audience filtering these tests exist to check.

```python
@pytest.mark.asyncio
async def test_a_failed_run_notifies_reviewers_and_whoever_triggered_it(client):
    await client.post("/projects", json=PROJECT)
    await _add_stakeholder(SLUG, "Actor", "actor@example.com", approver=False)
    await _set_dev_mode(SLUG, False)

    from api.services.commit_notify_service import notify_crew_failed

    with patch("api.services.commit_notify_service._send_email", AsyncMock()) as send:
        await notify_crew_failed(SLUG, "assessment_design", triggered_by="gov@example.com")

    recipients = send.await_args.kwargs["to"]
    assert "actor@example.com" in recipients
    assert "gov@example.com" in recipients


@pytest.mark.asyncio
async def test_a_failed_run_with_no_trigger_notifies_reviewers_only(client):
    """A manually started run has nobody who triggered it - reviewers still need to know.
    gov@example.com is deliberately added as an approver here, so the assertion proves the
    address is absent because nothing named it, not because nobody was in the project."""
    await client.post("/projects", json=PROJECT)
    await _add_stakeholder(SLUG, "Actor", "actor@example.com", approver=False)
    await _add_stakeholder(SLUG, "Gov", "gov@example.com", approver=True)
    await _set_dev_mode(SLUG, False)

    from api.services.commit_notify_service import notify_crew_failed

    with patch("api.services.commit_notify_service._send_email", AsyncMock()) as send:
        await notify_crew_failed(SLUG, "assessment_design", triggered_by=None)

    recipients = send.await_args.kwargs["to"]
    assert "actor@example.com" in recipients
    assert "gov@example.com" not in recipients


@pytest.mark.asyncio
async def test_a_failing_send_does_not_mask_the_run_failure(client):
    """dispatch_crew re-raises the original exception after calling this. If notification
    raised, a mail error would replace the real run error."""
    await client.post("/projects", json=PROJECT)
    await _add_stakeholder(SLUG, "Actor", "actor@example.com", approver=False)

    from api.services.commit_notify_service import notify_crew_failed

    with patch(
        "api.services.commit_notify_service._send_email",
        AsyncMock(side_effect=RuntimeError("resend down")),
    ):
        await notify_crew_failed(SLUG, "assessment_design", triggered_by="gov@example.com")
    # No exception escaping is the assertion.


@pytest.mark.asyncio
async def test_a_successful_run_still_sends_the_completion_notice_not_a_failure_one(client):
    await client.post("/projects", json=PROJECT)
    await _add_stakeholder(SLUG, "Actor", "actor@example.com", approver=False)
    await _set_dev_mode(SLUG, False)

    from api.services.commit_notify_service import notify_crew_awaiting_commit

    with patch("api.services.commit_notify_service._send_email", AsyncMock()) as send:
        await notify_crew_awaiting_commit(SLUG, "assessment_design")

    assert "failed" not in send.await_args.kwargs["subject"].lower()
    assert "ready for review" in send.await_args.kwargs["subject"].lower()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `./venv/bin/pytest tests/test_commit_notification.py -v`
Expected: FAIL with `ImportError: cannot import name 'notify_crew_failed'`.

- [ ] **Step 3: Add the sender**

In `api/services/commit_notify_service.py`, add `extra_recipient: str | None = None` to `_notify`'s signature, and after the recipients are resolved, append it when set and not already present. Then add:

```python
async def notify_crew_failed(
    slug: str, crew_name: str, *, triggered_by: str | None
) -> None:
    """Tell reviewers - and whoever's approval started it - that a run failed.

    Project 1 deliberately sends nothing when an approval lands, on the grounds that the
    next crew starting is the signal. If that crew then dies, the signal was false, and
    the person holding a wrong belief is the one who approved. They are notified in
    addition to reviewers, who would otherwise wait for output that is not coming.

    Never raises: dispatch_crew re-raises the original run failure after calling this, and
    a mail error must not replace the real one.
    """
    await _notify(
        slug, crew_name,
        flags=("is_reviewer",),
        extra_recipient=triggered_by,
        subject=f"{slug}: {crew_name} failed",
        intro=f"{crew_name} started but did not finish. Nothing is in flight for it now.",
        audience_label="reviewers",
    )
```

- [ ] **Step 4: Thread `triggered_by` through the dispatcher**

In `api/services/run_service.py`, change `dispatch_crew`'s signature to
`async def dispatch_crew(slug: str, crew_name: str, run_id: int, *, triggered_by: str | None = None) -> None:`
and in its `except` branch, after the status update and the `push_log` and **before** the `raise`:

```python
        from api.services.commit_notify_service import notify_crew_failed
        await notify_crew_failed(slug, crew_name, triggered_by=triggered_by)
```

The existing callers in `api/routers/run.py` pass no `triggered_by` and keep working - the default is `None`.

- [ ] **Step 5: Run the tests to verify they pass**

Run: `./venv/bin/pytest tests/test_commit_notification.py -v`
Expected: PASS.

- [ ] **Step 6: Run the full backend suite**

Run: `./venv/bin/pytest -q --ignore=tests/integration`
Expected: all passing.

- [ ] **Step 7: Commit**

```bash
git add api/services/commit_notify_service.py api/services/run_service.py tests/test_commit_notification.py
git commit -m "feat: tell reviewers and the approver when a run fails"
```

---

## Operational step after merge

**Every project in the database is `status='created'`** - verified on `sp-gs-am`, `smoke-test` and `vision-debug`. Until an approver activates a project, its approvals record and start nothing.

The activate control already exists on the Reviews page and, after Task 3, the banner explains the consequence correctly. No code is needed - but this codebase has twice shipped work that sat inert awaiting a manual poke, the baseline skills seeding and the value chain migration, and this would be the third. Activate each live project once.

## Notes carried from the two preceding branches

- **Fixture sizing.** Anything about partial readiness must be built on `discovery_interviews`, which depends on both `assessment_design` and `stakeholder_management`. A single-upstream crew cannot distinguish "ready" from "its one upstream was just committed", so a test built on one proves nothing. The last two branches shipped five defects hidden by fixtures too small to tell the correct implementation from the bug.
- **Absence needs a positive anchor.** A test asserting a crew was *not* started must first establish that something else *was*, or it passes when the whole endpoint is broken.
- **Status codes are not assertions.** Several tests here could be written as "a 201 came back". Every one of them asserts on the response body instead, because a 201 is returned under every defect this project exists to prevent.
