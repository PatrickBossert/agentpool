# api/routers/runs.py
"""GET /projects/{slug}/runs — list orchestration run history."""
from fastapi import APIRouter, HTTPException
from api.services.project_service import get_run_history

router = APIRouter(prefix="/projects", tags=["runs"])


@router.get("/{slug}/runs")
async def list_runs(slug: str):
    result = await get_run_history(slug)
    if result is None:
        raise HTTPException(status_code=404, detail=f"Project '{slug}' not found")
    return result
