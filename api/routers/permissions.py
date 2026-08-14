# api/routers/permissions.py
"""What the calling user may do on one project.

The rule itself lives in _caller_matches_stakeholder_flag and is not restated here. Authority
comes from the stakeholder assignment - is_reviewer and is_approver - rather than the login
role, and that helper is what commit and submission already consult.

It currently answers True for a sysadmin, and every login is sysadmin against an empty users
table, so this reports true for everyone today. That is the same latency the rest of the
authority model has, and it tightens with no change here once real accounts exist.
"""
from fastapi import APIRouter, Depends, HTTPException

from api.auth import check_project_access, require_any_auth
from api.database import fetch_project, get_connection
from api.services.commit_service import _caller_matches_stakeholder_flag

router = APIRouter(prefix="/projects", tags=["permissions"])


@router.get("/{slug}/my-permissions")
async def get_my_permissions(slug: str, payload: dict = Depends(require_any_auth)):
    await check_project_access(slug, payload)
    async with get_connection(slug) as conn:
        if not await fetch_project(conn, slug=slug):
            raise HTTPException(status_code=404, detail=f"Project '{slug}' not found")
    return {
        "can_review": await _caller_matches_stakeholder_flag(
            slug, payload, flags=("is_reviewer", "is_approver")),
        "can_approve": await _caller_matches_stakeholder_flag(
            slug, payload, flags=("is_approver",)),
    }
