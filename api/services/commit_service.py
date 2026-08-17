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
from api.services.authority_service import caller_may_approve, caller_may_contribute
from agents.graph import GRAPH

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


def _agents_of(crew_name: str) -> set[str]:
    """The agents whose current outputs a commit to this crew freezes.

    Read from the graph rather than from `_CREW_AGENT_NAMES` directly. The same object,
    today - but every consumer reaching past the graph for its own copy of the fact is how
    there came to be nine of them, and an unknown crew name answers with no agents here, so
    the wrong answer would be an empty commit that reports success.
    """
    crew = GRAPH.crews.get(crew_name)
    return set(crew.agent_ids) if crew else set()


async def caller_may_commit(slug: str, payload: dict) -> bool:
    """Whether this caller may commit in this project.

    Committing changes what the project currently says, so it is the approve gate under an
    older name. Delegating rather than re-testing "approver" in caller_roles(...) is the
    point: this was the fourth copy of the same two-line rule, and CLAUDE.md's own worked
    example of what goes wrong is two copies of a WHERE clause that had already diverged
    without anybody noticing. They had not diverged; now they cannot.
    """
    return await caller_may_approve(slug, payload)


async def caller_may_submit(slug: str, payload: dict) -> bool:
    """Whether this caller may mark a crew ready for approval.

    Wider than committing: a contributor who reviews but does not govern may submit, which
    is exactly the contribute gate. See caller_may_commit above for why this delegates.
    """
    return await caller_may_contribute(slug, payload)


async def commit_crew(
    slug: str, *, crew_name: str, committed_by: str, notes: str
) -> dict:
    """Freeze this crew's current outputs.

    This fixes the current output versions and attributes the approval; what happens
    downstream of it is the caller's business, not this function's.
    """
    agents = _agents_of(crew_name)

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
    agents = _agents_of(crew_name)
    async with get_connection(slug) as conn:
        project = await fetch_project(conn, slug=slug)
        outputs = await fetch_agent_outputs(conn, project_id=project["id"])
        output_ids = [
            o["id"] for o in outputs if o["agent_name"] in agents and o.get("is_current")
        ]
        since = await latest_commit_at(conn, crew_name=crew_name)
        return await fetch_output_changes(conn, output_ids=output_ids, since=since)
