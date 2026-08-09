# api/services/run_service.py
"""
Crew dispatch and build helpers.

build_and_run_crew() is a shared helper used by both dispatch_crew (REST path)
and RunCrewTool (PAM orchestration path).
dispatch_crew() is called by the run router via asyncio.create_task().
"""
import json
import logging
from pathlib import Path
from typing import Any
import aiosqlite
from api.config import get_settings, load_project_config
from api.database import get_connection, update_crew_run_status, fetch_project, fetch_documents, fetch_agent_outputs, fetch_stakeholder_assignments, fetch_stakeholders
from api.routers.ws import push_log

log = logging.getLogger(__name__)

# Crew name → snake_case agent names stored in agent_outputs.agent_name
_CREW_AGENT_NAMES: dict[str, list[str]] = {
    # Morgan reads levers and KPIs out of the documents, after Alex has given her the
    # chain to hang them on and before Maya designs instruments against them.
    "discovery_mapping":      ["value_chain_mapper", "value_lever_analyst"],
    "assessment_design":      ["interaction_designer"],
    "requirements":           ["requirements_capture", "requirements_analyst"],
    "stakeholder_management": ["stakeholder_manager"],
    "discovery_interviews":   ["interview_coordinator", "stakeholder_interviewer", "synthesis_analyst"],
    "value_design":           ["value_proposition_generator", "portfolio_manager"],
    "capabilities":           ["enterprise_architect", "initiative_identifier"],
    "delivery":               ["roadmap_generator"],
    # The Illustrator renders the value chain, the propositions, the roadmap and the
    # financials in one consistent style for the plan and the pitch pack. He was listed
    # under delivery on the org chart and dispatched by nothing at all.
    "business_plan":          ["business_plan_generator", "visual_illustrator"],
}

# Maps snake_case agent names (used in DB crew runs) to display names (used in agent_skills).
_SNAKE_TO_DISPLAY: dict[str, str] = {
    "value_chain_mapper":          "Value Chain Mapper",
    "interaction_designer":        "Interaction Designer",
    "requirements_capture":        "Requirements Capture",
    "requirements_analyst":        "Requirements Analyst",
    "value_lever_analyst":         "Value Lever Analyst",
    "stakeholder_manager":         "Stakeholder Manager",
    "interview_coordinator":       "Interview Coordinator",
    "stakeholder_interviewer":     "Stakeholder Interviewer",
    "synthesis_analyst":           "Synthesis Analyst",
    "value_proposition_generator": "Value Proposition Generator",
    "portfolio_manager":           "Portfolio Manager",
    "enterprise_architect":        "Enterprise Architect",
    "initiative_identifier":       "Initiative Identifier",
    "roadmap_generator":           "Roadmap Generator",
    "business_plan_generator":     "Business Plan Generator",
}


# Config keys a crew cannot run without, in the order their absence should be reported.
#
# build_and_run_crew raises below when one of these is empty. api/services/autostart_service.py
# reads the same map before it inserts a run, so an approval reports the crew as waiting on
# its configuration instead of starting a run that is certain to fail and mailing the
# approver that the crew they just approved has died. One map, read by both, so the check
# and the enforcement cannot drift apart.
REQUIRED_CONFIG_KEYS: dict[str, tuple[str, ...]] = {
    "delivery": ("value_stream_labels", "stakeholder_groups"),
}


def missing_config_keys(config: dict, crew_name: str) -> list[str]:
    """Which of this crew's required config keys are absent or empty, in declared order."""
    return [key for key in REQUIRED_CONFIG_KEYS.get(crew_name, ()) if not config.get(key)]


async def _fetch_skill_notes(crew_name: str) -> str:
    """Return stored skill notes and approved library skills for this crew's agents."""
    from api.database import get_system_connection, fetch_skill_notes as _fetch, fetch_skills
    agent_names = _CREW_AGENT_NAMES.get(crew_name, [])
    if not agent_names:
        return ""
    async with get_system_connection() as conn:
        notes: list[str] = []
        skills: list[str] = []
        seen_skill_ids: set[int] = set()
        for a in agent_names:
            rows = await _fetch(conn, agent_name=a)
            for r in rows:
                notes.append(f"- {r['note']}")
            display = _SNAKE_TO_DISPLAY.get(a)
            if display:
                skill_rows = await fetch_skills(conn, agent_name=display, status="approved")
                for s in skill_rows:
                    if s["id"] not in seen_skill_ids:
                        seen_skill_ids.add(s["id"])
                        skills.append(f"- {s['name']}: {s['description']}")
    sections: list[str] = []
    if notes:
        sections.append("SKILL IMPROVEMENT NOTES (apply these in your output):\n" + "\n".join(notes))
    if skills:
        sections.append("AGENT SKILLS (apply these capabilities in your work):\n" + "\n".join(skills))
    return "\n\n".join(sections)


# Which crew is answerable for each warning source. A warning is only useful to the agent
# that can act on it: Alex cannot fix a theme skew and Casey cannot add a root node.
_WARNING_SOURCE_CREW: dict[str, str] = {
    "value_chain_tree": "discovery_mapping",
    "theme_anchor": "discovery_interviews",
}


async def _fetch_validation_warnings(slug: str, crew_name: str) -> str:
    """Structural warnings this crew is answerable for, as a prompt block.

    open and acknowledged both reach the agent; dismissed does not. That asymmetry is the
    whole meaning of a disposition - acknowledged says "this is real, fix it", dismissed
    says "this is a false positive", and re-injecting a dismissed warning would make the
    dismissal pointless.

    This is the machine half of the feedback loop: no reviewer involvement, just an agent
    seeing what its last output was flagged for. The human half - a reviewer's note -
    arrives through _fetch_change_requests below.
    """
    from api.database import fetch_project, fetch_validation_warnings

    sources = [s for s, c in _WARNING_SOURCE_CREW.items() if c == crew_name]
    if not sources:
        return ""
    async with get_connection(slug) as conn:
        project = await fetch_project(conn, slug=slug)
        if not project:
            return ""
        rows = await fetch_validation_warnings(
            conn, project_id=project["id"], sources=sources,
            dispositions=["open", "acknowledged"],
        )
    if not rows:
        return ""
    lines = []
    for r in rows:
        subject = f"[{r['subject']}] " if r["subject"] else ""
        lines.append(f"- {subject}{r['detail']}")
    return (
        "STRUCTURAL WARNINGS (your last output was flagged for these; correct them):\n"
        + "\n".join(lines)
    )


async def _fetch_change_requests(slug: str, crew_name: str) -> tuple[str, list[int]]:
    """Open change requests for output types this crew's own agents produce, and the ids
    to close after.

    Scoped by output_type rather than pinned to one specific output_id: a request follows
    the artefact across versions, not the row it happened to be raised against. The old
    scoping (current output_id only) orphaned a request the moment the row it named stopped
    being current - either because the crew was re-run before a still-open review got
    resolved, or because a manual edit landed a new version afterwards. Gathering by type
    means a request against a since-superseded version is still reachable as long as this
    crew's own agents still hold the current version of that type.

    Ownership is still enforced per row via agent_name, exactly as the old scoping did -
    output_type only widens which of *this crew's own* rows are eligible, it is never used
    on its own. That matters because output_type is not unique to one crew: Portfolio
    Manager (value_design) and the Business Plan Generator (business_plan) both write
    output_type='excel'. Without the agent_name check, whichever crew's agent currently
    holds the live 'excel' row would also inherit the other crew's open request against it.
    tests/test_change_request_injection.py proves this does not happen.

    The injected text is deduplicated on the request string, first occurrence wins, but
    change_ids keeps every row regardless. RerunDialog's "Suggest a revision" posts the
    same note once per output in the crew (api/routers/reviews.py's submit_review then
    writes one output_changes row per POST), so without deduplication the same sentence
    would appear once per output the crew produces - the exact defect this wave exists to
    remove, reintroduced by fan-out instead of by double injection. Deduplicating change_ids
    itself instead would leave the un-deduplicated rows open forever, since only ids actually
    passed to mark_change_requests_applied ever close - assembly is the only layer that can
    fix the display without breaking the close.
    """
    from api.database import (
        fetch_agent_outputs, fetch_open_change_requests, fetch_project,
    )
    agents = set(_CREW_AGENT_NAMES.get(crew_name, []))
    if not agents:
        return "", []
    async with get_connection(slug) as conn:
        project = await fetch_project(conn, slug=slug)
        if not project:
            return "", []
        outputs = await fetch_agent_outputs(conn, project_id=project["id"])
        # Output types this crew's own agents currently hold the live version of.
        owned_types = {
            o["output_type"] for o in outputs
            if o["agent_name"] in agents and o.get("is_current")
        }
        # Every version of those types this crew's own agents ever produced, current or
        # not - agent_name is checked on every row, so widening past is_current can only
        # add this crew's own history, never another crew's.
        output_ids = [
            o["id"] for o in outputs
            if o["agent_name"] in agents and o["output_type"] in owned_types
        ]
        rows = await fetch_open_change_requests(conn, output_ids=output_ids)
    if not rows:
        return "", []
    seen_requests: set[str] = set()
    deduped_lines: list[str] = []
    for r in rows:
        if r["request"] not in seen_requests:
            seen_requests.add(r["request"])
            deduped_lines.append(f"- {r['request']}")
    header = (
        "REQUESTED CHANGES (a reviewer asked for these on your last output; apply them):\n"
    )
    return header + "\n".join(deduped_lines), [r["id"] for r in rows]


def make_step_callback(slug: str, crew_name: str):
    """Returns a sync step callback that pushes agent step events to the WebSocket.

    kickoff_async() runs the crew via asyncio.to_thread(), so the callback fires
    from a worker thread. We capture the running event loop here (in async context)
    and use run_coroutine_threadsafe to schedule push_log back on it.
    """
    import asyncio as _asyncio
    loop = _asyncio.get_event_loop()

    def _cb(step: Any) -> None:
        try:
            from crewai.agents.parser import AgentAction, AgentFinish
            if isinstance(step, AgentAction):
                inp = step.tool_input or ""
                if not isinstance(inp, str):
                    inp = json.dumps(inp)
                payload = json.dumps({
                    "type": "tool_use",
                    "crew": crew_name,
                    "tool": step.tool,
                    "input": inp[:150],
                })
            elif isinstance(step, AgentFinish):
                thought = (step.thought or "").strip()
                preview = (thought[:150] + "…") if len(thought) > 150 else thought
                payload = json.dumps({
                    "type": "agent_step",
                    "crew": crew_name,
                    "text": "Step completed",
                    "sub": preview,
                })
            else:
                return
            _asyncio.run_coroutine_threadsafe(push_log(slug, payload), loop)
        except Exception:
            pass
    return _cb


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

    elif crew_name == "requirements":
        from agents.crews.requirements_crew import create_requirements_crew

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

        crew = create_requirements_crew(
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

    elif crew_name == "capabilities":
        from agents.crews.capabilities_crew import create_capabilities_crew
        crew = create_capabilities_crew(slug=slug, run_id=run_id, llm_mode=llm_mode, sector=sector)

    elif crew_name == "delivery":
        missing = missing_config_keys(config, "delivery")
        if missing:
            named = ", ".join(repr(key) for key in missing)
            raise ValueError(f"Project config is missing {named} - required for Delivery crew")
        value_stream_labels = config.get("value_stream_labels", [])
        stakeholder_groups = config.get("stakeholder_groups", [])
        roadmap_time_axis = config.get("roadmap_time_axis", "quarters")
        from agents.crews.delivery_crew import create_delivery_crew
        crew = create_delivery_crew(
            slug=slug,
            run_id=run_id,
            llm_mode=llm_mode,
            sector=sector,
            value_stream_labels=value_stream_labels,
            stakeholder_groups=stakeholder_groups,
            roadmap_time_axis=roadmap_time_axis,
            client_name=config.get("client_name", slug),
        )

    elif crew_name == "business_plan":
        from agents.crews.business_plan_crew import create_business_plan_crew
        crew = create_business_plan_crew(
            slug=slug, run_id=run_id, llm_mode=llm_mode, sector=sector,
            client_name=config.get("client_name", slug),
        )

    elif crew_name in ("assessment_design", "questionnaire_builder"):
        # questionnaire_builder is kept as an alias for backward compatibility
        standards_references = config.get("standards_references", "")
        preferred_sections = config.get("preferred_questionnaire_sections", 4)
        preferred_questions = config.get("preferred_questions_per_section", 3)
        client_name = config.get("client_name", "")
        service_categories = config.get("service_categories", "")
        key_vendors = config.get("key_vendors", "")
        applicable_regulations = config.get("applicable_regulations", "")
        from agents.crews.assessment_design_crew import create_assessment_design_crew
        crew = create_assessment_design_crew(
            slug=slug,
            run_id=run_id,
            llm_mode=llm_mode,
            sector=sector,
            standards_references=standards_references,
            preferred_sections=preferred_sections,
            preferred_questions=preferred_questions,
            client_name=client_name,
            service_categories=service_categories,
            key_vendors=key_vendors,
            applicable_regulations=applicable_regulations,
        )

    elif crew_name == "stakeholder_management":
        public_url = config.get("public_url", "")
        public_interview_url_base = f"{public_url}/dashboard/interview" if public_url else ""
        from agents.crews.stakeholder_management_crew import create_stakeholder_management_crew
        crew = create_stakeholder_management_crew(
            slug=slug,
            run_id=run_id,
            llm_mode=llm_mode,
            sector=sector,
            public_interview_url_base=public_interview_url_base,
        )

    else:
        raise ValueError(f"Unknown crew: '{crew_name}'")

    crew.step_callback = make_step_callback(slug, crew_name)

    # A reviewer's note reaches the agent through _fetch_change_requests below, via
    # output_changes - not from here. human_reviews.notes / agent_outputs.reviewer_notes
    # are still written and still displayed in the UI (the revision dialog pre-populates
    # from them), but they are no longer injected directly: both doors that write
    # review_status='changes_requested' (POST /review and PATCH /reviews/{id}) also write
    # an output_changes row now, so injecting from here too would say the same thing twice.

    skill_notes = await _fetch_skill_notes(crew_name)
    if skill_notes:
        for task in crew.tasks:
            task.description = skill_notes + "\n\n" + task.description

    change_text, change_ids = await _fetch_change_requests(slug, crew_name)
    if change_text:
        for task in crew.tasks:
            task.description = change_text + "\n\n" + task.description

    warning_text = await _fetch_validation_warnings(slug, crew_name)
    if warning_text:
        for task in crew.tasks:
            task.description = warning_text + "\n\n" + task.description

    result = await crew.kickoff_async()

    if change_ids:
        try:
            async with get_connection(slug) as conn:
                from api.database import mark_change_requests_applied
                closed = await mark_change_requests_applied(
                    conn, change_ids=change_ids, run_id=run_id
                )
                if closed != len(change_ids):
                    # Zero is the ordinary shape of this mismatch - a concurrent duplicate
                    # run already closed some or all of them - but it looks identical here
                    # to a bug that silently failed to close any. Logging the actual counts
                    # is what tells the two apart after the fact.
                    log.warning(
                        "mark_change_requests_applied closed %d of %d requested for %s (run %s)",
                        closed, len(change_ids), crew_name, run_id,
                    )
        except Exception:
            # A request left open is re-injected next run, which is noisy but harmless.
            # Failing the run because bookkeeping failed would discard completed work.
            log.exception("could not close change requests for %s", crew_name)

    return result


_AUTO_ASSIGN_CREWS = {"discovery_interviews", "questionnaire_builder", "assessment_design"}


async def dispatch_crew(
    slug: str, crew_name: str, run_id: int, *, triggered_by: str | None = None
) -> None:
    """Entry point called by asyncio.create_task. Runs the named crew and updates status."""
    try:
        await push_log(slug, json.dumps({"type": "crew_started", "crew": crew_name, "run_id": run_id}))
        await build_and_run_crew(slug, crew_name, run_id)
        async with get_connection(slug) as conn:
            await update_crew_run_status(conn, run_id=run_id, status="completed")

        from api.services.commit_notify_service import notify_crew_awaiting_commit
        await notify_crew_awaiting_commit(slug, crew_name)

        # Auto-assign scripts to node templates after interview/questionnaire runs
        if crew_name in _AUTO_ASSIGN_CREWS:
            from api.services.auto_assign_service import (
                auto_assign_interview_scripts,
                auto_assign_questionnaire_scripts,
            )
            await auto_assign_interview_scripts(slug)
            await auto_assign_questionnaire_scripts(slug)
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

        from api.services.commit_notify_service import notify_crew_failed
        await notify_crew_failed(slug, crew_name, triggered_by=triggered_by)

        raise


# ── Standalone agent dispatch ──────────────────────────────────────────────────

# Which crew name to record in crew_runs for each agent key.
#
# Every key here MUST have a branch in build_and_run_agent. run_crew() checks
# membership of this dict and creates a crew_run row before dispatching, so a key
# without a branch produces a run that fails instantly with "Unknown agent key".
# tests/test_standalone_agent_dispatch.py enforces the invariant.
#
# questionnaire_builder is deliberately absent: its agent was removed when
# questionnaires moved inline into the interview. The crew-name alias in
# build_and_run_crew stays, for stored crew_run rows in other environments.
AGENT_CREW_NAME: dict[str, str] = {
    "requirements_analyst":        "requirements",
    "value_lever_analyst":         "discovery_mapping",
    "synthesis_analyst":           "discovery_interviews",
    "value_proposition_generator": "value_design",
    "portfolio_manager":           "value_design",
    "enterprise_architect":        "capabilities",
    "initiative_identifier":       "capabilities",
    "roadmap_generator":           "delivery",
    "business_plan_generator":     "business_plan",
    "interaction_designer":        "assessment_design",
    "stakeholder_manager":         "stakeholder_management",
}


async def build_and_run_agent(slug: str, agent_key: str, run_id: int) -> Any:
    """Build a single-agent crew and run it. Reads all state from SQLiteStateTool."""
    from crewai import Crew, Process
    from agents.model_registry import get_llm_for_agent
    from agents.tools.registry import get_tools_for_agent

    if agent_key not in AGENT_CREW_NAME:
        raise ValueError(f"Agent '{agent_key}' is not eligible for standalone dispatch")

    if agent_key == "synthesis_analyst":
        # Casey saturates the reasoning model, and during a campaign the fast model is answering
        # live follow-ups on the same machine. Inside the crew this cannot happen: the process is
        # sequential and Avery blocks on HumanInputTool until a consultant confirms interviews are
        # complete. Only this path bypasses that, so the refusal belongs here rather than in a
        # second general mechanism.
        from api.database import fetch_interview_sessions_status_for_project
        async with get_connection(slug) as conn:
            project = await fetch_project(conn, slug=slug)
            counts = (
                await fetch_interview_sessions_status_for_project(conn, project_id=project["id"])
                if project else {}
            )
        live = (counts.get("pending", 0) or 0) + (counts.get("active", 0) or 0)
        if live:
            raise ValueError(
                f"{live} interview session(s) are still pending or active. Casey reads the whole "
                f"corpus and would compete with the model answering live follow-ups. Wait for the "
                f"interviews to finish, or mark the outstanding sessions abandoned."
            )

    settings = get_settings()
    config = load_project_config(Path(settings.projects_dir) / slug)
    sector = config.get("sector", "")
    llm = get_llm_for_agent(agent_key, slug)
    tools = get_tools_for_agent(agent_key, slug=slug, run_id=run_id, sector=sector)

    if agent_key == "requirements_analyst":
        from agents.discovery.requirements_analyst import create_requirements_analyst, create_requirements_analyst_task
        agent_obj = create_requirements_analyst(slug=slug, llm=llm, tools=tools)
        task = create_requirements_analyst_task(agent=agent_obj, context_tasks=[])

    elif agent_key == "value_lever_analyst":
        from agents.discovery.value_lever_analyst import create_value_lever_analyst, create_value_lever_analyst_task
        agent_obj = create_value_lever_analyst(slug=slug, llm=llm, tools=tools)
        task = create_value_lever_analyst_task(agent=agent_obj, context_tasks=[])

    elif agent_key == "synthesis_analyst":
        from agents.discovery.synthesis_analyst import create_synthesis_analyst, create_synthesis_analyst_task
        agent_obj = create_synthesis_analyst(slug=slug, llm=llm, tools=tools)
        task = create_synthesis_analyst_task(agent=agent_obj, context_tasks=[])

    elif agent_key == "value_proposition_generator":
        from agents.value_design.value_proposition_generator import create_value_proposition_generator, create_value_proposition_generator_task
        agent_obj = create_value_proposition_generator(slug=slug, llm=llm, tools=tools)
        task = create_value_proposition_generator_task(agent=agent_obj)

    elif agent_key == "portfolio_manager":
        from agents.value_design.portfolio_manager import create_portfolio_manager, create_portfolio_manager_task
        agent_obj = create_portfolio_manager(slug=slug, llm=llm, tools=tools)
        task = create_portfolio_manager_task(agent=agent_obj, context_tasks=[])

    elif agent_key == "enterprise_architect":
        from agents.architecture.enterprise_architect import create_enterprise_architect, create_enterprise_architect_task
        agent_obj = create_enterprise_architect(slug=slug, llm=llm, tools=tools)
        task = create_enterprise_architect_task(agent=agent_obj)

    elif agent_key == "initiative_identifier":
        from agents.architecture.initiative_identifier import create_initiative_identifier, create_initiative_identifier_task
        agent_obj = create_initiative_identifier(slug=slug, llm=llm, tools=tools)
        task = create_initiative_identifier_task(agent=agent_obj, context_tasks=[])

    elif agent_key == "roadmap_generator":
        value_stream_labels = config.get("value_stream_labels", [])
        stakeholder_groups = config.get("stakeholder_groups", [])
        roadmap_time_axis = config.get("roadmap_time_axis", "quarters")
        if not value_stream_labels:
            raise ValueError("Project config missing 'value_stream_labels' — required for Roadmap Generator")
        from agents.delivery.roadmap_generator import create_roadmap_generator, create_roadmap_generator_task
        agent_obj = create_roadmap_generator(slug=slug, llm=llm, tools=tools)
        task = create_roadmap_generator_task(
            agent=agent_obj,
            value_stream_labels=value_stream_labels,
            stakeholder_groups=stakeholder_groups,
            roadmap_time_axis=roadmap_time_axis,
        )

    elif agent_key == "business_plan_generator":
        from agents.business_plan.business_plan_generator import create_business_plan_generator, create_business_plan_generator_task
        agent_obj = create_business_plan_generator(slug=slug, llm=llm, tools=tools)
        task = create_business_plan_generator_task(agent=agent_obj)

    elif agent_key == "interaction_designer":
        # Same construction as create_assessment_design_crew - that crew is this
        # single agent, so standalone dispatch and the crew must behave identically.
        from agents.discovery.interaction_designer import (
            create_interaction_designer,
            create_interaction_designer_task,
        )
        agent_obj = create_interaction_designer(slug=slug, llm=llm, tools=tools)
        task = create_interaction_designer_task(
            agent=agent_obj,
            standards_references=config.get("standards_references", ""),
            preferred_sections=config.get("preferred_questionnaire_sections", 4),
            preferred_questions=config.get("preferred_questions_per_section", 3),
            client_name=config.get("client_name", ""),
            service_categories=config.get("service_categories", ""),
            key_vendors=config.get("key_vendors", ""),
            applicable_regulations=config.get("applicable_regulations", ""),
        )

    elif agent_key == "stakeholder_manager":
        # Mirrors create_stakeholder_management_crew, which is also a single agent.
        from agents.discovery.stakeholder_manager_agent import (
            create_stakeholder_manager,
            create_stakeholder_manager_task,
        )
        public_url = config.get("public_url", "")
        agent_obj = create_stakeholder_manager(slug=slug, llm=llm, tools=tools)
        task = create_stakeholder_manager_task(
            agent=agent_obj,
            project_slug=slug,
            public_interview_url_base=f"{public_url}/dashboard/interview" if public_url else "",
        )

    else:
        raise ValueError(f"Unknown agent key: '{agent_key}'")

    crew = Crew(agents=[agent_obj], tasks=[task], process=Process.sequential, verbose=True)
    crew.step_callback = make_step_callback(slug, AGENT_CREW_NAME.get(agent_key, agent_key))
    return await crew.kickoff_async()


async def dispatch_agent(slug: str, agent_key: str, run_id: int) -> None:
    """Entry point for asyncio.create_task. Runs a single agent and updates crew_run status."""
    crew_label = AGENT_CREW_NAME.get(agent_key, agent_key)
    try:
        await push_log(slug, json.dumps({"type": "crew_started", "crew": crew_label, "run_id": run_id}))
        await build_and_run_agent(slug, agent_key, run_id)
        async with get_connection(slug) as conn:
            await update_crew_run_status(conn, run_id=run_id, status="completed")

        from api.services.commit_notify_service import notify_crew_awaiting_commit
        await notify_crew_awaiting_commit(slug, crew_label)

        await push_log(slug, json.dumps({"type": "crew_completed", "crew": crew_label, "run_id": run_id}))
    except Exception as e:
        try:
            async with get_connection(slug) as conn:
                await update_crew_run_status(conn, run_id=run_id, status="failed",
                                             result_json=json.dumps({"error": str(e)}))
        except Exception:
            pass
        await push_log(slug, json.dumps({"type": "crew_failed", "crew": crew_label, "error": str(e)}))
        raise
