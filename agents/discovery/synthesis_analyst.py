# agents/discovery/synthesis_analyst.py
from crewai import Agent, Task, LLM
from crewai.tools import BaseTool


def create_synthesis_analyst(slug: str, llm: LLM, tools: list[BaseTool]) -> Agent:
    return Agent(
        role="Synthesis Analyst",
        goal=(
            "Synthesise stakeholder interview transcripts into activity-level insights and "
            "the horizontal and vertical themes the evidence supports."
        ),
        backstory=(
            "You are a senior strategy analyst who transforms raw interview data into "
            "structured consulting deliverables. You identify patterns across stakeholders, "
            "surface actors, needs, and frustrations at each process activity, and separate "
            "themes that run horizontally across the value chain from those that run "
            "vertically within a discipline. You never assert a theme you cannot point at the "
            "interviews for."
        ),
        llm=llm,
        tools=tools,
        verbose=True,
        allow_delegation=False,
    )


def create_synthesis_analyst_task(
    agent: Agent,
    context_tasks: list[Task],
) -> Task:
    return Task(
        description=(
            "Synthesise interview transcripts into three structured outputs.\n\n"
            "Steps:\n"
            "1. Use SQLiteStateTool with operation='read', key='interview_transcripts', "
            "agent_name='synthesis_analyst' to retrieve all interview transcripts.\n"
            "2. Use SQLiteStateTool with operation='read', key='value_chain_tree', "
            "agent_name='synthesis_analyst' to retrieve the value chain node labels.\n"
            "3. Produce activity insights: for each L3 value chain node referenced in the "
            "transcripts, extract a JSON object:\n"
            "   {\n"
            "     \"label\": \"Goods-in Inspection\",\n"
            "     \"level\": \"L3\",\n"
            "     \"actors\": [\"Warehouse Operative\", \"Quality Inspector\"],\n"
            "     \"needs\": [\"Real-time visibility of delivery schedule\"],\n"
            "     \"frustrations\": [\"Manual paper-based receipt process causes delays\"]\n"
            "   }\n"
            "   Build an array covering every L3 node mentioned by at least one interviewee.\n"
            "4. Use SQLiteStateTool with operation='write', key='activity_insights', "
            "agent_name='synthesis_analyst' to save the activity insights array.\n"
            "5. Produce a requirements register: identify 5–15 discrete requirements surfaced "
            "across all transcripts. Each requirement:\n"
            "   {\"id\": \"REQ-001\", \"description\": \"...\", "
            "\"source_stakeholder_ids\": [1, 2], \"priority\": \"High|Medium|Low\"}\n"
            "6. Use SQLiteStateTool with operation='write', key='requirements', "
            "agent_name='synthesis_analyst' to save the requirements array.\n"
            "7. Produce the themes the evidence supports, of two kinds:\n"
            "   - horizontal: across the value chain, where digital transformation could "
            "improve efficiency or effectiveness;\n"
            "   - vertical: within a discipline - governance, data, a specific support "
            "service - where maturity could be raised.\n"
            "   Each theme:\n"
            "   {\"theme\": \"...\", \"kind\": \"horizontal|vertical\", \"description\": \"...\", "
            "\"activity_ids\": [\"1.2.3\", ...], \"evidence\": [{\"stakeholder_id\": 1, "
            "\"node_label\": \"...\", \"quote\": \"...\"}]}\n"
            "   Every theme carries at least two evidence entries from different stakeholders. "
            "A pattern seen in one transcript is an individual perspective, not a theme.\n"
            "8. Use SQLiteStateTool with operation='write', key='themes', "
            "agent_name='synthesis_analyst' to save the themes array.\n"
        ),
        expected_output=(
            "Three JSON files saved via SQLiteStateTool: "
            "activity_insights (per-node actors/needs/frustrations), "
            "requirements (requirements register), "
            "themes (horizontal and vertical themes, each evidenced by at least two "
            "stakeholders)."
        ),
        agent=agent,
        context=context_tasks,
    )
