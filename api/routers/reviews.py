# api/routers/reviews.py
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from aiosqlite import IntegrityError as AioSQLiteIntegrityError
from api.auth import require_any_auth, check_project_access
from api.database import (
    get_connection,
    get_db_path,
    fetch_project,
    fetch_review,
    insert_review,
    insert_output_change,
    update_review,
    delete_hitl_review,
)
from api.services.project_service import get_pending_reviews

router = APIRouter(prefix="/projects", tags=["reviews"])


class ReviewRequest(BaseModel):
    output_id: int
    decision: str  # "approved" | "changes_requested"
    notes: str = ""
    reviewer: str = "consultant"


@router.post("/{slug}/review", status_code=201)
async def submit_review(slug: str, req: ReviewRequest, payload: dict = Depends(require_any_auth)):
    await check_project_access(slug, payload)
    if not get_db_path(slug).exists():
        raise HTTPException(status_code=404, detail=f"Project '{slug}' not found")
    async with get_connection(slug) as conn:
        project = await fetch_project(conn, slug=slug)
        if not project:
            raise HTTPException(status_code=404, detail=f"Project '{slug}' not found")
        try:
            review_id = await insert_review(
                conn,
                output_id=req.output_id,
                reviewer=req.reviewer,
                decision=req.decision,
                notes=req.notes,
            )
        except AioSQLiteIntegrityError:
            raise HTTPException(status_code=422, detail=f"output_id {req.output_id} does not exist")
        return {
            "id": review_id,
            "output_id": req.output_id,
            "decision": req.decision,
            "notes": req.notes,
        }


_INTENTS = ("change_request", "correction", "skill")


class HITLReviewRequest(BaseModel):
    decision: str   # "approved" | "changes_requested"
    notes: str = ""
    intent: str = "change_request"


@router.patch("/{slug}/reviews/{review_id}", status_code=200)
async def resolve_hitl_review(slug: str, review_id: int, req: HITLReviewRequest, payload: dict = Depends(require_any_auth)):
    await check_project_access(slug, payload)
    if not get_db_path(slug).exists():
        raise HTTPException(status_code=404, detail=f"Project '{slug}' not found")
    if req.intent not in _INTENTS:
        raise HTTPException(
            status_code=422, detail=f"intent must be one of {', '.join(_INTENTS)}"
        )
    async with get_connection(slug) as conn:
        project = await fetch_project(conn, slug=slug)
        if not project:
            raise HTTPException(status_code=404, detail=f"Project '{slug}' not found")
        updated = await update_review(
            conn, review_id=review_id, decision=req.decision, notes=req.notes
        )
        if not updated:
            raise HTTPException(status_code=404, detail=f"Review {review_id} not found")
        # An approval is not feedback. Recording one would inject an instruction to do nothing.
        if req.decision == "changes_requested" and req.notes.strip():
            review = await fetch_review(conn, review_id=review_id)
            if review and review.get("output_id"):
                await insert_output_change(
                    conn,
                    output_id=review["output_id"],
                    requested_by=payload.get("sub", "unknown"),
                    source="review",
                    request=req.notes.strip(),
                    summary="",
                    kind=req.intent,
                )
        return {"id": review_id, "decision": req.decision, "notes": req.notes}


@router.delete("/{slug}/reviews/{review_id}", status_code=204)
async def delete_review(slug: str, review_id: int, payload: dict = Depends(require_any_auth)):
    await check_project_access(slug, payload)
    if not get_db_path(slug).exists():
        raise HTTPException(status_code=404, detail=f"Project '{slug}' not found")
    async with get_connection(slug) as conn:
        project = await fetch_project(conn, slug=slug)
        if not project:
            raise HTTPException(status_code=404, detail=f"Project '{slug}' not found")
        deleted = await delete_hitl_review(conn, review_id=review_id)
        if not deleted:
            raise HTTPException(status_code=404, detail=f"Review {review_id} not found")


@router.get("/{slug}/reviews")
async def list_pending_reviews(slug: str, payload: dict = Depends(require_any_auth)):
    await check_project_access(slug, payload)
    result = await get_pending_reviews(slug)
    if result is None:
        raise HTTPException(status_code=404, detail=f"Project '{slug}' not found")
    return result
