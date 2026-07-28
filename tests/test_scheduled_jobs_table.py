"""The scheduler's memory. Job state lives in system.db so all scheduling is
visible in one place and a restart can see what is overdue."""
import pytest

from api.database import (
    fetch_due_jobs,
    get_system_connection,
    mark_job_finished,
    mark_job_running,
    reset_stale_running_jobs,
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


@pytest.mark.asyncio
async def test_reset_stale_running_jobs_makes_a_job_due_again():
    """A job interrupted mid-run (power cut, SIGKILL, restart) is left in
    'running' forever, since fetch_due_jobs excludes that status and nothing
    else ever clears it. On boot the row must be reset to a runnable state
    without touching next_due_at, so an overdue job runs on the next tick
    rather than being postponed a day."""
    async with get_system_connection() as conn:
        await upsert_scheduled_job(conn, job_name="t_stuck", slug="p8",
                                   next_due_at="2020-01-01T17:00:00")
        await mark_job_running(conn, job_name="t_stuck", slug="p8",
                               now_iso="2020-01-02T09:00:00")

        await reset_stale_running_jobs(conn)

        due = await fetch_due_jobs(conn, now_iso="2020-01-02T09:00:00")
        async with conn.execute(
            "SELECT status, next_due_at, last_error FROM scheduled_jobs "
            "WHERE job_name=? AND slug=?", ("t_stuck", "p8"),
        ) as cur:
            row = await cur.fetchone()

    assert any(j["job_name"] == "t_stuck" and j["slug"] == "p8" for j in due)
    assert row["status"] != "running"
    assert row["next_due_at"] == "2020-01-01T17:00:00"
    assert "interrupted" in row["last_error"].lower()
