# api/routers/permissions.py
"""What the calling user may do on one project.

Authority is read from caller_roles(slug, payload) - the same walk that gates the
review and edit endpoints - so this reports exactly what those doors would accept.
It deliberately does not re-implement the rule: a second copy would drift, and the
copy the UI trusted would be the wrong one.
"""
from fastapi import APIRouter, Depends, HTTPException

from api.auth import check_project_access, require_any_auth
from api.database import fetch_project, get_connection
from api.services.authority_service import caller_may_grant_project_roles, caller_roles

router = APIRouter(prefix="/projects", tags=["permissions"])


@router.get("/{slug}/my-permissions")
async def get_my_permissions(slug: str, payload: dict = Depends(require_any_auth)):
    await check_project_access(slug, payload)
    async with get_connection(slug) as conn:
        if not await fetch_project(conn, slug=slug):
            raise HTTPException(status_code=404, detail=f"Project '{slug}' not found")
    roles = await caller_roles(slug, payload)
    return {
        "can_review": bool(roles & {"reviewer", "approver"}),
        "can_approve": "approver" in roles,
        # What StakeholderForm.tsx asks before rendering the project_admin and governor
        # checkboxes. A checkbox that always refuses is worse than no checkbox, and this is
        # the same rule `_assert_may_grant_role_flags` enforces rather than a second copy of
        # it - the copy the UI trusted would be the one that drifted.
        "can_grant_roles": await caller_may_grant_project_roles(slug, payload),
    }
