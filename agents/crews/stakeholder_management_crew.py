# agents/crews/stakeholder_management_crew.py
from crewai import Crew, Process, LLM
from agents.model_registry import get_llm_for_agent
from agents.tools.registry import get_tools_for_agent
from agents.discovery.stakeholder_manager_agent import (
    create_stakeholder_manager,
    create_stakeholder_manager_task,
)


def _format_coverage(coverage: dict | None) -> str:
    """The mapping and both proportions, as the block prepended to Jordan's task.

    Rendered here rather than in the dispatch path, and computed there rather than here: the
    numbers are `api/services/assignment_coverage.py`'s single derivation, and this function
    only writes them down. It must not divide anything - a second arithmetic in the presentation
    layer is how the figure Jordan reports would come to differ from the one Pamela raises.
    """
    if coverage is None:
        return ""

    assignments = coverage.get("assignments") or []
    lines = [
        "CURRENT STAKEHOLDER ASSIGNMENTS",
        "",
        "This mapping is a durable project fact, made by hand in your Setup tab. It is given to "
        "you here because it lives in a database table rather than in an output artefact, so "
        "SQLiteStateTool cannot read it. Do not attempt to read `stakeholder_assignments` with "
        "any tool - this block is the whole of it.",
        "",
    ]

    if assignments:
        for a in assignments:
            title = f" ({a['job_title']})" if a.get("job_title") else ""
            level = f"{a['level']}: " if a.get("level") else ""
            lines.append(
                f"- [id:{a['stakeholder_id']}] {a['name']}{title} - "
                f"{a['node_id']} ({level}{a['node_label']})"
            )
    else:
        lines.append("- (nobody is assigned to any activity)")

    uncovered = coverage.get("uncovered_node_ids") or []
    unplaced = coverage.get("unassigned_stakeholders") or []

    lines += [
        "",
        "COVERAGE, ALREADY COMPUTED - REPORT THESE FIGURES AS THEY STAND",
        "",
        f"- Activities with no stakeholder: {coverage['activities_uncovered']} of "
        f"{coverage['activities_total']} active value chain activities "
        f"({coverage['uncovered_proportion'] * 100:.1f}%)",
        f"- Stakeholders assigned to nothing: {coverage['stakeholders_unassigned']} of "
        f"{coverage['roster_total']} on the roster "
        f"({coverage['unassigned_proportion'] * 100:.1f}%)",
        "",
        "Do not recompute either proportion, and do not round them differently. Several "
        "stakeholders on one activity is normal - especially for frontline work - and is never "
        "a mismatch. Full coverage is not expected, and its absence is not by itself a problem: "
        "report the numbers and leave the judgement to the person reading them.",
    ]

    if uncovered:
        lines += [
            "",
            "Activities with nobody assigned: " + ", ".join(uncovered),
        ]
    if unplaced:
        named = ", ".join(f"[id:{s['id']}] {s['name']}" for s in unplaced)
        lines += ["", "Stakeholders assigned to nothing: " + named]

    # Reported, not dropped. These rows are excluded from the mapping above and from both
    # proportions - nobody is interviewed about a retired activity - but an assignment that
    # silently disappeared would be worse than one that is named: somebody made it on
    # purpose, and it is the clearest evidence available that the chain has moved under the
    # mapping.
    off_chain = coverage.get("off_chain_assignments") or []
    if off_chain:
        lines += [
            "",
            "ASSIGNED TO ACTIVITIES THAT ARE NOT IN THE ACTIVE CHAIN",
            "",
            "Retired nodes, or ids the registry no longer holds. They are excluded from the "
            "mapping and from both figures above, because nobody is interviewed about them. "
            "Report them as a finding: somebody assigned these deliberately, and the chain "
            "has moved since.",
            "",
        ]
        for a in off_chain:
            lines.append(
                f"- [id:{a['stakeholder_id']}] {a['name']} - {a['node_id']} "
                f"({a['node_label']})"
            )

    return "\n".join(lines) + "\n"


def create_stakeholder_management_crew(
    slug: str,
    run_id: int,
    sector: str,
    public_interview_url_base: str = "",
    coverage: dict | None = None,
    llm: LLM | None = None,
) -> Crew:
    resolved_llm = llm or get_llm_for_agent("stakeholder_manager", slug)

    tools = get_tools_for_agent("stakeholder_manager", slug=slug, run_id=run_id, sector=sector)
    agent = create_stakeholder_manager(slug=slug, llm=resolved_llm, tools=tools)
    task = create_stakeholder_manager_task(
        agent=agent,
        project_slug=slug,
        public_interview_url_base=public_interview_url_base,
        coverage_block=_format_coverage(coverage),
    )

    return Crew(
        agents=[agent],
        tasks=[task],
        process=Process.sequential,
        verbose=True,
    )
