# api/routers/orchestrate.py
"""POST /projects/{slug}/orchestrate — start full PAM pipeline."""
from fastapi import APIRouter, HTTPException
from api.services.orchestration_service import start_orchestration

router = APIRouter(tags=["orchestration"])


@router.post("/projects/{slug}/orchestrate", status_code=202)
async def orchestrate_project(slug: str):
    try:
        orchestration_run_id = await start_orchestration(slug)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return {"orchestration_run_id": orchestration_run_id, "status": "running"}
