# Making the Approval Loop Work End to End - Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A crew finishes, its contributor shapes the output and marks it ready, and only then is the approver summoned - with the twelve blocking gates gone so crews finish at all.

**Architecture:** One new table records submissions; crew state is derived by comparing the latest submission against the latest commit, never stored. The existing notification service is re-enabled with its audience narrowed to reviewers, and a sibling added for submissions addressed to approvers. Twelve agent task descriptions lose their end-of-phase blocks, a surgical migration replaces the two skill descriptions that never reseeded, and the commit control moves onto the live reviews page.

**Tech Stack:** FastAPI, aiosqlite, pytest / pytest-asyncio; React 18, TypeScript, Tailwind CSS v3, vitest, @testing-library/react.

## Global Constraints

- **British English** throughout - `-ise`, `-our`, `-re`.
- **Spaced hyphen ` - `** in prose, comments, and copy. Never an em dash. Hyphenated compound adjectives keep their tight hyphen.
- **No emoji** in rendered web content. Lucide React icons only.
- **Oxford comma** in lists of three or more.
- Backend: async `aiosqlite`; **all raw SQL lives in `api/database.py`**; no ORM. Routers in `api/routers/`, services in `api/services/`.
- Frontend: brand tokens only - `bg-brand`, `text-brand`, `brand-dark`. Never `sky-*` or `blue-*`.
- Backend tests run with `./venv/bin/pytest` - **not** bare `pytest`.
- **Baseline: 588 backend tests, 77 frontend tests, both green, `tsc --noEmit` clean.**
- **Crew state is computed, never stored.** A stored flag would need invalidating on every submission and commit.
- **`agents/tools/human_input.py` is never modified.** Only agent task descriptions change.
- Test files that create a project must unlink its database before **and** after each test - every task in the previous plan hit state leakage without this.

---

## File Structure

| File | Responsibility |
|------|----------------|
| `api/database.py` (modify) | `crew_submissions` table, its helpers, and the skills migration's SQL |
| `api/services/crew_state_service.py` (create) | Derives `working` / `ready` / `committed` from submission and commit history |
| `api/routers/commits.py` (modify) | Submission endpoint, state endpoint, activation endpoint |
| `api/services/commit_notify_service.py` (modify) | Audience narrowing, plus the submission notification |
| `api/services/pam_report_job.py` (modify) | Skip projects that are not active |
| `api/services/run_service.py` (modify) | Re-enable the completion notification |
| `agents/**/*.py` (modify, 12 files) | Remove the end-of-phase gates |
| `api/routers/skills.py` (modify) | Surgical description migration |
| `ui/src/pages/Reviews.tsx` (modify) | The crew section with its two controls |
| `ui/src/components/ReviewQueue.tsx` (delete) | Its commit parts move to `Reviews.tsx` |

---

## Task 1: Submissions and derived crew state

**Files:**
- Modify: `api/database.py` - table in `init_db` after `approval_commits`; helpers after `crew_has_commit`
- Create: `api/services/crew_state_service.py`
- Test: `tests/test_crew_state.py`

**Interfaces:**
- Consumes: `fetch_approval_commits(conn, *, crew_name=None)`, `get_connection(slug)`
- Produces:
  - `async def insert_crew_submission(conn, *, crew_name: str, submitted_by: str, notes: str = "") -> int`
  - `async def latest_submission_at(conn, *, crew_name: str) -> str | None`
  - `async def latest_commit_at(conn, *, crew_name: str) -> str | None` *(may already exist from the change-count work - check before adding a duplicate)*
  - `async def crew_state(conn, *, crew_name: str) -> str` returning `'working' | 'ready' | 'committed'`
  - `async def crew_state_report(conn) -> dict[str, str]` - every crew in `CREW_DEPENDENCIES` to its state

- [ ] **Step 1: Write the failing tests**

Create `tests/test_crew_state.py`:

```python
# tests/test_crew_state.py
"""Three states, derived rather than stored.

The contributor shapes the output and says when it is ready; only then is the approver
summoned. Two states could not express the gap between those two acts.
"""
import shutil
from pathlib import Path

import pytest

from api.config import get_settings

SLUG = "state-test"
PROJECT = {
    "client_slug": SLUG,
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
    """Unlink before and after - these tests share one slug."""
    def wipe():
        settings = get_settings()
        Path(settings.database_dir, f"{SLUG}.db").unlink(missing_ok=True)
        proj = Path(settings.projects_dir, SLUG)
        if proj.exists():
            shutil.rmtree(proj)
    wipe()
    yield
    get_settings.cache_clear()
    wipe()


@pytest.mark.asyncio
async def test_a_crew_nobody_has_touched_is_working(client):
    await client.post("/projects", json=PROJECT)
    from api.database import get_connection
    from api.services.crew_state_service import crew_state
    async with get_connection(SLUG) as conn:
        assert await crew_state(conn, crew_name="discovery_mapping") == "working"


@pytest.mark.asyncio
async def test_a_submission_makes_it_ready(client):
    await client.post("/projects", json=PROJECT)
    from api.database import get_connection, insert_crew_submission
    from api.services.crew_state_service import crew_state
    async with get_connection(SLUG) as conn:
        await insert_crew_submission(
            conn, crew_name="discovery_mapping", submitted_by="alice"
        )
        assert await crew_state(conn, crew_name="discovery_mapping") == "ready"


@pytest.mark.asyncio
async def test_a_commit_after_a_submission_makes_it_committed(client):
    await client.post("/projects", json=PROJECT)
    from api.database import (
        get_connection, insert_crew_submission, insert_approval_commit,
    )
    from api.services.crew_state_service import crew_state
    async with get_connection(SLUG) as conn:
        await insert_crew_submission(
            conn, crew_name="discovery_mapping", submitted_by="alice",
        )
        await conn.execute(
            "UPDATE crew_submissions SET submitted_at='2026-01-01 09:00:00'"
        )
        await insert_approval_commit(
            conn, crew_name="discovery_mapping", committed_by="bob"
        )
        await conn.execute(
            "UPDATE approval_commits SET committed_at='2026-01-01 10:00:00'"
        )
        await conn.commit()
        assert await crew_state(conn, crew_name="discovery_mapping") == "committed"


@pytest.mark.asyncio
async def test_a_commit_alone_is_committed(client):
    """A crew committed without ever being submitted - the SP20a path."""
    await client.post("/projects", json=PROJECT)
    from api.database import get_connection, insert_approval_commit
    from api.services.crew_state_service import crew_state
    async with get_connection(SLUG) as conn:
        await insert_approval_commit(
            conn, crew_name="discovery_mapping", committed_by="bob"
        )
        assert await crew_state(conn, crew_name="discovery_mapping") == "committed"


@pytest.mark.asyncio
async def test_resubmitting_after_approval_returns_it_to_ready(client):
    """The ordinary case once a crew has been round the loop once."""
    await client.post("/projects", json=PROJECT)
    from api.database import (
        get_connection, insert_crew_submission, insert_approval_commit,
    )
    from api.services.crew_state_service import crew_state
    async with get_connection(SLUG) as conn:
        await insert_approval_commit(
            conn, crew_name="discovery_mapping", committed_by="bob"
        )
        await conn.execute(
            "UPDATE approval_commits SET committed_at='2026-01-01 10:00:00'"
        )
        await insert_crew_submission(
            conn, crew_name="discovery_mapping", submitted_by="alice"
        )
        await conn.execute(
            "UPDATE crew_submissions SET submitted_at='2026-01-02 09:00:00'"
        )
        await conn.commit()
        assert await crew_state(conn, crew_name="discovery_mapping") == "ready"


@pytest.mark.asyncio
async def test_a_tie_resolves_to_committed(client):
    """The approver's act wins, so a crew cannot be stuck in ready after approval."""
    await client.post("/projects", json=PROJECT)
    from api.database import (
        get_connection, insert_crew_submission, insert_approval_commit,
    )
    from api.services.crew_state_service import crew_state
    async with get_connection(SLUG) as conn:
        await insert_crew_submission(
            conn, crew_name="discovery_mapping", submitted_by="alice"
        )
        await insert_approval_commit(
            conn, crew_name="discovery_mapping", committed_by="bob"
        )
        await conn.execute(
            "UPDATE crew_submissions SET submitted_at='2026-01-01 10:00:00'"
        )
        await conn.execute(
            "UPDATE approval_commits SET committed_at='2026-01-01 10:00:00'"
        )
        await conn.commit()
        assert await crew_state(conn, crew_name="discovery_mapping") == "committed"


@pytest.mark.asyncio
async def test_state_of_one_crew_says_nothing_about_another(client):
    await client.post("/projects", json=PROJECT)
    from api.database import get_connection, insert_crew_submission
    from api.services.crew_state_service import crew_state, crew_state_report
    async with get_connection(SLUG) as conn:
        await insert_crew_submission(
            conn, crew_name="discovery_mapping", submitted_by="alice"
        )
        assert await crew_state(conn, crew_name="assessment_design") == "working"
        report = await crew_state_report(conn)
    assert report["discovery_mapping"] == "ready"
    assert report["assessment_design"] == "working"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `./venv/bin/pytest tests/test_crew_state.py -v`
Expected: FAIL - `ImportError: cannot import name 'insert_crew_submission'`

- [ ] **Step 3: Add the table**

In `api/database.py`, inside `init_db`'s `executescript`, immediately after the
`approval_commits` table, add:

```sql
        -- One row per act of submitting a crew's work for approval. Parallel to
        -- approval_commits: together they derive the crew's state.
        CREATE TABLE IF NOT EXISTS crew_submissions (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            crew_name     TEXT NOT NULL,
            submitted_by  TEXT NOT NULL,
            submitted_at  TEXT NOT NULL DEFAULT (datetime('now')),
            notes         TEXT NOT NULL DEFAULT ''
        );
```

- [ ] **Step 4: Add the helpers**

In `api/database.py`, after `crew_has_commit`, add:

```python
async def insert_crew_submission(
    conn: aiosqlite.Connection, *, crew_name: str, submitted_by: str, notes: str = ""
) -> int:
    """Record that a contributor marked this crew's work ready for approval."""
    cur = await conn.execute(
        "INSERT INTO crew_submissions (crew_name, submitted_by, notes) VALUES (?,?,?)",
        (crew_name, submitted_by, notes),
    )
    await conn.commit()
    return cur.lastrowid


async def latest_submission_at(
    conn: aiosqlite.Connection, *, crew_name: str
) -> str | None:
    """When this crew was last submitted, or None if it never has been."""
    async with conn.execute(
        "SELECT MAX(submitted_at) AS at FROM crew_submissions WHERE crew_name=?",
        (crew_name,),
    ) as cur:
        row = await cur.fetchone()
    return row["at"] if row else None
```

**Before adding `latest_commit_at`, check whether it already exists** - a helper of that
name was added when the change count was scoped to since-the-last-commit. If it is there,
reuse it. If not, add the mirror of the above against `approval_commits.committed_at`.

- [ ] **Step 5: Add the state service**

Create `api/services/crew_state_service.py`:

```python
# api/services/crew_state_service.py
"""Where a crew's work has got to.

Three states rather than two: the agent produces, the contributor shapes the output and
says when it is ready, and the approver approves. Two states could not express the gap
between the last two, which is where most of the elapsed time in an engagement goes.

Computed, never stored - the same rule readiness follows. A stored flag would need
invalidating on every submission and every commit.
"""
from __future__ import annotations

import aiosqlite

from api.database import latest_commit_at, latest_submission_at
from api.services.crew_graph import CREW_DEPENDENCIES

WORKING = "working"
READY = "ready"
COMMITTED = "committed"


async def crew_state(conn: aiosqlite.Connection, *, crew_name: str) -> str:
    """One of working, ready, or committed.

    A tie resolves to committed: the approver's act wins, so a crew cannot be left
    showing "ready" after it has already been approved.
    """
    submitted = await latest_submission_at(conn, crew_name=crew_name)
    committed = await latest_commit_at(conn, crew_name=crew_name)

    if committed is not None and (submitted is None or submitted <= committed):
        return COMMITTED
    if submitted is not None:
        return READY
    return WORKING


async def crew_state_report(conn: aiosqlite.Connection) -> dict[str, str]:
    """Every crew's state, for the reviews page."""
    return {
        crew: await crew_state(conn, crew_name=crew) for crew in CREW_DEPENDENCIES
    }
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `./venv/bin/pytest tests/test_crew_state.py -v`
Expected: 7 passed

- [ ] **Step 7: Run the full backend suite**

Run: `./venv/bin/pytest -q --ignore=tests/integration`
Expected: 595 passed. No new warnings.

- [ ] **Step 8: Commit**

```bash
git add api/database.py api/services/crew_state_service.py tests/test_crew_state.py
git commit -m "feat: derive a crew's state from its submissions and commits"
```

---

## Task 2: The submission, state, and activation endpoints

**Files:**
- Modify: `api/routers/commits.py` - three routes
- Modify: `api/services/commit_service.py` - `caller_may_submit`
- Modify: `api/database.py` - `set_project_status`
- Test: `tests/test_submission_endpoint.py`

**Interfaces:**
- Consumes: `insert_crew_submission`, `crew_state_report`, `caller_may_commit`, `CREW_DEPENDENCIES`
- Produces:
  - `async def caller_may_submit(slug: str, payload: dict) -> bool` - as `caller_may_commit`, but a matching stakeholder needs `is_reviewer` **or** `is_approver`
  - `async def set_project_status(conn, *, slug: str, status: str) -> None`
  - `POST /projects/{slug}/submissions`, `GET /projects/{slug}/crew-states`, `POST /projects/{slug}/activate`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_submission_endpoint.py`, using the same `clean` fixture shape as
Task 1 with `SLUG = "submit-test"`:

```python
@pytest.mark.asyncio
async def test_submitting_moves_a_crew_to_ready(client):
    await client.post("/projects", json=PROJECT)
    resp = await client.post(
        f"/projects/{SLUG}/submissions",
        json={"crew_name": "discovery_mapping", "notes": "labels tidied"},
    )
    assert resp.status_code == 201

    states = (await client.get(f"/projects/{SLUG}/crew-states")).json()
    assert states["discovery_mapping"] == "ready"


@pytest.mark.asyncio
async def test_approving_a_submitted_crew_moves_it_to_committed(client):
    await client.post("/projects", json=PROJECT)
    await client.post(
        f"/projects/{SLUG}/submissions", json={"crew_name": "discovery_mapping"}
    )
    await client.post(
        f"/projects/{SLUG}/commits", json={"crew_name": "discovery_mapping"}
    )
    states = (await client.get(f"/projects/{SLUG}/crew-states")).json()
    assert states["discovery_mapping"] == "committed"


@pytest.mark.asyncio
async def test_an_unknown_crew_cannot_be_submitted(client):
    await client.post("/projects", json=PROJECT)
    resp = await client.post(
        f"/projects/{SLUG}/submissions", json={"crew_name": "not_a_crew"}
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_activation_sets_the_project_active(client):
    await client.post("/projects", json=PROJECT)
    resp = await client.post(f"/projects/{SLUG}/activate")
    assert resp.status_code == 200

    from api.database import get_connection, fetch_project
    async with get_connection(SLUG) as conn:
        project = await fetch_project(conn, slug=SLUG)
    assert project["status"] == "active"


@pytest.mark.asyncio
async def test_activating_twice_is_harmless(client):
    await client.post("/projects", json=PROJECT)
    await client.post(f"/projects/{SLUG}/activate")
    assert (await client.post(f"/projects/{SLUG}/activate")).status_code == 200
```

Add one test proving a reviewer who is not an approver **may submit but may not commit**,
following the pattern in `tests/test_commit_endpoint.py`'s
`test_caller_may_commit_matches_approver_by_email`: create a user with an email, a project
membership giving a `reviewer` role that clears `check_project_access`, and a stakeholder
with that email carrying `is_reviewer=1` and `is_approver=0`. Assert 201 from
`/submissions` and 403 from `/commits`. That pairing is the whole point of having two
permission rules - without it, either rule could be wrong and the suite would not notice.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `./venv/bin/pytest tests/test_submission_endpoint.py -v`
Expected: FAIL - the routes return 404.

- [ ] **Step 3: Add the permission rule**

In `api/services/commit_service.py`, beside `caller_may_commit`, add:

```python
async def caller_may_submit(slug: str, payload: dict) -> bool:
    """Whether this caller may mark a crew ready for approval.

    Wider than committing: a contributor who reviews but does not govern may submit.
    The shape is otherwise identical, and carries the same caveat - the sysadmin branch
    always fires today because the users table is empty.
    """
    return await _caller_matches_stakeholder_flag(
        slug, payload, flags=("is_reviewer", "is_approver")
    )
```

and refactor `caller_may_commit` to call the same helper with `flags=("is_approver",)`.
Extract `_caller_matches_stakeholder_flag(slug, payload, *, flags)` from the existing
body of `caller_may_commit` rather than duplicating the user lookup and email match -
two copies of an authorisation rule is how they drift apart.

- [ ] **Step 4: Add `set_project_status`**

In `api/database.py`, beside the other project helpers:

```python
async def set_project_status(
    conn: aiosqlite.Connection, *, slug: str, status: str
) -> None:
    """Set a project's lifecycle status. Idempotent."""
    await conn.execute("UPDATE projects SET status=? WHERE slug=?", (status, slug))
    await conn.commit()
```

- [ ] **Step 5: Add the three routes**

In `api/routers/commits.py`:

```python
class SubmissionRequest(BaseModel):
    crew_name: str
    notes: str = ""


@router.post("/{slug}/submissions", status_code=201)
async def create_submission(
    slug: str, req: SubmissionRequest, payload: dict = Depends(require_any_auth)
):
    """Mark a crew's work ready for approval - and summon the approvers."""
    await check_project_access(slug, payload)
    _require_project(slug)

    if req.crew_name not in CREW_DEPENDENCIES:
        raise HTTPException(status_code=422, detail=f"Unknown crew '{req.crew_name}'")
    if not await caller_may_submit(slug, payload):
        raise HTTPException(
            status_code=403, detail="Only a reviewer or approver may submit for approval"
        )

    async with get_connection(slug) as conn:
        submission_id = await insert_crew_submission(
            conn,
            crew_name=req.crew_name,
            submitted_by=payload.get("sub", ""),
            notes=req.notes,
        )

    await notify_crew_ready_for_approval(slug, req.crew_name)
    return {"id": submission_id, "crew_name": req.crew_name, "state": "ready"}


@router.get("/{slug}/crew-states")
async def get_crew_states(slug: str, payload: dict = Depends(require_any_auth)):
    await check_project_access(slug, payload)
    _require_project(slug)
    async with get_connection(slug) as conn:
        return await crew_state_report(conn)


@router.post("/{slug}/activate")
async def activate_project(slug: str, payload: dict = Depends(require_any_auth)):
    """Start the project. Until this, Pamela reports nothing."""
    await check_project_access(slug, payload)
    _require_project(slug)
    if not await caller_may_commit(slug, payload):
        raise HTTPException(
            status_code=403, detail="Only an approver may activate a project"
        )
    async with get_connection(slug) as conn:
        await set_project_status(conn, slug=slug, status="active")
    return {"slug": slug, "status": "active"}
```

`notify_crew_ready_for_approval` arrives in Task 3. Until then, import it inside the
function body and let this task's tests exercise the rest - or write Task 3 first if you
prefer; the two are independent apart from that name.

- [ ] **Step 6: Run the tests, then the full suite**

Run: `./venv/bin/pytest tests/test_submission_endpoint.py -v`
Expected: 6 passed

Run: `./venv/bin/pytest -q --ignore=tests/integration`
Expected: 601 passed.

- [ ] **Step 7: Commit**

```bash
git add api/routers/commits.py api/services/commit_service.py api/database.py tests/test_submission_endpoint.py
git commit -m "feat: submit a crew for approval, read crew states, activate a project"
```

---

## Task 3: The two audiences

**Files:**
- Modify: `api/services/pam_report_job.py` - `resolve_recipients` gains a flags parameter
- Modify: `api/services/commit_notify_service.py` - narrow the completion audience, add the submission notification
- Modify: `api/services/run_service.py` - re-enable the completion call sites
- Test: `tests/test_notification_audiences.py`

**Interfaces:**
- Produces:
  - `resolve_recipients(stakeholders, dev_mode, flags=REVIEW_FLAGS)` - existing callers unchanged
  - `async def notify_crew_ready_for_approval(slug: str, crew_name: str) -> None` - never raises

**This is the substance of the project.** Everything else is plumbing around it.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_notification_audiences.py`. Use the `clean` fixture shape from Task 1
with `SLUG = "audience-test"`, and set the review flags **directly in the database** -
`StakeholderIn` does accept them, but a direct insert keeps this a unit test of the
notification rather than of the endpoint's auth and validation. Set `dev_mode` to false in
`config_json`, or every address collapses to one and the filtering under test is invisible.

```python
@pytest.mark.asyncio
async def test_a_completed_crew_notifies_reviewers_and_not_approvers(client):
    await client.post("/projects", json=PROJECT)
    await _add_stakeholder(SLUG, "Rev", "rev@example.com", reviewer=True, approver=False)
    await _add_stakeholder(SLUG, "App", "app@example.com", reviewer=False, approver=True)
    await _set_dev_mode(SLUG, False)

    from api.services.commit_notify_service import notify_crew_awaiting_commit
    with patch("api.services.commit_notify_service._send_email", AsyncMock()) as send:
        await notify_crew_awaiting_commit(SLUG, "discovery_mapping")

    assert send.await_count == 1
    to = send.await_args.kwargs["to"]
    assert "rev@example.com" in to
    assert "app@example.com" not in to


@pytest.mark.asyncio
async def test_a_submission_notifies_approvers_and_not_reviewers(client):
    await client.post("/projects", json=PROJECT)
    await _add_stakeholder(SLUG, "Rev", "rev@example.com", reviewer=True, approver=False)
    await _add_stakeholder(SLUG, "App", "app@example.com", reviewer=False, approver=True)
    await _set_dev_mode(SLUG, False)

    from api.services.commit_notify_service import notify_crew_ready_for_approval
    with patch("api.services.commit_notify_service._send_email", AsyncMock()) as send:
        await notify_crew_ready_for_approval(SLUG, "discovery_mapping")

    assert send.await_count == 1
    to = send.await_args.kwargs["to"]
    assert "app@example.com" in to
    assert "rev@example.com" not in to


@pytest.mark.asyncio
async def test_somebody_who_is_both_hears_at_both_moments(client):
    await client.post("/projects", json=PROJECT)
    await _add_stakeholder(SLUG, "Both", "both@example.com", reviewer=True, approver=True)
    await _set_dev_mode(SLUG, False)

    from api.services.commit_notify_service import (
        notify_crew_awaiting_commit, notify_crew_ready_for_approval,
    )
    with patch("api.services.commit_notify_service._send_email", AsyncMock()) as send:
        await notify_crew_awaiting_commit(SLUG, "discovery_mapping")
        await notify_crew_ready_for_approval(SLUG, "discovery_mapping")

    assert send.await_count == 2
    assert all("both@example.com" in c.kwargs["to"] for c in send.await_args_list)


@pytest.mark.asyncio
async def test_a_submission_notification_failure_does_not_raise(client):
    await client.post("/projects", json=PROJECT)
    await _add_stakeholder(SLUG, "App", "app@example.com", reviewer=False, approver=True)
    await _set_dev_mode(SLUG, False)

    from api.services.commit_notify_service import notify_crew_ready_for_approval
    with patch(
        "api.services.commit_notify_service._send_email",
        AsyncMock(side_effect=RuntimeError("resend is down")),
    ):
        await notify_crew_ready_for_approval(SLUG, "discovery_mapping")
```

The third test is the one that catches an over-correction: narrowing the audiences must
not stop a person who is both reviewer and approver from hearing at both moments.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `./venv/bin/pytest tests/test_notification_audiences.py -v`
Expected: FAIL - the first test finds the approver in the recipient list; the others
cannot import `notify_crew_ready_for_approval`.

- [ ] **Step 3: Give `resolve_recipients` a flags parameter**

In `api/services/pam_report_job.py`:

```python
def resolve_recipients(
    stakeholders: list[dict], dev_mode: bool, flags: tuple[str, ...] = REVIEW_FLAGS
) -> tuple[list[str], list[str]]:
    """Return (actual, intended) email lists for stakeholders carrying any of `flags`.

    Defaulting to both review flags keeps the daily report's audience unchanged: it goes
    to everyone with a governance role, which is what it is for. The crew notifications
    pass a narrower tuple, because a completed crew concerns reviewers and a submission
    concerns approvers.
    """
    intended = [
        s["email"] for s in stakeholders
        if any(s.get(flag) for flag in flags) and (s.get("email") or "").strip()
    ]
    if not intended:
        return [], []
    return ([DEV_MODE_ADDRESS] if dev_mode else list(intended)), intended
```

The default keeps every existing caller behaving exactly as before.

- [ ] **Step 4: Narrow the completion audience and add the submission notification**

In `api/services/commit_notify_service.py`, extract the shared body of
`notify_crew_awaiting_commit` into a private helper taking the flags, the subject, and the
body lines, then express both public functions through it. `notify_crew_awaiting_commit`
passes `("is_reviewer",)`; `notify_crew_ready_for_approval` passes `("is_approver",)` with
a subject naming the crew as ready for approval. Both keep the existing `dev_mode` read
from `config_json`, the existing link to `/dashboard/{slug}/reviews`, and the guarantee
that neither raises.

- [ ] **Step 5: Re-enable the completion notification**

In `api/services/run_service.py`, restore the two call sites removed in SP20a - in
`dispatch_crew` and `dispatch_agent`, immediately after
`update_crew_run_status(..., status="completed")` and outside the `async with` block:

```python
        from api.services.commit_notify_service import notify_crew_awaiting_commit
        await notify_crew_awaiting_commit(slug, crew_name)
```

using `crew_label` in `dispatch_agent`. The import stays function-local, matching the
adjacent `auto_assign_service` import.

Also remove the "not currently called" note from the top of
`commit_notify_service.py` - it is called again.

- [ ] **Step 6: Run the tests, then the full suite**

Run: `./venv/bin/pytest tests/test_notification_audiences.py -v`
Expected: 4 passed

Run: `./venv/bin/pytest -q --ignore=tests/integration`
Expected: 605 passed. `tests/test_commit_notification.py` must still pass - if it asserts
an approver receives the completion email, that assertion encoded the defect and should be
updated, and you must say so in your report.

- [ ] **Step 7: Commit**

```bash
git add api/services/pam_report_job.py api/services/commit_notify_service.py api/services/run_service.py tests/test_notification_audiences.py
git commit -m "feat: notify reviewers when a crew finishes and approvers when it is submitted"
```

---

## Task 4: Pamela reports only on active projects

**Files:**
- Modify: `api/services/pam_report_job.py` - after the project fetch at line 124
- Test: `tests/test_pam_report_job.py` (append)

**Interfaces:**
- Consumes: `projects.status`, set to `'active'` by Task 2's endpoint

- [ ] **Step 1: Write the failing test**

Append to `tests/test_pam_report_job.py`, matching its existing fixture and helpers:

```python
@pytest.mark.asyncio
async def test_an_inactive_project_produces_no_report(client):
    """A project still in setup should not generate reports or mail."""
    await client.post("/projects", json=PROJECT)  # status defaults to 'created'

    from api.services.pam_report_job import run_pam_daily_report
    with patch("api.services.pam_report_job._send_email", AsyncMock()) as send:
        await run_pam_daily_report(SLUG)

    assert send.await_count == 0


@pytest.mark.asyncio
async def test_an_active_project_still_produces_a_report(client):
    """The guard must not stop the thing it is guarding."""
    await client.post("/projects", json=PROJECT)
    from api.database import get_connection, set_project_status
    async with get_connection(SLUG) as conn:
        await set_project_status(conn, slug=SLUG, status="active")

    from api.services.pam_report_job import run_pam_daily_report
    with patch("api.services.pam_report_job._send_email", AsyncMock()):
        await run_pam_daily_report(SLUG)

    from api.database import fetch_agent_outputs, fetch_project
    async with get_connection(SLUG) as conn:
        project = await fetch_project(conn, slug=SLUG)
        outputs = await fetch_agent_outputs(conn, project_id=project["id"])
    assert any(o["output_type"] == "pam_report" for o in outputs)
```

The second test is what stops the guard being written as "return early always".

- [ ] **Step 2: Run the tests to verify they fail**

Run: `./venv/bin/pytest tests/test_pam_report_job.py -v -k "inactive or still_produces"`
Expected: FAIL - the inactive project produces a report and sends mail.

- [ ] **Step 3: Add the guard**

In `api/services/pam_report_job.py`, inside `run_pam_daily_report`, immediately after the
`if not project:` check:

```python
        if project.get("status") != "active":
            logger.info(
                "pam report job: project %s is not active - skipping", slug
            )
            return
```

Place it before the report is stored or sent. Note the report is currently *built* before
this block is reached (`build_pam_report` is called at the top of the function); moving the
guard above that call avoids the wasted work, and is preferable if the surrounding code
allows it without restructuring.

- [ ] **Step 4: Run the tests, then the full suite**

Run: `./venv/bin/pytest tests/test_pam_report_job.py -v`
Expected: all pass, including the two new ones. Existing tests in this file that expect a
report may now need the project activated first - if so, activate it in their setup rather
than weakening the guard, and say so in your report.

Run: `./venv/bin/pytest -q --ignore=tests/integration`
Expected: 607 passed.

- [ ] **Step 5: Commit**

```bash
git add api/services/pam_report_job.py tests/test_pam_report_job.py
git commit -m "feat: report only on projects that have been activated"
```

---

## Task 5: Remove the twelve gates

**Files:**
- Modify: twelve agent modules, listed below
- Test: `tests/test_no_end_of_phase_gates.py`

**Interfaces:** none. Only task descriptions change.

**Do not modify `agents/tools/human_input.py`.** The tool stays registered and usable.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_no_end_of_phase_gates.py`:

```python
# tests/test_no_end_of_phase_gates.py
"""A crew's last act is finishing.

Approval is recorded in approval_commits, outside the run. An agent instructed to call
HumanInputTool and wait for "approved" blocks for up to 24 hours and then proceeds on
the string "timeout" as though it had an answer.
"""
from pathlib import Path

import pytest

GATED = [
    "discovery/value_chain_mapper",
    "discovery/requirements_analyst",
    "discovery/value_lever_analyst",
    "discovery/interview_coordinator",
    "discovery/interview_script_designer",
    "discovery/synthesis_analyst",
    "value_design/value_proposition_generator",
    "architecture/enterprise_architect",
    "architecture/initiative_identifier",
    "delivery/roadmap_generator",
    "delivery/visual_illustrator",
    "business_plan/business_plan_generator",
]

# These use the tool to ask a question, not to seek a sign-off. They are project 5's
# problem, and removing them here would silently disable the interview path.
KEEPS_A_GENUINE_USE = [
    "discovery/stakeholder_interviewer",
    "discovery/requirements_capture",
    "business_plan/business_plan_generator",
]


def _source(module: str) -> str:
    return Path("agents", f"{module}.py").read_text()


@pytest.mark.parametrize("module", GATED)
def test_no_module_asks_the_reviewer_to_reply_approved(module):
    """The gate's signature phrase, whatever wording surrounds it."""
    source = _source(module).lower()
    assert 'reply "approved"' not in source and "reply 'approved'" not in source, (
        f"{module} still gates on a typed approval"
    )


@pytest.mark.parametrize("module", GATED)
def test_no_module_loops_on_revision_notes(module):
    source = _source(module).lower()
    assert "call humaninputtool again" not in source, (
        f"{module} still loops waiting for revisions"
    )


@pytest.mark.parametrize("module", KEEPS_A_GENUINE_USE)
def test_the_genuine_uses_survive(module):
    """business_plan_generator appears in both lists deliberately: its gate goes and
    its context-gathering step stays, which a per-file count could not express."""
    assert "HumanInputTool" in _source(module), (
        f"{module} lost a use that is not an approval gate"
    )


def test_the_tool_itself_is_untouched():
    source = Path("agents/tools/human_input.py").read_text()
    assert "class HumanInputTool" in source
    assert "time.sleep" in source
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `./venv/bin/pytest tests/test_no_end_of_phase_gates.py -v`
Expected: FAIL - the first two parametrised tests fail for most of the twelve.

- [ ] **Step 3: Remove the gates**

For each of the twelve modules, delete the numbered step that asks the reviewer to reply
"approved", and the revision-loop step that serves it where one exists. **Nine** have both;
`roadmap_generator` and `visual_illustrator` have the gate alone.

`business_plan_generator` has two `HumanInputTool` steps and they are different: the one at
line 44 gathers business context and financial assumptions - **keep it** - and the one at
line 81 is the gate - remove it. Read what each prompt asks for; do not remove by position
or by count.

Renumber the remaining steps in each task description so the sequence has no gap. A list
that jumps from 7 to 9 invites the model to wonder what it missed.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `./venv/bin/pytest tests/test_no_end_of_phase_gates.py -v`
Expected: 28 passed

- [ ] **Step 5: Run the full backend suite**

Run: `./venv/bin/pytest -q --ignore=tests/integration`
Expected: 635 passed. Existing tests asserting on a removed step's wording should be
updated to the new text, not reverted - say which in your report.

- [ ] **Step 6: Commit**

```bash
git add agents/discovery/*.py agents/value_design/value_proposition_generator.py agents/architecture/*.py agents/delivery/*.py agents/business_plan/business_plan_generator.py tests/test_no_end_of_phase_gates.py
git commit -m "feat: crews finish rather than blocking for a typed approval"
```

---

## Task 6: Reseed the two skill descriptions

**Files:**
- Modify: `api/routers/skills.py` - the seeding function around lines 226-240
- Test: `tests/test_skill_description_migration.py`

**Interfaces:** none.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_skill_description_migration.py`. The seeding route is
`POST /admin/skills/seed` (`api/routers/skills.py:203`), sysadmin-only, which the shared
`client` fixture already satisfies. It writes to `system.db`, so these tests clean up the
two skill rows rather than a project database.

```python
# tests/test_skill_description_migration.py
"""A description somebody edited belongs to them.

Baseline seeding merges an existing skill's agents but never touched its description,
so the two rewritten in SP20a never reached an existing database. This replaces them -
but only where nobody has edited them.
"""
import pytest

from api.services.skills_service import BASELINE_SKILLS

OLD_PHASE_GATING = (
    "Block every downstream dispatch until the project team explicitly confirms "
    "human review. If review is pending, output the review request and halt \u2014 "
    "never proceed without confirmation."
)


def _baseline_description(name: str) -> str:
    for skill in BASELINE_SKILLS:
        if skill["name"] == name:
            return skill["description"]
    raise AssertionError(f"{name!r} is not a baseline skill")


async def _store_skill(name: str, description: str) -> None:
    from api.database import get_system_connection
    async with get_system_connection() as conn:
        await conn.execute("DELETE FROM agent_skills WHERE lower(name)=lower(?)", (name,))
        await conn.execute(
            "INSERT INTO agent_skills (name, description) VALUES (?,?)",
            (name, description),
        )
        await conn.commit()


async def _stored_description(name: str) -> str:
    from api.database import get_system_connection
    async with get_system_connection() as conn:
        async with conn.execute(
            "SELECT description FROM agent_skills WHERE lower(name)=lower(?)", (name,)
        ) as cur:
            row = await cur.fetchone()
    return row["description"] if row else ""


@pytest.fixture(autouse=True)
async def clean():
    yield
    from api.database import get_system_connection
    async with get_system_connection() as conn:
        await conn.execute("DELETE FROM agent_skills WHERE lower(name)='phase gating'")
        await conn.commit()


@pytest.mark.asyncio
async def test_an_untouched_description_is_replaced(client):
    await _store_skill("Phase Gating", OLD_PHASE_GATING)
    assert (await client.post("/admin/skills/seed")).status_code == 200
    assert await _stored_description("Phase Gating") == _baseline_description("Phase Gating")


@pytest.mark.asyncio
async def test_an_edited_description_is_left_alone(client):
    """One character different is still somebody's edit."""
    edited = OLD_PHASE_GATING + " Also check the budget."
    await _store_skill("Phase Gating", edited)
    assert (await client.post("/admin/skills/seed")).status_code == 200
    assert await _stored_description("Phase Gating") == edited


@pytest.mark.asyncio
async def test_a_missing_skill_is_still_seeded(client):
    """The migration must not break the ordinary insert-if-absent path."""
    from api.database import get_system_connection
    async with get_system_connection() as conn:
        await conn.execute("DELETE FROM agent_skills WHERE lower(name)='phase gating'")
        await conn.commit()

    assert (await client.post("/admin/skills/seed")).status_code == 200
    assert await _stored_description("Phase Gating") == _baseline_description("Phase Gating")
```

If `agent_skills`'s column names differ from `name`/`description`, read the table's
definition in `api/database.py` and match it - do not invent columns.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `./venv/bin/pytest tests/test_skill_description_migration.py -v`
Expected: FAIL - the first test finds the old description still stored.

- [ ] **Step 3: Implement**

In `api/routers/skills.py`, add a module-level map of the two skills' **pre-SP20a**
descriptions:

```python
# Descriptions as they stood before the end-of-phase gating was removed. Seeding
# replaces a stored description only when it still matches one of these exactly - a
# description anybody has edited through the Role & Skills tab is theirs to keep.
_SUPERSEDED_DESCRIPTIONS: dict[str, str] = {
    "phase gating": (
        "Block every downstream dispatch until the project team explicitly confirms "
        "human review. If review is pending, output the review request and halt \u2014 "
        "never proceed without confirmation."
    ),
    "human review gate": (
        "At the end of every work phase, pause and request human review. Write a clear "
        "summary of what was produced and what the reviewer needs to validate. Do not "
        "allow downstream crews to proceed until review is confirmed."
    ),
}
```

**These strings are recovered from git (`git show cdb05194^:api/services/skills_service.py`,
lines 110 and 131) and must match byte for byte.** Note both contain an **em dash or its
absence exactly as written** - the Phase Gating text has ` \u2014 ` (an em dash with spaces),
which the project style guide forbids in new prose but which is what is actually stored in
existing databases. Reproducing it faithfully is the whole point: a single character
difference makes the migration a silent no-op, which is the failure mode this design is
most exposed to. Do not "correct" the punctuation in this constant.

In the seeding loop, where an existing skill is found by name, add: if the stored
description equals `_SUPERSEDED_DESCRIPTIONS[key]`, update it to the baseline item's
description. Leave the existing agent-merging behaviour exactly as it is.

- [ ] **Step 4: Run the tests, then the full suite**

Run: `./venv/bin/pytest tests/test_skill_description_migration.py -v`
Expected: 3 passed

Run: `./venv/bin/pytest -q --ignore=tests/integration`
Expected: 638 passed.

- [ ] **Step 5: Commit**

```bash
git add api/routers/skills.py tests/test_skill_description_migration.py
git commit -m "feat: replace the two superseded skill descriptions, sparing edited ones"
```

---

## Task 7: The reviews page

**Files:**
- Modify: `ui/src/api/endpoints.ts` - two additions to `commitsApi`
- Modify: `ui/src/pages/Reviews.tsx` - the crew section
- Delete: `ui/src/components/ReviewQueue.tsx` and `ui/src/__tests__/ReviewQueueCommit.test.tsx`
- Create: `ui/src/components/CrewApprovalRow.tsx`
- Test: `ui/src/__tests__/CrewApprovalRow.test.tsx`

**Interfaces:**
- Consumes: `GET /projects/{slug}/crew-states` → `{ [crew]: 'working' | 'ready' | 'committed' }`; `POST /projects/{slug}/submissions`; the existing `commitsApi.create`, `readiness`, and `changeCount`
- Produces: `CrewApprovalRow`, exported for direct testing

- [ ] **Step 1: Write the failing test**

Create `ui/src/__tests__/CrewApprovalRow.test.tsx`:

```tsx
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, it, expect, vi, beforeEach } from 'vitest'

import { CrewApprovalRow } from '../components/CrewApprovalRow'

const onSubmit = vi.fn()
const onApprove = vi.fn()

function row(state: 'working' | 'ready' | 'committed', changeCount = 0) {
  return (
    <CrewApprovalRow
      crewName="discovery_mapping"
      state={state}
      changeCount={changeCount}
      onSubmit={onSubmit}
      onApprove={onApprove}
    />
  )
}

beforeEach(() => { onSubmit.mockReset(); onApprove.mockReset() })

describe('CrewApprovalRow', () => {
  it('offers the contributor a way to mark it ready while it is working', () => {
    render(row('working'))
    expect(screen.getByRole('button', { name: /ready for approval/i })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /approve/i })).not.toBeInTheDocument()
  })

  it('offers the approver a way to approve once it is ready', () => {
    render(row('ready'))
    expect(screen.getByRole('button', { name: /approve/i })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /ready for approval/i })).not.toBeInTheDocument()
  })

  it('offers nothing once it is committed', () => {
    render(row('committed'))
    expect(screen.queryByRole('button')).not.toBeInTheDocument()
  })

  it('names the outstanding changes on the approve control', () => {
    render(row('ready', 3))
    expect(screen.getByRole('button', { name: /approve/i }).textContent).toContain('3')
  })

  it('submits the crew it was given', async () => {
    render(row('working'))
    await userEvent.click(screen.getByRole('button', { name: /ready for approval/i }))
    expect(onSubmit).toHaveBeenCalledWith('discovery_mapping')
  })
})
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd ui && npx vitest run src/__tests__/CrewApprovalRow.test.tsx`
Expected: FAIL - cannot resolve `../components/CrewApprovalRow`

- [ ] **Step 3: Create the row**

Create `ui/src/components/CrewApprovalRow.tsx`:

```tsx
// ui/src/components/CrewApprovalRow.tsx
import CommitControl from './CommitControl'
import { CREW_LABELS } from './agentStatus'

export type CrewState = 'working' | 'ready' | 'committed'

/**
 * One crew's place in the approval loop, and the single act available from here.
 *
 * The contributor shapes the output and marks it ready; the approver approves. Showing
 * both controls at once would invite the approver to act before the contributor has
 * finished, which is the confusion this whole project exists to remove.
 */
export function CrewApprovalRow({
  crewName,
  state,
  changeCount,
  onSubmit,
  onApprove,
}: {
  crewName: string
  state: CrewState
  changeCount: number
  onSubmit: (crewName: string) => void | Promise<void>
  onApprove: (crewName: string) => void | Promise<void>
}) {
  const label = CREW_LABELS[crewName] ?? crewName

  return (
    <div className="flex items-center justify-between gap-3 py-2 border-b border-gray-100">
      <div className="min-w-0">
        <p className="text-sm font-medium text-gray-900 truncate">{label}</p>
        <p className="text-[11px] text-gray-500">
          {state === 'working'
            ? 'In progress'
            : state === 'ready'
              ? 'Ready for approval'
              : 'Approved'}
        </p>
      </div>

      {state === 'working' && (
        <CommitControl
          crewName={crewName}
          changeCount={0}
          onCommit={onSubmit}
          label="Ready for approval"
        />
      )}
      {state === 'ready' && (
        <CommitControl
          crewName={crewName}
          changeCount={changeCount}
          onCommit={onApprove}
          label="Approve"
        />
      )}
    </div>
  )
}

export default CrewApprovalRow
```

`CommitControl` currently hard-codes its own wording. Give it an optional `label` prop
defaulting to `'Commit'`, so one busy-state button serves both acts rather than a second
one being written; its "over N changes" suffix stays and appends to whichever label it is
given. Update `ui/src/__tests__/ReviewQueueCommit.test.tsx`'s expectations only if that
file still exists at this point - Step 5 deletes it.

- [ ] **Step 4: Add the API calls**

In `ui/src/api/endpoints.ts`, inside the existing `commitsApi` object:

```ts
  states: (slug: string): Promise<Record<string, 'working' | 'ready' | 'committed'>> =>
    apiClient.get<Record<string, 'working' | 'ready' | 'committed'>>(
      `/projects/${slug}/crew-states`,
    ).then((r) => r.data),
  submit: (slug: string, crewName: string, notes = ''): Promise<unknown> =>
    apiClient.post(`/projects/${slug}/submissions`, { crew_name: crewName, notes })
      .then((r) => r.data),
```

- [ ] **Step 5: Put the section on the page**

In `ui/src/pages/Reviews.tsx`, add a section above the existing review cards listing every
crew whose state is `working` or `ready`, each rendered as a `CrewApprovalRow`. Fetch
`commitsApi.states(slug)` and the per-crew change count, following the file's existing
`useQuery` conventions - read it before editing. On either action, invalidate the
`crew-states` and `crew-readiness` query keys so the page and the board both update.

A crew whose state is `working` **and** which has never been run has nothing to submit -
omit it, so the section lists work that exists rather than every crew in the graph.

Then delete `ui/src/components/ReviewQueue.tsx` and
`ui/src/__tests__/ReviewQueueCommit.test.tsx`. Their commit behaviour now lives in
`CrewApprovalRow` and its test.

- [ ] **Step 6: Run the whole frontend suite and typecheck**

Run: `cd ui && npx vitest run && npx tsc --noEmit`
Expected: 78 passed - 77 baseline, plus 5 new, less the 4 deleted with
`ReviewQueueCommit.test.tsx`. No type errors, and no import of the deleted component
anywhere.

- [ ] **Step 7: Run the backend suite**

Run: `./venv/bin/pytest -q --ignore=tests/integration`
Expected: 638 passed, unchanged by this task.

- [ ] **Step 8: Commit**

```bash
git add ui/src/api/endpoints.ts ui/src/pages/Reviews.tsx ui/src/components/CrewApprovalRow.tsx ui/src/__tests__/CrewApprovalRow.test.tsx
git rm ui/src/components/ReviewQueue.tsx ui/src/__tests__/ReviewQueueCommit.test.tsx
git commit -m "feat: mark a crew ready and approve it from the reviews page"
```

---

## Manual verification

Automated tests cannot confirm the loop feels right, and this project's whole point is a
sequence of human acts. With the API and UI running, and `dev_mode` on so mail is safe:

1. Create a project. Confirm Pamela produces no report - it is not active yet.
2. Activate it. Confirm the daily report job now produces one.
3. Run Alex (`discovery_mapping`). Confirm the run **finishes** rather than hanging - this
   is the 24-hour block being gone, and the single most important thing to see.
4. Confirm the completion email arrives and is addressed to reviewers only.
5. On the reviews page, confirm Alex shows as `working` with a **Ready for approval**
   control. Click it.
6. Confirm the approval email arrives, addressed to approvers only, and that the row now
   offers **Approve** rather than **Ready for approval**.
7. Approve. Confirm the row disappears and Maya's card turns Ready on the board.
8. Add a note against one of Alex's outputs, then confirm the approve control reads
   "Approve over 1 change" when Alex is next submitted.
