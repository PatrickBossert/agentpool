# api/services/autostart_service.py
"""Turning an approval into the next crew running.

Called after a commit has already been recorded, never before: an approval that landed
stays landed whatever happens here. Cascade safety is structural rather than enforced -
a crew completing does not commit anything, so nothing in this module is reachable from a
run finishing, and one approval can start at most the crews directly below it.
"""
from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from api.database import (
    fetch_project,
    fetch_user,
    get_connection,
    get_system_connection,
    insert_crew_run_if_not_running,
)
from api.config import get_settings, load_project_config
from api.services.crew_graph import classify_downstream
from api.services.run_service import dispatch_crew, missing_config_keys

log = logging.getLogger(__name__)

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

_PAM_REASON = (
    "Pamela starts it as part of an orchestration run, not from an approval."
)

# Config keys named for the person who has to go and set them, rather than for whoever
# reads the stack trace. A key with no entry here is reported by its own name, which is
# worse copy but never wrong.
_CONFIG_LABELS: dict[str, str] = {
    "value_stream_labels": "value streams",
    "stakeholder_groups": "stakeholder groups",
}


def _config_reason(missing: list[str]) -> str:
    labels = [_CONFIG_LABELS.get(key, key) for key in missing]
    if len(labels) > 1:
        named = f"{', '.join(labels[:-1])} and {labels[-1]}"
    else:
        named = labels[0]
    return f"It needs the project's {named} to be set first."


def _project_config(slug: str) -> dict | None:
    """This project's config.yaml, or None when it cannot be read.

    None means "not checked", not "nothing missing". A project whose config.yaml is
    unreadable has a problem no approval can diagnose - every crew in it would fail, not
    just the ones with required keys - so the start is left to proceed exactly as it did
    before, rather than reporting a specific missing setting that was never established.
    """
    try:
        return load_project_config(Path(get_settings().projects_dir) / slug)
    except Exception:
        log.warning("could not read config.yaml for %s - config checks skipped", slug)
        return None


async def _notification_address(committed_by: str) -> str | None:
    """The approver's email address, or None when the name does not resolve to one.

    `committed_by` is the JWT's `sub`, which is a **username** (api/auth.py:26), not an
    address - and it is handed to dispatch_crew as `triggered_by`, which notify_crew_failed
    puts straight into Resend's `to` list. A malformed entry there rejects the entire
    request, so a username would cost the reviewers their notification as well as the
    approver theirs. api/services/commit_service.py:60-62 already resolves `sub` this way.

    An unresolvable name is dropped rather than passed on: one person missing a notice is
    a smaller harm than everybody missing one.
    """
    if not committed_by:
        return None
    async with get_system_connection() as sys_conn:
        user = await fetch_user(sys_conn, username=committed_by)
    return ((user or {}).get("email") or "").strip() or None


async def start_ready_downstream(
    slug: str, crew_name: str, *, committed_by: str
) -> dict:
    """Start every crew directly downstream of `crew_name` that is ready to run.

    Returns a complete account of every downstream crew: `started` with its run id,
    `skipped` because it was already running, or `waiting` with the upstream crews it
    still needs. `inactive` is True when the project has not been activated, in which
    case nothing is started and the other three lists are empty - the ready crews are
    deliberately not reported as waiting, because they are not waiting on an upstream.

    A `waiting` entry carries either `waiting_on` - crew slugs, and only ever crew slugs -
    or a `reason` in prose for a blocker that is not an approval at all. Two produce a
    reason: a crew in `_PAM_DISPATCHED_ONLY`, which no approval can ever start, and one
    whose required configuration (`REQUIRED_CONFIG_KEYS` in run_service) is unset, which
    would otherwise be started and fail on the spot.

    `skipped` also absorbs a crew whose run appeared between the classification and the
    insert - insert_crew_run_if_not_running declines it, and a declined insert means the
    same thing to the reviewer as a crew that was already running when it was classified.
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
        config = _project_config(slug)
        for crew in classified["ready"]:
            if crew in _PAM_DISPATCHED_ONLY:
                waiting.append({"crew": crew, "waiting_on": [], "reason": _PAM_REASON})
                continue
            # Delivery is the milder case of the same class as discovery_interviews: it
            # cannot run without configuration the product never collects, but unlike
            # discovery_interviews it runs perfectly once that configuration exists. So
            # the precondition is checked rather than the crew excluded - a project that
            # has its value streams set still gets its Delivery crew started.
            missing = missing_config_keys(config, crew) if config is not None else []
            if missing:
                waiting.append(
                    {"crew": crew, "waiting_on": [], "reason": _config_reason(missing)}
                )
                continue
            startable.append(crew)

        started = []
        skipped = list(classified["running"])
        for crew in startable:
            run_id = await insert_crew_run_if_not_running(
                conn, project_id=project["id"], crew_name=crew
            )
            if run_id is None:
                # Another approval started this crew between classify_downstream's read
                # and this insert. The insert declines rather than duplicating the run,
                # and the crew is reported skipped for the same reason as one that was
                # already running when it was classified - it is running, and this
                # approval is not in it.
                skipped.append(crew)
                continue
            started.append({"crew": crew, "run_id": run_id})

    # Dispatch outside the connection: a crew run is minutes of work, and holding the
    # project's connection open for it would block every other write to this project.
    triggered_by = await _notification_address(committed_by) if started else None
    for entry in started:
        asyncio.create_task(
            dispatch_crew(
                slug=slug,
                crew_name=entry["crew"],
                run_id=entry["run_id"],
                triggered_by=triggered_by,
            )
        )

    return {
        "started": started,
        "skipped": skipped,
        "waiting": waiting,
        "inactive": False,
    }
