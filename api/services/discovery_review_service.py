"""Per-node and per-lever review, the `discovery_mapping` half of what
`script_review_service` does for Maya.

Maya's loop is the precedent and the reason: a script is a row with its own review state, so
a reviewer sends SC-014 back and the next run regenerates that one script. Alex's tree is one
artefact holding 89 activities and Morgan's levers are one artefact holding ten, so until
`value_chain_ledger` and `value_lever_ledger` existed there was nothing to send back but the
whole thing.

**Read only, and deliberately so.** The two functions below answer "what is awaiting this
agent"; nothing here records a review. The recorder is `record_item_review` in
`api/services/item_review_service.py`, which arrived with the review surface exactly as
`record_script_review` sits beside `ScriptReviewPanel`. See `_pending_discovery_revisions` in
`run_service.py` for what consumes these, and the COALESCE below for what the recorder owes
them.
"""
import aiosqlite

# One WHERE clause, not two. Both ledgers answer the same question and the conditions are the
# same conditions; written once so the pair cannot drift the way `register_scripts_sync` and
# `scripts_awaiting_regeneration` already have (CLAUDE.md records that divergence, and it is
# the same two-copies-of-one-condition shape).
#
# `COALESCE(reviewed_at_version, last_version, 0) >= COALESCE(last_version, 0)` is the
# staleness guard, and it is **not** spelled the way `scripts_awaiting_regeneration` spells
# the same idea. That function compares `COALESCE(last_version,0) <= COALESCE(
# reviewed_at_version,0)`, so a NULL `reviewed_at_version` reads as 0 and excludes any row
# whose agent has ever written - which is correct there, because `record_script_review` can
# never leave that column NULL and the only NULLs come from a backfill of `last_version`.
#
# Here, a recorder that set `review_status` and forgot the stamp would, spelled the script
# ledger's way, produce a send-back that reaches the agent **never**, silently, on every run.
# Spelled this way, `reviewed_at_version IS NULL` falls through to `last_version >=
# last_version` - true - so the same forgetful recorder produces a send-back that reaches the
# agent on every run until something clears it. Both are defects; one announces itself in the
# prompt and the other cannot be seen at all. The failure falls towards the loud direction on
# purpose. `record_item_review` does stamp the column - it reads `last_version` off the row
# rather than taking it from a caller, so neither review door can omit it - and with the stamp
# written the comparison is exact. The tolerance stays for the rows no recorder ever touched.
#
# Qualified with the `l.` alias both queries below give their ledger table, because each also
# joins `item_reviews` for the note and an unqualified `last_version` would then be ambiguous
# to read even where SQLite can resolve it.
_AWAITING_THE_AGENT = (
    " l.review_status='changes_requested'"
    "   AND l.review_return_to='agent'"
    "   AND COALESCE(l.reviewed_at_version, l.last_version, 0) >= COALESCE(l.last_version, 0)"
)


async def nodes_awaiting_regeneration(
    conn: aiosqlite.Connection, *, project_id: int
) -> list[dict]:
    """Value chain nodes a reviewer sent back to Alex, in node id order.

    Only `review_return_to='agent'`. A return to reviewers is a human-to-human loop and must
    never reach the agent - regenerating the node the reviewer was about to re-read rewrites
    the thing under discussion.

    Retired nodes are excluded (`active=1`). A node Alex has dropped from the chain is not
    one he can be asked to revise, and the ledger keeps the row for ever rather than deleting
    it, so without this filter a send-back recorded before a retirement would outlive it.
    The lever ledger carries no `active` column - Task 2 declined it deliberately - so its
    query below has no equivalent clause rather than a silently different one.

    The note is the most recent one recorded against this node, joined from `item_reviews` -
    the addition this docstring predicted, made the way it said it would be made. Before that
    table existed there was nowhere to join one from, and the reviewer's words reached the
    same prompt only through `_fetch_change_requests`' `output_changes` row. They still do,
    and that is not duplication: a change request is raised against the whole artefact and
    says what to fix, while this names the node and carries the sentence the reviewer wrote
    about that node. A row with no event - a hand-written one, or a backfill - joins NULL and
    reads as no note rather than dropping out of the result.
    """
    conn.row_factory = aiosqlite.Row
    cur = await conn.execute(
        "SELECT l.node_id, l.label, l.level,"
        "       (SELECT notes FROM item_reviews r"
        "         WHERE r.project_id = l.project_id AND r.item_kind = 'node'"
        "           AND r.item_id = l.node_id"
        "         ORDER BY r.id DESC LIMIT 1) AS notes"
        "  FROM value_chain_ledger l"
        " WHERE l.project_id=? AND l.active=1 AND" + _AWAITING_THE_AGENT +
        " ORDER BY l.node_id",
        (project_id,),
    )
    return [dict(r) for r in await cur.fetchall()]


async def levers_awaiting_regeneration(
    conn: aiosqlite.Connection, *, project_id: int
) -> list[dict]:
    """Value levers a reviewer sent back to Morgan, in lever id order.

    The mirror of `nodes_awaiting_regeneration`, and the same two rules: `agent` only, and a
    row clears when the agent writes past the version the reviewer read.

    `status` is the lever's own hypothesis state - untested, contradicted, confirmed - and is
    **not** its review state. It is selected because a reviewer who sent LV-003 back is
    telling Morgan something about a hypothesis the interviews may already have decided, and
    the two facts read together are what the note is about. It is never filtered on: a
    contradicted lever is exactly the sort a reviewer sends back.

    The note is joined from `item_reviews` on `item_kind='lever'`, which is why that column
    exists: a lever id and a node id are different namespaces, so without it LV-001's note and
    a node's note would be told apart by the shape of the id.
    """
    conn.row_factory = aiosqlite.Row
    cur = await conn.execute(
        "SELECT l.lever_id, l.title, l.status,"
        "       (SELECT notes FROM item_reviews r"
        "         WHERE r.project_id = l.project_id AND r.item_kind = 'lever'"
        "           AND r.item_id = l.lever_id"
        "         ORDER BY r.id DESC LIMIT 1) AS notes"
        "  FROM value_lever_ledger l"
        " WHERE l.project_id=? AND" + _AWAITING_THE_AGENT +
        " ORDER BY l.lever_id",
        (project_id,),
    )
    return [dict(r) for r in await cur.fetchall()]
