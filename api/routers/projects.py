# api/routers/projects.py
from fastapi import APIRouter, HTTPException, Response
from api.database import get_db_path, get_connection, fetch_project, fetch_outputs_by_type
from api.models import ProjectCreate, StatusResponse, ProjectResponse
from api.services.project_service import create_project, get_project_status, list_all_projects

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
