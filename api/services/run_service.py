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
import aiosqlite
from api.config import get_settings, load_project_config
from api.database import get_connection, update_crew_run_status, fetch_project, fetch_documents, fetch_stakeholder_assignments, fetch_stakeholders
from api.routers.ws import push_log


async def build_and_run_crew(slug: str, crew_name: str, run_id: int) -> Any:
    """Build the named crew, run it, and return the result. Does not update DB status."""
    settings = get_settings()
    config = load_project_config(Path(settings.projects_dir) / slug)
    llm_mode = config.get("llm_mode", "standard")
    sector = config.get("sector", "")

    if crew_name == "discovery_interviews":
        interview_method = config.get("interview_method", "none")
        if interview_method != "agent":
            raise ValueError(
                f"Cannot dispatch discovery_interviews crew: "
                f"interview_method is '{interview_method}', expected 'agent'"
            )

        # Recover orchestration_run_id from the crew_run row
        async with get_connection(slug) as conn:
            async with conn.execute(
                "SELECT orchestration_run_id FROM crew_runs WHERE id=?", (run_id,)
            ) as cur:
                cr_row = await cur.fetchone()
            orchestration_run_id = cr_row["orchestration_run_id"] if cr_row else None
            if not orchestration_run_id:
                raise ValueError(
                    f"crew_run {run_id} has no orchestration_run_id — "
                    "discovery_interviews must be dispatched via PAM"
                )

            # Fetch assignments and enrich with stakeholder details
            raw_assignments = await fetch_stakeholder_assignments(
                conn, orchestration_run_id=orchestration_run_id
            )
            project_row = await fetch_project(conn, slug=slug)
            all_stakeholders = await fetch_stakeholders(conn, project_id=project_row["id"])
            stakeholder_map = {s["id"]: s for s in all_stakeholders}

            stakeholder_assignments = [
                {
                    "stakeholder_id": a["stakeholder_id"],
                    "name": stakeholder_map.get(a["stakeholder_id"], {}).get("name", "Unknown"),
                    "job_title": stakeholder_map.get(a["stakeholder_id"], {}).get("job_title", ""),
                    "level": a["level"],
                    "node_label": a["node_label"],
                }
                for a in raw_assignments
                if a["stakeholder_id"] in stakeholder_map
            ]

        # Fetch node template assignments for script designer
        from api.database import fetch_node_template_assignments, get_system_db_path, init_system_db, fetch_template
        import json as _json

        node_templates = {}
        async with get_connection(slug) as conn:
            project = await fetch_project(conn, slug=slug)
            assignments = await fetch_node_template_assignments(conn, project["id"])
        for assignment in assignments:
            tid = assignment["interview_template_id"]
            if tid:
                # Fetch template schema from system.db
                sys_db_path = get_system_db_path()
                async with aiosqlite.connect(str(sys_db_path)) as sys_conn:
                    sys_conn.row_factory = aiosqlite.Row
                    await init_system_db(sys_conn)
                    tpl = await fetch_template(sys_conn, tid)
                if tpl:
                    try:
                        schema = _json.loads(tpl["schema_json"])
                    except Exception:
                        schema = None
                    node_templates[assignment["node_label"]] = schema

        node_templates_block = _json.dumps(node_templates, indent=2) if node_templates else ""

        from agents.crews.discovery_interviews_crew import create_discovery_interviews_crew
        crew = create_discovery_interviews_crew(
            slug=slug,
            run_id=run_id,
            llm_mode=llm_mode,
            sector=sector,
            stakeholder_assignments=stakeholder_assignments,
            discovery_brief=config.get("discovery_brief", ""),
            node_templates_block=node_templates_block,
        )

    elif crew_name == "discovery_mapping":
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
