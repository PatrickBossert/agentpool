# chainlit_app/app.py
"""
AgentPool Chainlit HITL interface.

Session flow:
  selecting_project  →  (enter project slug)
  selecting_crew     →  (enter crew name)
  running            →  crew runs; cl.AskUserMessage handles HITL transparently

HITL gates do NOT go through on_message — Chainlit handles cl.AskUserMessage
at the protocol level. The on_message handler only needs to manage project/crew
selection, not in-flight crew communication.
"""
import chainlit as cl
import httpx
from pathlib import Path

from api.config import get_settings, load_project_config
from api.database import (
    get_connection,
    fetch_project,
    insert_crew_run,
    update_crew_run_status,
)

FASTAPI_BASE = "http://localhost:8000"
_VALID_CREWS = frozenset(
    {"discovery", "value_design", "architecture", "delivery", "business_plan"}
)
_settings = get_settings()


# ── Chainlit handlers ────────────────────────────────────────────────────────


@cl.on_chat_start
async def start() -> None:
    cl.user_session.set("slug", None)
    cl.user_session.set("crew", None)
    await cl.Message(
        content=(
            "**AgentPool** — Digital Modernisation Agent Team\n\n"
            "Enter a project slug to begin (e.g. `acme-rail`)."
        )
    ).send()


@cl.on_message
async def handle_message(msg: cl.Message) -> None:
    slug = cl.user_session.get("slug")
    crew_name = cl.user_session.get("crew")

    if slug is None:
        await _handle_project_selection(msg.content.strip().lower())
        return

    if crew_name is None:
        await _handle_crew_selection(slug, msg.content.strip().lower())
        return

    # This branch should not be reached in normal operation:
    # cl.AskUserMessage handles HITL gates transparently without going through on_message.
    await cl.Message(content="Please respond to the agent prompt above.").send()


# ── Selection helpers ────────────────────────────────────────────────────────


async def _handle_project_selection(candidate: str) -> None:
    async with httpx.AsyncClient() as client:
        try:
            resp = await client.get(
                f"{FASTAPI_BASE}/projects/{candidate}/status", timeout=5.0
            )
        except Exception as e:
            await cl.Message(content=f"Could not reach API: {e}").send()
            return
    if resp.status_code == 200:
        cl.user_session.set("slug", candidate)
        await cl.Message(
            content=(
                f"Project **{candidate}** loaded.\n\n"
                "Which crew would you like to run?\n"
                "```\ndiscovery | value_design | architecture | delivery | business_plan\n```"
            )
        ).send()
    else:
        await cl.Message(
            content=(
                f"Project `{candidate}` not found. "
                "Create it first via the API, then try again."
            )
        ).send()


async def _handle_crew_selection(slug: str, crew_name: str) -> None:
    if crew_name not in _VALID_CREWS:
        await cl.Message(
            content=(
                f"Unknown crew `{crew_name}`. Choose one of:\n"
                "```\ndiscovery | value_design | architecture | delivery | business_plan\n```"
            )
        ).send()
        return
    cl.user_session.set("crew", crew_name)
    await _run_crew(slug, crew_name)
    cl.user_session.set("crew", None)  # ready for another run on the same project


# ── Crew execution ───────────────────────────────────────────────────────────


async def _run_crew(slug: str, crew_name: str) -> None:
    run_id: int | None = None
    try:
        run_id = await _create_run_record(slug, crew_name)

        from agents.tools.chainlit_human_input import ChainlitHumanInputTool
        hitl_tool = ChainlitHumanInputTool(slug=slug, run_id=run_id)

        config = load_project_config(Path(_settings.projects_dir) / slug)
        llm_mode = config.get("llm_mode", "standard")
        sector = config.get("sector", "")

        crew = _build_crew(crew_name, slug, run_id, llm_mode, sector, config, hitl_tool)

        await cl.Message(content=f"⚙ Running **{crew_name}** crew…").send()
        await crew.kickoff_async()

        await _mark_run_completed(slug, run_id, "completed")
        await _send_completion_message(slug)

    except Exception as e:
        if run_id is not None:
            await _mark_run_completed(slug, run_id, "failed")
        await cl.Message(content=f"✗ Crew failed: {e}").send()


def _build_crew(
    crew_name: str,
    slug: str,
    run_id: int,
    llm_mode: str,
    sector: str,
    config: dict,
    hitl_tool,
):
    """Dispatch to the correct crew factory based on crew_name."""
    base = dict(slug=slug, run_id=run_id, llm_mode=llm_mode, sector=sector, hitl_tool=hitl_tool)

    if crew_name == "discovery":
        from agents.crews.discovery_crew import create_discovery_crew
        return create_discovery_crew(**base)

    if crew_name == "value_design":
        from agents.crews.value_design_crew import create_value_design_crew
        return create_value_design_crew(**base)

    if crew_name == "architecture":
        from agents.crews.architecture_crew import create_architecture_crew
        return create_architecture_crew(**base)

    if crew_name == "delivery":
        from agents.crews.delivery_crew import create_delivery_crew
        value_stream_labels = config.get("value_stream_labels", [])
        stakeholder_groups = config.get("stakeholder_groups", [])
        roadmap_time_axis = config.get("roadmap_time_axis", "quarters")
        if not value_stream_labels:
            raise ValueError("Project config missing 'value_stream_labels'")
        if not stakeholder_groups:
            raise ValueError("Project config missing 'stakeholder_groups'")
        return create_delivery_crew(
            slug=slug,
            run_id=run_id,
            llm_mode=llm_mode,
            sector=sector,
            value_stream_labels=value_stream_labels,
            stakeholder_groups=stakeholder_groups,
            roadmap_time_axis=roadmap_time_axis,
            hitl_tool=hitl_tool,
        )

    if crew_name == "business_plan":
        from agents.crews.business_plan_crew import create_business_plan_crew
        return create_business_plan_crew(**base)

    raise ValueError(f"Unknown crew: {crew_name}")  # guarded by _VALID_CREWS check upstream


# ── DB helpers ───────────────────────────────────────────────────────────────


async def _create_run_record(slug: str, crew_name: str) -> int:
    async with get_connection(slug) as conn:
        project = await fetch_project(conn, slug=slug)
        if not project:
            raise ValueError(f"Project '{slug}' not found in database")
        run_id = await insert_crew_run(
            conn, project_id=project["id"], crew_name=crew_name, status="running"
        )
    return run_id


async def _mark_run_completed(slug: str, run_id: int, status: str) -> None:
    async with get_connection(slug) as conn:
        await update_crew_run_status(conn, run_id=run_id, status=status)


# ── Completion message ───────────────────────────────────────────────────────


async def _send_completion_message(slug: str) -> None:
    outputs_dir = Path(_settings.projects_dir) / slug / "outputs"
    lines = ["✓ Crew complete."]
    if outputs_dir.exists():
        files = sorted(f for f in outputs_dir.iterdir() if f.is_file())
        if files:
            lines.append("\nOutputs:")
            for f in files:
                size_kb = f.stat().st_size // 1024
                lines.append(f"• {f.name}  ({size_kb} KB)")
    await cl.Message(content="\n".join(lines)).send()
