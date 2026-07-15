# agents/crews/questionnaire_builder_crew.py
from crewai import Crew, Process, LLM
from agents.llm import get_crew_llm
from agents.tools.registry import get_tools_for_agent
from agents.discovery.questionnaire_builder import (
    create_questionnaire_builder,
    create_questionnaire_builder_task,
)


def create_questionnaire_builder_crew(
    slug: str,
    run_id: int,
    llm_mode: str,
    sector: str,
    standards_references: str = "",
    preferred_sections: int = 4,
    preferred_questions: int = 3,
    llm: LLM | None = None,
) -> Crew:
    if llm is None:
        llm = get_crew_llm(llm_mode)

    tools = get_tools_for_agent("questionnaire_builder", slug=slug, run_id=run_id, sector=sector)
    agent = create_questionnaire_builder(slug=slug, llm=llm, tools=tools)
    task = create_questionnaire_builder_task(
        agent=agent,
        standards_references=standards_references,
        preferred_sections=preferred_sections,
        preferred_questions=preferred_questions,
    )

    return Crew(
        agents=[agent],
        tasks=[task],
        process=Process.sequential,
        verbose=True,
    )
