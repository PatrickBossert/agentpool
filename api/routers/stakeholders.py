# api/routers/stakeholders.py
"""CRUD + CSV import for project stakeholders.

Setting a role is a consequence, not a step: the moment any flag other than is_participant
is set on a stakeholder who holds no other role yet, an invite goes out (see
_issue_invite_if_newly_privileged below). A role that cannot be delivered - set with no
email - is refused with 422 rather than stored quietly; see _validate_deliverable_role.
"""
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from pydantic import BaseModel
from api.auth import require_any_auth, require_org_admin_or_above, check_project_access
from api.services.stakeholder_service import (
    list_stakeholders,
    create_stakeholder,
    update_stakeholder_svc,
    delete_stakeholder_svc,
    import_csv,
)
from api.services.invite_service import issue_invite
from api.database import (
    get_connection,
    fetch_project,
    fetch_stakeholder,
    get_stakeholder_node_assignments,
    upsert_stakeholder_node_assignments,
)

router = APIRouter(prefix="/projects", tags=["stakeholders"])


class StakeholderIn(BaseModel):
    name: str
    job_title: str = ""
    organisation: str = ""
    email: str = ""
    slack_handle: str = ""
    stakeholder_groups: list[str] = []
    project_role: str = "recipient"
    value_streams: list[str] = []
    value_chain_stage: str = ""
    activity: str = ""
    disposition: str = "neutral"
    location: str = ""
    country_code: str = ""
    timezone: str = ""
    preferred_language: str = ""
    currency: str = ""
    level: str = ""
    entity: str = ""
    mobile: str = ""
    comms_channel: str = "email"
    is_participant: bool = False
    is_reviewer: bool = False
    is_approver: bool = False


class StakeholderPatch(BaseModel):
    """Partial update - only fields actually supplied (model_dump(exclude_unset=True)) are
    changed. Unlike StakeholderIn's full-replace PUT, `name` is not required here."""
    name: str | None = None
    job_title: str | None = None
    organisation: str | None = None
    email: str | None = None
    slack_handle: str | None = None
    stakeholder_groups: list[str] | None = None
    project_role: str | None = None
    value_streams: list[str] | None = None
    value_chain_stage: str | None = None
    activity: str | None = None
    disposition: str | None = None
    location: str | None = None
    country_code: str | None = None
    timezone: str | None = None
    preferred_language: str | None = None
    currency: str | None = None
    level: str | None = None
    entity: str | None = None
    mobile: str | None = None
    comms_channel: str | None = None
    is_participant: bool | None = None
    is_reviewer: bool | None = None
    is_approver: bool | None = None


class NodeAssignmentItem(BaseModel):
    stakeholder_id: int
    node_key: str


class NodeAssignmentsIn(BaseModel):
    assignments: list[NodeAssignmentItem] = []


def _404(slug: str):
    raise HTTPException(status_code=404, detail=f"Project '{slug}' not found")


# Every role but participant confers some form of administration or review authority, so any
# of these being set is what makes a stakeholder somebody who needs a way to log in.
_ROLE_FLAGS = ("is_reviewer", "is_approver", "is_project_admin", "is_governor")


def _holds_other_role(flags: dict) -> bool:
    """Whether any role beyond is_participant is set on this (possibly partial) flag dict."""
    return any(flags.get(f) for f in _ROLE_FLAGS)


def _validate_deliverable_role(effective: dict) -> None:
    """Refuse rather than store quietly: a role that cannot be delivered - set with no
    address to deliver it to - is a state somebody must be told about. Applies on every
    write, not only the moment a role first appears, since Dougie McCrone's row already
    exists in this state on the live project and nothing today catches it."""
    if _holds_other_role(effective) and not (effective.get("email") or "").strip():
        raise HTTPException(
            status_code=422,
            detail="email is required to invite a stakeholder holding a role beyond participant",
        )


async def _fetch_stakeholder_row(slug: str, stakeholder_id: int) -> dict | None:
    async with get_connection(slug) as conn:
        project = await fetch_project(conn, slug=slug)
        if not project:
            return None
        return await fetch_stakeholder(conn, stakeholder_id=stakeholder_id, project_id=project["id"])


async def _issue_invite_if_newly_privileged(slug: str, before: dict | None, after: dict) -> None:
    """Setting any role other than participant on somebody with no linked login issues the
    invite - the moment it is first set, not on every later write that touches the row.

    A login is only created when an invite is accepted (see accept_token in
    invite_service.py), so at write time the row's own history is the only signal available:
    "no linked login" is operationalised here as "this record held no role beyond
    participant before this write". That is exactly what makes a second role on the same
    record (is_reviewer already true, is_approver newly added) a no-op rather than a second
    invite - `before` already carries the first role, so `had_role` is already true.
    """
    if not _holds_other_role(after):
        return
    had_role = _holds_other_role(before) if before else False
    if had_role:
        return
    await issue_invite(email=after["email"], project_slug=slug, stakeholder_id=after["id"])


@router.get("/{slug}/stakeholders")
async def list_stakeholders_endpoint(slug: str, payload: dict = Depends(require_any_auth)):
    await check_project_access(slug, payload)
    result = await list_stakeholders(slug)
    if result is None:
        _404(slug)
    return result


# IMPORTANT: /import must be registered BEFORE /{stakeholder_id} routes
@router.post("/{slug}/stakeholders/import")
async def import_stakeholders_endpoint(slug: str, file: UploadFile = File(...), payload: dict = Depends(require_org_admin_or_above)):
    await check_project_access(slug, payload)
    content = (await file.read()).decode("utf-8", errors="replace")
    result = await import_csv(slug, content)
    if result is None:
        _404(slug)
    return result


@router.post("/{slug}/stakeholders", status_code=201)
async def create_stakeholder_endpoint(slug: str, body: StakeholderIn, payload: dict = Depends(require_org_admin_or_above)):
    await check_project_access(slug, payload)
    data = body.model_dump()
    _validate_deliverable_role(data)
    result = await create_stakeholder(slug, data)
    if result is None:
        _404(slug)
    await _issue_invite_if_newly_privileged(slug, None, result)
    return result


@router.put("/{slug}/stakeholders/{stakeholder_id}")
async def update_stakeholder_endpoint(slug: str, stakeholder_id: int, body: StakeholderIn, payload: dict = Depends(require_org_admin_or_above)):
    await check_project_access(slug, payload)
    before = await _fetch_stakeholder_row(slug, stakeholder_id)
    data = body.model_dump()
    _validate_deliverable_role(data)
    result = await update_stakeholder_svc(slug, stakeholder_id, data)
    if result is None:
        raise HTTPException(status_code=404, detail="Stakeholder not found")
    await _issue_invite_if_newly_privileged(slug, before, result)
    return result


@router.patch("/{slug}/stakeholders/{stakeholder_id}")
async def patch_stakeholder_endpoint(slug: str, stakeholder_id: int, body: StakeholderPatch, payload: dict = Depends(require_org_admin_or_above)):
    """Partial update - only the fields the caller actually sent are changed. This is what
    lets a second role be granted (e.g. adding is_approver to an existing reviewer) without
    resending the whole record, and it is the write _issue_invite_if_newly_privileged must
    treat as a no-op rather than a second invite."""
    await check_project_access(slug, payload)
    before = await _fetch_stakeholder_row(slug, stakeholder_id)
    if before is None:
        raise HTTPException(status_code=404, detail="Stakeholder not found")
    patch_fields = body.model_dump(exclude_unset=True)
    if not patch_fields:
        return before
    effective = {**before, **patch_fields}
    _validate_deliverable_role(effective)
    result = await update_stakeholder_svc(slug, stakeholder_id, patch_fields)
    if result is None:
        raise HTTPException(status_code=404, detail="Stakeholder not found")
    await _issue_invite_if_newly_privileged(slug, before, result)
    return result


@router.delete("/{slug}/stakeholders/{stakeholder_id}", status_code=204)
async def delete_stakeholder_endpoint(slug: str, stakeholder_id: int, payload: dict = Depends(require_org_admin_or_above)):
    await check_project_access(slug, payload)
    result = await delete_stakeholder_svc(slug, stakeholder_id)
    if result is None:
        _404(slug)
    if result is False:
        raise HTTPException(status_code=404, detail="Stakeholder not found")


@router.get("/{slug}/stakeholder-assignments")
async def get_stakeholder_assignments_endpoint(slug: str, payload: dict = Depends(require_any_auth)):
    """Return all stakeholder-node assignments for a project."""
    await check_project_access(slug, payload)
    async with get_connection(slug) as conn:
        project = await fetch_project(conn, slug=slug)
        if not project:
            _404(slug)
        return await get_stakeholder_node_assignments(conn, project["id"])


@router.put("/{slug}/stakeholder-assignments")
async def put_stakeholder_assignments_endpoint(
    slug: str,
    body: NodeAssignmentsIn,
    payload: dict = Depends(require_org_admin_or_above),
):
    """Replace all stakeholder-node assignments for a project."""
    await check_project_access(slug, payload)
    async with get_connection(slug) as conn:
        project = await fetch_project(conn, slug=slug)
        if not project:
            _404(slug)
        assignments = [a.model_dump() for a in body.assignments]
        await upsert_stakeholder_node_assignments(conn, project["id"], assignments)
        return {"count": len(assignments)}
