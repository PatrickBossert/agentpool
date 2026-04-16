# api/services/project_service.py
import json
import os
import tempfile
import yaml
from pathlib import Path
from api.config import get_settings
from api.database import (
    get_connection,
    get_db_path,
    insert_project,
    fetch_project,
    fetch_crew_runs,
    fetch_latest_orchestration_run,
    fetch_agent_outputs,
    list_projects,
)
from api.models import ProjectCreate


async def create_project(req: ProjectCreate) -> dict:
    slug = req.client_slug
    settings = get_settings()

    # Create project directory structure
    project_dir = Path(settings.projects_dir) / slug
    (project_dir / "docs").mkdir(parents=True, exist_ok=True)
    (project_dir / "outputs").mkdir(parents=True, exist_ok=True)

    # Write config.yaml atomically (tempfile + os.replace prevents partial writes)
    config = req.model_dump()
    config_path = project_dir / "config.yaml"
    if not config_path.exists():
        fd, tmp_path = tempfile.mkstemp(dir=project_dir, suffix=".yaml.tmp")
        try:
            with os.fdopen(fd, "w") as f:
                yaml.dump(config, f, default_flow_style=False)
            os.replace(tmp_path, config_path)
        except Exception:
            os.unlink(tmp_path)
            raise

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
    if not get_db_path(slug).exists():
        return None
    async with get_connection(slug) as conn:
        project = await fetch_project(conn, slug=slug)
        if not project:
            return None
        runs = await fetch_crew_runs(conn, project_id=project["id"])
        latest_orch = await fetch_latest_orchestration_run(conn, project_id=project["id"])
        return {
            "project_slug": slug,
            "project_status": project["status"],
            "crew_runs": runs,
            "latest_orchestration_run": latest_orch,
        }


async def get_project_outputs(slug: str) -> list[dict]:
    if not get_db_path(slug).exists():
        return []
    async with get_connection(slug) as conn:
        project = await fetch_project(conn, slug=slug)
        if not project:
            return []
        return await fetch_agent_outputs(conn, project_id=project["id"])


async def list_all_projects() -> list[dict]:
    """Return all projects across all project DBs."""
    settings = get_settings()
    db_dir = Path(settings.database_dir)
    if not db_dir.exists():
        return []
    results = []
    for db_file in sorted(db_dir.glob("*.db")):
        slug = db_file.stem
        if slug == "system":
            continue  # system.db holds users, not projects
        async with get_connection(slug) as conn:
            rows = await list_projects(conn)
            results.extend(rows)
    return results
