# agents/crews/value_design_crew.py
from crewai import Crew, Process, LLM
from agents.llm import get_crew_llm, get_pam_llm, get_haiku_llm
from agents.tools.registry import get_tools_for_agent
from agents.value_design.value_proposition_generator import (
    create_value_proposition_generator,
    create_value_proposition_generator_task,
)
from agents.value_design.portfolio_manager import (
    create_portfolio_manager,
    create_portfolio_manager_task,
)


def create_value_design_crew(
    slug: str,
    run_id: int,
    llm_mode: str,
    sector: str,
    llm: LLM | None = None,
    hitl_tool=None,
) -> Crew:
    """
    Assemble and return the Value Design Crew.

    Args:
        slug: Project slug (used for DB/file scoping).
        run_id: crew_runs.id for this execution (used by HumanInputTool).
        llm_mode: "standard" | "sensitive" | "fallback" — determines LLM routing.
        sector: Client sector (unused by Value Design but kept for interface consistency).
        llm: Optional LLM override (used in tests to inject a cheap model for all agents).
    """
    if llm is not None:
        # Test override: use the same cheap model for all agents
        vpg_llm = pm_llm = llm
    elif llm_mode == "sensitive":
        # Sensitive mode: all agents use local LLM
        _local = get_crew_llm("sensitive")
        vpg_llm = pm_llm = _local
    else:
        # Production: per-spec model assignment
        vpg_llm = get_pam_llm()    # Claude Opus 4.6
        pm_llm = get_haiku_llm()   # Claude Haiku 4.5

    vpg = create_value_proposition_generator(
        slug=slug,
        llm=vpg_llm,
        tools=get_tools_for_agent("value_proposition_generator", slug=slug, run_id=run_id, sector=sector, hitl_tool=hitl_tool),
    )
    pm = create_portfolio_manager(
        slug=slug,
        llm=pm_llm,
        tools=get_tools_for_agent("portfolio_manager", slug=slug, run_id=run_id, sector=sector, hitl_tool=hitl_tool),
    )

    vpg_task = create_value_proposition_generator_task(agent=vpg)
    pm_task = create_portfolio_manager_task(agent=pm, context_tasks=[vpg_task])

    return Crew(
        agents=[vpg, pm],
        tasks=[vpg_task, pm_task],
        process=Process.sequential,
        verbose=True,
    )
