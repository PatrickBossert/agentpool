# api/routers/run.py
import asyncio
from fastapi import APIRouter, Depends, HTTPException
from api.auth import require_org_admin_or_above, check_project_access
from api.database import get_connection, get_db_path, fetch_project, insert_crew_run
from api.models import RunRequest, RunResponse

router = APIRouter(prefix="/projects", tags=["run"])


@router.post("/{slug}/run", status_code=202, response_model=RunResponse)
async def run_crew(slug: str, req: RunRequest, payload: dict = Depends(require_org_admin_or_above)):
    await check_project_access(slug, payload)
    if not get_db_path(slug).exists():
        raise HTTPException(status_code=404, detail=f"Project '{slug}' not found")

    async with get_connection(slug) as conn:
        project = await fetch_project(conn, slug=slug)
        if not project:
            raise HTTPException(status_code=404, detail=f"Project '{slug}' not found")

        if req.agent:
            from api.services.run_service import dispatch_agent, AGENT_CREW_NAME
            if req.agent not in AGENT_CREW_NAME:
                raise HTTPException(status_code=400, detail=f"Agent '{req.agent}' is not eligible for standalone dispatch")
            crew_label = AGENT_CREW_NAME[req.agent]
            run_id = await insert_crew_run(
                conn, project_id=project["id"], crew_name=crew_label, status="running"
            )
            asyncio.create_task(dispatch_agent(slug=slug, agent_key=req.agent, run_id=run_id))
            return RunResponse(run_id=run_id, project_slug=slug, crew=crew_label, status="running")

        crew = req.crew or "discovery"
        run_id = await insert_crew_run(
            conn, project_id=project["id"], crew_name=crew, status="running"
        )

    from api.services.run_service import dispatch_crew
    asyncio.create_task(dispatch_crew(slug=slug, crew_name=crew, run_id=run_id))

    return RunResponse(run_id=run_id, project_slug=slug, crew=crew, status="running")
