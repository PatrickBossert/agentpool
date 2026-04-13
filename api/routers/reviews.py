# api/routers/reviews.py
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from aiosqlite import IntegrityError as AioSQLiteIntegrityError
from api.database import get_connection, get_db_path, fetch_project, insert_review

router = APIRouter(prefix="/projects", tags=["reviews"])


class ReviewRequest(BaseModel):
    output_id: int
    decision: str  # "approved" | "changes_requested"
    notes: str = ""
    reviewer: str = "consultant"


@router.post("/{slug}/review", status_code=201)
async def submit_review(slug: str, req: ReviewRequest):
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
