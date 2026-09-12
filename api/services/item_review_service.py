"""Recording a review of one value chain node or one value lever.

`discovery_review_service` is the read half - "what is awaiting this agent" - and said of
itself, honestly, that it read a state only a hand-written row or a backfill could reach.
This is the write half it named: the recorder that belongs with the review surface, exactly
as `record_script_review` sits beside `ScriptReviewPanel`.

Three differences from `record_script_review`, each deliberate:

**Two item kinds, one recorder.** A node lives in `value_chain_ledger` and a lever in
`value_lever_ledger`, and the two tables differ in three column names and nothing else that
matters here. `ITEM_LEDGERS` is that difference, declared once; the review logic is written
once. Two recorders would be two copies of one rule, which on this codebase is how
`register_scripts_sync` and `scripts_awaiting_regeneration` came to hold the same condition
in two spellings and then diverge.

**`reviewed_at_version` is read off the row, never passed in.** `record_script_review` takes
an `at_version` argument and `script_reviews.py` fills it from the ledger row it has just
read - correct, and one door away from being forgotten. There are two doors here (a node one
and a lever one) and the stamp is the thing Task 3 said must reach both, so the recorder owns
it: it already selects the row to check `review_status`, so it selects `last_version` in the
same statement and stamps from that. CLAUDE.md states the general form - *when a signature
obliges every caller to restate state it does not own, the signature is the defect. Give the
writer the row, or narrow it.* A door cannot forget a parameter it does not have.

**No `edited` decision.** The script vocabulary has four; this has three. `edited` records
that a reader changed the thing in front of them, and there is nothing here to change: the
design decided levers are review-only with no manual editor, and put per-node editing of
`value_chain_model` - which has `StructureTab` and a different workflow - out of scope. A
decision no surface can produce is a decision nothing enforces, and it would arrive in
`review_status` as a state the ledger row could hold and the reviewer could never explain.
Add it here when an editor arrives, not before.
"""
from dataclasses import dataclass

import aiosqlite

# The exceptions are script_review_service's, imported rather than redeclared. Both routers
# branch on the *type* to choose 409 from 422 - the reason that module gives for making them
# distinct classes in the first place - and two classes both meaning "already approved" is
# exactly the shape where a caller catches one and silently misses the other.
from api.services.script_review_service import (  # noqa: F401  (re-exported for the router)
    AlreadyApprovedError,
    NotYetReviewedError,
)

VALID_DECISIONS = ("reviewed", "approved", "changes_requested")
VALID_RETURN_TO = ("agent", "reviewer")


@dataclass(frozen=True)
class ItemLedger:
    """Where one kind of reviewable item's ledger row lives, and what its columns are called.

    `label` is the human-readable field a reviewer identifies the item by - `label` on a node,
    `title` on a lever. The two tables were written to mirror each other everywhere the fields
    mean the same thing, so this is the whole of the difference the recorder cares about.
    """

    table: str
    id_column: str
    label_column: str


ITEM_LEDGERS: dict[str, ItemLedger] = {
    "node": ItemLedger("value_chain_ledger", "node_id", "label"),
    "lever": ItemLedger("value_lever_ledger", "lever_id", "title"),
}


def ledger_for(kind: str) -> ItemLedger:
    """The ledger for an item kind, raising on one that does not exist.

    A `ValueError` and not a `KeyError`, because the router turns a `ValueError` from this
    module into a 422 and would turn a `KeyError` into a 500. The kind never comes from a
    request body - each door names its own - so this is a guard against a future door, not
    against a caller.
    """
    ledger = ITEM_LEDGERS.get(kind)
    if ledger is None:
        raise ValueError(f"unknown item kind '{kind}'")
    return ledger


async def record_item_review(
    conn: aiosqlite.Connection, *, project_id: int, kind: str, item_id: str,
    reviewer: str, decision: str, notes: str = "", return_to: str | None = None,
    forced: bool = False,
) -> dict:
    """Append a review event and update the ledger row's derived state.

    Approval is once per item: a second approval is refused while the row is already
    approved, and it must be sent back first. A send-back must name its target, because both
    defaults are wrong - to the agent it regenerates the item a reviewer is about to re-read,
    to the reviewer it silently drops a request for regeneration.

    An approver may override the not-yet-reviewed gate with `forced=True`, but the record
    must show they did - the default stays refusal, and the override is never silent.

    **`reviewed_at_version` is stamped in the same UPDATE that sets `review_status`, from the
    `last_version` this function has just read off the row.** That is the whole of what makes
    a send-back clear: `nodes_awaiting_regeneration` and `levers_awaiting_regeneration` treat
    a row as still awaiting the agent until `last_version` moves past it, and
    `register_nodes_sync` / `register_levers_sync` bump `last_version` on every id a write
    names. Without the stamp the comparison falls through to "still awaiting" for ever, which
    is the loud failure Task 3 chose over a silent one - see the COALESCE in
    `discovery_review_service`. Stamped on every decision and not only on `changes_requested`,
    because the staleness indicator a reviewer reads ("changed since v3 -> v7") is the same
    number and is just as wrong when it is missing from a plain `reviewed`.
    """
    ledger = ledger_for(kind)
    if decision not in VALID_DECISIONS:
        raise ValueError(f"unknown decision '{decision}'")
    if decision == "changes_requested":
        if return_to not in VALID_RETURN_TO:
            raise ValueError("changes_requested needs return_to of 'agent' or 'reviewer'")
    else:
        return_to = None

    cur = await conn.execute(
        f"SELECT review_status, last_version FROM {ledger.table}"
        f" WHERE {ledger.id_column}=? AND project_id=?",
        (item_id, project_id),
    )
    row = await cur.fetchone()
    if row is None:
        raise ValueError(f"no ledger row for {kind} '{item_id}'")
    current_status, last_version = row[0], row[1]
    if decision == "approved" and current_status == "approved":
        raise AlreadyApprovedError(
            f"{kind} {item_id} cannot re-approve, send it back first"
        )
    if decision == "approved" and not forced:
        if await item_review_count(
            conn, project_id=project_id, kind=kind, item_id=item_id
        ) == 0:
            raise NotYetReviewedError(
                f"{kind} {item_id} has no reviews - it must be read before it is approved"
            )

    # COALESCE at the Python boundary rather than in SQL: last_version is nullable (the
    # column has no default, and a backfilled row never had a version to record), and a NULL
    # stamp is the one value the awaiting-the-agent comparison reads as "no recorder has ever
    # touched this row". Writing 0 instead says "read at the beginning of time", which is
    # true of a row whose agent has never written and is the reading that clears correctly
    # the moment it does.
    at_version = last_version or 0

    await conn.execute(
        "INSERT INTO item_reviews"
        " (project_id, item_kind, item_id, reviewer, decision, notes, at_version,"
        "  return_to, forced)"
        " VALUES (?,?,?,?,?,?,?,?,?)",
        (project_id, kind, item_id, reviewer, decision, notes, at_version, return_to,
         int(forced)),
    )
    await conn.execute(
        f"UPDATE {ledger.table}"
        "   SET review_status=?, reviewed_at_version=?, review_return_to=?,"
        "       updated_at=CURRENT_TIMESTAMP"
        f" WHERE {ledger.id_column}=? AND project_id=?",
        (decision, at_version, return_to, item_id, project_id),
    )
    await conn.commit()

    conn.row_factory = aiosqlite.Row
    cur = await conn.execute(
        f"SELECT * FROM {ledger.table} WHERE {ledger.id_column}=? AND project_id=?",
        (item_id, project_id),
    )
    return dict(await cur.fetchone())


async def item_review_count(
    conn: aiosqlite.Connection, *, project_id: int, kind: str, item_id: str
) -> int:
    """How many times a human has read this item and said something about it.

    Derived on every read rather than stored, for the reason `review_count` gives one module
    over: a stored counter is a second source of truth for something one query answers.

    'approved' is excluded, so an approval cannot satisfy its own gate.
    """
    cur = await conn.execute(
        "SELECT COUNT(*) FROM item_reviews"
        " WHERE project_id=? AND item_kind=? AND item_id=? AND decision != 'approved'",
        (project_id, kind, item_id),
    )
    return (await cur.fetchone())[0]


async def item_ledger_rows(
    conn: aiosqlite.Connection, *, project_id: int, kind: str
) -> list[dict]:
    """Every ledger row of one kind, in id order, each carrying its review count.

    The count is joined here rather than in the router so both doors report it the same way,
    and it is the number the surface disables Approve on until an item has actually been read.
    """
    ledger = ledger_for(kind)
    conn.row_factory = aiosqlite.Row
    cur = await conn.execute(
        f"SELECT * FROM {ledger.table} WHERE project_id=? ORDER BY {ledger.id_column}",
        (project_id,),
    )
    rows = [dict(r) for r in await cur.fetchall()]
    for row in rows:
        row["review_count"] = await item_review_count(
            conn, project_id=project_id, kind=kind, item_id=row[ledger.id_column]
        )
    return rows
