# api/routers/admin.py
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from api.auth import (
    check_org_access, check_project_access, require_sysadmin, require_org_admin_or_above,
)
from api.services.admin_service import (
    svc_list_orgs, svc_create_org, svc_get_org, svc_update_org, svc_delete_org,
    svc_list_org_members, svc_add_org_member, svc_update_org_member_role, svc_remove_org_member,
    svc_list_registry, svc_register_project, svc_unregister_project,
    svc_list_users, svc_create_user, svc_update_user, svc_delete_user,
    svc_list_user_projects, svc_grant_project_access, svc_revoke_project_access,
    svc_issue_reset_link,
    ForbiddenRoleChange, OrganisationInUse, AccountOutOfScope,
)

router = APIRouter(prefix="/auth", tags=["admin"])


def _404(msg: str):
    raise HTTPException(status_code=404, detail=msg)


# ── Organisations ─────────────────────────────────────────────────────────────

class OrgCreate(BaseModel):
    slug: str
    name: str


class OrgUpdate(BaseModel):
    name: str


@router.get("/orgs", dependencies=[Depends(require_sysadmin)])
async def list_orgs():
    return await svc_list_orgs()


@router.post("/orgs", status_code=201, dependencies=[Depends(require_sysadmin)])
async def create_org(req: OrgCreate):
    try:
        return await svc_create_org(slug=req.slug, name=req.name)
    except Exception:
        raise HTTPException(status_code=409, detail="Org slug already exists")


@router.get("/orgs/{org_id}", dependencies=[Depends(require_org_admin_or_above)])
async def get_org(org_id: int):
    org = await svc_get_org(org_id)
    if not org:
        _404(f"Org {org_id} not found")
    return org


@router.patch("/orgs/{org_id}", dependencies=[Depends(require_sysadmin)])
async def update_org(org_id: int, req: OrgUpdate):
    org = await svc_update_org(org_id, req.name)
    if not org:
        _404(f"Org {org_id} not found")
    return org


@router.delete("/orgs/{org_id}", status_code=204, dependencies=[Depends(require_sysadmin)])
async def delete_org(org_id: int):
    # 409 and the reason in full: this refusal is the operator's only warning that a 204 here
    # would have cascaded through project_registry and taken every org_admin's access with it.
    try:
        deleted = await svc_delete_org(org_id)
    except OrganisationInUse as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    if not deleted:
        _404(f"Org {org_id} not found")


# ── Org membership ────────────────────────────────────────────────────────────

class MemberAdd(BaseModel):
    user_id: int
    role: str = "member"


class MemberRoleUpdate(BaseModel):
    role: str


@router.get("/orgs/{org_id}/members", dependencies=[Depends(require_org_admin_or_above)])
async def list_org_members(org_id: int):
    return await svc_list_org_members(org_id)


# The three writes to `org_memberships`, all scoped to the caller's own organisation.
#
# They take their dependency in the signature rather than the decorator, like
# grant_project_access below and for the same reason: check_org_access needs the payload in
# the handler body.
#
# Why it matters more than "an org_admin should stay in their lane". `org_memberships` is the
# table `_assert_may_administer` reads to decide whether an account belongs to the caller's
# organisation, so these doors decide the answer to the question that guards
# `PATCH /auth/users/{id}`. Unscoped, an org_admin refused on another organisation's account
# could remove its membership, add it to their own organisation, and return to the account
# door with the guard now agreeing - three requests at the same tier, ending in a password of
# their choosing on somebody else's login. The refusal was real; the premise underneath it was
# writable.

@router.post("/orgs/{org_id}/members", status_code=201)
async def add_org_member(org_id: int, req: MemberAdd, payload: dict = Depends(require_org_admin_or_above)):
    check_org_access(org_id, payload)
    try:
        ok = await svc_add_org_member(org_id, req.user_id, req.role, calling_payload=payload)
    except AccountOutOfScope as exc:
        # 409 rather than 403: the tier and the organisation in the path were both fine, and
        # what is refused is claiming an account another organisation already holds.
        raise HTTPException(status_code=409, detail=str(exc))
    if not ok:
        raise HTTPException(status_code=409, detail="User already a member of this org")
    return {"ok": True}


@router.patch("/orgs/{org_id}/members/{user_id}")
async def update_org_member(org_id: int, user_id: int, req: MemberRoleUpdate, payload: dict = Depends(require_org_admin_or_above)):
    """Scoped alongside its two neighbours. It cannot move an account between organisations,
    so it is not part of the chain above - but it writes the same table on an organisation the
    caller may not own, and leaving one door on that table unscoped is how the next chain
    starts."""
    check_org_access(org_id, payload)
    await svc_update_org_member_role(org_id, user_id, req.role)
    return {"ok": True}


@router.delete("/orgs/{org_id}/members/{user_id}", status_code=204)
async def remove_org_member(org_id: int, user_id: int, payload: dict = Depends(require_org_admin_or_above)):
    check_org_access(org_id, payload)
    await svc_remove_org_member(org_id, user_id)


# ── Project registry ──────────────────────────────────────────────────────────

class ProjectRegister(BaseModel):
    slug: str
    org_id: int
    display_name: str = ""


@router.get("/projects")
async def list_registry(payload: dict = Depends(require_org_admin_or_above)):
    return await svc_list_registry(payload)


@router.post("/projects", status_code=201, dependencies=[Depends(require_sysadmin)])
async def register_project(req: ProjectRegister):
    await svc_register_project(req.slug, req.org_id, req.display_name)
    return {"ok": True}


@router.delete("/projects/{slug}", status_code=204, dependencies=[Depends(require_sysadmin)])
async def unregister_project(slug: str):
    if not await svc_unregister_project(slug):
        _404(f"Project '{slug}' not in registry")


# ── Users ─────────────────────────────────────────────────────────────────────

class UserCreate(BaseModel):
    username: str
    email: str
    password: str
    role: str = "reviewer"
    org_id: int | None = None


class UserUpdate(BaseModel):
    email: str
    role: str
    password: str | None = None


# `project` selects the lens a name is read through - see svc_list_users. Authorised by
# check_project_access, which is the answer to "may this caller see this project" that
# `GET /auth/projects` (the selector's own options) is built from: the org branch of both
# reads project_registry, so the selector cannot offer a slug this refuses. Deliberately not
# a second rule of its own.
@router.get("/users")
async def list_users(
    project: str | None = None, payload: dict = Depends(require_org_admin_or_above)
):
    # An empty string is not a project. Normalised rather than authorised, because
    # check_project_access would answer it differently by tier - a sysadmin returns early and
    # would then be scoped to a slug nothing matches, while an org_admin would get a 403 on
    # what is plainly the unscoped view. Absent and blank mean the same thing here.
    project = project or None
    if project is not None:
        await check_project_access(project, payload)
    return await svc_list_users(payload, project_slug=project)


@router.post("/users", status_code=201)
async def create_user(req: UserCreate, payload: dict = Depends(require_org_admin_or_above)):
    user = await svc_create_user(
        username=req.username,
        email=req.email,
        password=req.password,
        role=req.role,
        org_id=req.org_id,
        calling_payload=payload,
    )
    if user is None:
        raise HTTPException(status_code=409, detail="Username already exists or forbidden role")
    return user


@router.patch("/users/{user_id}")
async def update_user_endpoint(
    user_id: int, req: UserUpdate, payload: dict = Depends(require_org_admin_or_above)
):
    try:
        user = await svc_update_user(
            user_id, req.email, req.role, req.password, calling_payload=payload
        )
    except ForbiddenRoleChange:
        raise HTTPException(status_code=409, detail="Forbidden role")
    except AccountOutOfScope as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    if not user:
        _404(f"User {user_id} not found")
    return user


@router.post("/users/{user_id}/reset-link")
async def issue_reset_link_endpoint(
    user_id: int, payload: dict = Depends(require_org_admin_or_above)
):
    """Mint a password-reset link for an account and return the raw token to send by hand.

    The counterpart to `POST /auth/reset-request`, which is the self-service door and stays
    exactly as it is: 204 always, token discarded, live the moment outbound mail works. This
    is the door that works today, and it mirrors
    `POST /{slug}/stakeholders/{id}/resend-invite` - an administrator issues the link, PAM or
    a person carries it. See svc_issue_reset_link for why returning the token is acceptable
    here and for the two guards a tier check cannot express.

    Gated on the platform tier rather than on `caller_roles`, and deliberately not widened to
    project_admin: resetting a login is account administration, not project content, and the
    reset it mints is global - the account it recovers may hold memberships on engagements
    the caller has nothing to do with. There is no slug in this URL for that reason, so there
    is no `check_project_access` call to make either.

    409 for a refusal, matching the other refusals on this router (ForbiddenRoleChange), and
    kept distinct from the 404 so an org_admin cannot read "not yours" as "does not exist"
    and enumerate other organisations' accounts by id.
    """
    try:
        result = await svc_issue_reset_link(user_id, calling_payload=payload)
    except AccountOutOfScope as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    if result is None:
        _404(f"User {user_id} not found")
    return result


@router.delete("/users/{user_id}", status_code=204)
async def delete_user_endpoint(user_id: int, payload: dict = Depends(require_org_admin_or_above)):
    """The dependency moved out of the decorator and into the signature so the handler can
    see who is calling. Deleting an account is administering it, and until this change
    nothing on this path asked whose account it was - there was no payload here to ask with.
    """
    try:
        deleted = await svc_delete_user(user_id, calling_payload=payload)
    except AccountOutOfScope as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    if not deleted:
        _404(f"User {user_id} not found")


# ── Project memberships ───────────────────────────────────────────────────────

@router.get("/users/{user_id}/projects", dependencies=[Depends(require_org_admin_or_above)])
async def list_user_projects(user_id: int):
    return await svc_list_user_projects(user_id)


# These two take their dependency in the signature rather than in the decorator, unlike
# their neighbours, because they need the payload: `check_project_access` is not a FastAPI
# dependency (it needs the slug at call time) and has to be called in the handler body.
#
# Why it belongs here at all. Every gate on this codebase's project doors ultimately reads
# `project_memberships`, so a door that *writes* that table without asking whose engagement
# the slug is decides the answer for all of them. Without the check an org_admin of one
# organisation could grant themselves - or anyone - a membership on another organisation's
# slug, and then walk through every `check_project_access` in the API as a legitimate
# member. The other holes closed on this branch bypassed the floor; this one manufactured
# it.
#
# Scoping, not new policy: `svc_create_user` already forces `org_id` to the caller's own,
# and `check_project_access`'s org_admin branch already compares `project_registry.org_id`
# against the JWT's. An org_admin acting outside their own organisation is refused
# everywhere the question has been asked - these two simply never asked. `sysadmin` keeps
# its early return, so administering across organisations remains a sysadmin capability.

@router.post("/users/{user_id}/projects/{slug}", status_code=201)
async def grant_project_access(
    user_id: int, slug: str, payload: dict = Depends(require_org_admin_or_above)
):
    await check_project_access(slug, payload)
    ok = await svc_grant_project_access(user_id, slug)
    if not ok:
        raise HTTPException(status_code=409, detail="Access already granted")
    return {"ok": True}


@router.delete("/users/{user_id}/projects/{slug}", status_code=204)
async def revoke_project_access(
    user_id: int, slug: str, payload: dict = Depends(require_org_admin_or_above)
):
    await check_project_access(slug, payload)
    await svc_revoke_project_access(user_id, slug)
