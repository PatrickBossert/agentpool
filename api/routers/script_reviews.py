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
from api.services.authority_service import caller_roles
from api.services.script_review_service import (
    AlreadyApprovedError,
    NotYetReviewedError,
    record_script_review,
    review_count,
)

log = logging.getLogger(__name__)

router = APIRouter(prefix="/projects", tags=["script-reviews"])


class ScriptReviewRequest(BaseModel):
    decision: str
    notes: str = ""
    return_to: str | None = None
    forced: bool = False


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
