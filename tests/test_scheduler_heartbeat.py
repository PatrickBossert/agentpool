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
