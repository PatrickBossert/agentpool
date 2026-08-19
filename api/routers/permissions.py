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
# The carve-out on PATCH /{slug}/settings, imported rather than re-listed. It is the same
# tuple the door refuses with, so the page cannot be told a field is changeable that the
# door then refuses - the failure this endpoint exists to prevent. tests/test_grantable_
# roles.py already imports it under this name for the same reason.
from api.routers.projects import _PLATFORM_TIER_SETTINGS
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
        # What Settings.tsx asks before offering the local-inference toggle. The same
        # predicate `patch_settings_endpoint` decides `_PLATFORM_TIER_SETTINGS` with - it
        # calls `is_org_admin_or_above` rather than restating the tuple, so this is that door
        # observed from the reporting side rather than a second copy of its rule.
        #
        # Reported under its own name rather than by reusing `can_issue_invite_links`, which
        # is the identical predicate today. That reuse would be right by predicate and wrong
        # by referent: `can_issue_invite_links` is pinned by test to the resend-invite door,
        # so if that door ever changed tier the settings toggle would silently follow a door
        # it has nothing to do with, every test still green. Two names, two doors, two tests.
        "can_change_platform_tier_settings": is_org_admin_or_above(payload),
        # *Which* fields that permission covers - the server's own `_PLATFORM_TIER_SETTINGS`,
        # served rather than restated. The Settings tab disables a control by asking whether
        # its field is in this list, so the nine names live in exactly one place: a
        # hand-copied list in TypeScript is a rule in two places, and the copy the UI trusts
        # is the one that drifts. Adding a tenth member to the tuple disables its control
        # with no frontend change.
        #
        # Not a secret, and not gated on the boolean above: it is the field list of a model
        # every member of the project can already GET, and a caller who may not change them
        # still has to be told which ones those are - a greyed control with no reason reads
        # as a bug.
        "platform_tier_settings": list(_PLATFORM_TIER_SETTINGS),
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
