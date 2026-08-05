# api/routers/runs.py
"""GET /projects/{slug}/runs — list orchestration run history."""
from fastapi import APIRouter, Depends, HTTPException
from api.auth import require_any_auth, check_project_access
from api.database import get_connection, get_db_path, fetch_project, fetch_blocked_writes
from api.services.project_service import get_run_history
from api.services.lineage_service import fetch_lineage, staleness, approved_versions

router = APIRouter(prefix="/projects", tags=["runs"])


@router.get("/{slug}/runs")
async def list_runs(slug: str, payload: dict = Depends(require_any_auth)):
    await check_project_access(slug, payload)
    result = await get_run_history(slug)
    if result is None:
        raise HTTPException(status_code=404, detail=f"Project '{slug}' not found")
    return result


@router.get("/{slug}/lineage")
async def get_lineage(slug: str, payload: dict = Depends(require_any_auth)):
    await check_project_access(slug, payload)
    if not get_db_path(slug).exists():
        raise HTTPException(status_code=404, detail=f"Project '{slug}' not found")

    async with get_connection(slug) as conn:
        project = await fetch_project(conn, slug=slug)
        if not project:
            raise HTTPException(status_code=404, detail=f"Project '{slug}' not found")

        outputs = await fetch_lineage(conn, project_id=project["id"])
        approvals = await approved_versions(conn, project_id=project["id"])
        blocked = await fetch_blocked_writes(conn)
        async with conn.execute(
            "SELECT id, original_name FROM client_documents WHERE project_id=?",
            (project["id"],),
        ) as cur:
            documents = {str(row[0]): row[1] async for row in cur}

    states = staleness(outputs, approvals)
    for output in outputs:
        output.update(states[output["id"]])
    return {"outputs": outputs, "documents": documents, "blocked_writes": blocked}
