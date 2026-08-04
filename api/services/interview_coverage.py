# api/services/interview_coverage.py
"""Which nodes have been interviewed about, and by whom - pure, no I/O.

Coverage used to be an agent's reading of a stakeholder list, which is how "an executive
interviewed with an L0 script covers the stages below them" was ever believable. It is a query
over stored anchors: an answer names the node it was given about, and nothing infers a
position from a job title.
"""
from __future__ import annotations


def coverage(registry: dict, answers: list[dict]) -> list[dict]:
    """One row per active registry node, with the relationships that have answered about it.

    Nodes with no answers are listed with `covered: False` rather than omitted - a node absent
    from the report reads as covered, and the gaps are the point of the report.
    """
    by_node: dict[str, set[str]] = {}
    for answer in answers:
        # A blank answer records that the question was asked, not that it was answered.
        # Counting it would report a node as covered because someone opened a session.
        if not answer.get("answered"):
            continue
        node_id = answer.get("node_id")
        if node_id:
            by_node.setdefault(node_id, set()).add(answer.get("relationship") or "internal")

    return [
        {
            "node_id": entry["id"],
            "level": entry.get("level", ""),
            "label": entry.get("label", ""),
            # No inheritance in either direction. An entity-level interview says nothing about
            # any particular stage, and interviewing every process manager says nothing about
            # what the board thinks it is doing.
            "relationships": by_node.get(entry["id"], set()),
            "covered": bool(by_node.get(entry["id"])),
        }
        for entry in registry.get("activities", [])
        # A retired node reported as uncovered is a gap nobody can ever close, and it makes
        # the real gaps harder to see.
        if entry.get("active", True)
    ]
