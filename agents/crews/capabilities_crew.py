# agents/crews/capabilities_crew.py
from crewai import Crew, Process, LLM
from agents.model_registry import get_llm_for_agent
from agents.tools.registry import get_tools_for_agent
from agents.architecture.enterprise_architect import (
    create_enterprise_architect,
    create_enterprise_architect_task,
)
from agents.architecture.initiative_identifier import (
    create_initiative_identifier,
    create_initiative_identifier_task,
)


def create_capabilities_crew(
    slug: str,
    run_id: int,
    sector: str,
    llm: LLM | None = None,
) -> Crew:
    """
    Assemble and return the Architecture Crew.

    Args:
        slug: Project slug (used for DB/file scoping).
        run_id: crew_runs.id for this execution (used by HumanInputTool).
        sector: Client sector (used by ChromaQueryTool for sector knowledge base).
        llm: Optional LLM override (used in tests to inject a cheap model).
    """
    ea = create_enterprise_architect(
        slug=slug,
        llm=llm or get_llm_for_agent("enterprise_architect", slug),
        tools=get_tools_for_agent("enterprise_architect", slug=slug, run_id=run_id, sector=sector),
    )
    ii = create_initiative_identifier(
        slug=slug,
        llm=llm or get_llm_for_agent("initiative_identifier", slug),
        tools=get_tools_for_agent("initiative_identifier", slug=slug, run_id=run_id, sector=sector),
    )

    ea_task = create_enterprise_architect_task(agent=ea)
    ii_task = create_initiative_identifier_task(agent=ii, context_tasks=[ea_task])

    return Crew(
        agents=[ea, ii],
        tasks=[ea_task, ii_task],
        process=Process.sequential,
        verbose=True,
    )
