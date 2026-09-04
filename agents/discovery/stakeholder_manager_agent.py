# agents/discovery/stakeholder_manager_agent.py
"""Stakeholder Manager - the stakeholder roster and its coverage of the value chain."""
from crewai import Agent, Task, LLM
from crewai.tools import BaseTool


def create_stakeholder_manager(slug: str, llm: LLM, tools: list[BaseTool]) -> Agent:
    return Agent(
        role="Stakeholder Manager",
        goal=(
            "Report how well the stakeholder roster covers the value chain: which activities "
            "have somebody who can speak for them, which have nobody, and which people on the "
            "roster are assigned to nothing."
        ),
        backstory=(
            "You are an experienced stakeholder engagement manager who combines analytical "
            "rigour with interpersonal intelligence. You own the stakeholder roster and its "
            "assignment to the value chain, and you know that a chain is only as well "
            "understood as the people speaking for its activities. You read the coverage as "
            "it stands, name the activities nobody has been assigned to, and name the people "
            "who have been assigned to nothing, so the engagement lead can decide what to do "
            "about either. You report the figures you are given rather than working them out "
            "again, and you leave the judgement about whether a gap matters to the person "
            "reading your report. The interview process itself - who is invited, who has "
            "started, who has finished, and what they are sent - belongs to the Interview "
            "Coordinator, not to you."
        ),
        llm=llm,
        tools=tools,
        verbose=True,
        allow_delegation=False,
    )


def create_stakeholder_manager_task(
    agent: Agent,
    project_slug: str = "",
    coverage_block: str = "",
) -> Task:
    """His task, with the mapping and its coverage prepended when the dispatch path supplies them.

    `coverage_block` defaults to empty so the factory's other callers - and the standalone
    `build_and_run_agent` path, which fetches nothing on an agent's behalf - still build a task.
    Step 2 below says where the mapping is in both cases, and in neither case does it send him
    back to `SQLiteStateTool`: that read was never once served, and an instruction to retry it
    would be an instruction to read an error message.

    The interview process is not his, and nothing here mentions it. He used to read
    `interview_sessions`, derive four session-state findings from it, and draft invitations,
    reminders and re-engagement messages; all of that belongs to the Interview Coordinator,
    who holds the tools for it. The breadth was legacy and it had already produced one live
    defect: the drafting step told him to emit `{url_base}/{session_token}` when he has no
    route to any stakeholder's session token, so the only way to satisfy it was to fabricate
    one - a well-formed dead link on the deployment's own domain. It had never fired only
    because the URL base was empty and falsy, which made repairing the base the moment the
    instruction would have armed. The `public_interview_url_base` parameter went with the
    step rather than being kept for a future consumer, for the same reason.
    """
    return Task(
        description=(
            f"{coverage_block}"
            "Report how well the stakeholder roster covers the value chain, and name the "
            "gaps on both sides of it.\n\n"
            "Steps:\n"
            "1. Use SQLiteStateTool with operation='read', key='value_chain_registry', "
            "agent_name='stakeholder_manager' to load all active nodes at every level, "
            "including the organisation node and its role nodes. This defines the full "
            "coverage target.\n"
            "2. Read the CURRENT STAKEHOLDER ASSIGNMENTS block at the top of this task for "
            "which stakeholders are assigned to which node ids. The mapping is a database "
            "table, not an output artefact, so SQLiteStateTool cannot reach it - it has been "
            "handed to you above instead. If no such block is present, the mapping was not "
            "supplied to this run: say so in your report and treat the assignments as "
            "unknown rather than as empty.\n"
            "3. Identify the nodes with NO stakeholder assigned at all (coverage gap). The "
            "COVERAGE block above already gives you both proportions and the node ids: carry "
            "those figures through unchanged rather than working them out again.\n"
            "4. Use SQLiteStateTool with operation='write', key='stakeholder_engagement_plan', "
            "agent_name='stakeholder_manager' to save the coverage report as structured "
            "JSON:\n"
            "   {\n"
            "     \"summary\": {\n"
            "       \"total_nodes\": N,\n"
            "       \"nodes_fully_covered\": N,\n"
            "       \"nodes_at_risk\": N,\n"
            "       \"nodes_uncovered\": N\n"
            "     },\n"
            "     \"assignment_coverage\": {\n"
            "       \"assignments\": [ { \"stakeholder_id\": N, \"name\": \"...\", "
            "\"node_id\": \"...\", \"node_label\": \"...\", \"level\": \"...\" } ],\n"
            "       \"activities_total\": N,\n"
            "       \"activities_uncovered\": N,\n"
            "       \"uncovered_proportion\": 0.0,\n"
            "       \"roster_total\": N,\n"
            "       \"stakeholders_unassigned\": N,\n"
            "       \"unassigned_proportion\": 0.0\n"
            "     },\n"
            "     \"coverage_gaps\": [ { \"node_id\": \"...\", \"node_label\": \"...\", "
            "\"level\": \"L2\", \"issue\": \"No stakeholder assigned\" } ]\n"
            "   }\n\n"
            "   Every figure in `assignment_coverage`, and the mapping itself, is copied from "
            "the block at the top of this task exactly as given. Report them; do not judge "
            "them. Whether a gap is acceptable is the engagement lead's call to make from the "
            "numbers, and several stakeholders on one activity is normal rather than a "
            "mismatch.\n\n"
            "   The interview process - who has been invited, who has started, who has "
            "finished, and what any of them are sent - is the Interview Coordinator's, not "
            "yours. Do not report on it, and do not draft any message to a stakeholder.\n"
        ),
        expected_output=(
            "A structured JSON coverage report saved to "
            "outputs/stakeholder_engagement_plan.json covering all nodes, reporting the "
            "stakeholder-to-activity mapping with the proportion of activities that have "
            "nobody and the proportion of the roster assigned to nothing, and identifying "
            "every node with no stakeholder assigned to it."
        ),
        agent=agent,
    )
