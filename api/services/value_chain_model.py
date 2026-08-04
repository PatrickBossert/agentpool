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

# Stands in for a non-numeric ID part so it sorts last within its position, rather than
# raising - a malformed ID must not stop a whole project migrating or a collision message
# from being produced.
_UNORDERABLE = 10**9


def id_order(activity_id: str) -> tuple[int, ...]:
    """The ID's numeric parts, so "1.10" sorts after "1.9" rather than before it.

    Shared by this module (ordering the activities named in a collision message) and
    value_chain_migration.py (ordering activities into columns) - one implementation so the
    two never disagree about what "1.10" means relative to "1.9".
    """
    return tuple(
        int(part) if part.isdigit() else _UNORDERABLE
        for part in str(activity_id).split(".")
    )


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


# Which model array each registry level governs. An entry's level is a claim about what
# kind of thing an id names, so an id registered as an L3 cannot arrive as an activity.
_LEVEL_ARRAYS = (("L1", "segments"), ("L2", "activities"), ("L3", "tasks"))

# The L0 entity is the organisation itself. Its id is reserved: A, C, and S interview scripts
# anchor here because a regulator regulates the entity and a customer of the entity may sit in
# another company entirely, so neither has a position in any chain.
ENTITY_ID = "0"

_LEVEL_NOUN = {"L0": "entity", "L1": "segment", "L2": "activity", "L3": "task"}


def validate_entity(model: dict) -> list[str]:
    """The reserved id is held, and no value chain takes it.

    In validate_model, which gates the grid's Save, because both rules are cheap and true of
    every model. Absence is NOT checked here - see validate_has_entity.
    """
    problems: list[str] = []
    entity = model.get("entity")
    if entity is not None and entity.get("id") != ENTITY_ID:
        problems.append(
            f"the L0 entity must have id {ENTITY_ID!r}, not {entity.get('id')!r} - the id is "
            "reserved and never renumbered"
        )
    for segment in model.get("segments", []):
        if segment.get("id") == ENTITY_ID:
            problems.append(
                f"id {ENTITY_ID} is reserved for the L0 entity and cannot be a value chain - "
                "take the next unused number"
            )
    return problems


def validate_has_entity(model: dict) -> list[str]:
    """The entity is present.

    Held to the agent, not to the editor, exactly as validate_contributions_have_tasks is.
    Every model built before this rule existed lacks an entity, and refusing those in
    validate_model would refuse to save any project until its chain was rebuilt.
    """
    if model.get("entity") is None:
        return [
            'the model has no L0 entity - add {"entity": {"id": "0", "label": ..., '
            '"description": ...}} naming the organisation itself, because interview scripts '
            "for regulators, customers, and corporate services anchor to it"
        ]
    return []


def validate_against_registry(model: dict, registry: dict) -> list[str]:
    """Every way this model contradicts the registry's ID ledger.

    Pure - the caller loads the registry, because this module does no I/O. An id already in
    the ledger must still name the same thing; an id absent from it is a genuine addition
    and is allowed, so the chain can still grow. An empty ledger accepts anything, which is
    what a first run needs and what a project with no registry yet must not be blocked by.
    """
    problems: list[str] = []
    known = {
        entry.get("id"): (entry.get("level"), entry.get("label"))
        for entry in registry.get("activities", [])
    }
    if not known:
        return problems

    # The entity is checked alongside the arrays rather than beside them: it is a dict, so a
    # loop over the three arrays skips it, and it would be the one node whose id could be
    # silently redefined.
    entity = model.get("entity")
    levels: list[tuple[str, list]] = [("L0", [entity] if entity else [])]
    levels += [(level, model.get(array, [])) for level, array in _LEVEL_ARRAYS]

    for level, items in levels:
        for item in items:
            registered = known.get(item.get("id"))
            if registered is None:
                continue
            registered_level, registered_label = registered
            if registered_level != level:
                problems.append(
                    f"{_LEVEL_NOUN[level]} {item.get('id')} is registered as a "
                    f"{registered_level}, not a {level} - use an unused id for it"
                )
            # Both labels must actually be present to disagree. Live tasks carry a
            # description and no label at all, while every registry entry has one, so
            # comparing an absent label against a present one reported every task in the
            # model as renamed - 48 of 48 on the real file, against a registry written by
            # the same run. An item that states no label states nothing to contradict.
            elif registered_label and item.get("label") and item["label"] != registered_label:
                problems.append(
                    f"id {item.get('id')} already means {registered_label!r} and cannot be "
                    f"reused for {item.get('label')!r} - take the next unused number instead"
                )
    return problems


def validate_contributions_have_tasks(model: dict) -> list[str]:
    """Every contribution that decomposes into nothing.

    Per contribution, not per activity. Tasks aggregate across parties, so an activity can
    carry six of them and still leave one party's part undecomposed - 3.1 held six tasks,
    all the custodian's, while the maintainer's stated obligation to use two named systems
    had none. Nothing downstream can interview about that, schedule it, or hold anyone to it.

    Deliberately NOT part of validate_model. That gates the grid's Save, and adding a party
    creates a contribution before its tasks exist; holding the editor to this rule would
    refuse the very save that created the contribution. A person may hold an incomplete
    state while working. A deliverable may not be incomplete.
    """
    owned = {(t.get("activity_id"), t.get("party_id")) for t in model.get("tasks", [])}
    problems: list[str] = []
    for contribution in model.get("contributions", []):
        pair = (contribution.get("activity_id"), contribution.get("party_id"))
        if pair not in owned:
            problems.append(
                f"contribution {contribution_key(*[str(x) for x in pair])} has no activity "
                "of its own - describe what this party actually does as at least one "
                "numbered task, or remove the contribution"
            )
    return problems


def validate_registry_succession(current: dict, proposed: dict) -> list[str]:
    """Every way a proposed registry would break the meanings the current one records.

    validate_against_registry is only as good as the ledger it reads, and the agent writing
    the model can write the ledger too - which is how fourteen IDs were reused in one run
    while every model check passed against the registry that same run had just replaced.

    Growth is free: a new id is a new thing. Retirement is free too, as long as the meaning
    is kept - `active: false` with the same label and level. What is refused is redefining
    an id, moving it to another level, or dropping it altogether. Dropping is the worst of
    the three: the ledger forgets the meaning, and nothing then stops the number being
    handed to something else later.
    """
    problems: list[str] = []
    proposed_entries = {e.get("id"): e for e in proposed.get("activities", [])}

    for entry in current.get("activities", []):
        entry_id = entry.get("id")
        successor = proposed_entries.get(entry_id)
        if successor is None:
            problems.append(
                f"id {entry_id} ({entry.get('label')!r}) is in the registry and missing "
                "from this one - retire it with active: false rather than dropping it, so "
                "the number is never handed to anything else"
            )
            continue
        if successor.get("level") != entry.get("level"):
            problems.append(
                f"id {entry_id} is registered as a {entry.get('level')} and this makes it "
                f"a {successor.get('level')} - use an unused id for the new thing"
            )
        elif entry.get("label") and successor.get("label") != entry.get("label"):
            problems.append(
                f"id {entry_id} already means {entry.get('label')!r} and cannot be "
                f"redefined as {successor.get('label')!r} - take the next unused number"
            )
    return problems


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
    # Deliberately not derived from cell_occupants. That is keyed on (segment, party,
    # column) and answers "does one party hold this cell twice"; this is keyed on the
    # activity and answers "do this activity's parties agree where it sits". A model can
    # break either alone, and reporting one as the other sends the reader to the wrong card.
    activity_columns: dict[str, list[tuple[int, str]]] = {}
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
            activity_columns.setdefault(activity_id, []).append((column, party_id))

    # One problem per over-occupied cell, naming every activity in it. The previous form
    # appended a message each time a cell repeated, so five contributions in one cell
    # produced four identical messages that named none of the five - and the reader's next
    # action is to go and move those activities. Sorted by id_order rather than left in
    # discovery order, or as plain strings, so the list reads in a stable, predictable
    # order ("5.9" before "5.10") regardless of which contribution happened to be recorded
    # first.
    for (segment_id, party_id, column), occupants in cell_occupants.items():
        if len(occupants) > 1:
            ordered = sorted(occupants, key=id_order)
            problems.append(
                f"{len(occupants)} contributions occupy column {column} in party "
                f"{party_id}'s lane in segment {segment_id}: {', '.join(ordered)}"
            )

    # An activity is one thing, so it occupies one position in the chain and its parties'
    # contributions share that column. Offset columns between two parties on one activity
    # used to be how a handoff was expressed; a handoff is two activities, or two tasks of
    # one, and expressing it as an offset left partner cards sitting under nothing.
    # Reported once per activity naming every party and column, because the reader's next
    # action is to move one of them and a message naming neither could not be acted on.
    for activity_id, placements in activity_columns.items():
        if len({column for column, _ in placements}) > 1:
            listed = ", ".join(
                f"{party_id} at {column}" for column, party_id in sorted(placements)
            )
            problems.append(f"activity {activity_id} is split across columns: {listed}")

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

    problems.extend(validate_entity(model))

    return problems
