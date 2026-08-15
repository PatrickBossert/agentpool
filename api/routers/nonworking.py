# api/routers/nonworking.py
#
# Non-working ranges are the project calendar - configuration, not content - so the writes
# sit on the administration axis with `require_org_admin_or_above`, and every door reads
# the membership floor first with `check_project_access`. See the two-axis table in
# CLAUDE.md's API conventions.
#
# The payload is bound by name rather than to `_`. Binding it to `_` was not a tidiness
# choice: it made a gate structurally impossible to write here, because nothing in the
# handler held the caller.
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from api.auth import require_any_auth, require_org_admin_or_above, check_project_access
from api.database import (
    get_connection,
    list_nonworking_ranges,
    insert_nonworking_range,
    update_nonworking_range,
    delete_nonworking_range,
)

router = APIRouter(prefix="/projects/{slug}/nonworking", tags=["nonworking"])


class NonWorkingRangeBody(BaseModel):
    label: str
    start_date: str
    end_date: str


@router.get("")
async def list_ranges(slug: str, payload: dict = Depends(require_any_auth)):
    await check_project_access(slug, payload)
    async with get_connection(slug) as conn:
        return await list_nonworking_ranges(conn, slug)


@router.post("", status_code=201)
async def create_range(
    slug: str, body: NonWorkingRangeBody,
    payload: dict = Depends(require_org_admin_or_above),
):
    await check_project_access(slug, payload)
    async with get_connection(slug) as conn:
        new_id = await insert_nonworking_range(
            conn, slug=slug, label=body.label,
            start_date=body.start_date, end_date=body.end_date,
        )
        rows = await list_nonworking_ranges(conn, slug)
    return next(r for r in rows if r["id"] == new_id)


@router.patch("/{range_id}")
async def update_range(
    slug: str, range_id: int, body: NonWorkingRangeBody,
    payload: dict = Depends(require_org_admin_or_above),
):
    await check_project_access(slug, payload)
    async with get_connection(slug) as conn:
        ok = await update_nonworking_range(
            conn, slug=slug, range_id=range_id,
            label=body.label, start_date=body.start_date, end_date=body.end_date,
        )
    if not ok:
        raise HTTPException(404, "Range not found")
    return {"id": range_id, "slug": slug, **body.model_dump()}


@router.delete("/{range_id}", status_code=204)
async def delete_range(
    slug: str, range_id: int,
    payload: dict = Depends(require_org_admin_or_above),
):
    await check_project_access(slug, payload)
    async with get_connection(slug) as conn:
        ok = await delete_nonworking_range(conn, slug=slug, range_id=range_id)
    if not ok:
        raise HTTPException(404, "Range not found")
