# tests/test_scheduler_heartbeat.py
"""The scheduler's liveness stamp.

One row, always id=1: "there is exactly one heartbeat" is a property of the schema
rather than of the code that writes it.
"""
import pytest
import pytest_asyncio

from api.database import (
    fetch_scheduler_heartbeat,
    get_system_connection,
    record_scheduler_heartbeat,
)


@pytest_asyncio.fixture(autouse=True)
async def clear_heartbeat():
    """Each test starts from no heartbeat, whatever ran before it."""
    async with get_system_connection() as conn:
        await conn.execute("DELETE FROM scheduler_heartbeat")
        await conn.commit()
    yield


@pytest.mark.asyncio
async def test_fetch_returns_none_before_any_tick():
    async with get_system_connection() as conn:
        assert await fetch_scheduler_heartbeat(conn) is None


@pytest.mark.asyncio
async def test_recording_then_fetching_round_trips():
    async with get_system_connection() as conn:
        await record_scheduler_heartbeat(conn, now_iso="2026-07-28T10:00:00")
        assert await fetch_scheduler_heartbeat(conn) == "2026-07-28T10:00:00"


@pytest.mark.asyncio
async def test_recording_twice_updates_rather_than_accumulating():
    """A per - minute stamp must not grow a row per minute."""
    async with get_system_connection() as conn:
        await record_scheduler_heartbeat(conn, now_iso="2026-07-28T10:00:00")
        await record_scheduler_heartbeat(conn, now_iso="2026-07-28T10:01:00")
        assert await fetch_scheduler_heartbeat(conn) == "2026-07-28T10:01:00"
        async with conn.execute("SELECT COUNT(*) AS n FROM scheduler_heartbeat") as cur:
            assert (await cur.fetchone())["n"] == 1


import asyncio
from unittest.mock import AsyncMock, patch
from datetime import datetime, timedelta


@pytest.mark.asyncio
async def test_tick_is_one_minute():
    """The heartbeat is only as good as its resolution."""
    from api.services import scheduler_service
    assert scheduler_service.TICK_SECONDS == 60


@pytest.mark.asyncio
async def test_loop_stamps_the_heartbeat_even_when_a_job_raises():
    """The heartbeat reports that the loop is cycling, not that jobs succeeded.

    A job failing every night must not make the board look dead - that is a
    different fault, and conflating them would hide both.
    """
    from api.services.scheduler_service import scheduler_loop

    stop = asyncio.Event()
    with patch(
        "api.services.scheduler_service.run_due_jobs",
        AsyncMock(side_effect=RuntimeError("boom")),
    ), patch("api.services.scheduler_service.TICK_SECONDS", 0.01):
        task = asyncio.create_task(scheduler_loop(stop))
        await asyncio.sleep(0.1)
        stop.set()
        await task

    async with get_system_connection() as conn:
        assert await fetch_scheduler_heartbeat(conn) is not None


@pytest.mark.asyncio
async def test_a_heartbeat_failure_does_not_stop_the_loop():
    """The scheduler must never be able to take the application down."""
    from api.services.scheduler_service import scheduler_loop

    stop = asyncio.Event()
    with patch(
        "api.services.scheduler_service.run_due_jobs", AsyncMock()
    ) as run, patch(
        "api.services.scheduler_service.record_scheduler_heartbeat",
        AsyncMock(side_effect=RuntimeError("disk full")),
    ), patch("api.services.scheduler_service.TICK_SECONDS", 0.01):
        task = asyncio.create_task(scheduler_loop(stop))
        await asyncio.sleep(0.1)
        stop.set()
        await task

    assert run.await_count >= 2, "the loop stopped cycling after a heartbeat failure"


@pytest.mark.asyncio
async def test_slow_job_cannot_starve_the_heartbeat():
    """The gap between stamps must be bounded by TICK_SECONDS, not by job duration.

    If the heartbeat is only stamped after run_due_jobs returns, a job that runs
    long enough pushes the loop past the staleness window even though the loop is
    perfectly healthy. Stamping before the pass too bounds the gap to
    max(job duration, TICK_SECONDS).
    """
    from api.services.scheduler_service import scheduler_loop

    job_running = asyncio.Event()
    release_job = asyncio.Event()

    async def slow_job(now=None):
        job_running.set()
        await release_job.wait()

    stop = asyncio.Event()
    with patch(
        "api.services.scheduler_service.run_due_jobs", AsyncMock(side_effect=slow_job)
    ), patch(
        "api.services.scheduler_service.record_scheduler_heartbeat", AsyncMock()
    ) as heartbeat, patch("api.services.scheduler_service.TICK_SECONDS", 0.01):
        task = asyncio.create_task(scheduler_loop(stop))
        await asyncio.wait_for(job_running.wait(), timeout=5)

        # The slow job is still in flight - release_job has not been set - so the
        # only way a stamp can already exist is if it was written before the pass.
        assert heartbeat.await_count >= 1, (
            "heartbeat was not recorded while the slow job was still running"
        )

        release_job.set()
        stop.set()
        await task


@pytest.mark.asyncio
async def test_heartbeat_endpoint_reports_not_alive_before_any_tick(client):
    resp = await client.get("/system/heartbeat")
    assert resp.status_code == 200
    body = resp.json()
    assert body == {"last_tick_at": None, "seconds_since": None, "alive": False}


@pytest.mark.asyncio
async def test_heartbeat_endpoint_reports_alive_for_a_recent_tick(client):
    recent = (datetime.now() - timedelta(seconds=140)).isoformat(timespec="seconds")
    async with get_system_connection() as conn:
        await record_scheduler_heartbeat(conn, now_iso=recent)

    body = (await client.get("/system/heartbeat")).json()
    assert body["alive"] is True
    assert body["last_tick_at"] == recent
    assert 135 <= body["seconds_since"] <= 145


@pytest.mark.asyncio
async def test_heartbeat_endpoint_reports_stale_for_an_old_tick(client):
    old = (datetime.now() - timedelta(seconds=200)).isoformat(timespec="seconds")
    async with get_system_connection() as conn:
        await record_scheduler_heartbeat(conn, now_iso=old)

    assert (await client.get("/system/heartbeat")).json()["alive"] is False


@pytest.mark.asyncio
async def test_heartbeat_endpoint_requires_authentication():
    """The dashboard is authenticated; liveness should not leak to anyone who asks."""
    from httpx import ASGITransport, AsyncClient

    from api.main import app

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as anon:
        assert (await anon.get("/system/heartbeat")).status_code in (401, 403)
