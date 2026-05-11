# agents/crews/discovery_mapping_crew.py
from crewai import Crew, Process, LLM
from agents.llm import get_crew_llm
from agents.tools.registry import get_tools_for_agent
from agents.discovery.value_chain_mapper import (
    create_value_chain_mapper,
    create_value_chain_mapper_task,
)


def create_discovery_mapping_crew(
    slug: str,
    run_id: int,
    llm_mode: str,
    sector: str,
    llm: LLM | None = None,
    hitl_tool=None,
    discovery_brief: str = "",
    discovery_links: list[dict] | None = None,
    priority_doc_names: list[str] | None = None,
) -> Crew:
    """Single-agent crew: runs Value Chain Mapper only.

    Args:
        slug: Project slug.
        run_id: crew_runs.id for this execution.
        llm_mode: LLM routing mode.
        sector: Client sector for ChromaDB sector queries.
        llm: Optional LLM override (used in tests).
        hitl_tool: Optional HumanInputTool override (used in tests).
        discovery_brief: Free-text research brief from project settings.
        discovery_links: List of {"url": str, "label": str} dicts.
        priority_doc_names: Original filenames of prioritised documents.
    """
    if llm is None:
        llm = get_crew_llm(llm_mode)

    vcm = create_value_chain_mapper(
        slug=slug,
        llm=llm,
        tools=get_tools_for_agent(
            "value_chain_mapper",
            slug=slug,
            run_id=run_id,
            sector=sector,
            hitl_tool=hitl_tool,
        ),
    )
    vcm_task = create_value_chain_mapper_task(
        agent=vcm,
        discovery_brief=discovery_brief,
        discovery_links=discovery_links,
        priority_doc_names=priority_doc_names,
    )

    return Crew(
        agents=[vcm],
        tasks=[vcm_task],
        process=Process.sequential,
        verbose=True,
    )
