# api/routers/outputs.py
import os
from fastapi import APIRouter, Depends, HTTPException
from api.auth import require_any_auth, check_project_access
from api.database import get_connection, fetch_project, revert_to_version
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


@router.post("/{slug}/outputs/{output_id}/revert", response_model=OutputResponse)
async def revert_output(slug: str, output_id: int, payload: dict = Depends(require_any_auth)):
    await check_project_access(slug, payload)
    async with get_connection(slug) as conn:
        project = await fetch_project(conn, slug=slug)
        if not project:
            raise HTTPException(status_code=404, detail=f"Project '{slug}' not found")
        row, paths_to_delete = await revert_to_version(conn, project_id=project["id"], output_id=output_id)
    if not row:
        raise HTTPException(status_code=404, detail=f"Output {output_id} not found")
    # Delete files for the removed versions from disk (ignore missing files)
    for path in paths_to_delete:
        try:
            os.unlink(path)
        except FileNotFoundError:
            pass
        # Also remove an associated .svg rendered alongside some outputs
        base, ext = os.path.splitext(path)
        if ext != '.svg':
            try:
                os.unlink(base + '.svg')
            except FileNotFoundError:
                pass
    return row
