# agents/discovery/requirements_analyst.py
from crewai import Agent, Task, LLM
from crewai.tools import BaseTool


def create_requirements_analyst(slug: str, llm: LLM, tools: list[BaseTool]) -> Agent:
    return Agent(
        role="Requirements Analyst",
        goal=(
            "Synthesise the stakeholder interview transcript and client documents into a "
            "structured, prioritised requirements register ready for value design."
        ),
        backstory=(
            "You are a meticulous business analyst who specialises in translating messy "
            "stakeholder inputs into clear, actionable requirements. You are skilled at "
            "deduplication, prioritisation, and linking requirements to business outcomes."
        ),
        llm=llm,
        tools=tools,
        verbose=True,
        allow_delegation=False,
    )


def create_requirements_analyst_task(
    agent: Agent, context_tasks: list[Task]
) -> Task:
    return Task(
        description=(
            "Synthesise the interview transcript and client documents into a structured requirements register.\n\n"
            "Steps:\n"
            "1. Use SQLiteStateTool with operation='read', key='interview_transcript', "
            "agent_name='requirements_analyst' to retrieve the interview transcript.\n"
            "2. Use ChromaQueryTool with collection='project' to retrieve any additional context "
            "from client documents.\n"
            "3. Use ChromaQueryTool with collection='sector' to compare against sector-standard requirements.\n"
            "4. Produce a requirements register as a JSON array. Each requirement must follow this schema:\n"
            "   {\"id\": \"REQ-001\", \"description\": \"...\", \"source\": \"interview|document\", "
            "\"priority\": \"high|medium|low\", \"value_chain_activity\": \"...\", "
            "\"acceptance_criteria\": \"...\"}\n"
            "   Number requirements sequentially from REQ-001. Deduplicate overlapping requirements.\n"
            "5. Use SQLiteStateTool with operation='write', key='requirements', "
            "agent_name='requirements_analyst' to save the JSON array.\n"
            "6. Use HumanInputTool with prompt: 'Please review the requirements register saved at "
            "outputs/requirements.json. Reply \"approved\" to proceed, or provide notes.'\n"
            "7. If revision notes are received, revise and call HumanInputTool again (maximum 3 times).\n"
        ),
        expected_output=(
            "A JSON requirements register saved to outputs/requirements.json "
            "and confirmed approved by a human reviewer. "
            "Register must contain at least 3 requirements with id, description, source, "
            "priority, value_chain_activity, and acceptance_criteria fields."
        ),
        agent=agent,
        context=context_tasks,
    )
