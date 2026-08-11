"""Per-script review, in the vocabulary the crew-level loop already uses.

The existing loop is not missing anything conceptually - it is at the wrong granularity.
agent_outputs.review_status and human_reviews.decision already carry approved,
changes_requested, dismissed, and rejected, but they apply to a whole artefact version,
and for Maya one version is all eighty-six scripts. Nobody reviews 1,711 questions in one
decision.
"""
import aiosqlite

VALID_DECISIONS = ("reviewed", "approved", "changes_requested")
VALID_RETURN_TO = ("agent", "reviewer")


async def record_script_review(
    conn: aiosqlite.Connection, *, project_id: int, script_id: str, reviewer: str,
    decision: str, notes: str = "", at_version: int = 0, return_to: str | None = None,
) -> dict:
    """Append a review event and update the ledger row's derived state.

    Approval is once per script: a second approval is refused while the row is already
    approved, and it must be sent back first. A send-back must name its target, because
    both defaults are wrong - to the agent it rewrites an instrument a reviewer is about
    to re-read, to the reviewer it silently drops a request for regeneration.
    """
    if decision not in VALID_DECISIONS:
        raise ValueError(f"unknown decision '{decision}'")
    if decision == "changes_requested":
        if return_to not in VALID_RETURN_TO:
            raise ValueError("changes_requested needs return_to of 'agent' or 'reviewer'")
    else:
        return_to = None

    cur = await conn.execute(
        "SELECT review_status FROM interview_script_ledger WHERE script_id=? AND project_id=?",
        (script_id, project_id),
    )
    row = await cur.fetchone()
    if row is None:
        raise ValueError(f"no ledger row for script_id '{script_id}'")
    if decision == "approved" and row[0] == "approved":
        raise ValueError(f"script {script_id} is already approved - send it back first")

    await conn.execute(
        "INSERT INTO script_reviews"
        " (project_id, script_id, reviewer, decision, notes, at_version, return_to)"
        " VALUES (?,?,?,?,?,?,?)",
        (project_id, script_id, reviewer, decision, notes, at_version, return_to),
    )
    await conn.execute(
        "UPDATE interview_script_ledger"
        " SET review_status=?, reviewed_at_version=?, review_return_to=?,"
        "     updated_at=CURRENT_TIMESTAMP"
        " WHERE script_id=? AND project_id=?",
        (decision, at_version, return_to, script_id, project_id),
    )
    await conn.commit()

    conn.row_factory = aiosqlite.Row
    cur = await conn.execute(
        "SELECT * FROM interview_script_ledger WHERE script_id=? AND project_id=?",
        (script_id, project_id),
    )
    return dict(await cur.fetchone())


async def scripts_awaiting_regeneration(conn: aiosqlite.Connection, *, project_id: int) -> list[dict]:
    """Ledger rows sent back to the agent, with the note that came with them.

    Only return_to = 'agent'. A return to reviewers is a human-to-human loop and must
    never reach Maya's differential.
    """
    conn.row_factory = aiosqlite.Row
    cur = await conn.execute(
        "SELECT l.script_id, l.node_id, l.node_label,"
        "       (SELECT notes FROM script_reviews r WHERE r.script_id = l.script_id"
        "         ORDER BY r.id DESC LIMIT 1) AS notes"
        "  FROM interview_script_ledger l"
        " WHERE l.project_id=? AND l.review_status='changes_requested'"
        "   AND l.review_return_to='agent' AND l.active=1",
        (project_id,),
    )
    return [dict(r) for r in await cur.fetchall()]
