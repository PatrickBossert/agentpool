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

# Crews that only PAM may dispatch, whatever the approval graph says about them.
#
# Do not delete this without reading api/services/run_service.py:147-166.
# build_and_run_crew enforces two preconditions for discovery_interviews that the
# approval graph knows nothing about: interview_method must be 'agent', and the
# crew_runs row must carry an orchestration_run_id, which only PAM's orchestration
# ever sets - insert_crew_run leaves it NULL. So an auto-started discovery_interviews
# raises "crew_run N has no orchestration_run_id" the moment it is built, flips to
# failed, and mails the approver that the crew they just approved has died. That
# would happen on every commit of stakeholder_management, on an ordinary step, with
# no way to opt out. It is reported as waiting on PAM rather than silently dropped,
# so a reviewer wondering why nothing started is told what it is actually blocked on.
# Those guards in build_and_run_crew are correct; this is the exclusion they imply.
_PAM_DISPATCHED_ONLY: frozenset[str] = frozenset({"discovery_interviews"})


async def start_ready_downstream(
    slug: str, crew_name: str, *, committed_by: str
) -> dict:
    """Start every crew directly downstream of `crew_name` that is ready to run.

    Returns a complete account of every downstream crew: `started` with its run id,
    `skipped` because it was already running, or `waiting` with the upstream crews it
    still needs. `inactive` is True when the project has not been activated, in which
    case nothing is started and the other three lists are empty - the ready crews are
    deliberately not reported as waiting, because they are not waiting on an upstream.

    A crew in `_PAM_DISPATCHED_ONLY` is never started here however ready it looks; it is
    moved into `waiting` naming PAM as what it needs.
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

        waiting = list(classified["waiting"])
        startable = []
        for crew in classified["ready"]:
            if crew in _PAM_DISPATCHED_ONLY:
                waiting.append({"crew": crew, "waiting_on": ["PAM orchestration"]})
            else:
                startable.append(crew)

        started = []
        for crew in startable:
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
        "waiting": waiting,
        "inactive": False,
    }
