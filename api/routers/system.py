# api/routers/system.py
"""System liveness.

The dashboard polls this to decide whether the idle agents should breathe. It
reports whether the scheduler loop is cycling - not whether the jobs it runs
succeed, which is a separate signal.
"""
from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends

from api.auth import require_any_auth
from api.database import fetch_scheduler_heartbeat, get_system_connection

router = APIRouter(prefix="/system", tags=["system"])

# Two and a half ticks - tolerant of one missed pass, and still fast enough that a
# stopped clock becomes visible within a few minutes.
STALE_AFTER_SECONDS = 150


@router.get("/heartbeat")
async def get_heartbeat(payload: dict = Depends(require_any_auth)) -> dict:
    """Whether the scheduler loop is cycling.

    `alive` is decided here rather than in the browser so that a client with a
    skewed system clock cannot report a healthy server as dead, or the reverse.
    """
    async with get_system_connection() as conn:
        last_tick_at = await fetch_scheduler_heartbeat(conn)

    if last_tick_at is None:
        return {"last_tick_at": None, "seconds_since": None, "alive": False}

    seconds_since = int(
        (datetime.now() - datetime.fromisoformat(last_tick_at)).total_seconds()
    )
    return {
        "last_tick_at": last_tick_at,
        "seconds_since": seconds_since,
        "alive": seconds_since <= STALE_AFTER_SECONDS,
    }
