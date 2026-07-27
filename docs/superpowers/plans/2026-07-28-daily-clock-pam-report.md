# Daily Clock + Pamela's Status Report Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give the platform a scheduler, with Pamela's 17:00 daily status report as its only consumer - generated from live state, diffed against yesterday, stored for audit, and emailed as a link.

**Architecture:** A `scheduled_jobs` table in `system.db` records when each job is next due. A scheduler started in the FastAPI lifespan ticks every 15 minutes, and also on boot so an overdue job self-heals after a restart. The report derivation currently inline in the router is extracted to a service so the endpoint and the job share one code path.

**Tech Stack:** FastAPI, aiosqlite, asyncio, httpx (Resend), pytest + pytest-asyncio, `unittest.mock`.

**Spec:** `docs/superpowers/specs/2026-07-27-daily-clock-pam-report-design.md`

**Scope note:** the spec's tokenised report access is a separate plan. Until it lands, the emailed link requires a login - acceptable because `dev_mode` defaults to true and routes all mail to a single address whose owner has an account.

## Global Constraints

- Schedule is **17:00 daily, server local time**. Tick interval **15 minutes**. Run once on boot if overdue; **never backfill** missed days.
- Change detection keys on the risk/issue **`title`** field.
- `dev_mode` defaults to **true** for existing and new projects. When true every recipient is replaced by `Patrick@FutureEdge.consulting`, and the body still names who would have received it.
- Report recipients are stakeholders flagged `is_reviewer` or `is_approver` - the existing multi-valued
  engagement-role columns. NOT `project_role`, which is single-select and cannot express someone who is
  both a recipient and a reviewer.
- The async `insert_agent_output` helper does **not** set `is_current` (unlike `insert_agent_output_sync`). The job must set it explicitly and supersede prior reports, or every report will look superseded.
- A job that throws records the error and schedules the next run normally. The scheduler itself must never be able to kill the app.
- British English (`-ise`, `-our`). Use ` - ` (spaced hyphen), never an em dash, in comments and strings.
- Run tests with `./venv/bin/pytest` (Python 3.13 venv; do NOT use system python). Baseline before this plan: **490 passing** with `--ignore=tests/integration`.

## File Structure

| File | Responsibility |
|------|----------------|
| `api/services/pam_report_service.py` (create) | `build_pam_report(slug)` - the derivation, extracted from the router |
| `api/routers/pam_report.py` (modify) | Thin endpoint delegating to the service |
| `api/services/report_diff_service.py` (create) | Pure diff of two report snapshots |
| `api/services/scheduler_service.py` (create) | Due selection, run-with-guard, next-due calculation |
| `api/services/pam_report_job.py` (create) | The job: compute, store, diff, email |
| `api/database.py` (modify) | `scheduled_jobs` table + its helpers |
| `api/main.py` (modify) | Start and stop the scheduler in the lifespan |
| `api/models.py` (modify) | `dev_mode` on `ProjectSettings` |
| `api/services/stakeholder_service.py` (modify) | Comment recording that review routing uses the boolean columns |

---

### Task 1: Extract the report derivation into a service

**Files:**
- Create: `api/services/pam_report_service.py`
- Modify: `api/routers/pam_report.py`
- Test: `tests/test_pam_report_service.py`

**Interfaces:**
- Consumes: nothing from earlier tasks
- Produces: `async def build_pam_report(slug: str) -> dict` - returns the same dict the endpoint returns today

The whole derivation currently lives inside the route handler `get_pam_report(slug, payload)` in `api/routers/pam_report.py` (roughly lines 73-345). The scheduled job cannot call a route handler, so this is a pure move with no behaviour change.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_pam_report_service.py
"""The report derivation must be callable outside a request.

It lived inside the route handler, so the scheduled job could not reach it.
This asserts the service exists and returns the same shape the endpoint returns.
"""
import pytest


@pytest.mark.asyncio
async def test_build_pam_report_returns_the_report_shape(client):
    await client.post("/projects", json={
        "client_slug": "pam-svc-test", "llm_mode": "standard", "sector": "rail",
    })
    from api.services.pam_report_service import build_pam_report

    report = await build_pam_report("pam-svc-test")

    for key in ["generated_at", "project_slug", "overall_health", "health_summary",
                "milestones", "crews", "risks", "issues", "interview_tracker"]:
        assert key in report, f"missing {key}"
    assert report["project_slug"] == "pam-svc-test"


@pytest.mark.asyncio
async def test_endpoint_and_service_agree(client):
    """The endpoint must delegate, not duplicate - otherwise they can drift."""
    await client.post("/projects", json={
        "client_slug": "pam-svc-agree", "llm_mode": "standard", "sector": "rail",
    })
    from api.services.pam_report_service import build_pam_report

    via_service = await build_pam_report("pam-svc-agree")
    resp = await client.get("/projects/pam-svc-agree/pam-report")
    via_endpoint = resp.json()

    assert resp.status_code == 200
    # generated_at is a timestamp and will differ between the two calls
    via_service.pop("generated_at", None)
    via_endpoint.pop("generated_at", None)
    assert via_service == via_endpoint
```

- [ ] **Step 2: Run test to verify it fails**

Run: `./venv/bin/pytest tests/test_pam_report_service.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'api.services.pam_report_service'`

- [ ] **Step 3: Move the derivation**

Create `api/services/pam_report_service.py`. Move the **entire body** of `get_pam_report` from `api/routers/pam_report.py` into:

```python
# api/services/pam_report_service.py
"""Derives Pamela's status report from live project state.

Extracted from the route handler so the scheduled daily job can call it. The
endpoint and the job must share one derivation - two copies would drift, and the
stored artefact would stop matching what the UI shows.
"""


async def build_pam_report(slug: str) -> dict:
    ...
```

Move the module-level helpers `_today`, `_days_delta` and `_milestone_rag` across with it, along with the imports they need. Change nothing inside the logic - this is a move, not a rewrite.

- [ ] **Step 4: Make the endpoint delegate**

In `api/routers/pam_report.py`, replace the handler body:

```python
from api.services.pam_report_service import build_pam_report


@router.get("")
async def get_pam_report(slug: str, payload: dict = Depends(require_any_auth)):
    return await build_pam_report(slug)
```

Delete the now-unused imports from the router.

- [ ] **Step 5: Run tests to verify they pass**

Run: `./venv/bin/pytest tests/test_pam_report_service.py -v`
Expected: PASS (2 passed)

Then run the existing report tests to confirm nothing changed:
Run: `./venv/bin/pytest -q --ignore=tests/integration -k "pam or report"`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add api/services/pam_report_service.py api/routers/pam_report.py tests/test_pam_report_service.py
git commit -m "refactor: extract the PAM report derivation into a service"
```

---

### Task 2: The dev_mode setting

**Files:**
- Modify: `api/services/stakeholder_service.py:16`
- Modify: `api/models.py` (`ProjectSettings`)
- Test: `tests/test_reviewer_role_and_dev_mode.py`

**Interfaces:**
- Consumes: nothing
- Produces: `VALID_ROLES` including `"reviewer"`; `ProjectSettings.dev_mode: bool = True`

`stakeholders.project_role` is `TEXT` with no CHECK constraint, so no migration is needed.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_reviewer_role_and_dev_mode.py
"""reviewer may review and request changes but cannot approve. dev_mode keeps
outbound email away from real stakeholders until deliberately switched off."""
import pytest

from api.services.stakeholder_service import VALID_ROLES


def test_reviewer_is_a_valid_project_role():
    assert "reviewer" in VALID_ROLES


def test_the_four_roles_are_exactly_these():
    assert VALID_ROLES == {"recipient", "governing", "actor", "reviewer"}


def test_dev_mode_defaults_to_true():
    """A scheduler that emails real stakeholders the first time it runs correctly
    is a worse failure than one that emails nobody."""
    from api.models import ProjectSettings
    assert ProjectSettings(sector="rail").dev_mode is True


@pytest.mark.asyncio
async def test_dev_mode_round_trips_through_the_settings_endpoint(client):
    await client.post("/projects", json={
        "client_slug": "devmode-test", "llm_mode": "standard", "sector": "rail",
    })
    got = await client.get("/projects/devmode-test/settings")
    assert got.json()["dev_mode"] is True

    body = got.json()
    body["dev_mode"] = False
    patched = await client.patch("/projects/devmode-test/settings", json=body)
    assert patched.status_code == 200
    assert patched.json()["dev_mode"] is False

    again = await client.get("/projects/devmode-test/settings")
    assert again.json()["dev_mode"] is False


@pytest.mark.asyncio
async def test_reviewer_role_is_accepted_on_a_stakeholder(client):
    await client.post("/projects", json={
        "client_slug": "reviewer-test", "llm_mode": "standard", "sector": "rail",
    })
    resp = await client.post("/projects/reviewer-test/stakeholders", json={
        "name": "Reviewing Person", "email": "reviewer@example.test",
        "project_role": "reviewer",
    })
    assert resp.status_code in (200, 201)
    assert resp.json()["project_role"] == "reviewer"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `./venv/bin/pytest tests/test_reviewer_role_and_dev_mode.py -v`
Expected: FAIL - `reviewer` not in `VALID_ROLES`, and `ProjectSettings` has no `dev_mode`

- [ ] **Step 3: Add the role**

In `api/services/stakeholder_service.py`, line 16:

```python
# recipient receives approved output; governing approves; actor is engaged with;
# reviewer may review and request changes but cannot approve.
VALID_ROLES = {"recipient", "governing", "actor", "reviewer"}
```

- [ ] **Step 4: Add the setting**

In `api/models.py`, add to `ProjectSettings` after `slack_channel`:

```python
    # When true, all outbound project email goes to a single dev address instead
    # of real stakeholders. Defaults to true: emailing real people the first time
    # the scheduler runs correctly is a worse failure than emailing nobody.
    dev_mode: bool = True
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `./venv/bin/pytest tests/test_reviewer_role_and_dev_mode.py -v`
Expected: PASS (5 passed)

- [ ] **Step 6: Add the role to the UI picker**

In `ui/src/pages/StakeholderForm.tsx`, find the `project_role` select options and add `reviewer` alongside the existing three, labelled "Reviewer (may request changes, cannot approve)". Then run:

Run: `cd ui && npx tsc --noEmit -p tsconfig.json`
Expected: exit 0

- [ ] **Step 7: Commit**

```bash
git add api/services/stakeholder_service.py api/models.py \
        tests/test_reviewer_role_and_dev_mode.py ui/src/pages/StakeholderForm.tsx
git commit -m "feat: add the reviewer role and the per-project dev_mode flag"
```

---

### Task 3: The scheduled_jobs table

**Files:**
- Modify: `api/database.py` (`init_system_db`, plus helpers)
- Test: `tests/test_scheduled_jobs_table.py`

**Interfaces:**
- Consumes: `get_system_connection()`
- Produces:
  - `async def upsert_scheduled_job(conn, *, job_name: str, slug: str, next_due_at: str) -> None`
  - `async def fetch_due_jobs(conn, *, now_iso: str) -> list[dict]`
  - `async def mark_job_running(conn, *, job_name: str, slug: str, now_iso: str) -> bool`
  - `async def mark_job_finished(conn, *, job_name: str, slug: str, status: str, next_due_at: str, last_error: str = "") -> None`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_scheduled_jobs_table.py
"""The scheduler's memory. Job state lives in system.db so all scheduling is
visible in one place and a restart can see what is overdue."""
import pytest

from api.database import (
    fetch_due_jobs,
    get_system_connection,
    mark_job_finished,
    mark_job_running,
    upsert_scheduled_job,
)


@pytest.mark.asyncio
async def test_a_job_due_in_the_past_is_returned():
    async with get_system_connection() as conn:
        await upsert_scheduled_job(conn, job_name="t_due", slug="p1",
                                   next_due_at="2020-01-01T17:00:00")
        due = await fetch_due_jobs(conn, now_iso="2020-01-02T09:00:00")
    assert any(j["job_name"] == "t_due" and j["slug"] == "p1" for j in due)


@pytest.mark.asyncio
async def test_a_job_due_in_the_future_is_not_returned():
    async with get_system_connection() as conn:
        await upsert_scheduled_job(conn, job_name="t_future", slug="p2",
                                   next_due_at="2099-01-01T17:00:00")
        due = await fetch_due_jobs(conn, now_iso="2020-01-02T09:00:00")
    assert not any(j["job_name"] == "t_future" for j in due)


@pytest.mark.asyncio
async def test_upsert_is_idempotent_per_job_and_slug():
    """Registering a job every boot must not create duplicate rows."""
    async with get_system_connection() as conn:
        await upsert_scheduled_job(conn, job_name="t_once", slug="p3",
                                   next_due_at="2099-01-01T17:00:00")
        await upsert_scheduled_job(conn, job_name="t_once", slug="p3",
                                   next_due_at="2099-01-01T17:00:00")
        async with conn.execute(
            "SELECT COUNT(*) FROM scheduled_jobs WHERE job_name=? AND slug=?",
            ("t_once", "p3"),
        ) as cur:
            n = (await cur.fetchone())[0]
    assert n == 1


@pytest.mark.asyncio
async def test_marking_running_claims_the_job_once():
    """The second claim must fail, so a job cannot run twice concurrently."""
    async with get_system_connection() as conn:
        await upsert_scheduled_job(conn, job_name="t_claim", slug="p4",
                                   next_due_at="2020-01-01T17:00:00")
        first = await mark_job_running(conn, job_name="t_claim", slug="p4",
                                       now_iso="2020-01-02T09:00:00")
        second = await mark_job_running(conn, job_name="t_claim", slug="p4",
                                        now_iso="2020-01-02T09:00:00")
    assert first is True
    assert second is False


@pytest.mark.asyncio
async def test_a_running_job_is_not_returned_as_due():
    async with get_system_connection() as conn:
        await upsert_scheduled_job(conn, job_name="t_busy", slug="p5",
                                   next_due_at="2020-01-01T17:00:00")
        await mark_job_running(conn, job_name="t_busy", slug="p5",
                               now_iso="2020-01-02T09:00:00")
        due = await fetch_due_jobs(conn, now_iso="2020-01-02T09:00:00")
    assert not any(j["job_name"] == "t_busy" for j in due)


@pytest.mark.asyncio
async def test_finishing_records_status_and_reschedules():
    async with get_system_connection() as conn:
        await upsert_scheduled_job(conn, job_name="t_fin", slug="p6",
                                   next_due_at="2020-01-01T17:00:00")
        await mark_job_running(conn, job_name="t_fin", slug="p6",
                               now_iso="2020-01-02T09:00:00")
        await mark_job_finished(conn, job_name="t_fin", slug="p6", status="ok",
                                next_due_at="2020-01-03T17:00:00")
        async with conn.execute(
            "SELECT status, next_due_at, last_run_at FROM scheduled_jobs "
            "WHERE job_name=? AND slug=?", ("t_fin", "p6"),
        ) as cur:
            row = await cur.fetchone()
    assert row["status"] == "ok"
    assert row["next_due_at"] == "2020-01-03T17:00:00"
    assert row["last_run_at"] == "2020-01-02T09:00:00"


@pytest.mark.asyncio
async def test_a_failed_job_records_its_error_and_still_reschedules():
    """One bad day must not stop the schedule."""
    async with get_system_connection() as conn:
        await upsert_scheduled_job(conn, job_name="t_err", slug="p7",
                                   next_due_at="2020-01-01T17:00:00")
        await mark_job_running(conn, job_name="t_err", slug="p7",
                               now_iso="2020-01-02T09:00:00")
        await mark_job_finished(conn, job_name="t_err", slug="p7", status="failed",
                                next_due_at="2020-01-03T17:00:00",
                                last_error="Resend returned 502")
        async with conn.execute(
            "SELECT status, last_error, next_due_at FROM scheduled_jobs "
            "WHERE job_name=? AND slug=?", ("t_err", "p7"),
        ) as cur:
            row = await cur.fetchone()
    assert row["status"] == "failed"
    assert "502" in row["last_error"]
    assert row["next_due_at"] == "2020-01-03T17:00:00"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `./venv/bin/pytest tests/test_scheduled_jobs_table.py -v`
Expected: FAIL with `ImportError: cannot import name 'upsert_scheduled_job'`

- [ ] **Step 3: Add the table**

In `api/database.py`, inside `init_system_db`, add alongside the existing `CREATE TABLE IF NOT EXISTS` statements:

```python
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS scheduled_jobs (
            job_name     TEXT NOT NULL,
            slug         TEXT NOT NULL,
            next_due_at  TEXT NOT NULL,
            last_run_at  TEXT,
            status       TEXT NOT NULL DEFAULT 'idle',
            last_error   TEXT NOT NULL DEFAULT '',
            PRIMARY KEY (job_name, slug)
        )
    """)
```

- [ ] **Step 4: Add the helpers**

Append to `api/database.py`:

```python
# ── Scheduled jobs ────────────────────────────────────────────────────────────

async def upsert_scheduled_job(
    conn: aiosqlite.Connection, *, job_name: str, slug: str, next_due_at: str
) -> None:
    """Register a job, leaving an existing row's schedule untouched.

    Called on every boot, so it must not reset the next due time of a job that is
    already scheduled - otherwise a restart would postpone every job.
    """
    await conn.execute(
        "INSERT INTO scheduled_jobs (job_name, slug, next_due_at) VALUES (?,?,?) "
        "ON CONFLICT(job_name, slug) DO NOTHING",
        (job_name, slug, next_due_at),
    )
    await conn.commit()


async def fetch_due_jobs(conn: aiosqlite.Connection, *, now_iso: str) -> list[dict]:
    """Jobs whose next_due_at has passed and which are not already running."""
    async with conn.execute(
        "SELECT * FROM scheduled_jobs WHERE next_due_at <= ? AND status != 'running' "
        "ORDER BY next_due_at",
        (now_iso,),
    ) as cur:
        return [dict(row) for row in await cur.fetchall()]


async def mark_job_running(
    conn: aiosqlite.Connection, *, job_name: str, slug: str, now_iso: str
) -> bool:
    """Claim a job. Returns False when another claim already holds it.

    The status guard in the WHERE clause is what makes the claim atomic.
    """
    cur = await conn.execute(
        "UPDATE scheduled_jobs SET status='running', last_run_at=? "
        "WHERE job_name=? AND slug=? AND status != 'running'",
        (now_iso, job_name, slug),
    )
    await conn.commit()
    return cur.rowcount > 0


async def mark_job_finished(
    conn: aiosqlite.Connection, *, job_name: str, slug: str, status: str,
    next_due_at: str, last_error: str = "",
) -> None:
    await conn.execute(
        "UPDATE scheduled_jobs SET status=?, next_due_at=?, last_error=? "
        "WHERE job_name=? AND slug=?",
        (status, next_due_at, last_error, job_name, slug),
    )
    await conn.commit()
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `./venv/bin/pytest tests/test_scheduled_jobs_table.py -v`
Expected: PASS (7 passed)

- [ ] **Step 6: Commit**

```bash
git add api/database.py tests/test_scheduled_jobs_table.py
git commit -m "feat: add the scheduled_jobs table and its helpers"
```

---

### Task 4: The scheduler

**Files:**
- Create: `api/services/scheduler_service.py`
- Test: `tests/test_scheduler_service.py`

**Interfaces:**
- Consumes: `upsert_scheduled_job`, `fetch_due_jobs`, `mark_job_running`, `mark_job_finished`, `get_system_connection`
- Produces:
  - `JOB_REGISTRY: dict[str, Callable[[str], Awaitable[None]]]`
  - `def next_due_at(after: datetime, hour: int = REPORT_HOUR) -> str`
  - `async def run_due_jobs(now: datetime | None = None) -> int` - returns how many ran
  - `async def scheduler_loop(stop_event: asyncio.Event) -> None`
  - `TICK_SECONDS = 900`, `REPORT_HOUR = 17`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_scheduler_service.py
"""Selection, claiming and rescheduling. The clock itself is passed in, so these
tests never wait on real time."""
from datetime import datetime
from unittest.mock import AsyncMock, patch

import pytest

from api.database import get_system_connection, upsert_scheduled_job


@pytest.mark.asyncio
async def test_next_due_at_is_todays_17_00_when_earlier():
    from api.services.scheduler_service import next_due_at
    assert next_due_at(datetime(2026, 7, 28, 9, 0, 0)) == "2026-07-28T17:00:00"


@pytest.mark.asyncio
async def test_next_due_at_rolls_to_tomorrow_when_past_17_00():
    from api.services.scheduler_service import next_due_at
    assert next_due_at(datetime(2026, 7, 28, 17, 30, 0)) == "2026-07-29T17:00:00"


@pytest.mark.asyncio
async def test_run_due_jobs_runs_an_overdue_job_once():
    from api.services import scheduler_service as svc

    ran = AsyncMock()
    async with get_system_connection() as conn:
        await upsert_scheduled_job(conn, job_name="jr_one", slug="s1",
                                   next_due_at="2020-01-01T17:00:00")

    with patch.dict(svc.JOB_REGISTRY, {"jr_one": ran}, clear=False):
        count = await svc.run_due_jobs(now=datetime(2026, 7, 28, 9, 0, 0))

    assert count >= 1
    ran.assert_awaited_once_with("s1")


@pytest.mark.asyncio
async def test_run_due_jobs_does_not_backfill():
    """A week of missed days produces one run, not seven."""
    from api.services import scheduler_service as svc

    ran = AsyncMock()
    async with get_system_connection() as conn:
        await upsert_scheduled_job(conn, job_name="jr_nb", slug="s2",
                                   next_due_at="2020-01-01T17:00:00")

    with patch.dict(svc.JOB_REGISTRY, {"jr_nb": ran}, clear=False):
        await svc.run_due_jobs(now=datetime(2026, 7, 28, 9, 0, 0))
        await svc.run_due_jobs(now=datetime(2026, 7, 28, 9, 5, 0))

    assert ran.await_count == 1


@pytest.mark.asyncio
async def test_a_failing_job_records_the_error_and_reschedules():
    from api.services import scheduler_service as svc

    boom = AsyncMock(side_effect=RuntimeError("kaboom"))
    async with get_system_connection() as conn:
        await upsert_scheduled_job(conn, job_name="jr_fail", slug="s3",
                                   next_due_at="2020-01-01T17:00:00")

    with patch.dict(svc.JOB_REGISTRY, {"jr_fail": boom}, clear=False):
        await svc.run_due_jobs(now=datetime(2026, 7, 28, 9, 0, 0))

    async with get_system_connection() as conn:
        async with conn.execute(
            "SELECT status, last_error, next_due_at FROM scheduled_jobs "
            "WHERE job_name=? AND slug=?", ("jr_fail", "s3"),
        ) as cur:
            row = await cur.fetchone()

    assert row["status"] == "failed"
    assert "kaboom" in row["last_error"]
    assert row["next_due_at"] > "2026-07-28"


@pytest.mark.asyncio
async def test_an_unknown_job_name_is_skipped_not_fatal():
    """A row for a job that no longer exists in code must not stop the tick."""
    from api.services import scheduler_service as svc

    async with get_system_connection() as conn:
        await upsert_scheduled_job(conn, job_name="jr_gone", slug="s4",
                                   next_due_at="2020-01-01T17:00:00")

    count = await svc.run_due_jobs(now=datetime(2026, 7, 28, 9, 0, 0))
    assert count == 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `./venv/bin/pytest tests/test_scheduler_service.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'api.services.scheduler_service'`

- [ ] **Step 3: Write the implementation**

```python
# api/services/scheduler_service.py
"""The platform's clock.

Job state lives in the database rather than in memory, so a restart can see what
is overdue and run it. An external scheduler cannot do that: if the machine is
asleep when a cron fires, the tick is simply lost and nothing knows.
"""
import asyncio
import logging
from datetime import datetime, timedelta
from typing import Awaitable, Callable

from api.database import (
    fetch_due_jobs,
    get_system_connection,
    mark_job_finished,
    mark_job_running,
)

logger = logging.getLogger(__name__)

TICK_SECONDS = 900          # 15 minutes - a 17:00 job runs by 17:15
REPORT_HOUR = 17            # server local time

# job_name -> coroutine taking the project slug. Populated by the job modules.
JOB_REGISTRY: dict[str, Callable[[str], Awaitable[None]]] = {}


def next_due_at(after: datetime, hour: int = REPORT_HOUR) -> str:
    """The next occurrence of `hour`:00 strictly after `after`.

    Deliberately returns a single next occurrence rather than catching up on every
    missed day: a week of downtime should produce one report, not seven.
    """
    candidate = after.replace(hour=hour, minute=0, second=0, microsecond=0)
    if candidate <= after:
        candidate += timedelta(days=1)
    return candidate.isoformat(timespec="seconds")


async def run_due_jobs(now: datetime | None = None) -> int:
    """Run every job whose next_due_at has passed. Returns how many ran."""
    now = now or datetime.now()
    now_iso = now.isoformat(timespec="seconds")
    ran = 0

    async with get_system_connection() as conn:
        due = await fetch_due_jobs(conn, now_iso=now_iso)

    for job in due:
        name, slug = job["job_name"], job["slug"]
        handler = JOB_REGISTRY.get(name)
        if handler is None:
            logger.warning("scheduler: no handler registered for job %r - skipping", name)
            continue

        async with get_system_connection() as conn:
            claimed = await mark_job_running(conn, job_name=name, slug=slug, now_iso=now_iso)
        if not claimed:
            continue

        status, error = "ok", ""
        try:
            await handler(slug)
            ran += 1
        except Exception as exc:
            status, error = "failed", str(exc)
            logger.exception("scheduler: job %r failed for %s", name, slug)

        async with get_system_connection() as conn:
            await mark_job_finished(
                conn, job_name=name, slug=slug, status=status,
                next_due_at=next_due_at(now), last_error=error,
            )

    return ran


async def scheduler_loop(stop_event: asyncio.Event) -> None:
    """Run due jobs on boot, then every tick until asked to stop.

    Every exception is swallowed and logged: the scheduler must never be able to
    take the application down with it.
    """
    while not stop_event.is_set():
        try:
            await run_due_jobs()
        except Exception:
            logger.exception("scheduler: tick failed")
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=TICK_SECONDS)
        except asyncio.TimeoutError:
            pass
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `./venv/bin/pytest tests/test_scheduler_service.py -v`
Expected: PASS (6 passed)

- [ ] **Step 5: Commit**

```bash
git add api/services/scheduler_service.py tests/test_scheduler_service.py
git commit -m "feat: add the scheduler - due selection, claiming and rescheduling"
```

---

### Task 5: Change detection

**Files:**
- Create: `api/services/report_diff_service.py`
- Test: `tests/test_report_diff_service.py`

**Interfaces:**
- Consumes: nothing
- Produces: `def diff_reports(previous: dict | None, current: dict) -> dict` returning
  `{"is_first_report": bool, "new_risks": list[str], "resolved_risks": list[str], "new_issues": list[str], "resolved_issues": list[str], "milestone_changes": list[dict], "summary": str}`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_report_diff_service.py
"""'Flag any new risks' needs memory. This compares today's derived report with
the last stored one, keyed on the title field that identifies a risk."""
from api.services.report_diff_service import diff_reports


def _report(risks=(), issues=(), milestones=()):
    return {
        "risks": [{"severity": "high", "title": t} for t in risks],
        "issues": [{"severity": "medium", "title": t} for t in issues],
        "milestones": list(milestones),
    }


def test_first_report_reports_no_changes():
    """Otherwise every existing risk would be announced as new on day one."""
    d = diff_reports(None, _report(risks=["A", "B"]))
    assert d["is_first_report"] is True
    assert d["new_risks"] == []
    assert d["resolved_risks"] == []


def test_a_risk_in_both_reports_is_not_new():
    d = diff_reports(_report(risks=["A"]), _report(risks=["A"]))
    assert d["new_risks"] == []
    assert d["resolved_risks"] == []


def test_a_risk_only_in_the_current_report_is_new():
    d = diff_reports(_report(risks=["A"]), _report(risks=["A", "B"]))
    assert d["new_risks"] == ["B"]


def test_a_risk_that_has_gone_is_resolved():
    d = diff_reports(_report(risks=["A", "B"]), _report(risks=["A"]))
    assert d["resolved_risks"] == ["B"]


def test_issues_are_tracked_separately_from_risks():
    d = diff_reports(_report(issues=["X"]), _report(issues=["X", "Y"]))
    assert d["new_issues"] == ["Y"]
    assert d["new_risks"] == []


def test_milestone_rag_changes_are_reported():
    prev = {"risks": [], "issues": [],
            "milestones": [{"id": 1, "name": "Discovery", "rag": "green"}]}
    curr = {"risks": [], "issues": [],
            "milestones": [{"id": 1, "name": "Discovery", "rag": "amber"}]}
    d = diff_reports(prev, curr)
    assert d["milestone_changes"] == [
        {"name": "Discovery", "from": "green", "to": "amber"}
    ]


def test_summary_reads_as_prose():
    d = diff_reports(_report(risks=["A"]), _report(risks=["A", "B"], issues=["X"]))
    assert "1 new risk" in d["summary"]
    assert "1 new issue" in d["summary"]


def test_summary_says_nothing_changed_when_nothing_did():
    d = diff_reports(_report(risks=["A"]), _report(risks=["A"]))
    assert "No change" in d["summary"]


def test_missing_keys_are_tolerated():
    """A snapshot written by an older version may not have every key."""
    d = diff_reports({}, {})
    assert d["new_risks"] == []
    assert d["summary"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `./venv/bin/pytest tests/test_report_diff_service.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'api.services.report_diff_service'`

- [ ] **Step 3: Write the implementation**

```python
# api/services/report_diff_service.py
"""Compares two report snapshots so Pamela can say what changed.

Risks and issues are derived fresh on every report and have no stable id, so
`title` is the identity - it is the field the derivation uses to describe a risk.
"""


def _titles(report: dict | None, key: str) -> list[str]:
    if not report:
        return []
    return [r.get("title", "") for r in (report.get(key) or []) if r.get("title")]


def _milestone_rag(report: dict | None) -> dict:
    if not report:
        return {}
    out = {}
    for m in report.get("milestones") or []:
        name = m.get("name")
        if name:
            out[name] = m.get("rag")
    return out


def diff_reports(previous: dict | None, current: dict) -> dict:
    """Describe what changed between two reports.

    A first report has nothing to compare against and reports no changes, rather
    than announcing every existing risk as new.
    """
    is_first = previous is None

    prev_risks, curr_risks = set(_titles(previous, "risks")), set(_titles(current, "risks"))
    prev_issues, curr_issues = set(_titles(previous, "issues")), set(_titles(current, "issues"))

    new_risks = [] if is_first else sorted(curr_risks - prev_risks)
    resolved_risks = [] if is_first else sorted(prev_risks - curr_risks)
    new_issues = [] if is_first else sorted(curr_issues - prev_issues)
    resolved_issues = [] if is_first else sorted(prev_issues - curr_issues)

    milestone_changes = []
    if not is_first:
        prev_rag, curr_rag = _milestone_rag(previous), _milestone_rag(current)
        for name, rag in curr_rag.items():
            if name in prev_rag and prev_rag[name] != rag:
                milestone_changes.append({"name": name, "from": prev_rag[name], "to": rag})

    def _plural(n: int, word: str) -> str:
        return f"{n} {word}{'' if n == 1 else 's'}"

    if is_first:
        summary = "First report for this project - no previous position to compare against."
    else:
        parts = []
        if new_risks:
            parts.append(_plural(len(new_risks), "new risk"))
        if new_issues:
            parts.append(_plural(len(new_issues), "new issue"))
        if resolved_risks:
            parts.append(_plural(len(resolved_risks), "risk") + " resolved")
        if resolved_issues:
            parts.append(_plural(len(resolved_issues), "issue") + " resolved")
        if milestone_changes:
            parts.append(_plural(len(milestone_changes), "milestone") + " changed status")
        summary = ", ".join(parts) if parts else "No change since the previous report."

    return {
        "is_first_report": is_first,
        "new_risks": new_risks,
        "resolved_risks": resolved_risks,
        "new_issues": new_issues,
        "resolved_issues": resolved_issues,
        "milestone_changes": milestone_changes,
        "summary": summary,
    }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `./venv/bin/pytest tests/test_report_diff_service.py -v`
Expected: PASS (9 passed)

- [ ] **Step 5: Commit**

```bash
git add api/services/report_diff_service.py tests/test_report_diff_service.py
git commit -m "feat: add report change detection"
```

---

### Task 6: The daily report job

**Files:**
- Create: `api/services/pam_report_job.py`
- Test: `tests/test_pam_report_job.py`

**Interfaces:**
- Consumes: `build_pam_report(slug)`, `diff_reports(previous, current)`, `JOB_REGISTRY`, `insert_agent_output`, `fetch_stakeholders`, `fetch_project`, `get_connection`
- Produces: `JOB_NAME = "pam_daily_report"`; `async def run_pam_daily_report(slug: str) -> None`; `def resolve_recipients(stakeholders: list[dict], dev_mode: bool) -> tuple[list[str], list[str]]` returning `(actual_recipients, intended_recipients)`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_pam_report_job.py
"""The job: compute, store for audit, diff against yesterday, notify."""
import json
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from api.services.pam_report_job import JOB_NAME, resolve_recipients

SLUG = "pam-job-test"


def _sh(name, email, *, reviewer=False, approver=False):
    return {"name": name, "email": email,
            "is_reviewer": int(reviewer), "is_approver": int(approver)}


def test_recipients_are_reviewers_and_approvers_only():
    people = [
        _sh("Rev", "rev@example.test", reviewer=True),
        _sh("App", "app@example.test", approver=True),
        _sh("Both", "both@example.test", reviewer=True, approver=True),
        _sh("Neither", "none@example.test"),
    ]
    actual, intended = resolve_recipients(people, dev_mode=False)
    assert sorted(actual) == ["app@example.test", "both@example.test", "rev@example.test"]
    assert sorted(intended) == sorted(actual)


def test_someone_flagged_both_appears_once():
    """The flags are independent, so a person holding both must not be emailed twice."""
    people = [_sh("Both", "both@example.test", reviewer=True, approver=True)]
    actual, _ = resolve_recipients(people, dev_mode=False)
    assert actual == ["both@example.test"]


def test_dev_mode_redirects_but_still_reports_the_intended_list():
    people = [_sh("Rev", "rev@example.test", reviewer=True)]
    actual, intended = resolve_recipients(people, dev_mode=True)
    assert actual == ["Patrick@FutureEdge.consulting"]
    assert intended == ["rev@example.test"]


def test_stakeholders_without_an_email_are_skipped():
    people = [_sh("NoMail", "", reviewer=True), _sh("Rev", "rev@example.test", reviewer=True)]
    actual, _ = resolve_recipients(people, dev_mode=False)
    assert actual == ["rev@example.test"]


def test_dev_mode_sends_nowhere_when_there_are_no_eligible_stakeholders():
    """Redirecting an empty list must not invent a recipient."""
    actual, intended = resolve_recipients([_sh("Nobody", "a@example.test")], dev_mode=True)
    assert actual == []
    assert intended == []


@pytest.mark.asyncio
async def test_job_stores_the_report_as_a_current_versioned_output(client):
    await client.post("/projects", json={
        "client_slug": SLUG, "llm_mode": "standard", "sector": "rail",
    })
    from api.services.pam_report_job import run_pam_daily_report

    with patch("api.services.pam_report_job._send_email", new_callable=AsyncMock):
        await run_pam_daily_report(SLUG)

    resp = await client.get(f"/projects/{SLUG}/outputs")
    reports = [o for o in resp.json()
               if o["agent_name"] == "PAM" and o["output_type"] == "pam_report"]
    assert len(reports) == 1
    assert reports[0]["is_current"] is True


@pytest.mark.asyncio
async def test_second_run_supersedes_the_first(client):
    """insert_agent_output does not manage is_current - the job must."""
    await client.post("/projects", json={
        "client_slug": "pam-job-super", "llm_mode": "standard", "sector": "rail",
    })
    from api.services.pam_report_job import run_pam_daily_report

    with patch("api.services.pam_report_job._send_email", new_callable=AsyncMock):
        await run_pam_daily_report("pam-job-super")
        await run_pam_daily_report("pam-job-super")

    resp = await client.get("/projects/pam-job-super/outputs")
    reports = [o for o in resp.json()
               if o["agent_name"] == "PAM" and o["output_type"] == "pam_report"]
    current = [r for r in reports if r["is_current"]]
    assert len(reports) == 2
    assert len(current) == 1
    assert current[0]["version"] == 2


@pytest.mark.asyncio
async def test_first_run_reports_no_changes(client):
    await client.post("/projects", json={
        "client_slug": "pam-job-first", "llm_mode": "standard", "sector": "rail",
    })
    from api.services.pam_report_job import run_pam_daily_report

    with patch("api.services.pam_report_job._send_email", new_callable=AsyncMock):
        await run_pam_daily_report("pam-job-first")

    from api.config import get_settings
    outputs = Path(get_settings().projects_dir) / "pam-job-first" / "outputs"
    written = sorted(outputs.glob("pam_report*.json"))
    stored = json.loads(written[-1].read_text())
    assert stored["change_summary"]["is_first_report"] is True


@pytest.mark.asyncio
async def test_email_failure_does_not_lose_the_report(client):
    """The audit trail matters more than the notification."""
    await client.post("/projects", json={
        "client_slug": "pam-job-mail", "llm_mode": "standard", "sector": "rail",
    })
    from api.services.pam_report_job import run_pam_daily_report

    with patch("api.services.pam_report_job._send_email",
               new_callable=AsyncMock, side_effect=RuntimeError("resend down")):
        await run_pam_daily_report("pam-job-mail")

    resp = await client.get("/projects/pam-job-mail/outputs")
    assert any(o["output_type"] == "pam_report" for o in resp.json())


@pytest.mark.asyncio
async def test_job_is_registered_with_the_scheduler():
    from api.services import pam_report_job  # noqa: F401 - import registers it
    from api.services.scheduler_service import JOB_REGISTRY
    assert JOB_NAME in JOB_REGISTRY
```

- [ ] **Step 2: Run test to verify it fails**

Run: `./venv/bin/pytest tests/test_pam_report_job.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'api.services.pam_report_job'`

- [ ] **Step 3: Write the implementation**

```python
# api/services/pam_report_job.py
"""Pamela's daily status report.

Computes the report from live state using the same derivation the endpoint uses,
compares it with the previous stored report, records it as a versioned artefact
for the audit trail, and emails a link to the people who review it.
"""
import json
import logging
from datetime import datetime
from pathlib import Path

import httpx

from api.config import get_settings
from api.database import (
    fetch_project,
    fetch_stakeholders,
    get_connection,
    insert_agent_output,
)
from api.services.pam_report_service import build_pam_report
from api.services.report_diff_service import diff_reports
from api.services.scheduler_service import JOB_REGISTRY

logger = logging.getLogger(__name__)

JOB_NAME = "pam_daily_report"
OUTPUT_TYPE = "pam_report"
DEV_MODE_ADDRESS = "Patrick@FutureEdge.consulting"
# The multi-valued engagement-role columns, not project_role: one person can be
# both a recipient and a reviewer, which a single-select role cannot express.
REVIEW_FLAGS = ("is_reviewer", "is_approver")


def resolve_recipients(stakeholders: list[dict], dev_mode: bool) -> tuple[list[str], list[str]]:
    """Return (actual, intended) email lists.

    In dev mode everything is redirected to one address, but the intended list is
    still computed so the message can say who would have received it. An empty
    intended list stays empty - redirecting nothing must not invent a recipient.
    """
    intended = [
        s["email"] for s in stakeholders
        if any(s.get(flag) for flag in REVIEW_FLAGS) and (s.get("email") or "").strip()
    ]
    if not intended:
        return [], []
    return ([DEV_MODE_ADDRESS] if dev_mode else list(intended)), intended


async def _previous_report(conn, project_id: int) -> dict | None:
    """The most recent stored report, or None when this is the first."""
    async with conn.execute(
        "SELECT file_path FROM agent_outputs WHERE project_id=? AND agent_name='PAM' "
        "AND output_type=? ORDER BY version DESC LIMIT 1",
        (project_id, OUTPUT_TYPE),
    ) as cur:
        row = await cur.fetchone()
    if not row:
        return None
    try:
        return json.loads(Path(row["file_path"]).read_text())
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("pam report job: previous report unreadable (%s) - treating as first", exc)
        return None


async def _next_version(conn, project_id: int) -> int:
    async with conn.execute(
        "SELECT MAX(version) FROM agent_outputs WHERE project_id=? AND agent_name='PAM' "
        "AND output_type=?",
        (project_id, OUTPUT_TYPE),
    ) as cur:
        return ((await cur.fetchone())[0] or 0) + 1


async def _send_email(to: list[str], subject: str, body: str) -> None:
    """Send a plain-text message through Resend. Raises on failure."""
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


def _compose_body(slug: str, report: dict, change: dict, intended: list[str], dev_mode: bool) -> str:
    settings = get_settings()
    link = f"{settings.public_url.rstrip('/')}/dashboard/{slug}/report"
    lines = [
        f"Status report for {slug} - {datetime.now().strftime('%d %B %Y')}",
        "",
        f"Overall health: {report.get('overall_health', 'unknown')}",
        report.get("health_summary", ""),
        "",
        f"Changes since the last report: {change['summary']}",
    ]
    for label, key in [("New risks", "new_risks"), ("New issues", "new_issues")]:
        if change.get(key):
            lines.append("")
            lines.append(f"{label}:")
            lines.extend(f"  - {t}" for t in change[key])
    lines += ["", f"Read the full report: {link}"]
    if dev_mode:
        lines += [
            "",
            "-- dev mode --",
            "This project has dev_mode enabled, so this message was sent only to you.",
            "Intended recipients: " + (", ".join(intended) or "none"),
        ]
    return "\n".join(lines)


async def run_pam_daily_report(slug: str) -> None:
    """Generate, store and send Pamela's report for one project."""
    report = await build_pam_report(slug)

    async with get_connection(slug) as conn:
        project = await fetch_project(conn, slug=slug)
        if not project:
            logger.warning("pam report job: project %s not found - skipping", slug)
            return
        project_id = project["id"]
        config = json.loads(project.get("config_json") or "{}")
        dev_mode = bool(config.get("dev_mode", True))

        previous = await _previous_report(conn, project_id)
        change = diff_reports(previous, report)
        report["change_summary"] = change

        version = await _next_version(conn, project_id)
        outputs_dir = Path(get_settings().projects_dir) / slug / "outputs"
        outputs_dir.mkdir(parents=True, exist_ok=True)
        path = outputs_dir / f"{OUTPUT_TYPE}_v{version}.json"
        path.write_text(json.dumps(report, indent=2))

        # insert_agent_output does not manage is_current, unlike the sync helper
        # the crew tools use. Supersede explicitly or every report looks stale.
        await conn.execute(
            "UPDATE agent_outputs SET is_current=0 WHERE project_id=? AND agent_name='PAM' "
            "AND output_type=?",
            (project_id, OUTPUT_TYPE),
        )
        output_id = await insert_agent_output(
            conn, project_id=project_id, agent_name="PAM",
            output_type=OUTPUT_TYPE, file_path=str(path), version=version,
        )
        await conn.execute("UPDATE agent_outputs SET is_current=1 WHERE id=?", (output_id,))
        await conn.commit()

        stakeholders = await fetch_stakeholders(conn, project_id=project_id)

    actual, intended = resolve_recipients(stakeholders, dev_mode)
    if not actual:
        logger.info("pam report job: %s has no reviewer or approver stakeholders - stored, not sent", slug)
        return

    subject = f"{slug} status report - {datetime.now().strftime('%d %b %Y')}"
    body = _compose_body(slug, report, change, intended, dev_mode)
    try:
        await _send_email(actual, subject, body)
    except Exception as exc:
        # The report is already stored. A notification failure must not lose it.
        logger.warning("pam report job: email failed for %s: %s", slug, exc)


JOB_REGISTRY[JOB_NAME] = run_pam_daily_report
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `./venv/bin/pytest tests/test_pam_report_job.py -v`
Expected: PASS (9 passed)

- [ ] **Step 5: Commit**

```bash
git add api/services/pam_report_job.py tests/test_pam_report_job.py
git commit -m "feat: add Pamela's daily report job"
```

---

### Task 7: Start the scheduler in the application lifespan

**Files:**
- Modify: `api/main.py` (`lifespan`)
- Test: `tests/test_scheduler_lifespan.py`

**Interfaces:**
- Consumes: `scheduler_loop`, `run_due_jobs`, `next_due_at`, `upsert_scheduled_job`, `JOB_NAME`
- Produces: nothing consumed by later tasks

- [ ] **Step 1: Write the failing test**

```python
# tests/test_scheduler_lifespan.py
"""Every project gets a report job registered on boot, and the scheduler task is
started and stopped cleanly with the app."""
from unittest.mock import AsyncMock, patch

import pytest


@pytest.mark.asyncio
async def test_boot_registers_a_report_job_for_each_project(client):
    await client.post("/projects", json={
        "client_slug": "sched-reg-a", "llm_mode": "standard", "sector": "rail",
    })
    from api.main import _register_scheduled_jobs
    from api.database import get_system_connection
    from api.services.pam_report_job import JOB_NAME

    await _register_scheduled_jobs()

    async with get_system_connection() as conn:
        async with conn.execute(
            "SELECT COUNT(*) FROM scheduled_jobs WHERE job_name=? AND slug=?",
            (JOB_NAME, "sched-reg-a"),
        ) as cur:
            assert (await cur.fetchone())[0] == 1


@pytest.mark.asyncio
async def test_registering_twice_does_not_duplicate_or_reschedule(client):
    """Boot must not postpone a job that is already scheduled."""
    await client.post("/projects", json={
        "client_slug": "sched-reg-b", "llm_mode": "standard", "sector": "rail",
    })
    from api.main import _register_scheduled_jobs
    from api.database import get_system_connection
    from api.services.pam_report_job import JOB_NAME

    await _register_scheduled_jobs()
    async with get_system_connection() as conn:
        async with conn.execute(
            "SELECT next_due_at FROM scheduled_jobs WHERE job_name=? AND slug=?",
            (JOB_NAME, "sched-reg-b"),
        ) as cur:
            first = (await cur.fetchone())["next_due_at"]

    await _register_scheduled_jobs()
    async with get_system_connection() as conn:
        async with conn.execute(
            "SELECT COUNT(*) n, next_due_at FROM scheduled_jobs WHERE job_name=? AND slug=?",
            (JOB_NAME, "sched-reg-b"),
        ) as cur:
            row = await cur.fetchone()

    assert row["n"] == 1
    assert row["next_due_at"] == first


@pytest.mark.asyncio
async def test_registration_failure_does_not_stop_the_app():
    """A broken scheduler must not prevent the API from starting."""
    from api.main import _register_scheduled_jobs
    # _register_scheduled_jobs imports this inside the function to avoid a circular
    # import at module load, so the patch target is the source module, not api.main.
    with patch("api.database.upsert_scheduled_job", new_callable=AsyncMock,
               side_effect=RuntimeError("db locked")):
        await _register_scheduled_jobs()   # must not raise
```

- [ ] **Step 2: Run test to verify it fails**

Run: `./venv/bin/pytest tests/test_scheduler_lifespan.py -v`
Expected: FAIL with `ImportError: cannot import name '_register_scheduled_jobs' from 'api.main'`

- [ ] **Step 3: Write the implementation**

In `api/main.py`, add above `lifespan`:

```python
async def _register_scheduled_jobs() -> None:
    """Ensure every project has a daily report job registered.

    Uses an upsert that leaves an existing schedule alone, so restarting does not
    postpone a job that is already due. Never raises: a scheduling problem must
    not stop the API from starting.
    """
    import logging
    from datetime import datetime

    from api.database import get_system_connection, upsert_scheduled_job
    from api.services.pam_report_job import JOB_NAME
    from api.services.scheduler_service import next_due_at

    log = logging.getLogger(__name__)
    try:
        settings = get_settings()
        due = next_due_at(datetime.now())
        slugs = [p.stem for p in Path(settings.database_dir).glob("*.db")
                 if p.name != "system.db"]
        async with get_system_connection() as conn:
            for slug in slugs:
                await upsert_scheduled_job(conn, job_name=JOB_NAME, slug=slug, next_due_at=due)
        log.info("scheduler: registered the daily report job for %d project(s)", len(slugs))
    except Exception:
        log.exception("scheduler: could not register jobs - continuing without them")
```

Then extend `lifespan`:

```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    Path(settings.database_dir).mkdir(parents=True, exist_ok=True)
    Path(settings.projects_dir).mkdir(parents=True, exist_ok=True)
    await _mark_stale_runs_failed(settings.database_dir)

    await _register_scheduled_jobs()
    stop_event = asyncio.Event()
    scheduler_task = asyncio.create_task(scheduler_loop(stop_event))

    yield

    stop_event.set()
    scheduler_task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await scheduler_task
```

Add the imports `asyncio`, `contextlib`, and `from api.services.scheduler_service import scheduler_loop` at the top of the file. Also `import api.services.pam_report_job  # noqa: F401` so the job registers itself in `JOB_REGISTRY`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `./venv/bin/pytest tests/test_scheduler_lifespan.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Run the whole suite**

Run: `./venv/bin/pytest -q --ignore=tests/integration`
Expected: PASS. Baseline was 490; expect roughly 529 with this plan's new tests.

- [ ] **Step 6: Commit**

```bash
git add api/main.py tests/test_scheduler_lifespan.py
git commit -m "feat: start the scheduler with the application"
```

---

## Manual verification

The tests mock the clock and the email boundary. Before considering this done, verify against the real thing:

1. Start the API: `./start.sh` (do not use `--dev`; auto-reload restarts the app and would interrupt a running job).
2. Confirm registration: `sqlite3 data/system.db "SELECT * FROM scheduled_jobs;"` - one row per project, `next_due_at` at the next 17:00.
3. Force a run without waiting for 17:00:
   ```bash
   ./venv/bin/python -c "
   import asyncio
   from api.services.pam_report_job import run_pam_daily_report
   asyncio.run(run_pam_daily_report('sp-gs-am'))"
   ```
4. Confirm the report appears in Pamela's Outputs tab, is `is_current`, and that a second run supersedes the first.
5. Confirm the email arrived at `Patrick@FutureEdge.consulting` with the dev-mode footer naming the intended recipients, and that the link opens the report.
6. Flag a stakeholder `is_reviewer` and confirm they appear in the intended list on the next run.
