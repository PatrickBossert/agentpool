# agents/discovery/value_lever_analyst.py
from crewai import Agent, Task, LLM
from crewai.tools import BaseTool


def create_value_lever_analyst(slug: str, llm: LLM, tools: list[BaseTool]) -> Agent:
    return Agent(
        role="Value Lever Analyst",
        goal=(
            "Read the client's own documents to surface the value levers and KPIs the "
            "organisation already talks about, as hypotheses for the interviews to test."
        ),
        backstory=(
            "You are a transformation strategist who starts by listening to what an "
            "organisation says about itself. You read its strategy papers, performance "
            "reports and board packs to find the levers and measures it already uses, and "
            "you are careful to present them as claims to be tested rather than as findings - "
            "the interviews exist to confirm or contradict them."
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
            "Read the client's documents and record the value levers and KPIs the organisation "
            "itself uses, as hypotheses for the interviews to test.\n\n"
            "These are what the organisation CLAIMS to care about, not what the evidence "
            "supports. State every one as a hypothesis. Do not present any of them as an "
            "established finding, and do not estimate a benefit the documents do not state - "
            "the interviews exist to confirm or contradict these, and a lever presented as "
            "settled removes their ability to do so.\n\n"
            "Steps:\n"
            "1. Use ChromaQueryTool with collection='project' to retrieve the client's own "
            "strategy, performance and governance material.\n"
            "2. Use SQLiteStateTool with operation='read', key='value_chain_model', "
            "agent_name='value_lever_analyst' to retrieve the value chain, so each lever can "
            "name the activities it bears on. If the model is not yet written, leave "
            "related_activity_ids empty rather than inventing IDs.\n"
            "3. Use ChromaQueryTool with collection='sector' for transformation patterns and "
            "levers common in this sector.\n"
            "4. Use TavilySearchTool for published benchmarks against the KPIs the client names.\n"
            "5. Produce a value levers analysis as a JSON array. Each lever must follow this "
            "schema:\n"
            "   {\"lever\": \"...\", \"description\": \"...\", \"hypothesis\": \"...\", "
            "\"kpis\": [\"...\"], \"value_impact\": \"high|medium|low\", "
            "\"effort\": \"high|medium|low\", \"related_activity_ids\": [\"1.2.3\", ...], "
            "\"source\": \"...\", \"evidence\": \"...\"}\n"
            "   `hypothesis` states what the interviews would have to confirm for the lever to "
            "hold. `source` names the client document the lever came from, or the benchmark if "
            "it came from outside - a lever with neither must not be submitted.\n"
            "   Order levers by value_impact (high first), then by effort (low first).\n"
            "6. Use SQLiteStateTool with operation='write', key='value_levers', "
            "agent_name='value_lever_analyst' to save the JSON array.\n"
        ),
        expected_output=(
            "A JSON value levers analysis saved to outputs/value_levers.json. "
            "Analysis must contain at least 3 levers, each stated as a hypothesis to be tested "
            "in the interviews, with lever, description, hypothesis, kpis, value_impact, "
            "effort, related_activity_ids, source, and evidence fields."
        ),
        agent=agent,
        context=context_tasks,
    )
