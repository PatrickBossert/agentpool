# api/services/value_chain_migration.py
"""Recovering the model from a Mermaid diagram and the flat registry.

The diagram carries real attribution as CSS classes with a colour scheme. Mermaid's node
ids bear no relation to registry IDs, so a node is matched to a registry entry by its
label - the one fragile step in this whole project, which is why an unmatched entry falls
back to a dominant party rather than failing or being reported for remediation. A complete,
correctable chart beats an incomplete one with a to-do list.

Pure: takes a registry dict and the Mermaid text, returns a model.
"""
from __future__ import annotations

import re

from api.services.value_chain_model import COLUMN_STEP, empty_model

# NodeId["Some label"]:::className  - the label may be quoted or bare.
_NODE = re.compile(r'\w+\s*\[\s*"?(?P<label>[^"\]]+?)"?\s*\]\s*:::\s*(?P<cls>\w+)')
# classDef name fill:#rrggbb,...
_CLASSDEF = re.compile(r"classDef\s+(?P<cls>\w+)\s+.*?fill:\s*(?P<colour>#[0-9a-fA-F]{3,8})")


def normalise_label(label: str) -> str:
    """Trimmed, case-folded, whitespace-collapsed - the form labels are matched on."""
    return re.sub(r"\s+", " ", label).strip().casefold()


def parse_mermaid_attribution(mermaid: str) -> tuple[dict[str, str], dict[str, str]]:
    """Returns (normalised label -> class name, class name -> colour)."""
    labels = {
        normalise_label(m.group("label")): m.group("cls")
        for m in _NODE.finditer(mermaid)
    }
    colours = {
        m.group("cls"): m.group("colour").lower()
        for m in _CLASSDEF.finditer(mermaid)
    }
    return labels, colours


# Stands in for a non-numeric ID part so it sorts last within its position, rather than
# raising - a malformed ID must not stop a whole project migrating.
_UNORDERABLE = 10**9


def _id_order(activity_id: str) -> tuple[int, ...]:
    """The ID's numeric parts, so "1.10" sorts after "1.9" rather than before it."""
    return tuple(
        int(part) if part.isdigit() else _UNORDERABLE
        for part in str(activity_id).split(".")
    )


def _columns_by_activity(activities: list[dict]) -> dict[str, int]:
    """Each activity's column, from its position in its segment's numeric ID order.

    The column belongs to the activity, not to a lane, and every contribution of that
    activity takes it. That is what makes the layout a readable claim rather than
    decoration: two parties contributing to one activity land in the same column, which the
    design reads as concurrent delivery, and an activity a party does not touch leaves a gap
    in that party's lane, which is what a gap means. A per-lane counter instead claims a
    partner's fifth activity happens alongside the client's first.
    """
    columns: dict[str, int] = {}
    segments = {a.get("segment_id") for a in activities}
    for segment in segments:
        in_segment = [a for a in activities if a.get("segment_id") == segment]
        for position, activity in enumerate(sorted(in_segment, key=lambda a: _id_order(a["id"]))):
            columns[activity["id"]] = (position + 1) * COLUMN_STEP
    return columns


def _dominant(counts: dict[str, int]) -> str | None:
    """The most common party, ties broken by name ascending so this is deterministic."""
    if not counts:
        return None
    best = max(counts.values())
    return sorted(p for p, n in counts.items() if n == best)[0]


def migrate(registry: dict, mermaid: str) -> dict:
    """Build the model. Idempotent: the same inputs always give the same output."""
    label_to_class, class_to_colour = parse_mermaid_attribution(mermaid)
    entries = registry.get("activities", [])

    model = empty_model()

    # Only classes that carry a colour become parties - a class used but never defined is
    # a broken diagram, not a party.
    model["parties"] = [
        {"id": cls, "label": cls, "colour": colour}
        for cls, colour in sorted(class_to_colour.items())
        if cls in set(label_to_class.values())
    ]
    known_parties = {p["id"] for p in model["parties"]}

    model["segments"] = [
        {"id": e["id"], "label": e["label"], "description": ""}
        for e in entries
        if e.get("level") == "L1"
    ]
    model["activities"] = [
        {"id": e["id"], "segment_id": e.get("parent_id"), "label": e["label"],
         "description": "", "active": bool(e.get("active", True))}
        for e in entries
        if e.get("level") == "L2"
    ]
    activity_segment = {a["id"]: a["segment_id"] for a in model["activities"]}

    l3s = [e for e in entries if e.get("level") == "L3"]

    # First pass: whatever attribution the diagram states.
    stated: dict[str, str] = {}
    for entry in l3s:
        cls = label_to_class.get(normalise_label(entry["label"]))
        if cls in known_parties:
            stated[entry["id"]] = cls

    # Counts for the fallback cascade, from stated attribution only.
    per_segment: dict[str, dict[str, int]] = {}
    project_counts: dict[str, int] = {}
    for entry in l3s:
        party = stated.get(entry["id"])
        if party is None:
            continue
        segment = activity_segment.get(entry.get("parent_id"))
        per_segment.setdefault(segment, {}).setdefault(party, 0)
        per_segment[segment][party] += 1
        project_counts[party] = project_counts.get(party, 0) + 1

    project_dominant = _dominant(project_counts)

    # Second pass: assign every task a party, recording whether it was stated or derived.
    derived_pairs: set[tuple[str, str]] = set()
    stated_pairs: set[tuple[str, str]] = set()

    for entry in l3s:
        activity_id = entry.get("parent_id")
        segment = activity_segment.get(activity_id)
        party = stated.get(entry["id"])
        was_stated = party is not None
        if party is None:
            party = _dominant(per_segment.get(segment, {})) or project_dominant
        if party is None:
            # Nothing in the project is attributed - a fresh project with no diagram to
            # recover from. Tasks are dropped rather than invented, and the agent's own
            # structured output supplies the model instead.
            continue

        model["tasks"].append({
            "id": entry["id"], "activity_id": activity_id, "party_id": party,
            "label": entry["label"], "description": "",
            "active": bool(entry.get("active", True)),
        })
        (stated_pairs if was_stated else derived_pairs).add((activity_id, party))

    # An activity with no L3 children got no task, and contributions are built from task
    # attribution - so it got no contribution either, which validate_model now rejects
    # because such an activity appears in no lane and vanishes from the grid. The cascade
    # already answers "which party, when nothing states one" for an unmatched node; a
    # childless activity is the same question with no node at all, so it takes the same
    # answer, and lands in derived_pairs because nothing stated it.
    contributed = {activity_id for activity_id, _ in stated_pairs | derived_pairs}
    for activity in model["activities"]:
        if activity["id"] in contributed:
            continue
        party = _dominant(per_segment.get(activity["segment_id"], {})) or project_dominant
        if party is not None:
            # None means nothing in the project is attributed at all - a fresh project with
            # no diagram to recover from, where the tasks were dropped for the same reason.
            derived_pairs.add((activity["id"], party))

    # Contributions are derived from task attribution, one per (activity, party) seen.
    # A pair with any stated task counts as stated - the diagram said so for part of it.
    columns = _columns_by_activity(model["activities"])
    for activity_id, party in sorted(stated_pairs | derived_pairs):
        model["contributions"].append({
            "activity_id": activity_id,
            "party_id": party,
            "column": columns[activity_id],
            "description": "",
            "attribution": "stated" if (activity_id, party) in stated_pairs else "derived",
        })

    return model
