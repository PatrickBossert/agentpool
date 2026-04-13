# api/routers/projects.py
from fastapi import APIRouter, HTTPException, Response
from api.models import ProjectCreate, StatusResponse
from api.services.project_service import create_project, get_project_status

router = APIRouter(prefix="/projects", tags=["projects"])


@router.post("", status_code=201)
async def create_project_endpoint(req: ProjectCreate, response: Response):
    existing = await get_project_status(req.client_slug)
    if existing:
        response.status_code = 200
        return existing
    return await create_project(req)


@router.get("/{slug}/status", response_model=StatusResponse)
async def get_status(slug: str):
    result = await get_project_status(slug)
    if not result:
        raise HTTPException(status_code=404, detail=f"Project '{slug}' not found")
    return result
