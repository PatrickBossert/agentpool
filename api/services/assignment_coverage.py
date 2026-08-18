# api/services/assignment_coverage.py
"""How much of the value chain the stakeholder mapping actually covers, and who it leaves out.

One derivation, three call sites. The Interview Coordinator is handed the mapping so he can
plan a session per assignment, the Stakeholder Manager is handed the same mapping plus the two
proportions so he can report the gaps, and Pamela reads the proportions to decide whether to
raise an issue. Three copies of the arithmetic would be three answers to one question, and the
number a human is asked to judge would depend on which page they were looking at.

## The two proportions, and what each is over

- `uncovered_proportion` - activities with **no** stakeholder, over every **active** node in the
  value chain registry. Every level counts, including the organisation node `0` and its role
  nodes `0.A` and `0.S`: those became assignable when the assignment surface started keying on
  real node ids, they carry audit and corporate-services frontline, and excluding them would
  quietly shrink the denominator by the three hardest people to place. Nodes the registry marks
  inactive are excluded - a retired activity nobody speaks for is not a gap.

- `unassigned_proportion` - stakeholders assigned to **nothing**, over the whole roster. Seeded
  rows (`stakeholders.is_synthetic`) are counted. They are ordinary rows doing ordinary work in
  a test run: the Interview Coordinator plans sessions from them and the campaign service mails
  them, so a roster figure that pretended they were absent would not describe the engagement
  anybody is actually running.

**Several stakeholders on one activity is normal and is never a mismatch.** Both proportions are
computed from distinct node ids and distinct stakeholder ids, so doubling up on an activity - the
ordinary shape for frontline work - moves neither one. Neither does 100% coverage being missing:
the number is reported, and what an acceptable gap is remains a human's judgement.

An assignment citing a node the registry does not hold counts towards nothing. It is neither
coverage of an active activity nor evidence of one, and the stakeholder on it is still assigned,
so it is left out of the first proportion and counted in the second.
"""
from __future__ import annotations

import aiosqlite

from api.database import fetch_stakeholder_assignments, fetch_stakeholders
from api.services.project_service import get_value_chain_node_index

# Past this, in either direction, Pamela raises an issue and reports the number.
#
# **A judgement, not a law.** Patrick set it at a tenth because that is roughly where a mapping
# stops looking like ordinary discovery in progress and starts looking like nobody has been
# asked. Nothing downstream breaks at 11% and nothing is guaranteed at 9%; the threshold decides
# only whether a human is shown the figure, and the figure - not a verdict - is what they judge.
# Move it if experience says otherwise, and move it here, once.
COVERAGE_MISMATCH_THRESHOLD = 0.10


def _beyond(proportion: float) -> bool:
    """Strictly past the threshold - "more than a 10% mismatch", so exactly a tenth is not one."""
    return proportion > COVERAGE_MISMATCH_THRESHOLD


async def build_assignment_coverage(
    conn: aiosqlite.Connection, *, slug: str, project_id: int
) -> dict:
    """The mapping, enriched, and the two proportions derived from it.

    `assignments` carries the label and the level of each node, resolved from the registry at
    read time rather than stored on the row - the registry is the canonical spine, and a copy on
    the assignment would go stale the next time the mapper re-emits a label.

    An empty registry gives `activities_total` 0 and an uncovered proportion of 0.0 rather than
    1.0. Before the value chain mapper has run there are no activities to cover, and reporting a
    project as wholly uncovered at that point would raise an issue against work nobody could yet
    have done.
    """
    raw_assignments = await fetch_stakeholder_assignments(conn, project_id=project_id)
    roster = await fetch_stakeholders(conn, project_id=project_id)
    stakeholder_map = {s["id"]: s for s in roster}

    nodes = get_value_chain_node_index(slug)
    active_ids = {node_id for node_id, node in nodes.items() if node["active"]}

    assignments = [
        {
            "stakeholder_id": a["stakeholder_id"],
            "name": stakeholder_map.get(a["stakeholder_id"], {}).get("name", "Unknown"),
            "job_title": stakeholder_map.get(a["stakeholder_id"], {}).get("job_title", ""),
            "node_id": a["node_id"],
            "level": nodes.get(a["node_id"], {}).get("level", ""),
            "node_label": nodes.get(a["node_id"], {}).get("label", a["node_id"]),
        }
        for a in raw_assignments
        if a["stakeholder_id"] in stakeholder_map
    ]

    covered_ids = {a["node_id"] for a in assignments} & active_ids
    uncovered_ids = sorted(active_ids - covered_ids)
    activities_total = len(active_ids)
    raw_uncovered = len(uncovered_ids) / activities_total if activities_total else 0.0

    assigned_ids = {a["stakeholder_id"] for a in assignments}
    unassigned = [
        {"id": s["id"], "name": s["name"], "job_title": s.get("job_title") or ""}
        for s in roster
        if s["id"] not in assigned_ids
    ]
    roster_total = len(roster)
    raw_unassigned = len(unassigned) / roster_total if roster_total else 0.0

    return {
        "assignments": assignments,
        "activities_total": activities_total,
        "activities_covered": len(covered_ids),
        "activities_uncovered": len(uncovered_ids),
        "uncovered_node_ids": uncovered_ids,
        "uncovered_proportion": round(raw_uncovered, 4),
        "roster_total": roster_total,
        "stakeholders_assigned": len(assigned_ids),
        "stakeholders_unassigned": len(unassigned),
        "unassigned_stakeholders": unassigned,
        "unassigned_proportion": round(raw_unassigned, 4),
        "threshold": COVERAGE_MISMATCH_THRESHOLD,
        # Two independent flags over one threshold, deliberately. A single "mismatch" boolean
        # would let a covered chain with an idle roster and an uncovered chain with a fully
        # placed roster arrive as the same fact, and the action a human takes differs entirely.
        "uncovered_beyond_threshold": _beyond(raw_uncovered),
        "unassigned_beyond_threshold": _beyond(raw_unassigned),
    }


def format_coverage_percent(proportion: float) -> str:
    """One decimal place, because a tenth of a percent is where the threshold argument happens."""
    return f"{proportion * 100:.1f}%"
