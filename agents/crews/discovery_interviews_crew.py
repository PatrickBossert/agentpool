# agents/crews/discovery_interviews_crew.py
"""Discovery Interviews crew — Interview Coordinator → Stakeholder Interviewer → Synthesis Analyst.

Interview scripts are designed upstream by the assessment_design crew (Interaction Designer).
This crew handles scheduling, conducting, and synthesising the interviews themselves.
"""
from crewai import Crew, Process, LLM
from agents.llm import get_pam_llm
from agents.tools.registry import get_tools_for_agent
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
    """Conduct and synthesise stakeholder interviews using pre-designed scripts.

    Interview scripts must already exist in outputs/interview_scripts.json (written by
    the assessment_design crew). This crew handles coordination, delivery, and synthesis.

    stakeholder_assignments: list of dicts with keys: name, job_title, level, node_label.
    """
    if llm is None:
        llm = get_pam_llm()

    assignments_str = _format_assignments(stakeholder_assignments)

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

    t1 = create_interview_coordinator_task(agent=coordinator, stakeholder_assignments=assignments_str, context=[])
    t2 = create_stakeholder_interviewer_task(agent=interviewer, context_tasks=[t1])
    t3 = create_synthesis_analyst_task(agent=analyst, context_tasks=[t2])

    return Crew(
        agents=[coordinator, interviewer, analyst],
        tasks=[t1, t2, t3],
        process=Process.sequential,
        verbose=True,
    )
