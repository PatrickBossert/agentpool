# tests/test_scheduler_lifespan.py
"""Every project gets a report job registered on boot, and the scheduler task is
started and stopped cleanly with the app."""
import shutil
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from api.config import get_settings

_SLUGS = ("sched-reg-a", "sched-reg-b")


@pytest.fixture(autouse=True)
def clean():
    """Remove this file's project databases and directories before and after
    each test. Without this a leaked sched-reg-* db/project persists on disk
    across runs and this file relies on test_projects_list.py's blanket *.db
    cleanup happening to run afterwards (alphabetical ordering) to tidy up -
    the same fragile-by-accident exposure test_pam_report_job.py had."""
    settings = get_settings()
    for slug in _SLUGS:
        db_path = Path(settings.database_dir) / f"{slug}.db"
        proj_dir = Path(settings.projects_dir) / slug
        db_path.unlink(missing_ok=True)
        if proj_dir.exists():
            shutil.rmtree(proj_dir)
    yield
    for slug in _SLUGS:
        db_path = Path(settings.database_dir) / f"{slug}.db"
        proj_dir = Path(settings.projects_dir) / slug
        db_path.unlink(missing_ok=True)
        if proj_dir.exists():
            shutil.rmtree(proj_dir)


@pytest.mark.asyncio
async def test_boot_registers_a_report_job_for_each_project(client):
    await client.post("/projects", json={
        "client_slug": "sched-reg-a", "llm_mode": "standard", "sector": "rail",
        "approver_name": "Approver Fixture", "approver_email": "approver@fixture.test",})
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
        "approver_name": "Approver Fixture", "approver_email": "approver@fixture.test",})
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


@pytest.mark.asyncio
async def test_an_unreadable_registry_at_boot_does_not_stop_the_app():
    """The registry read in `lifespan` was added without a `try`, where the glob it replaced
    could not fail and `_register_scheduled_jobs` beside it already wraps its own.

    A locked `system.db` is a transient condition - another process mid-write, a stale lock -
    and it must cost this boot its two housekeeping sweeps, not the deployment. Driven through
    `lifespan` itself rather than asserted about the source, because the property is that the
    app comes up.
    """
    from fastapi import FastAPI

    from api.main import lifespan

    with patch("api.database.get_system_connection", side_effect=RuntimeError("locked")):
        with patch("api.main._register_scheduled_jobs", new=AsyncMock()):
            with patch("api.main.scheduler_loop", new=AsyncMock()):
                async with lifespan(FastAPI()):
                    pass  # reaching here IS the assertion: startup completed


@pytest.mark.asyncio
async def test_the_dropped_job_warning_names_the_backfill_rather_than_guessing():
    """It used to tell the operator these "are usually database files in data/ that are
    backups". A project created before registration existed looks identical and silently
    loses its daily report - `vc-sort-check.db` is such a file on this deployment - so the
    sentence sent somebody looking for a stray file instead of a missing row.
    """
    import inspect

    import api.main as main
    src = inspect.getsource(main._register_scheduled_jobs)
    assert "scripts/backfill_project_registry.py" in src
    assert "usually database files" not in src
