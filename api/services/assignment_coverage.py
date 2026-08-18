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

## An assignment that is not against an active activity

`assignments` is the mapping **against active activities**, and it is what both crews are handed.
Anything else - a node the registry has marked inactive, or an id it does not hold at all - goes
to `off_chain_assignments` instead, where it is reported rather than counted or discarded.

That split is the whole of the second proportion's honesty. Counting such a row as placement made
whoever spoke *only* for a retired activity disappear from the people assigned to nothing, which
is the one figure whose job is to say **these people will not be asked anything**; and handing it
to the dispatch path had the Interview Coordinator plan a session against a node no longer in the
chain. Both were reachable on the live project, whose registry already carries three retired
nodes.

Retired and unknown are treated alike because the consequence is identical - nobody is interviewed
about either - and one rule cannot drift from itself. The distinction is still visible: an inactive
node keeps the label the registry holds for it, an unknown id falls back to showing the id.

**An absent registry is unknown, not empty.** `get_value_chain_node_index` answers `{}` both
before the mapper has run and when the current output cannot be resolved, and reading that as
"every node is retired" would unplace the whole roster and deliver no assignments at all on a
project whose mapping is perfectly good. The split is made only when there is a registry to make
it against, which is the same reasoning that keeps the uncovered proportion at 0.0 in that state.
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

    enriched = [
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

    # An assignment to a node that is not an active activity is separated out rather than
    # counted or discarded. Both halves of that matter, and the first was a real defect:
    # counting it as placement made whoever spoke only for a retired activity vanish from
    # "who is not placed" - the one number whose job is to say *these people will not be
    # asked anything* - and handing it to the dispatch path had the Interview Coordinator
    # plan a session against a node no longer in the chain. `sp-gs-am`'s registry already
    # carries three retired nodes, so neither was hypothetical.
    #
    # An absent registry is unknown, not empty. `get_value_chain_node_index` answers `{}`
    # both before the mapper has ever run and when the current output cannot be resolved,
    # and treating that as "every node is retired" would unplace the whole roster and
    # deliver no assignments at all on a project whose mapping is perfectly good. So the
    # split is only made when there is a registry to make it against - the same reasoning
    # that keeps the uncovered proportion at 0.0 rather than 1.0 in that state.
    registry_known = bool(nodes)
    assignments: list[dict] = []
    off_chain: list[dict] = []
    for a in enriched:
        on_chain = not registry_known or a["node_id"] in active_ids
        (assignments if on_chain else off_chain).append(a)

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
        "off_chain_assignments": off_chain,
        "off_chain_total": len(off_chain),
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
