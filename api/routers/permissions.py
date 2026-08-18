# api/routers/permissions.py
"""What the calling user may do on one project.

Authority is read from caller_roles(slug, payload) - the same walk that gates the
review and edit endpoints - so this reports exactly what those doors would accept.
It deliberately does not re-implement the rule: a second copy would drift, and the
copy the UI trusted would be the wrong one.
"""
from fastapi import APIRouter, Depends, HTTPException

from api.auth import check_project_access, is_org_admin_or_above, require_any_auth
from api.database import fetch_project, get_connection
from api.services.authority_service import (
    caller_may_grant_project_roles,
    caller_roles,
    writable_tiers_on_project,
)

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
        # What Stakeholders.tsx asks before offering the "issue an invite link" action.
        # `POST .../resend-invite` hands back a redeemable credential, so it stayed on the
        # platform tier when sp44 widened the rest of its router to project_admin - which
        # makes this the one permission here that is *narrower* than administering the
        # engagement. `is_org_admin_or_above` is the same predicate the door refuses with
        # rather than a restatement of it.
        "can_issue_invite_links": is_org_admin_or_above(payload),
        # What the upload dialog's tier picker offers, broadest first. Answered here rather
        # than restated in TypeScript for the reason this whole endpoint exists: a second
        # copy of an authority rule drifts, and the copy the UI trusts is the wrong one -
        # here it would render a tier the door then refuses, which this project has
        # established twice is worse than not offering it at all.
        #
        # Project-scoped, not role-scoped. `knowledge_tiers.writable_tiers` reads the login
        # role alone and would tell every org_admin "organisation" on every project; the
        # honest answer on a project belonging to another organisation is that they may not
        # write it. A tier that does not exist for this project - the organisation tier of an
        # unregistered project - is absent for the same reason.
        "writable_knowledge_tiers": list(await writable_tiers_on_project(slug, payload)),
    }
