# agents/discovery/value_lever_analyst.py
from crewai import Agent, Task, LLM
from crewai.tools import BaseTool


def create_value_lever_analyst(slug: str, llm: LLM, tools: list[BaseTool]) -> Agent:
    return Agent(
        role="Value Lever Analyst",
        goal=(
            "Identify high-impact digital modernisation opportunities (value levers) "
            "across the client's value chain, prioritised by ROI potential and feasibility."
        ),
        backstory=(
            "You are a digital transformation strategist with a track record of identifying "
            "where technology investment delivers the greatest business value. You combine "
            "deep sector knowledge with analytical rigour to prioritise opportunities by "
            "impact, feasibility, and strategic alignment. You communicate findings clearly "
            "to executive audiences."
        ),
        tools=tools,
        llm=llm,
        verbose=True,
        allow_delegation=False,
    )


def create_value_lever_task(slug: str, sector: str) -> Task:
    return Task(
        description=(
            "Identify and prioritise digital modernisation value levers.\n\n"
            "Steps:\n"
            "1. Use SQLiteStateTool (operation='read', key='requirements_validated') to load "
            "   the validated requirements.\n"
            "2. Use SQLiteStateTool (operation='read', key='value_chain') to load the "
            "   value chain.\n"
            f"3. Use TavilySearchTool to research digital transformation ROI benchmarks for "
            f"   the {sector} sector.\n"
            "4. Use ChromaQueryTool (collection='sector') to retrieve sector knowledge base "
            "   content about typical transformation patterns.\n"
            "5. For each value lever identified, assess:\n"
            "   - impact_score (1-10)\n"
            "   - feasibility_score (1-10)\n"
            "   - estimated_roi_range\n"
            "   - affected_value_chain_stage\n"
            "   - technology_category (e.g. AI/ML, RPA, Cloud, IoT, Data Platform)\n"
            "6. Use HumanInputTool to present the top levers and request stakeholder validation.\n"
            "7. Use SQLiteStateTool to save the final levers with key='value_levers'.\n"
        ),
        expected_output=(
            "A JSON array of value lever objects, each with: lever_id, name, description, "
            "impact_score, feasibility_score, estimated_roi_range, affected_value_chain_stage, "
            "technology_category."
        ),
    )
