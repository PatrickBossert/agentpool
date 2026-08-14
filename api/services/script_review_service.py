"""Per-script review, in the vocabulary the crew-level loop already uses.

The existing loop is not missing anything conceptually - it is at the wrong granularity.
agent_outputs.review_status and human_reviews.decision already carry approved,
changes_requested, dismissed, and rejected, but they apply to a whole artefact version,
and for Maya one version is all eighty-six scripts. Nobody reviews 1,711 questions in one
decision.
"""
import aiosqlite

VALID_DECISIONS = ("reviewed", "edited", "approved", "changes_requested")
VALID_RETURN_TO = ("agent", "reviewer")


class AlreadyApprovedError(ValueError):
    """Raised when a second approval is attempted while the row is already approved.

    A ValueError subclass so any existing caller catching ValueError still works
    unchanged; a distinct type so a caller that needs to tell this conflict apart from
    a malformed request (an unknown decision, a send-back with no target) can branch on
    the exception's type rather than pattern-matching its message text. The router uses
    this to choose 409 vs 422 - branching on wording would silently reclassify a
    conflict as a bad request the moment the message was reworded.
    """


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
        raise AlreadyApprovedError(
            f"script {script_id} cannot re-approve, send it back first"
        )

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


async def review_count(conn: aiosqlite.Connection, *, project_id: int, script_id: str) -> int:
    """How many times a human has read this script and said something about it.

    Derived on every read rather than stored. A stored counter is a second source of truth
    for something one query answers, and a derived field going stale has already cost this
    codebase a fix round.

    'approved' is excluded: an approval must not satisfy its own gate.
    """
    cur = await conn.execute(
        "SELECT COUNT(*) FROM script_reviews"
        " WHERE project_id=? AND script_id=? AND decision != 'approved'",
        (project_id, script_id),
    )
    return (await cur.fetchone())[0]


async def scripts_awaiting_regeneration(conn: aiosqlite.Connection, *, project_id: int) -> list[dict]:
    """Ledger rows sent back to the agent, with the note that came with them.

    Only return_to = 'agent'. A return to reviewers is a human-to-human loop and must
    never reach Maya's differential.

    A row clears on evidence the work was done, not on the assumption that a kickoff meant
    it was: reviewed_at_version records the last_version a script was AT when the
    changes_requested review was recorded (record_script_review's at_version, stamped from
    the ledger row the reviewer actually read). register_scripts_sync bumps last_version
    past that only for a batch that actually names this script_id again, so
    last_version <= reviewed_at_version is true until the agent regenerates it and false
    from the moment she does - no separate close-out call needed, and nothing to forget if
    the run that regenerated it never reaches a close-out at all. Mirrors the ordinary
    review gate: agent_outputs.is_current advances on a real write, not on a caller's say-so.

    Code review round 2: the nullable column here is last_version, not reviewed_at_version.
    reviewed_at_version can never be NULL through record_script_review - the router always
    passes at_version=row["last_version"] or 0. last_version can: interview_script_ledger's
    column has no default, and script_ledger_backfill.py's INSERT deliberately omits it,
    because the JSON registry it loads (issued before per-batch versioning existed) carries
    no version for those ids. Comparing NULL <= 0 in SQL evaluates to NULL, which is not
    true, so a backfilled row sent back for revision failed this WHERE clause and never
    reached Maya on its first run - the send-back was recorded, visible on the ledger
    endpoint, and notified, but silently never injected. COALESCE both sides to 0 so a
    never-registered version reads as "older than any reviewed_at_version", which is the
    correct reading: no evidence of a fresh write means the row is still owed one.
    """
    conn.row_factory = aiosqlite.Row
    cur = await conn.execute(
        "SELECT l.script_id, l.node_id, l.node_label,"
        "       (SELECT notes FROM script_reviews r WHERE r.script_id = l.script_id"
        "         ORDER BY r.id DESC LIMIT 1) AS notes"
        "  FROM interview_script_ledger l"
        " WHERE l.project_id=? AND l.review_status='changes_requested'"
        "   AND l.review_return_to='agent' AND l.active=1"
        "   AND COALESCE(l.last_version, 0) <= COALESCE(l.reviewed_at_version, 0)",
        (project_id,),
    )
    return [dict(r) for r in await cur.fetchall()]
