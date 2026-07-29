# api/services/crew_graph.py
"""Which crews may run, and what they are waiting for.

The frontend has carried a CREW_DOWNSTREAM map for display since long before anything
could act on it. This is the authoritative form: upstream dependencies, because that is
what readiness is computed from. Downstream targets are derived by inversion.
"""
from __future__ import annotations

import aiosqlite

from api.database import crew_has_commit

# Each crew maps to the crews that must be committed before it may run.
# Alex -> Maya -> Jordan: stakeholder_management follows assessment_design, because
# Jordan's coming role is to report which steps and roles have no interview covering
# them, which he can only do once Maya's interviews exist.
CREW_DEPENDENCIES: dict[str, list[str]] = {
    "discovery_mapping":      [],
    "assessment_design":      ["discovery_mapping"],
    "stakeholder_management": ["assessment_design"],
    "discovery":              [],
    "discovery_interviews":   ["assessment_design", "stakeholder_management"],
    "value_design":           ["discovery", "discovery_interviews"],
    "architecture":           ["value_design"],
    "delivery":               ["architecture"],
    "business_plan":          ["delivery"],
}


def downstream_of(crew_name: str) -> list[str]:
    """The crews a commit to this one could release."""
    return [
        crew for crew, upstreams in CREW_DEPENDENCIES.items() if crew_name in upstreams
    ]


async def is_crew_ready(conn: aiosqlite.Connection, *, crew_name: str) -> bool:
    """True when every upstream crew has been committed at least once.

    Later uncommitted changes upstream do not un-arm a crew: readiness was released by
    a commit, and that release stands. The next upstream commit releases the next
    increment.
    """
    for upstream in CREW_DEPENDENCIES.get(crew_name, []):
        if not await crew_has_commit(conn, crew_name=upstream):
            return False
    return True


async def readiness_report(conn: aiosqlite.Connection) -> dict[str, dict]:
    """Per crew: whether it is ready, and which upstream crews it is still waiting on."""
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
