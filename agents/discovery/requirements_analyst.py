# agents/discovery/requirements_analyst.py
from crewai import Agent, Task, LLM
from crewai.tools import BaseTool


def create_requirements_analyst(slug: str, llm: LLM, tools: list[BaseTool]) -> Agent:
    return Agent(
        role="Requirements Analyst",
        goal=(
            "Analyse and validate captured requirements against the value chain and "
            "existing documentation. Identify gaps, conflicts, and implicit requirements."
        ),
        backstory=(
            "You are an experienced requirements analyst who bridges the gap between business "
            "stakeholders and technical teams. You excel at identifying inconsistencies, "
            "unstated assumptions, and missing requirements by cross-referencing interview "
            "findings with organisational documentation and industry standards."
        ),
        tools=tools,
        llm=llm,
        verbose=True,
        allow_delegation=False,
    )


def create_requirements_analyst_task(slug: str, sector: str) -> Task:
    return Task(
        description=(
            "Analyse and validate the captured requirements.\n\n"
            "Steps:\n"
            "1. Use SQLiteStateTool (operation='read', key='requirements') to load the "
            "   captured requirements.\n"
            "2. Use SQLiteStateTool (operation='read', key='value_chain') to load the "
            "   value chain context.\n"
            "3. Use ChromaQueryTool to search project documents for additional context.\n"
            "4. Identify: gaps (areas with no requirements), conflicts (contradictory requirements), "
            "   and implicit requirements (things stakeholders assumed but didn't state).\n"
            "5. Enrich each requirement with a 'validated' flag and any 'notes' from your analysis.\n"
            "6. Use HumanInputTool to present your analysis summary and request confirmation "
            "   before finalising.\n"
            "7. Use SQLiteStateTool to save the validated requirements with key='requirements_validated'.\n"
        ),
        expected_output=(
            "A JSON object with keys: 'requirements' (enriched list with validated flag), "
            "'gaps' (list of identified gaps), 'conflicts' (list of conflicts)."
        ),
    )
