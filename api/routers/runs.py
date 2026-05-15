# api/routers/runs.py
"""GET /projects/{slug}/runs — list orchestration run history."""
from fastapi import APIRouter, Depends, HTTPException
from api.auth import require_any_auth, check_project_access
from api.services.project_service import get_run_history

router = APIRouter(prefix="/projects", tags=["runs"])


@router.get("/{slug}/runs")
async def list_runs(slug: str, payload: dict = Depends(require_any_auth)):
    await check_project_access(slug, payload)
    result = await get_run_history(slug)
    if result is None:
        raise HTTPException(status_code=404, detail=f"Project '{slug}' not found")
    return result
