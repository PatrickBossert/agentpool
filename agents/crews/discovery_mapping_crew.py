# agents/crews/discovery_mapping_crew.py
from crewai import Crew, Process, LLM
from agents.model_registry import get_llm_for_agent
from agents.tools.registry import get_tools_for_agent
from agents.discovery.value_chain_mapper import (
    create_value_chain_mapper,
    create_value_chain_mapper_task,
)
from agents.discovery.value_lever_analyst import (
    create_value_lever_analyst,
    create_value_lever_analyst_task,
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
        llm_mode: unused - kept for signature compatibility with run_service.py's callers.
            Each agent's model comes from agents/model_registry.get_llm_for_agent, which reads
            the project's own llm_mode. A branch here would be a second authority for it.
        sector: Client sector for ChromaDB sector queries.
        llm: Optional LLM override (used in tests).
        hitl_tool: Optional HumanInputTool override (used in tests).
        discovery_brief: Free-text research brief from project settings.
        discovery_links: List of {"url": str, "label": str} dicts.
        priority_doc_names: Original filenames of prioritised documents.
    """
    vcm = create_value_chain_mapper(
        slug=slug,
        llm=llm or get_llm_for_agent("value_chain_mapper", slug),
        tools=get_tools_for_agent(
            "value_chain_mapper",
            slug=slug,
            run_id=run_id,
            sector=sector,
            hitl_tool=hitl_tool,
        ),
    )
    # Morgan reads the levers and KPIs the organisation itself uses out of the documents.
    # Her only context is Alex's chain: she used to also take the requirements analysis,
    # which now runs five steps later, and taking it here would have been impossible.
    vla = create_value_lever_analyst(
        slug=slug,
        llm=llm or get_llm_for_agent("value_lever_analyst", slug),
        tools=get_tools_for_agent(
            "value_lever_analyst", slug=slug, run_id=run_id, sector=sector, hitl_tool=hitl_tool
        ),
    )

    vcm_task = create_value_chain_mapper_task(
        agent=vcm,
        discovery_brief=discovery_brief,
        discovery_links=discovery_links,
        priority_doc_names=priority_doc_names,
    )

    vla_task = create_value_lever_analyst_task(agent=vla, context_tasks=[vcm_task])

    return Crew(
        agents=[vcm, vla],
        tasks=[vcm_task, vla_task],
        process=Process.sequential,
        verbose=True,
    )
