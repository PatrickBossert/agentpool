# api/services/crew_graph.py
"""Which crews may run, and what they are waiting for.

The frontend has carried a CREW_DOWNSTREAM map for display since long before anything
could act on it. This is the authoritative form: upstream dependencies, because that is
what readiness is computed from. Downstream targets are derived by inversion.
"""
from __future__ import annotations

import aiosqlite

from api.database import crew_has_commit, crew_is_running

# Each crew maps to the crews that must be committed before it may run.
# Alex -> Maya -> Jordan: stakeholder_management follows assessment_design, because
# Jordan's coming role is to report which steps and roles have no interview covering
# them, which he can only do once Maya's interviews exist.
CREW_DEPENDENCIES: dict[str, list[str]] = {
    "discovery_mapping":      [],
    "assessment_design":      ["discovery_mapping"],
    "stakeholder_management": ["assessment_design"],
    "discovery_interviews":   ["assessment_design", "stakeholder_management"],
    # Value propositions come from Casey's themes. This used to also wait on `discovery`,
    # which now runs two steps later - leaving that in place would deadlock the board,
    # with every crew waiting and none ever ready.
    "value_design":           ["discovery_interviews"],
    "capabilities":           ["value_design"],
    # `discovery` - Sam and Riley - had NO dependencies at all, so it could run before the
    # interviews it is meant to follow. It enumerates requirements against initiatives,
    # which do not exist until the capability work above has produced them.
    "requirements":           ["capabilities"],
    # The roadmap needs the complexity, method and cost that requirements produces, not
    # only the initiatives above it.
    "delivery":               ["requirements"],
    "business_plan":          ["delivery"],
}


def downstream_of(crew_name: str) -> list[str]:
    """The crews a commit to this one could release."""
    return [
        crew for crew, upstreams in CREW_DEPENDENCIES.items() if crew_name in upstreams
    ]


async def readiness_report(conn: aiosqlite.Connection) -> dict[str, dict]:
    """Per crew: whether it is ready, and which upstream crews it is still waiting on.

    Ready means every upstream crew has been committed at least once. Later uncommitted
    changes upstream do not un-arm a crew: readiness was released by a commit, and that
    release stands. The next upstream commit releases the next increment.

    A single-crew `is_crew_ready` stood here until its last production caller - the
    `released` computation in commit_crew - was deleted. `classify_downstream` answers
    the same question for the crews below one crew, and this answers it for the whole
    graph; a third form of the same loop is not worth keeping alive for tests only.
    """
    committed = {
        crew: await crew_has_commit(conn, crew_name=crew) for crew in CREW_DEPENDENCIES
    }
    return {
        crew: {
            "ready": all(committed[u] for u in upstreams),
            "waiting_on": [u for u in upstreams if not committed[u]],
        }
        for crew, upstreams in CREW_DEPENDENCIES.items()
    }


async def classify_downstream(
    conn: aiosqlite.Connection, *, crew_name: str
) -> dict[str, list]:
    """Sort every crew directly downstream of this one into ready, running, or waiting.

    Readiness is a state, not a transition. `commit_crew`'s older `released` list reported
    a crew only the first time it became ready, which meant a revision approved later
    started nothing - the first pass through the pipeline ran itself and every subsequent
    change was manual. Asking "is it ready" rather than "did it just become ready" is what
    makes re-approval re-run the crew below.

    A ready crew that is already running is reported as running, never as both: the caller
    starts everything in `ready`, and two concurrent runs of one crew would both write
    versioned outputs.
    """
    ready: list[str] = []
    running: list[str] = []
    waiting: list[dict] = []

    for crew in downstream_of(crew_name):
        blocking = [
            upstream
            for upstream in CREW_DEPENDENCIES.get(crew, [])
            if not await crew_has_commit(conn, crew_name=upstream)
        ]
        if blocking:
            waiting.append({"crew": crew, "waiting_on": blocking})
        elif await crew_is_running(conn, crew_name=crew):
            running.append(crew)
        else:
            ready.append(crew)

    return {"ready": ready, "running": running, "waiting": waiting}
