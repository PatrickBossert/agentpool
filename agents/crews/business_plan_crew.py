# agents/crews/business_plan_crew.py
from crewai import Crew, Process, LLM
from agents.model_registry import get_llm_for_agent
from agents.tools.registry import get_tools_for_agent
from agents.delivery.visual_illustrator import (
    create_visual_illustrator,
    create_visual_illustrator_task,
)
from agents.business_plan.business_plan_generator import (
    create_business_plan_generator,
    create_business_plan_generator_task,
)


def create_business_plan_crew(
    slug: str,
    run_id: int,
    sector: str,
    llm: LLM | None = None,
    # Defaulted so every existing caller keeps working; run_service passes the real one.
    client_name: str = "",
) -> Crew:
    """
    Assemble and return the Business Plan Crew.

    Args:
        slug: Project slug (used for DB/file scoping).
        run_id: crew_runs.id for this execution (used by HumanInputTool).
        sector: Client sector (passed to tool registry).
        llm: Optional LLM override (used in tests to inject a cheap model).
    """
    bpg_llm = llm or get_llm_for_agent("business_plan_generator", slug)

    bpg = create_business_plan_generator(
        slug=slug,
        llm=bpg_llm,
        tools=get_tools_for_agent(
            "business_plan_generator", slug=slug, run_id=run_id, sector=sector
        ),
    )

    # The Illustrator renders the value chain, the propositions, the roadmap and the
    # financials in one consistent style. He sat in delivery, where he could only see the
    # roadmap; here everything he illustrates already exists.
    vi = create_visual_illustrator(
        slug=slug,
        llm=llm or get_llm_for_agent("visual_illustrator", slug),
        tools=get_tools_for_agent(
            "visual_illustrator", slug=slug, run_id=run_id, sector=sector
        ),
    )

    bpg_task = create_business_plan_generator_task(agent=bpg)
    vi_task = create_visual_illustrator_task(agent=vi, sector=sector, client_name=client_name)

    return Crew(
        agents=[bpg, vi],
        tasks=[bpg_task, vi_task],
        process=Process.sequential,
        verbose=True,
    )
