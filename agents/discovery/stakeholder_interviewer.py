# agents/discovery/stakeholder_interviewer.py
from crewai import Agent, Task, LLM
from crewai.tools import BaseTool


def create_stakeholder_interviewer(slug: str, llm: LLM, tools: list[BaseTool]) -> Agent:
    return Agent(
        role="Stakeholder Interviewer",
        goal=(
            "Orchestrate self-serve voice interview sessions, monitor completion, "
            "and collect transcripts from all participating stakeholders."
        ),
        backstory=(
            "You are an experienced discovery interviewer who coordinates asynchronous "
            "voice interviews. You create sessions in the portal, share links with the "
            "consultant, wait for stakeholder responses, then harvest transcripts for "
            "synthesis."
        ),
        llm=llm,
        tools=tools,
        verbose=True,
        allow_delegation=False,
    )


def create_stakeholder_interviewer_task(
    agent: Agent,
    context_tasks: list[Task],
) -> Task:
    return Task(
        description=(
            "Run the stakeholder interview sessions using a three-phase approach.\n\n"
            "── Phase 1: Create sessions ──\n"
            "1. Use SQLiteStateTool with operation='read', key='interview_plan', "
            "agent_name='stakeholder_interviewer' to retrieve the approved interview plan.\n"
            "2. Use InterviewSessionTool with operation='create', sessions=[<interview_plan array>] "
            "to insert one interview_sessions DB row per stakeholder (initial status: pending). "
            "Each row stores the session_token, stakeholder_id, node_label, and voice_config.\n"
            "3. Produce a formatted interview URL list, one line per stakeholder:\n"
            "   [Name] — [node_label] — https://interview.portal/s/[session_token]\n"
            "4. Use HumanInputTool with prompt:\n"
            "   'Interview sessions are live. Please share these links with your stakeholders:"
            "\\n\\n[URL list]\\n\\nReply \"ready\" when all interviews are complete, "
            "or \"partial\" to proceed with whoever has responded.'\n\n"
            "── Phase 2: Wait for completion ──\n"
            "5. When the consultant replies, use InterviewSessionTool with "
            "operation='get_status' to retrieve pending/active/completed/abandoned counts.\n"
            "6. If any sessions are still pending or active and the consultant replied "
            "'ready', flag the discrepancy and ask again via HumanInputTool:\n"
            "   'There are still [N] session(s) pending or active. "
            "Reply \"ready\" to proceed anyway, or \"wait\" to check again shortly.'\n"
            "   Repeat until the consultant confirms readiness or explicitly proceeds.\n\n"
            "── Phase 3: Collect transcripts ──\n"
            "7. Use InterviewSessionTool with operation='get_transcripts' to retrieve all "
            "completed session transcripts.\n"
            "8. Compile transcripts into a JSON array where each element is:\n"
            "   {\n"
            "     \"stakeholder_id\": 1,\n"
            "     \"name\": \"Alice Chen\",\n"
            "     \"node_labels\": [\"Goods-in Inspection\"],\n"
            "     \"qa_pairs\": [\n"
            "       {\"question\": \"Walk me through how an order is received.\", "
            "\"answer\": \"We receive orders via email...\"}\n"
            "     ]\n"
            "   }\n"
            "9. Use SQLiteStateTool with operation='write', key='interview_transcripts', "
            "agent_name='stakeholder_interviewer' to save the JSON array.\n"
        ),
        expected_output=(
            "A JSON interview_transcripts array saved via SQLiteStateTool, containing all "
            "Q&A pairs for every completed stakeholder interview session."
        ),
        agent=agent,
        context=context_tasks,
    )
