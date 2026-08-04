# agents/discovery/requirements_capture.py
from crewai import Agent, Task, LLM
from crewai.tools import BaseTool


def create_requirements_capture(slug: str, llm: LLM, tools: list[BaseTool]) -> Agent:
    return Agent(
        role="Requirements Capture Specialist",
        goal=(
            "Enumerate the requirements each approved initiative places on data, people, "
            "process, decision flow, application and technology."
        ),
        backstory=(
            "You are an experienced business analyst who works from a defined scope rather "
            "than an open brief. Given a set of initiatives, you work through each one "
            "systematically across every requirement dimension, and you would rather record a "
            "dimension as 'none identified' than leave a reader guessing whether you "
            "considered it."
        ),
        llm=llm,
        tools=tools,
        verbose=True,
        allow_delegation=False,
    )


def create_requirements_capture_task(
    agent: Agent, context_tasks: list[Task]
) -> Task:
    return Task(
        description=(
            "Enumerate the requirements each approved initiative places on the organisation.\n\n"
            "Steps:\n"
            "1. Use SQLiteStateTool with operation='read', key='initiative_register', "
            "agent_name='requirements_capture' to retrieve the initiatives.\n"
            "2. Use SQLiteStateTool with operation='read', key='architecture_register', "
            "agent_name='requirements_capture' to retrieve the current-state capabilities, so "
            "each requirement is stated against what already exists.\n"
            "3. For every initiative in the register, work through all six dimensions - data, "
            "people, process, decision flow, application, and technology. Cover every "
            "initiative: an initiative absent from your output reads as having no requirements "
            "rather than as one you did not reach.\n"
            "4. Produce a JSON array. Each requirement:\n"
            "   {\"id\": \"REQ-001\", \"initiative_id\": \"...\", "
            "\"dimension\": \"data|people|process|decision_flow|application|technology\", "
            "\"description\": \"...\", \"rationale\": \"...\", "
            "\"priority\": \"High|Medium|Low\"}\n"
            "   Where a dimension genuinely carries no requirement for an initiative, record it "
            "with description 'none identified' and say why in rationale - a silent omission "
            "cannot be told apart from an oversight.\n"
            "5. Use SQLiteStateTool with operation='write', key='captured_requirements', "
            "agent_name='requirements_capture' to save the JSON array.\n"
        ),
        expected_output=(
            "A JSON requirement set saved via SQLiteStateTool under key "
            "'captured_requirements', covering every initiative in the register across all six "
            "requirement dimensions, each entry carrying id, initiative_id, dimension, "
            "description, rationale, and priority."
        ),
        agent=agent,
        context=context_tasks,
    )
