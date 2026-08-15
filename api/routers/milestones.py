# api/routers/milestones.py
#
# Two axes, per the table in CLAUDE.md's API conventions. A milestone is project
# *configuration* - what is scheduled, and when it was promised - so its writes sit on the
# administration axis beside `PATCH /{slug}/settings` and the campaign doors, and take
# `require_org_admin_or_above`. Re-baselining is the exception: moving a promise is a
# judgement about the work rather than a configuration change, so it keeps the content gate
# it already had.
#
# Every door here, reads included, calls `check_project_access` first. That is the
# membership floor, and it is the part that was missing: without it the login role alone
# decided, so an org_admin of one engagement could rewrite another engagement's milestones
# and any valid token at all could read and write them.
from fastapi import APIRouter, Depends, HTTPException
from api.auth import require_any_auth, require_org_admin_or_above, check_project_access
from api.database import (
    get_connection, list_milestones, insert_milestone, update_milestone,
    delete_milestone, seed_default_milestones, rebaseline_milestone,
    fetch_milestone_baselines,
)
from api.models import Milestone, MilestoneCreate, MilestoneUpdate, MilestoneRebaseline
from api.services.commit_service import caller_may_commit

router = APIRouter(prefix="/projects/{slug}/milestones", tags=["milestones"])


def _404(msg: str):
    raise HTTPException(404, msg)


@router.get("", response_model=list[Milestone])
async def get_milestones(slug: str, payload: dict = Depends(require_any_auth)):
    await check_project_access(slug, payload)
    async with get_connection(slug) as conn:
        rows = await list_milestones(conn, slug)
    # Auto-seed defaults on first visit
    if not rows:
        async with get_connection(slug) as conn:
            await seed_default_milestones(conn, slug)
            rows = await list_milestones(conn, slug)
    return rows


@router.post("/seed", response_model=list[Milestone])
async def seed_milestones(slug: str, payload: dict = Depends(require_org_admin_or_above)):
    """Insert any missing default milestones, then return the full list."""
    await check_project_access(slug, payload)
    async with get_connection(slug) as conn:
        await seed_default_milestones(conn, slug)
        return await list_milestones(conn, slug)


@router.post("", response_model=Milestone)
async def create_milestone(
    slug: str, body: MilestoneCreate,
    payload: dict = Depends(require_org_admin_or_above),
):
    await check_project_access(slug, payload)
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
    payload: dict = Depends(require_org_admin_or_above),
):
    await check_project_access(slug, payload)
    async with get_connection(slug) as conn:
        ok = await update_milestone(
            conn, milestone_id=milestone_id, slug=slug,
            title=body.title, description=body.description,
            due_date=body.due_date, status=body.status,
            notes=body.notes, sort_order=body.sort_order,
            completed_at=body.completed_at,
            # Pydantic cannot tell an omitted field from an explicit null, and the two mean
            # different things here: omitted leaves the date alone, null clears it.
            completed_at_given="completed_at" in body.model_fields_set,
        )
        if not ok:
            _404("Milestone not found")
        async with conn.execute("SELECT * FROM project_milestones WHERE id=?", (milestone_id,)) as cur:
            row = await cur.fetchone()
    return dict(row)


@router.delete("/{milestone_id}", status_code=204)
async def remove_milestone(
    slug: str, milestone_id: int,
    payload: dict = Depends(require_org_admin_or_above),
):
    await check_project_access(slug, payload)
    async with get_connection(slug) as conn:
        deleted = await delete_milestone(conn, milestone_id=milestone_id, slug=slug)
    if not deleted:
        _404("Milestone not found")


@router.post("/{milestone_id}/rebaseline", response_model=Milestone)
async def rebaseline(
    slug: str, milestone_id: int, body: MilestoneRebaseline,
    payload: dict = Depends(require_any_auth),
):
    """Move a milestone's promise, keeping the one it replaces.

    Approver-gated with the same rule as activation, which set the original: whoever may
    make a promise on this project is whoever may change one. That is a content judgement,
    not configuration, which is why this one door alone does not take the administration
    dependency its neighbours do.

    `check_project_access` runs before the content gate and before the 422, so a caller
    from outside the engagement is told they have no access rather than which of this
    project's milestone ids exist.
    """
    await check_project_access(slug, payload)
    if not body.reason.strip():
        raise HTTPException(422, "A re-baseline needs a reason")
    if not await caller_may_commit(slug, payload):
        raise HTTPException(403, "Only an approver may re-baseline a milestone")

    async with get_connection(slug) as conn:
        ok = await rebaseline_milestone(
            conn, milestone_id=milestone_id, slug=slug,
            baseline_date=body.baseline_date, reason=body.reason.strip(),
            set_by=str(payload.get("sub") or payload.get("email") or ""),
        )
        if not ok:
            # Either it does not exist, or it has no baseline to supersede. Allowing the
            # second would let work added after activation acquire a promise
            # retrospectively - which is how a project makes its own scope growth vanish.
            _404("Milestone not found, or it has no baseline to supersede")
        async with conn.execute(
            "SELECT * FROM project_milestones WHERE id=?", (milestone_id,)
        ) as cur:
            row = await cur.fetchone()
    return dict(row)


@router.get("/{milestone_id}/baselines")
async def list_baselines(
    slug: str, milestone_id: int, payload: dict = Depends(require_any_auth),
):
    """Every baseline this milestone has carried and been moved off, oldest first."""
    await check_project_access(slug, payload)
    async with get_connection(slug) as conn:
        return await fetch_milestone_baselines(conn, milestone_id=milestone_id)
