# api/routers/admin.py
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from api.auth import require_sysadmin, require_org_admin_or_above, get_token_payload
from api.services.admin_service import (
    svc_list_orgs, svc_create_org, svc_get_org, svc_update_org, svc_delete_org,
    svc_list_org_members, svc_add_org_member, svc_update_org_member_role, svc_remove_org_member,
    svc_list_registry, svc_register_project, svc_unregister_project,
    svc_list_users, svc_create_user, svc_update_user, svc_delete_user,
    svc_list_user_projects, svc_grant_project_access, svc_revoke_project_access,
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
    if not await svc_delete_org(org_id):
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


@router.post("/orgs/{org_id}/members", status_code=201, dependencies=[Depends(require_org_admin_or_above)])
async def add_org_member(org_id: int, req: MemberAdd):
    ok = await svc_add_org_member(org_id, req.user_id, req.role)
    if not ok:
        raise HTTPException(status_code=409, detail="User already a member of this org")
    return {"ok": True}


@router.patch("/orgs/{org_id}/members/{user_id}", dependencies=[Depends(require_org_admin_or_above)])
async def update_org_member(org_id: int, user_id: int, req: MemberRoleUpdate):
    await svc_update_org_member_role(org_id, user_id, req.role)
    return {"ok": True}


@router.delete("/orgs/{org_id}/members/{user_id}", status_code=204, dependencies=[Depends(require_org_admin_or_above)])
async def remove_org_member(org_id: int, user_id: int):
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


@router.get("/users")
async def list_users(payload: dict = Depends(require_org_admin_or_above)):
    return await svc_list_users(payload)


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


@router.patch("/users/{user_id}", dependencies=[Depends(require_org_admin_or_above)])
async def update_user_endpoint(user_id: int, req: UserUpdate):
    user = await svc_update_user(user_id, req.email, req.role, req.password)
    if not user:
        _404(f"User {user_id} not found")
    return user


@router.delete("/users/{user_id}", status_code=204, dependencies=[Depends(require_org_admin_or_above)])
async def delete_user_endpoint(user_id: int):
    if not await svc_delete_user(user_id):
        _404(f"User {user_id} not found")


# ── Project memberships ───────────────────────────────────────────────────────

@router.get("/users/{user_id}/projects", dependencies=[Depends(require_org_admin_or_above)])
async def list_user_projects(user_id: int):
    return await svc_list_user_projects(user_id)


@router.post("/users/{user_id}/projects/{slug}", status_code=201, dependencies=[Depends(require_org_admin_or_above)])
async def grant_project_access(user_id: int, slug: str):
    ok = await svc_grant_project_access(user_id, slug)
    if not ok:
        raise HTTPException(status_code=409, detail="Access already granted")
    return {"ok": True}


@router.delete("/users/{user_id}/projects/{slug}", status_code=204, dependencies=[Depends(require_org_admin_or_above)])
async def revoke_project_access(user_id: int, slug: str):
    await svc_revoke_project_access(user_id, slug)
