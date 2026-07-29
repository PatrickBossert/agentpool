# api/services/commit_service.py
"""Committing a crew's outputs, and deciding who may.

Committing is the one act that is not a change: it does not mutate an output, it fixes
the current version, attributes it, and releases the crews downstream.
"""
from __future__ import annotations

import logging

from api.database import (
    crew_is_running,
    fetch_agent_outputs,
    fetch_output_changes,
    fetch_project,
    fetch_stakeholders,
    fetch_user,
    get_connection,
    get_system_connection,
    insert_approval_commit,
    insert_output_change,
    latest_commit_at,
    link_commit_outputs,
)
from api.services.crew_graph import downstream_of, is_crew_ready
from api.services.run_service import _CREW_AGENT_NAMES

log = logging.getLogger(__name__)


class CrewRunInProgress(Exception):
    """Raised when a commit is attempted while the named crew has a run in flight.

    A commit freezes whichever output versions are current at that moment; taken
    mid-run it would freeze a mix of this run's outputs and the last's. The router
    translates this to 409 Conflict - the caller should retry once the run finishes,
    not treat the request as malformed.
    """

    def __init__(self, crew_name: str):
        self.crew_name = crew_name
        super().__init__(f"Crew '{crew_name}' has a run in progress - cannot commit yet")


async def _caller_matches_stakeholder_flag(
    slug: str, payload: dict, *, flags: tuple[str, ...]
) -> bool:
    """Whether this caller matches a stakeholder carrying any of the given flags.

    The intent is that only governing roles act, but nothing links a login to a
    stakeholder record: the users table is empty and every login is sysadmin. So the
    rule permits the platform operator, and otherwise matches the caller's account
    email against a stakeholder flagged with one of `flags`. Today the first branch
    always fires; the restriction becomes real when accounts exist, with no code
    change.
    """
    if payload.get("role") == "sysadmin":
        return True

    async with get_system_connection() as sys_conn:
        user = await fetch_user(sys_conn, username=payload.get("sub", ""))
    email = ((user or {}).get("email") or "").strip().lower()
    if not email:
        # A stakeholder with no email can never be matched either - the join needs
        # both sides to have one.
        return False

    async with get_connection(slug) as conn:
        project = await fetch_project(conn, slug=slug)
        if not project:
            return False
        stakeholders = await fetch_stakeholders(conn, project_id=project["id"])

    return any(
        ((s.get("email") or "").strip().lower() == email)
        and any(s.get(flag) for flag in flags)
        for s in stakeholders
    )


async def caller_may_commit(slug: str, payload: dict) -> bool:
    """Whether this caller may commit in this project.

    Only a stakeholder flagged is_approver may commit - see
    _caller_matches_stakeholder_flag for the shared lookup and its caveats.
    """
    return await _caller_matches_stakeholder_flag(slug, payload, flags=("is_approver",))


async def caller_may_submit(slug: str, payload: dict) -> bool:
    """Whether this caller may mark a crew ready for approval.

    Wider than committing: a contributor who reviews but does not govern may submit.
    The shape is otherwise identical, and carries the same caveat - the sysadmin
    branch always fires today because the users table is empty.
    """
    return await _caller_matches_stakeholder_flag(
        slug, payload, flags=("is_reviewer", "is_approver")
    )


async def commit_crew(
    slug: str, *, crew_name: str, committed_by: str, notes: str
) -> dict:
    """Freeze this crew's current outputs and report the crews it released.

    "Released" means newly ready: a crew that was already ready before this commit is
    not reported, so the caller can react to what actually changed.
    """
    agents = set(_CREW_AGENT_NAMES.get(crew_name, []))

    async with get_connection(slug) as conn:
        if await crew_is_running(conn, crew_name=crew_name):
            raise CrewRunInProgress(crew_name)

        project = await fetch_project(conn, slug=slug)
        outputs = await fetch_agent_outputs(conn, project_id=project["id"])
        output_ids = [
            o["id"]
            for o in outputs
            if o["agent_name"] in agents and o.get("is_current")
        ]

        candidates = downstream_of(crew_name)
        was_ready = {
            c: await is_crew_ready(conn, crew_name=c) for c in candidates
        }

        commit_id = await insert_approval_commit(
            conn, crew_name=crew_name, committed_by=committed_by, notes=notes
        )
        await link_commit_outputs(conn, commit_id=commit_id, output_ids=output_ids)

        released = [
            c
            for c in candidates
            if not was_ready[c] and await is_crew_ready(conn, crew_name=c)
        ]

    return {"commit_id": commit_id, "output_ids": output_ids, "released": released}


async def changes_for_crew(slug: str, *, crew_name: str) -> list[dict]:
    """The change log since this crew's last commit, newest first.

    Never committed means the whole history so far, which is correct - there is no
    later point to measure from.
    """
    agents = set(_CREW_AGENT_NAMES.get(crew_name, []))
    async with get_connection(slug) as conn:
        project = await fetch_project(conn, slug=slug)
        outputs = await fetch_agent_outputs(conn, project_id=project["id"])
        output_ids = [
            o["id"] for o in outputs if o["agent_name"] in agents and o.get("is_current")
        ]
        since = await latest_commit_at(conn, crew_name=crew_name)
        return await fetch_output_changes(conn, output_ids=output_ids, since=since)
