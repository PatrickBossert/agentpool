# api/services/value_chain_model.py
"""The value chain's shape.

An activity is one thing with one stable ID. Each party's part of it is a *contribution*,
which is what occupies a lane and a column, carries its own description, and owns its
tasks. That is what lets two parties be interviewed separately about the same activity.

A contribution has no ID of its own: (activity_id, party_id) is its identity. This module
is pure - no I/O, no database - so the rules can be tested without a project.
"""
from __future__ import annotations

MODEL_VERSION = 1

# Columns advance in steps so an insertion between neighbours picks an intermediate value
# rather than renumbering the lane.
COLUMN_STEP = 10

_ATTRIBUTIONS = ("stated", "derived")


def empty_model() -> dict:
    return {
        "model_version": MODEL_VERSION,
        "parties": [],
        "segments": [],
        "activities": [],
        "contributions": [],
        "tasks": [],
        "propositions": [],
        "links": [],
    }


def contribution_key(activity_id: str, party_id: str) -> str:
    """A usable key for the composite identity - for dicts and React keys, not storage."""
    return f"{activity_id}@{party_id}"


def next_column(model: dict, segment_id: str, party_id: str) -> int:
    """The next free column in one party's lane within one segment.

    Per lane, not per segment: a party joining later starts at the beginning of its own
    lane rather than after whatever another party has already done.
    """
    activity_segments = {a["id"]: a.get("segment_id") for a in model.get("activities", [])}
    columns = [
        c["column"]
        for c in model.get("contributions", [])
        if c.get("party_id") == party_id
        and activity_segments.get(c.get("activity_id")) == segment_id
        and isinstance(c.get("column"), int)
    ]
    return (max(columns) + COLUMN_STEP) if columns else COLUMN_STEP


def validate_model(model: dict) -> list[str]:
    """Every problem with this model, as readable sentences. Empty means valid.

    Returns all problems rather than raising on the first, so a caller can show a person
    everything that is wrong in one pass.
    """
    problems: list[str] = []

    party_ids = {p.get("id") for p in model.get("parties", [])}
    segment_ids = {s.get("id") for s in model.get("segments", [])}
    activity_segment = {a.get("id"): a.get("segment_id") for a in model.get("activities", [])}

    for activity in model.get("activities", []):
        if activity.get("segment_id") not in segment_ids:
            problems.append(
                f"activity {activity.get('id')} names unknown segment "
                f"{activity.get('segment_id')}"
            )

    cell_occupants: dict[tuple[str, str, int], list[str]] = {}
    contribution_ids: set[tuple[str, str]] = set()

    for contribution in model.get("contributions", []):
        activity_id = contribution.get("activity_id")
        party_id = contribution.get("party_id")
        column = contribution.get("column")

        # Each check below is independent and always runs, so a record with several
        # defects at once (say, an unknown party and an invalid attribution) reports
        # both rather than only whichever is checked first. Only the cell-overlap check
        # genuinely depends on activity, party, and column all having resolved.
        activity_known = activity_id in activity_segment
        party_known = party_id in party_ids
        column_known = isinstance(column, int)

        if not activity_known:
            problems.append(f"contribution names unknown activity {activity_id}")
        if not party_known:
            problems.append(f"contribution names unknown party {party_id}")
        if not column_known:
            problems.append(
                f"contribution {contribution_key(activity_id, party_id)} has no column"
            )
        if contribution.get("attribution") not in _ATTRIBUTIONS:
            problems.append(
                f"contribution {contribution_key(activity_id, party_id)} has attribution "
                f"{contribution.get('attribution')!r}, expected one of {_ATTRIBUTIONS}"
            )

        if activity_known and party_known:
            contribution_ids.add((activity_id, party_id))

        if activity_known and party_known and column_known:
            cell = (activity_segment[activity_id], party_id, column)
            cell_occupants.setdefault(cell, []).append(str(activity_id))

    # One problem per over-occupied cell, naming every activity in it. The previous form
    # appended a message each time a cell repeated, so five contributions in one cell
    # produced four identical messages that named none of the five - and the reader's next
    # action is to go and move those activities.
    for (segment_id, party_id, column), occupants in cell_occupants.items():
        if len(occupants) > 1:
            problems.append(
                f"{len(occupants)} contributions occupy column {column} in party "
                f"{party_id}'s lane in segment {segment_id}: {', '.join(sorted(occupants))}"
            )

    # An activity with no contribution belongs to no lane, so it disappears from the grid
    # while remaining in model["activities"] - and nothing in the UI can bring it back.
    # This became reachable when removing a party's contribution became possible.
    contributed_activity_ids = {activity_id for activity_id, _ in contribution_ids}
    for activity in model.get("activities", []):
        if activity.get("id") not in contributed_activity_ids:
            problems.append(
                f"activity {activity.get('id')} has no contribution - it would not appear "
                "in the grid and could not be recovered"
            )

    for task in model.get("tasks", []):
        pair = (task.get("activity_id"), task.get("party_id"))
        if pair not in contribution_ids:
            problems.append(
                f"task {task.get('id')} belongs to contribution "
                f"{contribution_key(*[str(x) for x in pair])}, which does not exist"
            )

    for proposition in model.get("propositions", []):
        if proposition.get("activity_id") not in activity_segment:
            problems.append(
                f"proposition {proposition.get('id')} names unknown activity "
                f"{proposition.get('activity_id')}"
            )

    for link in model.get("links", []):
        for end in ("from", "to"):
            pair = (link.get(f"{end}_activity_id"), link.get(f"{end}_party_id"))
            if pair not in contribution_ids:
                problems.append(
                    f"link {end} endpoint {contribution_key(*[str(x) for x in pair])} "
                    "does not exist"
                )

    return problems
