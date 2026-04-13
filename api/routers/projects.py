# api/routers/projects.py
from fastapi import APIRouter, HTTPException, Response
from api.database import get_db_path
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
