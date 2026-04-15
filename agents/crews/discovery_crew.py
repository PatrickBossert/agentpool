# agents/crews/discovery_crew.py
from crewai import Crew, Process, LLM
from agents.llm import get_crew_llm
from agents.tools.registry import get_tools_for_agent
from agents.discovery.value_chain_mapper import (
    create_value_chain_mapper,
    create_value_chain_mapper_task,
)
from agents.discovery.requirements_capture import (
    create_requirements_capture,
    create_requirements_capture_task,
)
from agents.discovery.requirements_analyst import (
    create_requirements_analyst,
    create_requirements_analyst_task,
)
from agents.discovery.value_lever_analyst import (
    create_value_lever_analyst,
    create_value_lever_analyst_task,
)


def create_discovery_crew(
    slug: str,
    run_id: int,
    llm_mode: str,
    sector: str,
    llm: LLM | None = None,
) -> Crew:
    """
    Assemble and return the Discovery Crew.

    Args:
        slug: Project slug (used for DB/file scoping).
        run_id: crew_runs.id for this execution (used by HumanInputTool).
        llm_mode: "standard" | "sensitive" | "fallback" — determines LLM routing.
        sector: Client sector (used by ChromaQueryTool for sector knowledge base).
        llm: Optional LLM override (used in tests to inject a cheap model).
    """
    if llm is None:
        llm = get_crew_llm(llm_mode)

    vcm = create_value_chain_mapper(
        slug=slug,
        llm=llm,
        tools=get_tools_for_agent("value_chain_mapper", slug=slug, run_id=run_id, sector=sector),
    )
    rc = create_requirements_capture(
        slug=slug,
        llm=llm,
        tools=get_tools_for_agent("requirements_capture", slug=slug, run_id=run_id, sector=sector),
    )
    ra = create_requirements_analyst(
        slug=slug,
        llm=llm,
        tools=get_tools_for_agent("requirements_analyst", slug=slug, run_id=run_id, sector=sector),
    )
    vla = create_value_lever_analyst(
        slug=slug,
        llm=llm,
        tools=get_tools_for_agent("value_lever_analyst", slug=slug, run_id=run_id, sector=sector),
    )

    vcm_task = create_value_chain_mapper_task(agent=vcm)
    rc_task = create_requirements_capture_task(agent=rc, context_tasks=[vcm_task], slug=slug)
    ra_task = create_requirements_analyst_task(agent=ra, context_tasks=[vcm_task, rc_task])
    vla_task = create_value_lever_analyst_task(agent=vla, context_tasks=[vcm_task, ra_task])

    return Crew(
        agents=[vcm, rc, ra, vla],
        tasks=[vcm_task, rc_task, ra_task, vla_task],
        process=Process.sequential,
        verbose=True,
    )
