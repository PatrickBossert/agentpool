# agents/crews/delivery_crew.py
from crewai import Crew, Process, LLM
from agents.llm import get_crew_llm
from agents.tools.registry import get_tools_for_agent
from agents.delivery.roadmap_generator import (
    create_roadmap_generator,
    create_roadmap_generator_task,
)


def create_delivery_crew(
    slug: str,
    run_id: int,
    llm_mode: str,
    sector: str,
    value_stream_labels: list[str],
    stakeholder_groups: list[str],
    roadmap_time_axis: str,
    llm: LLM | None = None,
    hitl_tool=None,
) -> Crew:
    """
    Assemble and return the Delivery Planning Crew.

    Args:
        slug: Project slug (used for DB/file scoping).
        run_id: crew_runs.id for this execution (used by HumanInputTool).
        llm_mode: "standard" | "sensitive" | "fallback" — determines LLM routing.
        sector: Client sector (passed to tool registry for ChromaDB scoping).
        value_stream_labels: Value stream names from project config.
        stakeholder_groups: Stakeholder group names from project config.
        roadmap_time_axis: "quarters" | "years" | "horizons".
        llm: Optional LLM override (used in tests to inject a cheap model).
    """
    if llm is None:
        llm = get_crew_llm(llm_mode)  # Sonnet 4.6 (standard) or local (sensitive)

    rg = create_roadmap_generator(
        slug=slug,
        llm=llm,
        tools=get_tools_for_agent(
            "roadmap_generator", slug=slug, run_id=run_id, sector=sector, hitl_tool=hitl_tool
        ),
    )

    rg_task = create_roadmap_generator_task(
        agent=rg,
        value_stream_labels=value_stream_labels,
        stakeholder_groups=stakeholder_groups,
        roadmap_time_axis=roadmap_time_axis,
    )

    return Crew(
        agents=[rg],
        tasks=[rg_task],
        process=Process.sequential,
        verbose=True,
    )
