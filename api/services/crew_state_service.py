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
