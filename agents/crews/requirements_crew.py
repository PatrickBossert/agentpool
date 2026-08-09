# agents/crews/requirements_crew.py
from crewai import Crew, Process, LLM
from agents.model_registry import get_llm_for_agent
from agents.tools.registry import get_tools_for_agent
from agents.discovery.requirements_capture import (
    create_requirements_capture,
    create_requirements_capture_task,
)
from agents.discovery.requirements_analyst import (
    create_requirements_analyst,
    create_requirements_analyst_task,
)


def create_requirements_crew(
    slug: str,
    run_id: int,
    llm_mode: str,
    sector: str,
    llm: LLM | None = None,
    hitl_tool=None,
) -> Crew:
    """
    Assemble and return the Requirements Crew.

    Sam captures requirements and Riley analyses them for completeness, consistency and
    conflict. The crew runs seventh, after Capabilities has produced the initiatives the
    requirements are enumerated against.

    The value chain mapper used to be built here as well, back when this crew was called
    `discovery` and ran before value design. He belongs to `discovery_mapping` and running
    him a second time would overwrite an approved value chain, so he is gone from the crew
    and its brief and document arguments went with him - the value chain reaches this crew
    through state, not through an in-crew task context.

    Args:
        slug: Project slug (used for DB/file scoping).
        run_id: crew_runs.id for this execution (used by HumanInputTool).
        llm_mode: unused - kept for signature compatibility with run_service.py's callers.
            Each agent's model comes from agents/model_registry.get_llm_for_agent, which reads
            the project's own llm_mode. A branch here would be a second authority for it.
        sector: Client sector (used by ChromaQueryTool for sector knowledge base).
        llm: Optional LLM override (used in tests to inject a cheap model).
    """
    rc = create_requirements_capture(
        slug=slug,
        llm=llm or get_llm_for_agent("requirements_capture", slug),
        tools=get_tools_for_agent("requirements_capture", slug=slug, run_id=run_id, sector=sector, hitl_tool=hitl_tool),
    )
    ra = create_requirements_analyst(
        slug=slug,
        llm=llm or get_llm_for_agent("requirements_analyst", slug),
        tools=get_tools_for_agent("requirements_analyst", slug=slug, run_id=run_id, sector=sector, hitl_tool=hitl_tool),
    )

    rc_task = create_requirements_capture_task(agent=rc, context_tasks=[])
    ra_task = create_requirements_analyst_task(agent=ra, context_tasks=[rc_task])

    return Crew(
        agents=[rc, ra],
        tasks=[rc_task, ra_task],
        process=Process.sequential,
        verbose=True,
    )
