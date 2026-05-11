# api/services/orchestration_service.py
"""Start and track full-pipeline PAM orchestration runs (two-phase)."""
import asyncio
import logging
from pathlib import Path
from api.config import get_settings, load_project_config

_log = logging.getLogger(__name__)
from api.database import (
    get_connection,
    fetch_project,
    insert_orchestration_run,
    update_orchestration_run_status,
)


async def start_orchestration(slug: str) -> int:
    """Insert an orchestration_run record and fire PAM Phase 1 as a background task.

    Returns the new orchestration_run_id.
    Raises ValueError if the project does not exist.
    """
    async with get_connection(slug) as conn:
        project = await fetch_project(conn, slug=slug)
        if not project:
            raise ValueError(f"Project '{slug}' not found")
        orchestration_run_id = await insert_orchestration_run(conn, project_id=project["id"])

    asyncio.create_task(run_pam_phase1(slug, orchestration_run_id))
    return orchestration_run_id


async def run_pam_phase1(slug: str, orchestration_run_id: int) -> None:
    """Run the mapping phase (discovery_mapping crew). On success set status to awaiting_assignment."""
    try:
        settings = get_settings()
        config = load_project_config(Path(settings.projects_dir) / slug)
        from agents.crews.pam_crew import create_pam_mapping_crew
        crew = create_pam_mapping_crew(
            slug=slug,
            orchestration_run_id=orchestration_run_id,
            llm_mode=config.get("llm_mode", "standard"),
        )
        await crew.kickoff_async()
        async with get_connection(slug) as conn:
            await update_orchestration_run_status(
                conn, run_id=orchestration_run_id, status="awaiting_assignment"
            )
    except Exception:
        _log.exception(
            "PAM phase1 failed for slug=%s orchestration_run_id=%d",
            slug,
            orchestration_run_id,
        )
        async with get_connection(slug) as conn:
            await update_orchestration_run_status(
                conn, run_id=orchestration_run_id, status="failed"
            )


async def resume_orchestration(slug: str, orchestration_run_id: int) -> None:
    """Set status to running and fire PAM Phase 2 (triggered by assignment confirmation)."""
    async with get_connection(slug) as conn:
        await update_orchestration_run_status(
            conn, run_id=orchestration_run_id, status="running"
        )
    asyncio.create_task(run_pam_phase2(slug, orchestration_run_id))


async def run_pam_phase2(slug: str, orchestration_run_id: int) -> None:
    """Run the resume phase (value_design → business_plan). On success set status to completed."""
    try:
        settings = get_settings()
        config = load_project_config(Path(settings.projects_dir) / slug)
        from agents.crews.pam_crew import create_pam_resume_crew
        crew = create_pam_resume_crew(
            slug=slug,
            orchestration_run_id=orchestration_run_id,
            llm_mode=config.get("llm_mode", "standard"),
        )
        await crew.kickoff_async()
        async with get_connection(slug) as conn:
            await update_orchestration_run_status(
                conn, run_id=orchestration_run_id, status="completed"
            )
    except Exception:
        _log.exception(
            "PAM phase2 failed for slug=%s orchestration_run_id=%d",
            slug,
            orchestration_run_id,
        )
        async with get_connection(slug) as conn:
            await update_orchestration_run_status(
                conn, run_id=orchestration_run_id, status="failed"
            )
