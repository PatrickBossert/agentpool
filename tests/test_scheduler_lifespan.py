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
