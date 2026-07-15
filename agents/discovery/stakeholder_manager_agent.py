# agents/discovery/stakeholder_manager_agent.py
"""Stakeholder Manager — actively manages stakeholder engagement, communications, and coverage."""
from crewai import Agent, Task, LLM
from crewai.tools import BaseTool


def create_stakeholder_manager(slug: str, llm: LLM, tools: list[BaseTool]) -> Agent:
    return Agent(
        role="Stakeholder Manager",
        goal=(
            "Ensure every value chain node has adequate stakeholder coverage by actively "
            "tracking engagement status, identifying gaps, prioritising outreach, and drafting "
            "targeted communications for stakeholders who have not yet responded."
        ),
        backstory=(
            "You are an experienced stakeholder engagement manager who combines analytical "
            "rigour with interpersonal intelligence. You know that interview coverage is only "
            "as good as the people who actually complete it, and you treat the engagement process "
            "as a project within the project. You monitor who has been invited, who has started "
            "but not finished, who has not been contacted at all, and which nodes remain "
            "uncovered or under-represented. You draft communications that are always respectful "
            "and professional — starting gentle and becoming progressively more direct without "
            "ever being discourteous. You also flag structural gaps where no suitable stakeholder "
            "has been identified for a node, so the project team can decide what to do."
        ),
        llm=llm,
        tools=tools,
        verbose=True,
        allow_delegation=False,
    )


def create_stakeholder_manager_task(
    agent: Agent,
    project_slug: str = "",
    public_interview_url_base: str = "",
) -> Task:
    url_block = (
        f"Interview URL base: {public_interview_url_base}\n"
        "When drafting invitation or reminder messages, include the stakeholder's personal "
        "interview link: {url_base}/{session_token}\n\n"
        if public_interview_url_base
        else ""
    )

    return Task(
        description=(
            "Review the current state of stakeholder engagement and produce a complete "
            "engagement status report and action plan.\n\n"
            f"{url_block}"
            "Steps:\n"
            "1. Use SQLiteStateTool with operation='read', key='value_chain_registry', "
            "agent_name='stakeholder_manager' to load all active L1, L2, and L3 nodes. "
            "This defines the full coverage target.\n"
            "2. Use SQLiteStateTool with operation='read', key='stakeholder_assignments', "
            "agent_name='stakeholder_manager' to understand which stakeholders are assigned "
            "to which nodes.\n"
            "3. Use SQLiteStateTool with operation='read', key='interview_sessions', "
            "agent_name='stakeholder_manager' to check the status of each interview session: "
            "pending (invited, not started), active (in progress), completed, or abandoned.\n"
            "4. Analyse coverage:\n"
            "   a) Identify nodes with NO stakeholder assigned at all (coverage gap).\n"
            "   b) Identify nodes with stakeholders assigned but NO sessions created (not yet invited).\n"
            "   c) Identify stakeholders with a 'pending' session older than 5 days (needs chasing).\n"
            "   d) Identify stakeholders with an 'abandoned' session (needs re-engagement).\n"
            "   e) Identify nodes with only one stakeholder completing (may need more perspectives).\n"
            "5. Draft stakeholder communications:\n"
            "   For each stakeholder who needs action, draft an appropriate message:\n"
            "   - NOT YET INVITED: A warm, professional invitation explaining the purpose of "
            "the interview, what to expect, and how long it will take (10–15 minutes).\n"
            "   - PENDING > 5 DAYS: A gentle first reminder that assumes busyness and offers "
            "a simple one-click link.\n"
            "   - PENDING > 10 DAYS: A firmer second reminder that emphasises the importance "
            "of their perspective and the upcoming deadline.\n"
            "   - ABANDONED: A brief re-engagement message acknowledging they started and "
            "inviting them to complete when ready.\n"
            "   All messages must be professional, concise (3–5 sentences), and personalised "
            "with the stakeholder's name and node context.\n"
            "6. Use SlackNotifyTool if available to send a coverage summary to the project "
            "team channel, including: total nodes, nodes with full coverage, nodes at risk, "
            "and count of pending outreach actions.\n"
            "7. Use SQLiteStateTool with operation='write', key='stakeholder_engagement_plan', "
            "agent_name='stakeholder_manager' to save the complete engagement status and "
            "action plan as structured JSON:\n"
            "   {\n"
            "     \"summary\": {\n"
            "       \"total_nodes\": N,\n"
            "       \"nodes_fully_covered\": N,\n"
            "       \"nodes_at_risk\": N,\n"
            "       \"nodes_uncovered\": N,\n"
            "       \"stakeholders_pending\": N,\n"
            "       \"stakeholders_completed\": N\n"
            "     },\n"
            "     \"coverage_gaps\": [ { \"node_label\": \"...\", \"level\": \"L2\", "
            "\"issue\": \"No stakeholder assigned\" } ],\n"
            "     \"outreach_actions\": [\n"
            "       { \"stakeholder_id\": N, \"name\": \"...\", \"node_label\": \"...\",\n"
            "         \"action_type\": \"invite|remind_1|remind_2|re_engage\",\n"
            "         \"draft_message\": \"...\" }\n"
            "     ]\n"
            "   }\n"
        ),
        expected_output=(
            "A structured JSON engagement plan saved to outputs/stakeholder_engagement_plan.json "
            "covering all nodes, identifying coverage gaps, and providing a prioritised list of "
            "outreach actions with drafted communications for each stakeholder who needs contact."
        ),
        agent=agent,
    )
