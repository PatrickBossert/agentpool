# agents/discovery/value_lever_analyst.py
from crewai import Agent, Task, LLM
from crewai.tools import BaseTool


def create_value_lever_analyst(slug: str, llm: LLM, tools: list[BaseTool]) -> Agent:
    return Agent(
        role="Value Lever Analyst",
        goal=(
            "Identify the highest-impact value levers for digital modernisation by connecting "
            "the requirements register to known transformation patterns and sector benchmarks."
        ),
        backstory=(
            "You are a transformation strategist with expertise in identifying where digital "
            "interventions create the most business value. You combine requirements analysis "
            "with market knowledge to pinpoint high-ROI modernisation opportunities."
        ),
        llm=llm,
        tools=tools,
        verbose=True,
        allow_delegation=False,
    )


def create_value_lever_analyst_task(
    agent: Agent, context_tasks: list[Task]
) -> Task:
    return Task(
        description=(
            "Identify the highest-impact value levers from the requirements register and value chain.\n\n"
            "Steps:\n"
            "1. Use SQLiteStateTool with operation='read', key='requirements', "
            "agent_name='value_lever_analyst' to retrieve the requirements.\n"
            "2. Use ChromaQueryTool with collection='sector' to retrieve known digital transformation "
            "patterns and value levers for this sector.\n"
            "3. Use TavilySearchTool to research best practices and benchmarks relevant to "
            "the top requirements.\n"
            "4. Produce a value levers analysis as a JSON array. Each lever must follow this schema:\n"
            "   {\"lever\": \"...\", \"description\": \"...\", \"value_impact\": \"high|medium|low\", "
            "\"effort\": \"high|medium|low\", \"related_requirements\": [\"REQ-001\", ...], "
            "\"evidence\": \"...\"}\n"
            "   Order levers by value_impact (high first), then by effort (low first).\n"
            "5. Use SQLiteStateTool with operation='write', key='value_levers', "
            "agent_name='value_lever_analyst' to save the JSON array.\n"
            "6. Use HumanInputTool with prompt: 'Please review the value levers analysis saved at "
            "outputs/value_levers.json. Reply \"approved\" to conclude the Discovery phase, "
            "or provide notes.'\n"
            "7. If revision notes are received, revise and call HumanInputTool again (maximum 3 times).\n"
        ),
        expected_output=(
            "A JSON value levers analysis saved to outputs/value_levers.json "
            "and confirmed approved by a human reviewer. "
            "Analysis must contain at least 3 levers each with lever, description, value_impact, "
            "effort, related_requirements, and evidence fields."
        ),
        agent=agent,
        context=context_tasks,
    )
