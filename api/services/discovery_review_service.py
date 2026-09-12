"""Per-node and per-lever review, the `discovery_mapping` half of what
`script_review_service` does for Maya.

Maya's loop is the precedent and the reason: a script is a row with its own review state, so
a reviewer sends SC-014 back and the next run regenerates that one script. Alex's tree is one
artefact holding 89 activities and Morgan's levers are one artefact holding ten, so until
`value_chain_ledger` and `value_lever_ledger` existed there was nothing to send back but the
whole thing.

**Read only, and deliberately so.** The two functions below answer "what is awaiting this
agent"; nothing here records a review. The recorder belongs with the review surface, exactly
as `record_script_review` sits beside `ScriptReviewPanel`, and until it exists these read a
state only a hand-written row or a backfill can reach. That is the honest description of this
module today - see `_pending_discovery_revisions` in `run_service.py` for what consumes it,
and the COALESCE below for what the recorder owes it.
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
# Here, nothing writes `reviewed_at_version` yet: the recorder arrives with the review
# surface. Spelled the script ledger's way, a recorder that set `review_status` and forgot the
# stamp would produce a send-back that reaches the agent **never**, silently, on every run.
# Spelled this way, `reviewed_at_version IS NULL` falls through to `last_version >=
# last_version` - true - so the same forgetful recorder produces a send-back that reaches the
# agent on every run until something clears it. Both are defects; one announces itself in the
# prompt and the other cannot be seen at all. The failure falls towards the loud direction on
# purpose, and the moment a recorder does stamp the column the comparison is exact.
_AWAITING_THE_AGENT = (
    " review_status='changes_requested'"
    "   AND review_return_to='agent'"
    "   AND COALESCE(reviewed_at_version, last_version, 0) >= COALESCE(last_version, 0)"
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

    No note is joined, because there is nowhere yet to join one from. A script's note comes
    from `script_reviews`, one row per review event; the equivalent table for nodes and levers
    arrives with the review surface that writes it. **The reviewer's words are not lost in the
    meantime**: both review doors write an `output_changes` row, and `_fetch_change_requests`
    puts it in the same prompt as this block - so today the two blocks divide the work, this
    one naming which items and that one carrying what was asked. When the event table lands,
    the note joins here the way `scripts_awaiting_regeneration` joins `script_reviews`, and
    that is an addition to this SELECT rather than a change to it.
    """
    conn.row_factory = aiosqlite.Row
    cur = await conn.execute(
        "SELECT node_id, label, level"
        "  FROM value_chain_ledger"
        " WHERE project_id=? AND active=1 AND" + _AWAITING_THE_AGENT +
        " ORDER BY node_id",
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
    """
    conn.row_factory = aiosqlite.Row
    cur = await conn.execute(
        "SELECT lever_id, title, status"
        "  FROM value_lever_ledger"
        " WHERE project_id=? AND" + _AWAITING_THE_AGENT +
        " ORDER BY lever_id",
        (project_id,),
    )
    return [dict(r) for r in await cur.fetchall()]
