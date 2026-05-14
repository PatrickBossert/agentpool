# agents/crews/discovery_interviews_crew.py
"""Discovery Interviews crew — Script Designer → Interview Coordinator → Stakeholder Interviewer → Synthesis Analyst."""
from crewai import Crew, Process, LLM
from agents.llm import get_pam_llm
from agents.tools.registry import get_tools_for_agent
from agents.discovery.interview_script_designer import (
    create_interview_script_designer_agent,
    create_interview_script_designer_task,
)
from agents.discovery.interview_coordinator import (
    create_interview_coordinator,
    create_interview_coordinator_task,
)
from agents.discovery.stakeholder_interviewer import (
    create_stakeholder_interviewer,
    create_stakeholder_interviewer_task,
)
from agents.discovery.synthesis_analyst import (
    create_synthesis_analyst,
    create_synthesis_analyst_task,
)


def _format_assignments(stakeholder_assignments: list[dict]) -> str:
    """Format a list of assignment dicts into a human-readable block."""
    if not stakeholder_assignments:
        return "(No stakeholder assignments provided)"
    lines = []
    for a in stakeholder_assignments:
        stakeholder_id = a.get("stakeholder_id", "?")
        name = a.get("name", "Unknown")
        job_title = a.get("job_title", "")
        level = a.get("level", "")
        node_label = a.get("node_label", "")
        line = f"- [id:{stakeholder_id}] {name}"
        if job_title:
            line += f" ({job_title})"
        if level and node_label:
            line += f" → {level}: {node_label}"
        lines.append(line)
    return "\n".join(lines)


def create_discovery_interviews_crew(
    slug: str,
    run_id: int,
    llm_mode: str,
    sector: str,
    stakeholder_assignments: list[dict],
    discovery_brief: str = "",
    node_templates_block: str = "",
    llm: LLM | None = None,
    hitl_tool=None,
) -> Crew:
    """Create a sequential crew that conducts and synthesises stakeholder interviews.

    stakeholder_assignments: list of dicts with keys: name, job_title, level, node_label.
    """
    if llm is None:
        llm = get_pam_llm()

    assignments_str = _format_assignments(stakeholder_assignments)

    script_designer = create_interview_script_designer_agent(
        slug=slug,
        run_id=run_id,
        llm_mode=llm_mode,
        sector=sector,
        llm=llm,
        tools=get_tools_for_agent("interview_script_designer", slug=slug, run_id=run_id, sector=sector, hitl_tool=hitl_tool),
    )
    coordinator = create_interview_coordinator(
        slug=slug,
        llm=llm,
        tools=get_tools_for_agent("interview_coordinator", slug=slug, run_id=run_id, sector=sector, hitl_tool=hitl_tool),
    )
    interviewer = create_stakeholder_interviewer(
        slug=slug,
        llm=llm,
        tools=get_tools_for_agent("stakeholder_interviewer", slug=slug, run_id=run_id, sector=sector, hitl_tool=hitl_tool),
    )
    analyst = create_synthesis_analyst(
        slug=slug,
        llm=llm,
        tools=get_tools_for_agent("synthesis_analyst", slug=slug, run_id=run_id, sector=sector, hitl_tool=hitl_tool),
    )

    t0 = create_interview_script_designer_task(
        agent=script_designer,
        discovery_brief=discovery_brief,
        stakeholder_assignments_block=assignments_str,
        node_templates_block=node_templates_block,
    )
    t1 = create_interview_coordinator_task(agent=coordinator, stakeholder_assignments=assignments_str, context=[t0])
    t2 = create_stakeholder_interviewer_task(agent=interviewer, context_tasks=[t1])
    t3 = create_synthesis_analyst_task(agent=analyst, context_tasks=[t2])

    return Crew(
        agents=[script_designer, coordinator, interviewer, analyst],
        tasks=[t0, t1, t2, t3],
        process=Process.sequential,
        verbose=True,
    )
