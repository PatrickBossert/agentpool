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
            "1. Use SQLiteStateTool with operation='read', key='value_levers', "
            "agent_name='value_lever_analyst' to retrieve the levers already on record. "
            "Every one of them carries a `lever_id`, and that id is a permanent contract: a "
            "lever you are restating, rewording, sharpening or correcting KEEPS THE ID IT "
            "ALREADY HAS, whatever you do to its title and wherever it ends up in the array. "
            "If nothing is on record yet, start at LV-001. Never renumber; never reuse an id "
            "you have dropped.\n"
            "2. Use ChromaQueryTool with collection='project' to retrieve the client's own "
            "strategy, performance and governance material.\n"
            "3. Use SQLiteStateTool with operation='read', key='value_chain_model', "
            "agent_name='value_lever_analyst' to retrieve the value chain, so each lever can "
            "name the activities it bears on. If the model is not yet written, leave "
            "related_activity_ids empty rather than inventing IDs.\n"
            "4. Use ChromaQueryTool with collection='sector' for transformation patterns and "
            "levers common in this sector.\n"
            "5. Use TavilySearchTool for published benchmarks against the KPIs the client names.\n"
            "6. Produce a value levers analysis as a JSON array. Each lever must follow this "
            "schema:\n"
            "   {\"lever_id\": \"LV-001\", \"lever\": \"...\", \"description\": \"...\", "
            "\"hypothesis\": \"...\", "
            "\"kpis\": [\"...\"], \"status\": \"untested\", "
            "\"value_impact\": \"high|medium|low\", "
            "\"effort\": \"high|medium|low\", \"related_activity_ids\": [\"1.2.3\", ...], "
            "\"source\": \"...\", \"evidence\": \"...\"}\n"
            "   `lever_id` is the lever's name for the life of the project - `LV-` followed "
            "by three digits. It identifies the lever; `lever` is only its current title, and "
            "a reviewer who sends LV-003 back expects LV-003 to come back addressed, not "
            "renamed into something else. A lever that is genuinely new takes the next unused "
            "number above the highest on record. Two levers may never share an id, and a "
            "lever may never change the one it has.\n"
            "   `hypothesis` states what the interviews would have to confirm for the lever to "
            "hold. `source` cites where the lever came from: for a client document, the "
            "doc_id shown in the citation above the chunk (\"doc_id=3 "
            "SPUK_2025_Annual_Accounts.pdf\"); for outside evidence, the benchmark and its "
            "date. A lever with neither must not be submitted. Cite the doc_id rather than a "
            "name you recall - the citation is what lets a reader open the source and check "
            "the figure.\n"
            "   `status` is always \"untested\" when you write it. The interviews decide it "
            "later - contradicted, confirmed_unprompted, confirmed_prompted, or untested - "
            "and a lever nothing asked about stays untested, which is the finding a reader "
            "most needs. Never write a status claiming evidence you do not have.\n"
            "   Order levers by value_impact (high first), then by effort (low first). The "
            "order carries no meaning beyond presentation - the id is what identifies a "
            "lever, so reordering costs nothing and renumbering breaks everything.\n"
            "7. Use SQLiteStateTool with operation='write', key='value_levers', "
            "agent_name='value_lever_analyst' to save the JSON array. Write the complete "
            "array, every lever carrying its lever_id. If the tool warns you that levers "
            "carry no lever_id, fix those levers and write again - a lever with no id cannot "
            "be reviewed, sent back, or followed from one version to the next.\n"
        ),
        expected_output=(
            "A JSON value levers analysis saved to outputs/value_levers.json. "
            "Analysis must contain at least 3 levers, each stated as a hypothesis to be tested "
            "in the interviews, with lever_id, lever, description, hypothesis, kpis, status, "
            "value_impact, effort, related_activity_ids, source, and evidence fields. Every "
            "lever already on record keeps the lever_id it already had."
        ),
        agent=agent,
        context=context_tasks,
    )
