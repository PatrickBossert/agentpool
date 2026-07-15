# api/routers/stakeholders.py
"""CRUD + CSV import for project stakeholders."""
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
from api.database import (
    get_connection,
    fetch_project,
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


class NodeAssignmentItem(BaseModel):
    stakeholder_id: int
    node_key: str


class NodeAssignmentsIn(BaseModel):
    assignments: list[NodeAssignmentItem] = []


def _404(slug: str):
    raise HTTPException(status_code=404, detail=f"Project '{slug}' not found")


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
    result = await create_stakeholder(slug, body.model_dump())
    if result is None:
        _404(slug)
    return result


@router.put("/{slug}/stakeholders/{stakeholder_id}")
async def update_stakeholder_endpoint(slug: str, stakeholder_id: int, body: StakeholderIn, payload: dict = Depends(require_org_admin_or_above)):
    await check_project_access(slug, payload)
    result = await update_stakeholder_svc(slug, stakeholder_id, body.model_dump())
    if result is None:
        raise HTTPException(status_code=404, detail="Stakeholder not found")
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
