# api/routers/outputs.py
from fastapi import APIRouter, Depends, HTTPException
from api.auth import require_any_auth, check_project_access
from api.models import OutputResponse
from api.services.project_service import get_project_outputs, get_project_status

router = APIRouter(prefix="/projects", tags=["outputs"])


@router.get("/{slug}/outputs", response_model=list[OutputResponse])
async def list_outputs(slug: str, payload: dict = Depends(require_any_auth)):
    await check_project_access(slug, payload)
    status = await get_project_status(slug)
    if not status:
        raise HTTPException(status_code=404, detail=f"Project '{slug}' not found")
    return await get_project_outputs(slug)
