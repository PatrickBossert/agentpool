# agents/crews/business_plan_crew.py
from crewai import Crew, Process, LLM
from agents.llm import get_pam_llm, get_crew_llm
from agents.tools.registry import get_tools_for_agent
from agents.business_plan.business_plan_generator import (
    create_business_plan_generator,
    create_business_plan_generator_task,
)


def create_business_plan_crew(
    slug: str,
    run_id: int,
    llm_mode: str,
    sector: str,
    llm: LLM | None = None,
) -> Crew:
    """
    Assemble and return the Business Plan Crew.

    Args:
        slug: Project slug (used for DB/file scoping).
        run_id: crew_runs.id for this execution (used by HumanInputTool).
        llm_mode: "standard" | "sensitive" | "fallback" — determines LLM routing.
        sector: Client sector (passed to tool registry).
        llm: Optional LLM override (used in tests to inject a cheap model).
    """
    if llm is not None:
        bpg_llm = llm  # test override
    elif llm_mode == "sensitive":
        bpg_llm = get_crew_llm("sensitive")  # local LLM for sensitive data
    else:
        bpg_llm = get_pam_llm()  # Claude Opus 4.6

    bpg = create_business_plan_generator(
        slug=slug,
        llm=bpg_llm,
        tools=get_tools_for_agent(
            "business_plan_generator", slug=slug, run_id=run_id, sector=sector
        ),
    )

    bpg_task = create_business_plan_generator_task(agent=bpg)

    return Crew(
        agents=[bpg],
        tasks=[bpg_task],
        process=Process.sequential,
        verbose=True,
    )
