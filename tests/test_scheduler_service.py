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
