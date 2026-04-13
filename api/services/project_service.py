# api/services/project_service.py
import json
import yaml
from pathlib import Path
from api.config import get_settings, load_project_config
from api.database import get_connection, insert_project, fetch_project
from api.models import ProjectCreate


async def create_project(req: ProjectCreate) -> dict:
    slug = req.client_slug
    settings = get_settings()

    # Create project directory structure
    project_dir = Path(settings.projects_dir) / slug
    (project_dir / "docs").mkdir(parents=True, exist_ok=True)
    (project_dir / "outputs").mkdir(parents=True, exist_ok=True)

    # Write config.yaml only if it doesn't exist (idempotent)
    config = req.model_dump()
    config_path = project_dir / "config.yaml"
    if not config_path.exists():
        with open(config_path, "w") as f:
            yaml.dump(config, f, default_flow_style=False)

    # Initialise SQLite DB and insert project
    async with get_connection(slug) as conn:
        await insert_project(
            conn,
            slug=slug,
            llm_mode=req.llm_mode,
            sector=req.sector,
            config_json=json.dumps(config),
        )
        return await fetch_project(conn, slug=slug)


async def get_project_status(slug: str) -> dict | None:
    from api.database import fetch_crew_runs
    async with get_connection(slug) as conn:
        project = await fetch_project(conn, slug=slug)
        if not project:
            return None
        runs = await fetch_crew_runs(conn, project_id=project["id"])
        return {"project_slug": slug, "project_status": project["status"], "crew_runs": runs}


async def get_project_outputs(slug: str) -> list[dict]:
    from api.database import fetch_agent_outputs
    async with get_connection(slug) as conn:
        project = await fetch_project(conn, slug=slug)
        if not project:
            return []
        return await fetch_agent_outputs(conn, project_id=project["id"])
