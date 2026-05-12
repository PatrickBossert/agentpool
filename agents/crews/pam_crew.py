# agents/crews/pam_crew.py
"""PAM orchestration crews — Phase 1 (mapping) and Phase 2 (resume pipeline)."""
from crewai import Crew, Process, LLM
from agents.llm import get_pam_llm
from agents.tools.registry import get_tools_for_agent
from agents.pam.pam_agent import (
    create_pam_agent,
    create_run_discovery_mapping_task,
    create_run_discovery_interviews_task,
    create_run_value_design_task,
    create_run_architecture_task,
    create_run_delivery_task,
    create_run_business_plan_task,
)


def create_pam_mapping_crew(
    slug: str,
    orchestration_run_id: int,
    llm_mode: str,
    llm: LLM | None = None,
) -> Crew:
    """Phase 1 PAM crew: runs discovery_mapping only.

    On completion the orchestration service sets status to 'awaiting_assignment'.
    """
    if llm is None:
        llm = get_pam_llm()

    tools = get_tools_for_agent("pam", slug=slug, run_id=orchestration_run_id)
    pam = create_pam_agent(slug=slug, llm=llm, tools=tools)
    t1 = create_run_discovery_mapping_task(agent=pam, slug=slug)

    return Crew(
        agents=[pam],
        tasks=[t1],
        process=Process.sequential,
        verbose=True,
    )


def create_pam_resume_crew(
    slug: str,
    orchestration_run_id: int,
    llm_mode: str,
    interview_method: str = "none",
    llm: LLM | None = None,
) -> Crew:
    """Phase 2 PAM crew: optionally discovery_interviews, then value_design → business_plan."""
    if llm is None:
        llm = get_pam_llm()

    tools = get_tools_for_agent("pam", slug=slug, run_id=orchestration_run_id)
    pam = create_pam_agent(slug=slug, llm=llm, tools=tools)

    tasks = []
    if interview_method == "agent":
        t_interviews = create_run_discovery_interviews_task(pam, slug=slug, context_tasks=[])
        tasks.append(t_interviews)
        context_for_value_design = [t_interviews]
    else:
        context_for_value_design = []

    t1 = create_run_value_design_task(pam, slug=slug, context_tasks=context_for_value_design)
    t2 = create_run_architecture_task(pam, slug=slug, context_tasks=[t1])
    t3 = create_run_delivery_task(pam, slug=slug, context_tasks=[t2])
    t4 = create_run_business_plan_task(pam, slug=slug, context_tasks=[t3])
    tasks += [t1, t2, t3, t4]

    return Crew(
        agents=[pam],
        tasks=tasks,
        process=Process.sequential,
        verbose=True,
    )
