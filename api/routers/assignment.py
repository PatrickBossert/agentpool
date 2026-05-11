# api/routers/assignment.py
"""Assignment endpoints: GET/POST assignment data, PATCH advance orchestration."""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from api.database import (
    get_connection,
    fetch_project,
    fetch_stakeholder_assignments,
    replace_stakeholder_assignments,
    fetch_stakeholders,
    fetch_orchestration_run,
)
from api.services.project_service import get_value_chain_tree
from api.services.orchestration_service import resume_orchestration

router = APIRouter(tags=["assignment"])


class AssignmentItem(BaseModel):
    stakeholder_id: int
    level: str
    node_label: str


@router.get("/projects/{slug}/assignment/{orchestration_run_id}")
async def get_assignment(slug: str, orchestration_run_id: int):
    """Return value chain tree, current assignments, and stakeholder list."""
    async with get_connection(slug) as conn:
        project = await fetch_project(conn, slug=slug)
        if not project:
            raise HTTPException(status_code=404, detail=f"Project '{slug}' not found")
        assignments = await fetch_stakeholder_assignments(
            conn, orchestration_run_id=orchestration_run_id
        )
        stakeholders = await fetch_stakeholders(conn, project_id=project["id"])

    value_chain_tree = await get_value_chain_tree(slug)

    return {
        "value_chain_tree": value_chain_tree or [],
        "assignments": [dict(a) for a in assignments],
        "stakeholders": [dict(s) for s in stakeholders],
    }


@router.post("/projects/{slug}/assignment/{orchestration_run_id}")
async def save_assignment(slug: str, orchestration_run_id: int, items: list[AssignmentItem]):
    """Replace all stakeholder assignments for an orchestration run."""
    if not items:
        raise HTTPException(status_code=422, detail="At least one assignment is required")
    async with get_connection(slug) as conn:
        project = await fetch_project(conn, slug=slug)
        if not project:
            raise HTTPException(status_code=404, detail=f"Project '{slug}' not found")
        count = await replace_stakeholder_assignments(
            conn,
            orchestration_run_id=orchestration_run_id,
            assignments=[a.model_dump() for a in items],
        )
    return {"saved": count}


@router.patch("/projects/{slug}/orchestration-runs/{orchestration_run_id}/advance")
async def advance_orchestration(slug: str, orchestration_run_id: int):
    """Advance an awaiting_assignment run to Phase 2 (triggers resume_orchestration)."""
    async with get_connection(slug) as conn:
        project = await fetch_project(conn, slug=slug)
        if not project:
            raise HTTPException(status_code=404, detail=f"Project '{slug}' not found")
        run = await fetch_orchestration_run(conn, run_id=orchestration_run_id)
        if not run:
            raise HTTPException(status_code=404, detail="Orchestration run not found")
        if run["status"] != "awaiting_assignment":
            raise HTTPException(
                status_code=400,
                detail=f"Cannot advance: run status is '{run['status']}', expected 'awaiting_assignment'",
            )
    await resume_orchestration(slug, orchestration_run_id)
    return {"status": "running"}
