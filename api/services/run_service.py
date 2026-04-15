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
        elif crew_name == "value_design":
            await _run_value_design_crew(slug=slug, run_id=run_id)
        elif crew_name == "architecture":
            await _run_architecture_crew(slug=slug, run_id=run_id)
        elif crew_name == "delivery":
            await _run_delivery_crew(slug=slug, run_id=run_id)
        elif crew_name == "business_plan":
            await _run_business_plan_crew(slug=slug, run_id=run_id)
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


async def _run_value_design_crew(slug: str, run_id: int) -> None:
    """Build and run the Value Design Crew asynchronously."""
    settings = get_settings()
    config = load_project_config(Path(settings.projects_dir) / slug)
    llm_mode = config.get("llm_mode", "standard")
    sector = config.get("sector", "")

    from agents.crews.value_design_crew import create_value_design_crew
    crew = create_value_design_crew(
        slug=slug,
        run_id=run_id,
        llm_mode=llm_mode,
        sector=sector,
    )
    # kickoff_async() runs the crew on the event loop without blocking
    await crew.kickoff_async()


async def _run_architecture_crew(slug: str, run_id: int) -> None:
    """Build and run the Architecture Crew asynchronously."""
    settings = get_settings()
    config = load_project_config(Path(settings.projects_dir) / slug)
    llm_mode = config.get("llm_mode", "standard")
    sector = config.get("sector", "")

    from agents.crews.architecture_crew import create_architecture_crew
    crew = create_architecture_crew(
        slug=slug,
        run_id=run_id,
        llm_mode=llm_mode,
        sector=sector,
    )
    # kickoff_async() runs the crew on the event loop without blocking
    await crew.kickoff_async()


async def _run_delivery_crew(slug: str, run_id: int) -> None:
    """Build and run the Delivery Planning Crew asynchronously."""
    settings = get_settings()
    config = load_project_config(Path(settings.projects_dir) / slug)
    llm_mode = config.get("llm_mode", "standard")
    sector = config.get("sector", "")
    value_stream_labels = config.get("value_stream_labels", [])
    stakeholder_groups = config.get("stakeholder_groups", [])
    roadmap_time_axis = config.get("roadmap_time_axis", "quarters")

    if not value_stream_labels:
        raise ValueError("Project config is missing 'value_stream_labels' — required for Delivery crew")
    if not stakeholder_groups:
        raise ValueError("Project config is missing 'stakeholder_groups' — required for Delivery crew")

    from agents.crews.delivery_crew import create_delivery_crew
    crew = create_delivery_crew(
        slug=slug,
        run_id=run_id,
        llm_mode=llm_mode,
        sector=sector,
        value_stream_labels=value_stream_labels,
        stakeholder_groups=stakeholder_groups,
        roadmap_time_axis=roadmap_time_axis,
    )
    # kickoff_async() runs the crew on the event loop without blocking
    await crew.kickoff_async()


async def _run_business_plan_crew(slug: str, run_id: int) -> None:
    """Build and run the Business Plan Crew asynchronously."""
    settings = get_settings()
    config = load_project_config(Path(settings.projects_dir) / slug)
    llm_mode = config.get("llm_mode", "standard")
    sector = config.get("sector", "")

    from agents.crews.business_plan_crew import create_business_plan_crew
    crew = create_business_plan_crew(
        slug=slug,
        run_id=run_id,
        llm_mode=llm_mode,
        sector=sector,
    )
    # kickoff_async() runs the crew on the event loop without blocking
    await crew.kickoff_async()
