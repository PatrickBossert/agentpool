# api/routers/assignment.py
"""Assignment endpoints: GET/POST assignment data, PATCH advance orchestration."""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from api.auth import require_any_auth, require_org_admin_or_above, check_project_access
from api.database import (
    get_connection,
    fetch_project,
    fetch_stakeholder_assignments,
    replace_stakeholder_assignments,
    fetch_stakeholders,
    fetch_orchestration_run,
)
from api.services.project_service import get_value_chain_node_index, get_value_chain_tree
from api.services.orchestration_service import resume_orchestration

router = APIRouter(tags=["assignment"])


class AssignmentItem(BaseModel):
    """One stakeholder against one value chain node, cited by node id.

    No `level` and no `node_label`: both are facts about the node, read back from the
    value chain registry, and a copy on the assignment would drift away from the node it
    describes on the next run of the mapper.
    """
    stakeholder_id: int
    node_id: str


@router.get("/projects/{slug}/assignment")
async def get_assignment(slug: str, payload: dict = Depends(require_any_auth)):
    """Return value chain tree, the project's assignments, and the stakeholder list.

    No orchestration run is involved. The mapping is a project fact, so this answers
    before the first run has ever been started - which is the defect this replaced.
    """
    await check_project_access(slug, payload)
    async with get_connection(slug) as conn:
        project = await fetch_project(conn, slug=slug)
        if not project:
            raise HTTPException(status_code=404, detail=f"Project '{slug}' not found")
        assignments = await fetch_stakeholder_assignments(conn, project_id=project["id"])
        stakeholders = await fetch_stakeholders(conn, project_id=project["id"])

    value_chain_tree = await get_value_chain_tree(slug)
    nodes = get_value_chain_node_index(slug)

    return {
        "value_chain_tree": value_chain_tree or [],
        "assignments": [
            {
                **dict(a),
                "node_label": nodes.get(a["node_id"], {}).get("label", ""),
                "level": nodes.get(a["node_id"], {}).get("level", ""),
            }
            for a in assignments
        ],
        "stakeholders": [dict(s) for s in stakeholders],
    }


@router.post("/projects/{slug}/assignment")
async def save_assignment(slug: str, items: list[AssignmentItem], payload: dict = Depends(require_org_admin_or_above)):
    """Replace the project's whole stakeholder-to-node mapping.

    An empty list is accepted: unassigning the last stakeholder is an edit, and refusing
    it would leave the mapping impossible to clear.
    """
    await check_project_access(slug, payload)
    async with get_connection(slug) as conn:
        project = await fetch_project(conn, slug=slug)
        if not project:
            raise HTTPException(status_code=404, detail=f"Project '{slug}' not found")
        count = await replace_stakeholder_assignments(
            conn,
            project_id=project["id"],
            assignments=[a.model_dump() for a in items],
        )
    return {"saved": count}


@router.patch("/projects/{slug}/orchestration-runs/{orchestration_run_id}/advance")
async def advance_orchestration(slug: str, orchestration_run_id: int, payload: dict = Depends(require_org_admin_or_above)):
    """Advance an awaiting_assignment run to Phase 2 (triggers resume_orchestration)."""
    await check_project_access(slug, payload)
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
