# api/routers/projects.py
from pathlib import Path
from fastapi import APIRouter, HTTPException, Response
from fastapi.responses import FileResponse
from api.database import get_db_path, get_connection, fetch_project, fetch_outputs_by_type
from api.models import ProjectCreate, ProjectSettings, OutputContent, StatusResponse, ProjectResponse
from api.services.project_service import (
    create_project,
    get_project_status,
    list_all_projects,
    get_project_settings,
    update_project_settings,
    get_output_content,
    get_output_file,
)

router = APIRouter(prefix="/projects", tags=["projects"])


@router.get("", response_model=list[ProjectResponse])
async def list_projects_endpoint():
    return await list_all_projects()


@router.post("", status_code=201)
async def create_project_endpoint(req: ProjectCreate, response: Response):
    if get_db_path(req.client_slug).exists():
        response.status_code = 200
    return await create_project(req)


@router.get("/{slug}/status", response_model=StatusResponse)
async def get_status(slug: str):
    result = await get_project_status(slug)
    if not result:
        raise HTTPException(status_code=404, detail=f"Project '{slug}' not found")
    return result


@router.get("/{slug}/value-chain")
async def get_value_chain(slug: str):
    if not get_db_path(slug).exists():
        raise HTTPException(status_code=404, detail=f"Project '{slug}' not found")
    async with get_connection(slug) as conn:
        project = await fetch_project(conn, slug=slug)
        if not project:
            raise HTTPException(status_code=404, detail=f"Project '{slug}' not found")
        return await fetch_outputs_by_type(conn, project_id=project["id"], output_type="value_chain")


@router.get("/{slug}/roadmap")
async def get_roadmap(slug: str):
    if not get_db_path(slug).exists():
        raise HTTPException(status_code=404, detail=f"Project '{slug}' not found")
    async with get_connection(slug) as conn:
        project = await fetch_project(conn, slug=slug)
        if not project:
            raise HTTPException(status_code=404, detail=f"Project '{slug}' not found")
        return await fetch_outputs_by_type(conn, project_id=project["id"], output_type="roadmap")


@router.get("/{slug}/settings", response_model=ProjectSettings)
async def get_settings_endpoint(slug: str):
    result = await get_project_settings(slug)
    if result is None:
        raise HTTPException(status_code=404, detail=f"Project '{slug}' not found")
    return result


@router.patch("/{slug}/settings", response_model=ProjectSettings)
async def patch_settings_endpoint(slug: str, req: ProjectSettings):
    result = await update_project_settings(slug, req)
    if result is None:
        raise HTTPException(status_code=404, detail=f"Project '{slug}' not found")
    return result


@router.get("/{slug}/outputs/{output_id}/content", response_model=OutputContent)
async def get_output_content_endpoint(slug: str, output_id: int):
    result = await get_output_content(slug, output_id)
    if result is None:
        raise HTTPException(status_code=404, detail=f"Output {output_id} not found for project '{slug}'")
    if result.get("not_found_on_disk"):
        raise HTTPException(status_code=404, detail="Output file not found on disk")
    return result


_CONTENT_TYPES = {
    ".md":   "text/markdown",
    ".html": "text/html",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
}


def _content_type(path: Path) -> str:
    return _CONTENT_TYPES.get(path.suffix.lower(), "application/octet-stream")


@router.get("/{slug}/outputs/{output_id}/download")
async def download_output_endpoint(slug: str, output_id: int):
    result = await get_output_file(slug, output_id)
    if result is None:
        raise HTTPException(status_code=404, detail=f"Output {output_id} not found for project '{slug}'")
    if result.get("not_found_on_disk"):
        raise HTTPException(status_code=404, detail="Output file not found on disk")
    file_path: Path = result["file_path"]
    filename: str = result["filename"]
    return FileResponse(
        path=file_path,
        filename=filename,
        media_type=_content_type(file_path),
        headers={"X-Filename": filename},
    )
