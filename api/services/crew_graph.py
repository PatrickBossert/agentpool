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
#
# `assessment_design` and `stakeholder_management` are **parallel**: both wait on the value
# chain and nothing else, and both feed the interviews. Jordan used to be declared behind Maya,
# on the reading that he reports which steps and roles have no interview covering them - but the
# artefacts disagreed and had done since the reads were declared. He reads `value_chain_registry`,
# which only `discovery_mapping` writes; `assessment_design` writes `interview_scripts` alone,
# which he does not read. So the declared edge carried nothing while the real one - the value
# chain his coverage target is computed from - was undeclared, and the board held him back a
# whole crew for an input he never took.
#
# `discovery_interviews` waits on both of them, and only one of the two hands anything over.
# `stakeholder_management -> discovery_interviews` is a **sequencing** dependency and is meant to
# stay one: what actually connects the two is `stakeholder_assignments`, a table made by hand in
# Jordan's Setup tab and injected into both crews by the dispatch path - not an artefact either
# crew writes. Jordan does not write it. He can now read it: it is enriched and prepended to his
# task, which closed the defect where his own task told him to read it through `SQLiteStateTool`,
# a door onto `outputs/<key>.json` that could never see a table. That makes him better informed
# and moves nothing along this edge - two crews reading one table from the dispatch path is not
# one handing over to the other, and `EdgeKind` derives INFORMATION from artefacts that travel,
# which these are not. The ordering is real all the same: he invites and chases the people Avery
# then interviews. Do not invent a flow to make the arrow look busier than it is.
CREW_DEPENDENCIES: dict[str, list[str]] = {
    "discovery_mapping":      [],
    "assessment_design":      ["discovery_mapping"],
    "stakeholder_management": ["discovery_mapping"],
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
