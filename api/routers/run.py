# api/routers/run.py
import asyncio
from fastapi import APIRouter, HTTPException
from api.database import get_connection, get_db_path, fetch_project, insert_crew_run
from api.models import RunRequest, RunResponse

router = APIRouter(prefix="/projects", tags=["run"])


@router.post("/{slug}/run", status_code=202, response_model=RunResponse)
async def run_crew(slug: str, req: RunRequest):
    if not get_db_path(slug).exists():
        raise HTTPException(status_code=404, detail=f"Project '{slug}' not found")

    crew = req.crew or "discovery"
    async with get_connection(slug) as conn:
        project = await fetch_project(conn, slug=slug)
        if not project:
            raise HTTPException(status_code=404, detail=f"Project '{slug}' not found")
        run_id = await insert_crew_run(
            conn, project_id=project["id"], crew_name=crew, status="running"
        )

    # Fire and forget — dispatch_crew runs in the background
    from api.services.run_service import dispatch_crew
    asyncio.create_task(dispatch_crew(slug=slug, crew_name=crew, run_id=run_id))

    return RunResponse(run_id=run_id, project_slug=slug, crew=crew, status="running")
