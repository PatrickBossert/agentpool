# agents/discovery/requirements_capture.py
from pathlib import Path
from crewai import Agent, Task, LLM
from crewai.tools import BaseTool
from api.config import get_settings, load_project_config


def create_requirements_capture(slug: str, llm: LLM, tools: list[BaseTool]) -> Agent:
    return Agent(
        role="Requirements Capture Specialist",
        goal=(
            "Conduct a structured stakeholder interview to surface digital modernisation requirements. "
            "Use the value chain as a frame to ask targeted, high-value questions."
        ),
        backstory=(
            "You are an experienced business analyst who has conducted hundreds of requirements "
            "workshops. You know how to ask open questions that reveal hidden pain points, "
            "and how to probe for priorities, constraints, and success criteria."
        ),
        llm=llm,
        tools=tools,
        verbose=True,
        allow_delegation=False,
    )


def create_requirements_capture_task(
    agent: Agent, context_tasks: list[Task], slug: str
) -> Task:
    settings = get_settings()
    try:
        config = load_project_config(Path(settings.projects_dir) / slug)
        max_turns = config.get("requirements_capture_max_turns", 10)
    except Exception:
        max_turns = 10

    return Task(
        description=(
            "Conduct a structured stakeholder interview to capture digital modernisation requirements.\n\n"
            "The value chain map is available from the previous task's output. "
            f"Conduct the interview over a minimum of 5 and a maximum of {max_turns} exchanges.\n\n"
            "Process:\n"
            "1. Formulate your first question covering the most critical pain points in the value chain.\n"
            "2. Use HumanInputTool to ask the question.\n"
            "3. Based on the response, formulate a follow-up question that probes deeper or covers "
            "a new area. Cover: pain points by value chain activity, current technology constraints, "
            "desired outcomes, priorities, regulatory constraints, and budget/timeline context.\n"
            "4. Repeat steps 2-3 until you have sufficient coverage (minimum 5 exchanges) or "
            f"reach {max_turns} questions.\n"
            "5. Use SQLiteStateTool with operation='write', key='interview_transcript', "
            "agent_name='requirements_capture' to save the complete Q&A as JSON: "
            "[{\"question\": \"...\", \"answer\": \"...\"}, ...].\n"
        ),
        expected_output=(
            "A complete interview transcript saved via SQLiteStateTool under key 'interview_transcript', "
            f"containing between 5 and {max_turns} question-answer pairs covering "
            "pain points, constraints, priorities, and desired outcomes."
        ),
        agent=agent,
        context=context_tasks,
    )
