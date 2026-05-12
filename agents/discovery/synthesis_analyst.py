# agents/discovery/synthesis_analyst.py
from crewai import Agent, Task, LLM
from crewai.tools import BaseTool


def create_synthesis_analyst(slug: str, llm: LLM, tools: list[BaseTool]) -> Agent:
    return Agent(
        role="Synthesis Analyst",
        goal=(
            "Synthesise stakeholder interview transcripts into structured discovery outputs: "
            "activity-level insights, a requirements register, and a value lever register."
        ),
        backstory=(
            "You are a senior strategy analyst who transforms raw interview data into "
            "structured consulting deliverables. You identify patterns across stakeholders, "
            "surface actors, needs, and frustrations at each process activity, and articulate "
            "the value levers that unlock transformation."
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
            "7. Produce a value lever register: identify 3–8 distinct value levers (themes "
            "of value creation). Each lever:\n"
            "   {\"lever\": \"Process Automation\", \"description\": \"...\", "
            "\"supporting_requirement_ids\": [\"REQ-001\"]}\n"
            "8. Use SQLiteStateTool with operation='write', key='value_levers', "
            "agent_name='synthesis_analyst' to save the value levers array.\n"
            "9. Use HumanInputTool with prompt: 'Please review the synthesis outputs: "
            "outputs/activity_insights.json, outputs/requirements.json, "
            "outputs/value_levers.json. Reply \"approved\" to proceed to Value Design, "
            "or provide revision notes.'\n"
            "10. If revision notes are received, revise the relevant outputs and call "
            "HumanInputTool again. Repeat at most 3 times total.\n"
        ),
        expected_output=(
            "Three JSON files saved via SQLiteStateTool: "
            "activity_insights (per-node actors/needs/frustrations), "
            "requirements (requirements register), "
            "value_levers (value lever register). "
            "Confirmed approved by a human reviewer."
        ),
        agent=agent,
        context=context_tasks,
    )
