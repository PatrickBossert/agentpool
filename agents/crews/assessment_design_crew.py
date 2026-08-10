# agents/crews/assessment_design_crew.py
from crewai import Crew, Process, LLM
from agents.model_registry import get_llm_for_agent
from agents.tools.registry import get_tools_for_agent
from agents.discovery.interaction_designer import (
    create_interaction_designer,
    create_interaction_designer_task,
)


def create_assessment_design_crew(
    slug: str,
    run_id: int,
    sector: str,
    standards_references: str = "",
    preferred_sections: int = 4,
    preferred_questions: int = 3,
    client_name: str = "",
    service_categories: str = "",
    key_vendors: str = "",
    applicable_regulations: str = "",
    llm: LLM | None = None,
) -> Crew:
    resolved_llm = llm or get_llm_for_agent("interaction_designer", slug)

    tools = get_tools_for_agent("interaction_designer", slug=slug, run_id=run_id, sector=sector)
    agent = create_interaction_designer(slug=slug, llm=resolved_llm, tools=tools)
    task = create_interaction_designer_task(
        agent=agent,
        standards_references=standards_references,
        preferred_sections=preferred_sections,
        preferred_questions=preferred_questions,
        client_name=client_name,
        service_categories=service_categories,
        key_vendors=key_vendors,
        applicable_regulations=applicable_regulations,
    )

    return Crew(
        agents=[agent],
        tasks=[task],
        process=Process.sequential,
        verbose=True,
    )
