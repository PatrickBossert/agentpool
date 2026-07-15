# agents/crews/stakeholder_management_crew.py
from crewai import Crew, Process, LLM
from agents.llm import get_crew_llm
from agents.tools.registry import get_tools_for_agent
from agents.discovery.stakeholder_manager_agent import (
    create_stakeholder_manager,
    create_stakeholder_manager_task,
)


def create_stakeholder_management_crew(
    slug: str,
    run_id: int,
    llm_mode: str,
    sector: str,
    public_interview_url_base: str = "",
    llm: LLM | None = None,
) -> Crew:
    if llm is None:
        llm = get_crew_llm(llm_mode)

    tools = get_tools_for_agent("stakeholder_manager", slug=slug, run_id=run_id, sector=sector)
    agent = create_stakeholder_manager(slug=slug, llm=llm, tools=tools)
    task = create_stakeholder_manager_task(
        agent=agent,
        project_slug=slug,
        public_interview_url_base=public_interview_url_base,
    )

    return Crew(
        agents=[agent],
        tasks=[task],
        process=Process.sequential,
        verbose=True,
    )
