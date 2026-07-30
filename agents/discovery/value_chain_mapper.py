# agents/discovery/value_chain_mapper.py
from crewai import Agent, Task, LLM
from crewai.tools import BaseTool


def create_value_chain_mapper(slug: str, llm: LLM, tools: list[BaseTool]) -> Agent:
    return Agent(
        role="Value Chain Mapper",
        goal=(
            "Map the client organisation's complete value chain by analysing uploaded documents "
            "and researching the sector. Produce a clear, accurate structured value chain model."
        ),
        backstory=(
            "You are a senior strategy consultant specialising in value chain analysis. "
            "You have deep expertise in identifying primary and support activities across "
            "industry sectors and translating them into a structured model that a human editor "
            "can refine activity by activity."
        ),
        llm=llm,
        tools=tools,
        verbose=True,
        allow_delegation=False,
    )


def _build_discovery_context(
    discovery_brief: str,
    discovery_links: list[dict],
    priority_doc_names: list[str],
) -> str:
    """Build a context preamble for the task description. Returns empty string if all inputs are empty."""
    parts = []
    if discovery_brief:
        parts.append(f"Research brief: {discovery_brief}")
    if discovery_links:
        links_list = "\n".join(
            f"  {i+1}. {entry.get('label', entry['url'])} — {entry['url']}"
            for i, entry in enumerate(discovery_links)
        )
        parts.append(
            "The client has provided these research links — fetch and read each "
            "using WebFetchTool before beginning your analysis:\n" + links_list
        )
    if priority_doc_names:
        docs_list = ", ".join(priority_doc_names)
        parts.append(
            f"Priority source documents (prioritise these when querying ChromaDB): {docs_list}"
        )
    if not parts:
        return ""
    return "\n\n".join(parts) + "\n\n"


def create_value_chain_mapper_task(
    agent: Agent,
    discovery_brief: str = "",
    discovery_links: list[dict] | None = None,
    priority_doc_names: list[str] | None = None,
) -> Task:
    context_preamble = _build_discovery_context(
        discovery_brief=discovery_brief,
        discovery_links=discovery_links or [],
        priority_doc_names=priority_doc_names or [],
    )
    return Task(
        description=(
            f"{context_preamble}"
            "Analyse the client documents and sector context to map the organisation's value chain.\n\n"
            "REFERENTIAL INTEGRITY RULE: Every L1, L2 and L3 activity carries a stable numeric ID "
            "(n / n.n / n.n.n) that MUST NOT change between iterations. IDs are assigned once and are "
            "permanent, even if labels are refined. New activities appended in later iterations get the "
            "next available number in their level sequence.\n\n"
            "Steps:\n"
            "0. Use SQLiteStateTool with operation='read', key='value_chain_registry', "
            "agent_name='value_chain_mapper' to load the existing activity ID registry. "
            "If found, note all existing {id → label} pairs — you must preserve these IDs. "
            "If not found (first run), you will assign IDs starting from 1.\n"
            "1. Use DocumentIngestionTool with filename=None to ingest all client documents.\n"
            "2. Use ChromaQueryTool with collection='project' to understand the client's operations.\n"
            "3. Use TavilySearchTool to research the sector's typical value chain structure.\n"
            "4. Use ChromaQueryTool with collection='sector' for additional sector benchmarks.\n"
            "5. Build the value chain as a single structured model - not a diagram. The model is a "
                "JSON object with exactly these top-level arrays: `segments`, `parties`, `activities`, "
                "`contributions`, `tasks`, `propositions`, and `links`. A human editor works directly "
                "from this JSON afterwards, so every level below must carry a `description` written in "
                "full sentences - a bare label is not enough, and description has never existed on "
                "this model before, so do not skip it anywhere it is required.\n\n"
                "  SAME ID SPACE, NOT A PARALLEL ONE: `segments[].id`, `activities[].id` and "
                "`tasks[].id` in this model MUST be exactly the IDs from the registry you loaded in "
                "step 0 - an L1 registry entry becomes a segment, an L2 entry becomes an activity, "
                "and an L3 entry becomes a task, each keeping its registry id unchanged. Do not invent "
                "a fresh numbering for the model. A genuinely new segment, activity or task takes the "
                "next unused number in its level sequence - never an id that has ever been used, "
                "including one now marked inactive in the registry.\n\n"
                "  a) `segments` - the primary value chain lanes (e.g. Strategy/Planning, Acquisition, "
                "Delivery, Monitoring/Review - adapt to client context rather than forcing generic "
                "Porter labels). Each segment has `id`, `label`, and `description`.\n\n"
                "  b) `parties` - the client organisation and every partner or supplier that performs "
                "part of the chain. Each party has `id`, `label`, and `description` of what it is and "
                "how it relates to the client.\n\n"
                "  c) `activities` - one entry per distinct piece of work, each with its own stable "
                "`id`, a `segment_id` naming which segment it sits in, a `label`, a `description`, "
                "and `active` (false for an activity withdrawn from the chain - never delete a "
                "withdrawn activity from this array, since contributions, tasks and links may still "
                "reference its id). An activity is ONE thing regardless of how many parties touch it "
                "- do not create a second activity just because a second party is involved in it.\n\n"
                "  d) `contributions` - this is where parties attach to activities. Where one activity "
                "is delivered jointly by several parties, it has one contribution per party, each "
                "with its own description and its own tasks - this is the whole point of separating "
                "contributions from activities, so each party's part can be understood and, later, "
                "interviewed about on its own. Each contribution names `activity_id` and `party_id`, "
                "and carries:\n"
                "     - `column`: an integer in steps of 10 (10, 20, 30, ...) giving this "
                "contribution's position within its party's own lane. Two contributions of the same "
                "activity sharing a column means those parties act on it concurrently; offset columns "
                "mean a handoff from one party to the next.\n"
                "     - `description`: this party's part of the activity, in full sentences.\n"
                "     - `attribution`: \"stated\" when you are attributing this contribution yourself "
                "from what the documents or research say - use \"derived\" only where you are carrying "
                "forward an inference that was not itself directly stated.\n\n"
                "  e) `tasks` - the concrete steps that make up one contribution. Each task names the "
                "`activity_id` and `party_id` of the contribution it belongs to, plus its own `id` and "
                "`description`.\n\n"
                "  f) `propositions` - value propositions or observations that attach to an activity "
                "as a whole (not to a single party's contribution). Each has `id`, `activity_id`, and "
                "`description`.\n\n"
                "  g) `links` - dependencies or handoffs between two contributions. Each link names a "
                "source and a target contribution (`from_activity_id`/`from_party_id` and "
                "`to_activity_id`/`to_party_id`) plus a `description` of the relationship.\n"
            "6. Use SQLiteStateTool with operation='write', key='value_chain_model', "
            "agent_name='value_chain_mapper', value=<the JSON model from step 5, as a JSON string> "
            "to save it. This is versioned on write to outputs/value_chain_model_v{N}.json with "
            "output_type='value_chain_model'.\n"
            "7. Use SQLiteStateTool with operation='write', key='value_chain_summary', "
            "agent_name='value_chain_mapper' to save a brief JSON summary: "
            "{\"activities\": [list of key activities identified], \"sector\": \"...\"}.\n"
            "8. Use SQLiteStateTool with operation='write', "
            "key='value_chain_tree', agent_name='value_chain_mapper' to save the value chain as a "
            "structured JSON tree. EVERY L1, L2 and L3 node MUST include an 'id' field — reuse "
            "existing IDs from step 0 for matching activities, assign new sequential IDs for new ones. "
            "The ID scheme is n.n.n: L1 use integers (1, 2, 3), L2 use L1.n (1.1, 1.2), "
            "L3 use L2.n (1.1.1, 1.1.2). The format must be a JSON array where each element is an L1 node:\n"
            "[\n"
            "  {\n"
            "    \"id\": \"1\",\n"
            "    \"label\": \"Inbound Logistics\",\n"
            "    \"level\": \"L1\",\n"
            "    \"children\": [\n"
            "      {\n"
            "        \"id\": \"1.1\",\n"
            "        \"label\": \"Materials Receipt\",\n"
            "        \"level\": \"L2\",\n"
            "        \"children\": [\n"
            "          {\"id\": \"1.1.1\", \"label\": \"Goods-in Inspection\", \"level\": \"L3\"}\n"
            "        ]\n"
            "      }\n"
            "    ]\n"
            "  }\n"
            "]\n"
            "Use client-specific labels. L1 = primary value stream (owned by senior leader e.g. GM), "
            "L2 = process stage (owned by process stage manager), L3 = specific activity. "
            "Children arrays are optional — include them only where sub-stages are known.\n"
            "9. Use DeriveRegistryTool with agent_name='value_chain_mapper' to automatically "
            "derive value_chain_registry from the tree you just wrote. "
            "This creates the permanent flat ID ledger — activities in the tree are marked "
            "active=true, and any entries that existed in a previous registry but are absent "
            "from the new tree are preserved as active=false. "
            "Do NOT write the registry manually — DeriveRegistryTool guarantees completeness.\n"
        ),
        expected_output=(
            "A structured value chain model - segments, parties, activities, contributions, tasks, "
            "propositions and links, every one carrying a description - saved via SQLiteStateTool to "
            "key='value_chain_model' (output_type='value_chain_model'); "
            "a JSON summary saved via SQLiteStateTool to key='value_chain_summary'; "
            "a structured JSON tree with stable IDs saved to key='value_chain_tree'; "
            "and an updated activity registry saved to key='value_chain_registry'."
        ),
        agent=agent,
    )
