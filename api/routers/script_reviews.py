# api/routers/script_reviews.py
"""Per-script review endpoints.

Authority is read from caller_roles(slug, payload) - the walk from JWT to user to
membership to the stakeholder row that carries the person's role flags. It is the one
place this rule lives, and it is real now: there is no sysadmin bypass for content
authority, only for project administration.
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from api.auth import check_project_access, require_any_auth
from api.database import fetch_project, get_connection
from api.services.authority_service import caller_may_contribute, caller_roles
from api.services.script_review_service import (
    VALID_RETURN_TO,
    AlreadyApprovedError,
    NotYetReviewedError,
    record_script_review,
    review_count,
    scripts_awaiting_regeneration,
)

log = logging.getLogger(__name__)

router = APIRouter(prefix="/projects", tags=["script-reviews"])

# The only decision this door records in bulk, and the exclusions are not uniform in their
# reasoning.
#
# `approved` is refused because bulk approval is precisely the click-through the approval gate
# exists to prevent: approving an instrument is a deliberate act per script, and a door that
# does eighty-five of them at once is a door that has removed the act.
#
# `reviewed` and `edited` are refused for a sharper reason that is easy to miss. `review_count`
# excludes only `approved`, so either of them recorded in bulk would satisfy the
# not-yet-reviewed gate on every script in the batch at once - unlocking approval for all of
# them through a door that never mentions approval. `edited` additionally asserts a human
# changed the text of each script, which in a batch is simply untrue, and the review event is
# the audit record of what a person did.
#
# So the vocabulary is narrower than the singular door's by design, not by omission. A caller
# who wants any of the other three has the singular door, one script at a time, which is what
# those decisions mean.
BULK_DECISIONS = ("changes_requested",)


class ScriptReviewRequest(BaseModel):
    decision: str
    notes: str = ""
    return_to: str | None = None
    forced: bool = False


class BulkScriptReviewRequest(BaseModel):
    """An explicit list of script ids, never a filter and never "all".

    The blast radius must be visible in the request. `{"all_active": true}` would be shorter
    and the next caller would not know what it had matched - and on this ledger the difference
    between eighty-five scripts and eighty-six is the one already-corrected script being
    rewritten again.
    """

    script_ids: list[str]
    decision: str
    notes: str = ""
    return_to: str | None = None


@router.get("/{slug}/script-ledger")
async def get_script_ledger(slug: str, payload: dict = Depends(require_any_auth)):
    await check_project_access(slug, payload)
    async with get_connection(slug) as conn:
        project = await fetch_project(conn, slug=slug)
        if not project:
            raise HTTPException(status_code=404, detail=f"Project '{slug}' not found")
        cur = await conn.execute(
            "SELECT * FROM interview_script_ledger WHERE project_id=? ORDER BY script_id",
            (project["id"],),
        )
        rows = [dict(r) for r in await cur.fetchall()]
        for row in rows:
            row["review_count"] = await review_count(
                conn, project_id=project["id"], script_id=row["script_id"])
        return rows


@router.post("/{slug}/script-ledger/{script_id}/review")
async def review_script(
    slug: str, script_id: str, body: ScriptReviewRequest,
    payload: dict = Depends(require_any_auth),
):
    await check_project_access(slug, payload)
    roles = await caller_roles(slug, payload)
    needed = {"approver"} if body.decision == "approved" else {"reviewer", "approver"}
    if not (roles & needed):
        raise HTTPException(status_code=403, detail="Not permitted to review this script")

    async with get_connection(slug) as conn:
        project = await fetch_project(conn, slug=slug)
        if not project:
            raise HTTPException(status_code=404, detail=f"Project '{slug}' not found")
        cur = await conn.execute(
            "SELECT last_version FROM interview_script_ledger"
            " WHERE script_id=? AND project_id=?", (script_id, project["id"]))
        row = await cur.fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail=f"No script '{script_id}'")
        try:
            updated = await record_script_review(
                conn, project_id=project["id"], script_id=script_id,
                reviewer=payload.get("sub", ""), decision=body.decision,
                notes=body.notes, at_version=row["last_version"] or 0,
                return_to=body.return_to, forced=body.forced,
            )
        except (AlreadyApprovedError, NotYetReviewedError) as e:
            # A conflict with stored state, not a malformed request - branching on the
            # exception's type rather than its message means a reworded message cannot
            # silently reclassify this as a 422.
            raise HTTPException(status_code=409, detail=str(e))
        except ValueError as e:
            # Everything else the service refuses (unknown decision, a send-back with
            # no target) is a malformed request.
            raise HTTPException(status_code=422, detail=str(e))

    if body.decision == "changes_requested":
        from api.services.commit_notify_service import notify_script_sent_back
        # The review is already committed above; a failed notification must not turn a
        # recorded review into a failed request. notify_script_sent_back already wraps
        # its own body in a blanket except, so this is redundant today - but that
        # guarantee lives two modules away, and a bare call here would silently start
        # relying on it staying that way. Defended locally too, so this endpoint's own
        # contract does not depend on a helper it does not own.
        try:
            await notify_script_sent_back(slug, script_id, body.return_to or "", body.notes)
        except Exception:
            log.exception(
                "could not notify about script %s sent back on %s", script_id, slug
            )
    return updated


@router.post("/{slug}/script-ledger/review-batch")
async def review_scripts_in_bulk(
    slug: str, body: BulkScriptReviewRequest,
    payload: dict = Depends(require_any_auth),
):
    """Send a named batch of interview scripts back in one call, with one notification.

    Why this exists: Maya's prompt was corrected in 8be5f373 after a real interview found two
    defects in the instrument, and eighty-five scripts still carry the old closing. The only
    route to correcting them was eighty-five calls to the singular door, each firing its own
    email about one decision.

    **What it answers, and why that number rather than a cap.** `awaiting_regeneration` is the
    *total* number of scripts now awaiting regeneration, not the number this call added. Run 32
    is the reason: it wrote 41 scripts, hit CrewAI's default max_iter before its ledger write,
    and reported `completed` - so a run asked to regenerate more than it finishes is a recorded
    failure of this system, and a bulk send-back is the easiest way to create one. The quantity
    that decides whether the next run finishes is the whole backlog, because two modest calls
    make one immodest run and a per-call figure cannot see that. It is read from
    `scripts_awaiting_regeneration` - the same function `run_service._fetch_regeneration_
    requests` reads - so the number shown to the operator is by construction the number the
    prompt will name, rather than a second count free to drift from it.

    A cap was considered and refused. Nobody has measured where Maya stops: 41 is one
    observation of a failure and run 38 regenerated one script successfully, so any threshold
    between them is a guess presented as a limit. A cap also does not compose - it bounds the
    call and not the backlog, which is the quantity that matters - and it would refuse exactly
    the correction this door was asked for. Reporting the risk lets the operator decide whether
    to run now or in batches; refusing at a guessed number decides it for them, wrongly.

    Per-item outcomes rather than all-or-nothing: one stale id must not block a correction of
    eighty-five, and silent partial success is worse than either. There is one entry per entry
    in the request, in the order asked, so the answer can be checked against the call.
    """
    await check_project_access(slug, payload)
    # Asked by name rather than by restating `{reviewer, approver}` inline. The four older
    # call sites that spell the set out - this module's singular door among them - are on
    # record in CLAUDE.md as not being uniform with each other, which is what a condition
    # copied into several handlers becomes. A new door does not add a fifth copy.
    if not await caller_may_contribute(slug, payload):
        # A sentence of its own, so a refusal here is attributable to this gate rather than to
        # the singular door's next to it.
        raise HTTPException(
            status_code=403, detail="Not permitted to review scripts on this project")

    # Refused at the door rather than per item: a malformed request should fail once, not
    # produce eighty-five identical failures the caller has to read through.
    if body.decision not in BULK_DECISIONS:
        raise HTTPException(
            status_code=422,
            detail=(
                f"'{body.decision}' cannot be recorded in bulk - this door records "
                f"{', '.join(BULK_DECISIONS)} only. Use the per-script door for the rest."
            ),
        )
    if body.return_to not in VALID_RETURN_TO:
        raise HTTPException(
            status_code=422,
            detail="changes_requested needs return_to of 'agent' or 'reviewer'",
        )
    if not body.script_ids:
        raise HTTPException(
            status_code=422, detail="script_ids must name at least one script")

    results: list[dict] = []
    sent_back: list[str] = []
    seen: set[str] = set()

    async with get_connection(slug) as conn:
        project = await fetch_project(conn, slug=slug)
        if not project:
            raise HTTPException(status_code=404, detail=f"Project '{slug}' not found")

        for script_id in body.script_ids:
            # A repeated id is reported rather than collapsed silently, so len(results) always
            # equals len(script_ids) and the answer can be lined up against the request.
            if script_id in seen:
                results.append({
                    "script_id": script_id, "status": "duplicate",
                    "detail": "named more than once in this request",
                })
                continue
            seen.add(script_id)

            cur = await conn.execute(
                "SELECT last_version FROM interview_script_ledger"
                " WHERE script_id=? AND project_id=?", (script_id, project["id"]))
            row = await cur.fetchone()
            if row is None:
                results.append({
                    "script_id": script_id, "status": "not_found",
                    "detail": f"no script '{script_id}' on {slug}",
                })
                continue

            try:
                await record_script_review(
                    conn, project_id=project["id"], script_id=script_id,
                    reviewer=payload.get("sub", ""), decision=body.decision,
                    notes=body.notes, at_version=row["last_version"] or 0,
                    return_to=body.return_to, forced=False,
                )
            except (AlreadyApprovedError, NotYetReviewedError) as e:
                # Defence rather than a live path: both fire only on `approved`, which this
                # door refuses above, so no request can reach here today. Kept - and classified
                # on the exception's type, as the singular door does - so that a widening of
                # what record_script_review refuses is reported per item instead of becoming a
                # 500 that loses the rest of the batch.
                results.append({
                    "script_id": script_id, "status": "conflict", "detail": str(e)})
                continue
            except ValueError as e:
                results.append({
                    "script_id": script_id, "status": "refused", "detail": str(e)})
                continue

            results.append({"script_id": script_id, "status": "sent_back"})
            sent_back.append(script_id)

        awaiting = await scripts_awaiting_regeneration(conn, project_id=project["id"])

    if sent_back:
        from api.services import commit_notify_service
        # Outside the transaction, guarded locally, and called once - all three for the reasons
        # the singular door states. The import is of the module rather than of the name, so a
        # test patching `commit_notify_service.notify_scripts_sent_back` reaches this call; a
        # `from ... import` here would bind the function before the patch was applied.
        try:
            await commit_notify_service.notify_scripts_sent_back(
                slug, sent_back, body.return_to or "", body.notes)
        except Exception:
            log.exception(
                "could not notify about %d scripts sent back on %s", len(sent_back), slug)

    return {
        "results": results,
        "sent_back": len(sent_back),
        "awaiting_regeneration": len(awaiting),
    }
