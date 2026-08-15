# api/services/commit_service.py
"""Committing a crew's outputs, and deciding who may.

Committing is the one act that is not a change: it does not mutate an output, it fixes
the current version and attributes it. Whichever crews a commit makes ready are started
by the caller, not from here - see api.services.autostart_service.
"""
from __future__ import annotations

import logging

from api.database import (
    crew_is_running,
    fetch_agent_outputs,
    fetch_output_changes,
    fetch_project,
    get_connection,
    insert_approval_commit,
    insert_output_change,
    latest_commit_at,
    link_commit_outputs,
)
from api.services.authority_service import caller_roles
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


async def caller_may_commit(slug: str, payload: dict) -> bool:
    """Whether this caller may commit in this project.

    Only a caller holding the approver role - read from caller_roles(slug, payload),
    the walk from JWT to user to membership to stakeholder - may commit.
    """
    roles = await caller_roles(slug, payload)
    return "approver" in roles


async def caller_may_submit(slug: str, payload: dict) -> bool:
    """Whether this caller may mark a crew ready for approval.

    Wider than committing: a contributor who reviews but does not govern may submit.
    """
    roles = await caller_roles(slug, payload)
    return bool(roles & {"reviewer", "approver"})


async def commit_crew(
    slug: str, *, crew_name: str, committed_by: str, notes: str
) -> dict:
    """Freeze this crew's current outputs.

    This fixes the current output versions and attributes the approval; what happens
    downstream of it is the caller's business, not this function's.
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

        commit_id = await insert_approval_commit(
            conn, crew_name=crew_name, committed_by=committed_by, notes=notes
        )
        await link_commit_outputs(conn, commit_id=commit_id, output_ids=output_ids)

    return {"commit_id": commit_id, "output_ids": output_ids}


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
