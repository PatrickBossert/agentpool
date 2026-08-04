# agents/discovery/synthesis_analyst.py
from crewai import Agent, Task, LLM
from crewai.tools import BaseTool


def create_synthesis_analyst(slug: str, llm: LLM, tools: list[BaseTool]) -> Agent:
    return Agent(
        role="Synthesis Analyst",
        goal=(
            "Synthesise stakeholder interview transcripts into activity-level insights, the "
            "horizontal and vertical themes the evidence supports, and the strategic "
            "requirements those themes imply."
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
            "1. Use ChromaQueryTool with collection='interviews' to retrieve the interview "
            "answers relevant to each area you examine. Every answer carries its node, level, "
            "relationship, discipline, and elicitation as metadata, and its answer_id. Query "
            "per area rather than trying to read the corpus whole - it is too large, and a "
            "transcript blob cannot be filtered by discipline or by who the speaker is to "
            "this organisation.\n"
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
            "5. Produce the themes the evidence supports, of two kinds:\n"
            "   - horizontal: across the value chain, where digital transformation could "
            "improve efficiency or effectiveness;\n"
            "   - vertical: within a discipline - governance, data, a specific support "
            "service - where maturity could be raised.\n"
            "   Each theme:\n"
            "   {\"id\": \"TH-01\", \"theme\": \"...\", \"kind\": \"horizontal|vertical\", "
            "\"description\": \"...\", \"activity_ids\": [\"1.2.3\", ...], "
            "\"evidence\": [{\"answer_id\": 812, \"stakeholder_id\": 1, \"quote\": \"...\"}]}\n"
            "   Cite answer_id, never a node label or a section title - those are strings that "
            "may be rewritten, and an answer_id resolves to exactly one answer, in one "
            "session, on one node.\n"
            "   Weight evidence by elicitation: an unprompted mention is stronger than a "
            "prompted agreement, because a prompted question handed the interviewee the "
            "phrase. Say which when the distinction matters to the theme.\n"
            "   Every theme carries at least two evidence entries from different stakeholders. "
            "A pattern seen in one transcript is an individual perspective, not a theme.\n"
            "6. Use SQLiteStateTool with operation='write', key='themes', "
            "agent_name='synthesis_analyst' to save the themes array.\n"
            "7. Derive the STRATEGIC requirements from those themes: the challenges and "
            "opportunities in value chain activity or maturity that the organisation must "
            "address to unlock value. A theme is what people said; a strategic requirement is "
            "what the organisation must therefore be able to do.\n"
            "   These are NOT change requirements. Do not specify systems, projects, or "
            "delivery approaches - the Requirements crew enumerates those later, against "
            "initiatives that do not exist yet.\n"
            "   Each strategic requirement:\n"
            "   {\"id\": \"SR-01\", \"statement\": \"...\", \"kind\": \"challenge|opportunity\", "
            "\"from_themes\": [\"TH-01\", ...], \"activity_ids\": [\"1.2.3\", ...], "
            "\"priority\": \"High|Medium|Low\"}\n"
            "   Every strategic requirement names at least one theme it derives from. One "
            "supported by several themes is written once, listing all of them.\n"
            "8. Use SQLiteStateTool with operation='write', key='strategic_requirements', "
            "agent_name='synthesis_analyst' to save the strategic requirements array.\n"
        ),
        expected_output=(
            "Three JSON files saved via SQLiteStateTool: "
            "activity_insights (per-node actors/needs/frustrations), "
            "themes (horizontal and vertical themes, each evidenced by at least two "
            "stakeholders), and strategic_requirements (challenges and opportunities, each "
            "deriving from at least one theme)."
        ),
        agent=agent,
        context=context_tasks,
    )
