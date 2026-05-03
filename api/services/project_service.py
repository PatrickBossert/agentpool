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
    update_project_config,
)
from api.models import ProjectCreate, ProjectSettings, OutputContent  # noqa: F401


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


async def get_project_settings(slug: str) -> dict | None:
    if not get_db_path(slug).exists():
        return None
    async with get_connection(slug) as conn:
        project = await fetch_project(conn, slug=slug)
        if not project:
            return None
        raw = project.get("config_json") or "{}"
        config = json.loads(raw)
        config.pop("client_slug", None)
        return config


async def update_project_settings(slug: str, settings: ProjectSettings) -> dict | None:
    if not get_db_path(slug).exists():
        return None
    settings_dict = settings.model_dump()
    full_config = {"client_slug": slug, **settings_dict}
    async with get_connection(slug) as conn:
        project = await fetch_project(conn, slug=slug)
        if not project:
            return None
        await update_project_config(
            conn,
            project_id=project["id"],
            llm_mode=settings.llm_mode,
            sector=settings.sector,
            config_json=json.dumps(full_config),
        )
    project_dir = Path(get_settings().projects_dir) / slug
    config_path = project_dir / "config.yaml"
    project_dir.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(dir=project_dir, suffix=".yaml.tmp")
    try:
        with os.fdopen(fd, "w") as f:
            yaml.dump(full_config, f, default_flow_style=False)
        os.replace(tmp_path, config_path)
    except Exception:
        os.unlink(tmp_path)
        raise
    return settings_dict


async def get_output_content(slug: str, output_id: int) -> dict | None:
    """Return file content for a given output record.

    Returns:
        None — project not found or output not found in this project's DB
        {"not_found_on_disk": True} — row exists but file deleted from disk
        {"content": str, "output_type": str} — success
    """
    if not get_db_path(slug).exists():
        return None
    async with get_connection(slug) as conn:
        project = await fetch_project(conn, slug=slug)
        if not project:
            return None
        async with conn.execute(
            "SELECT file_path, output_type FROM agent_outputs WHERE id=? AND project_id=?",
            (output_id, project["id"]),
        ) as cur:
            row = await cur.fetchone()
        if not row:
            return None
    file_path = Path(row["file_path"])
    if not file_path.exists():
        return {"not_found_on_disk": True}
    content = file_path.read_text(encoding="utf-8")
    return {"content": content, "output_type": row["output_type"]}


async def get_output_file(slug: str, output_id: int) -> dict | None:
    """Locate the file for a given output record.

    Returns:
        None — project not found or output not found in this project's DB
        {"not_found_on_disk": True} — row exists but file deleted from disk
        {"file_path": Path, "filename": str} — success
    """
    if not get_db_path(slug).exists():
        return None
    async with get_connection(slug) as conn:
        project = await fetch_project(conn, slug=slug)
        if not project:
            return None
        async with conn.execute(
            "SELECT file_path FROM agent_outputs WHERE id=? AND project_id=?",
            (output_id, project["id"]),
        ) as cur:
            row = await cur.fetchone()
        if not row:
            return None
    file_path = Path(row["file_path"])
    if not file_path.exists():
        return {"not_found_on_disk": True}
    return {"file_path": file_path, "filename": file_path.name}


async def get_roadmap_data(slug: str) -> dict | None:
    """Return parsed roadmap JSON for the Gantt tab.

    Returns:
        None — project not found or no roadmap_data output exists
        {"not_found_on_disk": True} — row exists but file deleted from disk
        dict — parsed roadmap_data JSON (periods, initiatives, etc.)
    """
    if not get_db_path(slug).exists():
        return None
    async with get_connection(slug) as conn:
        project = await fetch_project(conn, slug=slug)
        if not project:
            return None
        async with conn.execute(
            "SELECT file_path FROM agent_outputs "
            "WHERE project_id=? AND output_type=? ORDER BY created_at DESC LIMIT 1",
            (project["id"], "roadmap_data"),
        ) as cur:
            row = await cur.fetchone()
        if not row:
            return None
    file_path = Path(row["file_path"])
    if not file_path.exists():
        return {"not_found_on_disk": True}
    return json.loads(file_path.read_text(encoding="utf-8"))
