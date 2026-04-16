# agents/crews/pam_crew.py
"""PAM orchestration crew — runs all five sub-crews sequentially."""
from crewai import Crew, Process, LLM
from agents.llm import get_pam_llm
from agents.tools.registry import get_tools_for_agent
from agents.pam.pam_agent import (
    create_pam_agent,
    create_run_discovery_task,
    create_run_value_design_task,
    create_run_architecture_task,
    create_run_delivery_task,
    create_run_business_plan_task,
)


def create_pam_crew(
    slug: str,
    orchestration_run_id: int,
    llm_mode: str,
    llm: LLM | None = None,
) -> Crew:
    """
    Assemble and return the PAM orchestration Crew.

    Args:
        slug: Project slug.
        orchestration_run_id: orchestration_runs.id for this pipeline run.
            Passed as run_id to the tool registry so RunCrewTool has it.
        llm_mode: "standard" | "sensitive" — PAM always uses Opus 4.6 unless
            a test injects a mock LLM.
        llm: Optional LLM override for tests.
    """
    if llm is None:
        llm = get_pam_llm()

    tools = get_tools_for_agent("pam", slug=slug, run_id=orchestration_run_id)

    pam = create_pam_agent(slug=slug, llm=llm, tools=tools)

    t1 = create_run_discovery_task(agent=pam, slug=slug)
    t2 = create_run_value_design_task(agent=pam, slug=slug, context_tasks=[t1])
    t3 = create_run_architecture_task(agent=pam, slug=slug, context_tasks=[t2])
    t4 = create_run_delivery_task(agent=pam, slug=slug, context_tasks=[t3])
    t5 = create_run_business_plan_task(agent=pam, slug=slug, context_tasks=[t4])

    return Crew(
        agents=[pam],
        tasks=[t1, t2, t3, t4, t5],
        process=Process.sequential,
        verbose=True,
    )
