# api/services/autostart_service.py
"""Turning an approval into the next crew running.

Called after a commit has already been recorded, never before: an approval that landed
stays landed whatever happens here. Cascade safety is structural rather than enforced -
a crew completing does not commit anything, so nothing in this module is reachable from a
run finishing, and one approval can start at most the crews directly below it.
"""
from __future__ import annotations

import asyncio

from api.database import fetch_project, get_connection, insert_crew_run
from api.services.crew_graph import classify_downstream
from api.services.run_service import dispatch_crew


async def start_ready_downstream(
    slug: str, crew_name: str, *, committed_by: str
) -> dict:
    """Start every crew directly downstream of `crew_name` that is ready to run.

    Returns a complete account of every downstream crew: `started` with its run id,
    `skipped` because it was already running, or `waiting` with the upstream crews it
    still needs. `inactive` is True when the project has not been activated, in which
    case nothing is started and the other three lists are empty - the ready crews are
    deliberately not reported as waiting, because they are not waiting on an upstream.
    """
    async with get_connection(slug) as conn:
        project = await fetch_project(conn, slug=slug)
        # A nonexistent project folds into the same branch as an inactive one. This
        # function only ever runs after a commit has already been recorded against
        # `slug`, which requires the project to exist, so `not project` is not a case
        # any caller can reach in practice - but treating it as "inactive" rather than
        # raising keeps this function total over its inputs.
        if not project or project.get("status") != "active":
            return {"started": [], "skipped": [], "waiting": [], "inactive": True}

        classified = await classify_downstream(conn, crew_name=crew_name)

        started = []
        for crew in classified["ready"]:
            run_id = await insert_crew_run(
                conn, project_id=project["id"], crew_name=crew, status="running"
            )
            started.append({"crew": crew, "run_id": run_id})

    # Dispatch outside the connection: a crew run is minutes of work, and holding the
    # project's connection open for it would block every other write to this project.
    for entry in started:
        asyncio.create_task(
            dispatch_crew(
                slug=slug,
                crew_name=entry["crew"],
                run_id=entry["run_id"],
                triggered_by=committed_by,
            )
        )

    return {
        "started": started,
        "skipped": classified["running"],
        "waiting": classified["waiting"],
        "inactive": False,
    }
