# api/routers/milestones.py
from fastapi import APIRouter, Depends, HTTPException
from api.auth import require_any_auth as get_current_user
from api.database import get_connection, list_milestones, insert_milestone, update_milestone, delete_milestone, seed_default_milestones
from api.models import Milestone, MilestoneCreate, MilestoneUpdate

router = APIRouter(prefix="/projects/{slug}/milestones", tags=["milestones"])


def _404(msg: str):
    raise HTTPException(404, msg)


@router.get("", response_model=list[Milestone])
async def get_milestones(slug: str, payload: dict = Depends(get_current_user)):
    async with get_connection(slug) as conn:
        rows = await list_milestones(conn, slug)
    # Auto-seed defaults on first visit
    if not rows:
        async with get_connection(slug) as conn:
            await seed_default_milestones(conn, slug)
            rows = await list_milestones(conn, slug)
    return rows


@router.post("/seed", response_model=list[Milestone])
async def seed_milestones(slug: str, payload: dict = Depends(get_current_user)):
    """Insert any missing default milestones, then return the full list."""
    async with get_connection(slug) as conn:
        await seed_default_milestones(conn, slug)
        return await list_milestones(conn, slug)


@router.post("", response_model=Milestone)
async def create_milestone(slug: str, body: MilestoneCreate, payload: dict = Depends(get_current_user)):
    import uuid
    key = body.milestone_key or f"custom_{uuid.uuid4().hex[:8]}"
    async with get_connection(slug) as conn:
        new_id = await insert_milestone(
            conn, slug=slug, milestone_key=key,
            title=body.title, description=body.description,
            due_date=body.due_date, notes=body.notes, sort_order=body.sort_order,
        )
        async with conn.execute("SELECT * FROM project_milestones WHERE id=?", (new_id,)) as cur:
            row = await cur.fetchone()
    return dict(row)


@router.patch("/{milestone_id}", response_model=Milestone)
async def patch_milestone(
    slug: str, milestone_id: int, body: MilestoneUpdate,
    payload: dict = Depends(get_current_user),
):
    async with get_connection(slug) as conn:
        ok = await update_milestone(
            conn, milestone_id=milestone_id, slug=slug,
            title=body.title, description=body.description,
            due_date=body.due_date, status=body.status,
            notes=body.notes, sort_order=body.sort_order,
        )
        if not ok:
            _404("Milestone not found")
        async with conn.execute("SELECT * FROM project_milestones WHERE id=?", (milestone_id,)) as cur:
            row = await cur.fetchone()
    return dict(row)


@router.delete("/{milestone_id}", status_code=204)
async def remove_milestone(slug: str, milestone_id: int, payload: dict = Depends(get_current_user)):
    async with get_connection(slug) as conn:
        deleted = await delete_milestone(conn, milestone_id=milestone_id, slug=slug)
    if not deleted:
        _404("Milestone not found")
