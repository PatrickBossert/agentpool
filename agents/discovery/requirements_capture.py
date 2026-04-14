# agents/discovery/requirements_capture.py
from crewai import Agent, Task, LLM
from crewai.tools import BaseTool


def create_requirements_capture(slug: str, llm: LLM, tools: list[BaseTool]) -> Agent:
    return Agent(
        role="Requirements Capture Specialist",
        goal=(
            "Conduct structured stakeholder interviews to capture business requirements, "
            "pain points, and strategic priorities. Produce a structured requirements list."
        ),
        backstory=(
            "You are a senior business analyst with expertise in requirements engineering and "
            "stakeholder management. You use structured interview techniques — open questions, "
            "probing follow-ups, and active listening — to uncover both stated and unstated needs. "
            "You are skilled at interviewing stakeholders at all levels, from C-suite to "
            "front-line operations."
        ),
        tools=tools,
        llm=llm,
        verbose=True,
        allow_delegation=False,
    )


def create_requirements_capture_task(
    slug: str, stakeholder_groups: list[str], max_turns: int = 5
) -> Task:
    groups_str = ", ".join(stakeholder_groups) if stakeholder_groups else "key stakeholders"
    return Task(
        description=(
            f"Conduct stakeholder interviews with representatives from: {groups_str}.\n\n"
            f"Interview each group using HumanInputTool (maximum {max_turns} exchanges total).\n\n"
            "Interview structure:\n"
            "1. Open with: 'What are the biggest operational challenges your team faces today?'\n"
            "2. For each challenge mentioned, probe: 'How significant is this? What's the "
            "   business impact?'\n"
            "3. Ask about strategic priorities: 'What outcomes would make this initiative a "
            "   clear success for you?'\n"
            "4. Constraints: 'Are there budget, timeline, or regulatory constraints we should "
            "   be aware of?'\n"
            "5. After all exchanges, consolidate into a structured requirements list.\n\n"
            "For each requirement, capture:\n"
            "- requirement_id (e.g. REQ-001)\n"
            "- description\n"
            "- stakeholder_group\n"
            "- priority (high/medium/low)\n"
            "- type (functional/non-functional/constraint)\n\n"
            "Use SQLiteStateTool to save the final requirements list with key='requirements'.\n"
        ),
        expected_output=(
            "A JSON array of requirement objects, each with: requirement_id, description, "
            "stakeholder_group, priority, type."
        ),
    )
