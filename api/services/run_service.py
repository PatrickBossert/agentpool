# api/services/run_service.py
"""
PAM orchestration layer.

dispatch_crew() is called by the run router via asyncio.create_task().
It loads the project config, builds the appropriate crew, runs it, and
writes the final status back to crew_runs.
"""
import json
from pathlib import Path
from api.config import get_settings, load_project_config
from api.database import get_connection, update_crew_run_status
from api.routers.ws import push_log


async def dispatch_crew(slug: str, crew_name: str, run_id: int) -> None:
    """Entry point called by asyncio.create_task. Runs the named crew and updates status."""
    try:
        await push_log(slug, json.dumps({"type": "crew_started", "crew": crew_name, "run_id": run_id}))
        if crew_name == "discovery":
            await _run_discovery_crew(slug=slug, run_id=run_id)
        else:
            raise ValueError(f"Unknown crew: '{crew_name}'")
        async with get_connection(slug) as conn:
            await update_crew_run_status(conn, run_id=run_id, status="completed")
        await push_log(slug, json.dumps({"type": "crew_completed", "crew": crew_name, "run_id": run_id}))
    except Exception as e:
        try:
            async with get_connection(slug) as conn:
                await update_crew_run_status(
                    conn,
                    run_id=run_id,
                    status="failed",
                    result_json=json.dumps({"error": str(e)}),
                )
        except Exception:
            pass  # Best-effort — don't mask the original exception
        await push_log(slug, json.dumps({"type": "crew_failed", "crew": crew_name, "error": str(e)}))
        raise


async def _run_discovery_crew(slug: str, run_id: int) -> None:
    """Build and run the Discovery Crew asynchronously."""
    settings = get_settings()
    config = load_project_config(Path(settings.projects_dir) / slug)
    llm_mode = config.get("llm_mode", "standard")
    sector = config.get("sector", "")

    from agents.crews.discovery_crew import create_discovery_crew
    crew = create_discovery_crew(
        slug=slug,
        run_id=run_id,
        llm_mode=llm_mode,
        sector=sector,
    )
    # kickoff_async() runs the crew on the event loop without blocking
    await crew.kickoff_async()
