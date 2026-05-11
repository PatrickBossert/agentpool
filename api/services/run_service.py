# api/services/run_service.py
"""
Crew dispatch and build helpers.

build_and_run_crew() is a shared helper used by both dispatch_crew (REST path)
and RunCrewTool (PAM orchestration path).
dispatch_crew() is called by the run router via asyncio.create_task().
"""
import json
from pathlib import Path
from typing import Any
from api.config import get_settings, load_project_config
from api.database import get_connection, update_crew_run_status, fetch_project, fetch_documents
from api.routers.ws import push_log


async def build_and_run_crew(slug: str, crew_name: str, run_id: int) -> Any:
    """Build the named crew, run it, and return the result. Does not update DB status."""
    settings = get_settings()
    config = load_project_config(Path(settings.projects_dir) / slug)
    llm_mode = config.get("llm_mode", "standard")
    sector = config.get("sector", "")

    if crew_name == "discovery_mapping":
        from agents.crews.discovery_mapping_crew import create_discovery_mapping_crew

        discovery_brief = config.get("discovery_brief", "")
        discovery_links = config.get("discovery_links", [])
        discovery_document_ids = config.get("discovery_document_ids", [])

        priority_doc_names: list[str] = []
        if discovery_document_ids:
            async with get_connection(slug) as conn:
                project_row = await fetch_project(conn, slug=slug)
                if project_row:
                    all_docs = await fetch_documents(conn, project_id=project_row["id"])
                    doc_map = {d["id"]: d["original_name"] for d in all_docs}
                    priority_doc_names = [
                        doc_map[doc_id]
                        for doc_id in discovery_document_ids
                        if doc_id in doc_map
                    ]

        crew = create_discovery_mapping_crew(
            slug=slug,
            run_id=run_id,
            llm_mode=llm_mode,
            sector=sector,
            discovery_brief=discovery_brief,
            discovery_links=discovery_links,
            priority_doc_names=priority_doc_names,
        )

    elif crew_name == "discovery":
        from agents.crews.discovery_crew import create_discovery_crew

        discovery_brief = config.get("discovery_brief", "")
        discovery_links = config.get("discovery_links", [])
        discovery_document_ids = config.get("discovery_document_ids", [])

        priority_doc_names: list[str] = []
        if discovery_document_ids:
            async with get_connection(slug) as conn:
                project_row = await fetch_project(conn, slug=slug)
                if project_row:
                    all_docs = await fetch_documents(conn, project_id=project_row["id"])
                    doc_map = {d["id"]: d["original_name"] for d in all_docs}
                    priority_doc_names = [
                        doc_map[doc_id]
                        for doc_id in discovery_document_ids
                        if doc_id in doc_map
                    ]

        crew = create_discovery_crew(
            slug=slug,
            run_id=run_id,
            llm_mode=llm_mode,
            sector=sector,
            discovery_brief=discovery_brief,
            discovery_links=discovery_links,
            priority_doc_names=priority_doc_names,
        )

    elif crew_name == "value_design":
        from agents.crews.value_design_crew import create_value_design_crew
        crew = create_value_design_crew(slug=slug, run_id=run_id, llm_mode=llm_mode, sector=sector)

    elif crew_name == "architecture":
        from agents.crews.architecture_crew import create_architecture_crew
        crew = create_architecture_crew(slug=slug, run_id=run_id, llm_mode=llm_mode, sector=sector)

    elif crew_name == "delivery":
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

    elif crew_name == "business_plan":
        from agents.crews.business_plan_crew import create_business_plan_crew
        crew = create_business_plan_crew(slug=slug, run_id=run_id, llm_mode=llm_mode, sector=sector)

    else:
        raise ValueError(f"Unknown crew: '{crew_name}'")

    return await crew.kickoff_async()


async def dispatch_crew(slug: str, crew_name: str, run_id: int) -> None:
    """Entry point called by asyncio.create_task. Runs the named crew and updates status."""
    try:
        await push_log(slug, json.dumps({"type": "crew_started", "crew": crew_name, "run_id": run_id}))
        await build_and_run_crew(slug, crew_name, run_id)
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
