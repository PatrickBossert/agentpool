# agents/discovery/value_chain_mapper.py
from crewai import Agent, Task, LLM
from crewai.tools import BaseTool


def create_value_chain_mapper(slug: str, llm: LLM, tools: list[BaseTool]) -> Agent:
    return Agent(
        role="Value Chain Mapper",
        goal=(
            "Map the client organisation's complete value chain by analysing uploaded documents "
            "and researching the sector. Produce a clear, accurate Mermaid diagram."
        ),
        backstory=(
            "You are a senior strategy consultant specialising in value chain analysis. "
            "You have deep expertise in identifying primary and support activities across "
            "industry sectors and translating them into clear visual models."
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
            "5. Produce a Mermaid diagram using EXACTLY `flowchart LR` as the first line "
            "(never `flowchart TB`, `flowchart TD`, `graph TD`, or any top-down variant). "
            "The diagram MUST use the following structure — deviating from it will produce "
            "an illegible layout:\n\n"
            "  STRUCTURE RULES:\n"
            "  a) SUPPORT BLOCK (leftmost) — Place a single outer subgraph first:\n"
            "       subgraph SUPPORT_GRP[\"⚙ SUPPORT ACTIVITIES — <client>\"]\\n  direction TB\n"
            "     Inside it, add one nested subgraph per support category "
            "(e.g. subgraph S1_GRP[\"TECHNOLOGY & DIGITAL\"]) each with `direction LR` "
            "so L3 detail nodes flow left-to-right inside each L2 box. "
            "Do NOT use `---` to attach L3 nodes — they simply live inside the subgraph block.\n\n"
            "  b) PRIMARY LANE SUBGRAPHS — After SUPPORT_GRP, add one subgraph per primary value chain:\n"
            "       subgraph LANE_KEY[\"<icon> <L1 LABEL>\\n<owner line>\"]\\n  direction LR\n"
            "     Inside each lane, EVERY L2 stage must be its own nested subgraph with `direction TB`:\n"
            "       subgraph P1_GRP[\"① <L2 label>\\n── <owner>\"]\\n  direction TB\n"
            "         P1A[\"<L3 activity>\"]:::sp\n"
            "         P1B[\"<L3 activity>\"]:::partnerX\n"
            "       end\n"
            "     L3 nodes live INSIDE their L2 subgraph — do NOT attach them with `---` outside.\n"
            "     Chain L2 subgraphs left-to-right AFTER all end declarations inside the lane:\n"
            "       P1_GRP --> P2_GRP --> P3_GRP --> ...\n"
            "     Do NOT use flat L2 nodes with `---` branches — every L2 must be a subgraph container.\n\n"
            "  c) CROSS-SUBGRAPH ARROWS — After all subgraph blocks, add one arrow per lane:\n"
            "       SUPPORT_GRP --> LANE_KEY\n"
            "     This places support visually to the left, feeding into the value chains.\n\n"
            "  d) COLOUR SCHEME — fixed palette, applied strictly as follows:\n"
            "     • L1 and L2 subgraph backgrounds: add `style` directives after ALL subgraph/end blocks.\n"
            "         style SUPPORT_GRP fill:#fef9c3,stroke:#ca8a04,color:#1a1a1a\n"
            "         style S1_GRP fill:#fef9c3,stroke:#ca8a04  (repeat for every support inner subgraph)\n"
            "         style LANE_KEY fill:#<lane-colour>,stroke:#<lane-stroke>,color:#<lane-text>\n"
            "         style P1_GRP fill:#<l2-shade>,stroke:#<l2-stroke>  (lighter shade of lane colour)\n"
            "     • L3 detail nodes: coloured by the ENTITY that DELIVERS that specific activity. "
            "Define one classDef per distinct entity:\n"
            "         classDef sp        fill:#1a5276,color:#fff  (client/owner organisation)\n"
            "         classDef partnerA  fill:#c0392b,color:#fff  (name it after the real partner, "
            "e.g. classDef partnerISS; choose a DISTINCT colour per partner)\n"
            "         classDef partnerB  fill:#27ae60,color:#fff\n"
            "         classDef partnerC  fill:#2980b9,color:#fff\n"
            "         classDef partnerD  fill:#8e44ad,color:#fff  (add more if needed)\n"
            "       Every L3 node MUST carry :::sp or :::partnerX matching who PERFORMS that activity.\n"
            "     • Do NOT define per-lane colour triplets (l1prop/l2prop/l3prop) — abandoned.\n\n"
            "  e) ENTITY LEGEND — End with a subgraph LEGEND[\"ENTITY LEGEND\"] with `direction LR` "
            "so legend items flow left-to-right. List the client entity and each partner with their distinct styling.\n\n"
            "  f) LABELS — Use client-specific process names wherever known. "
            "Primary lanes follow: Strategy/Planning → Portfolio/Optimisation → Acquisition/Scheduling "
            "→ Delivery → Monitoring/Review (adapt to client context — do not force generic Porter labels).\n"
            "6. Use MermaidRenderTool to save the diagram with filename='value_chain'.\n"
            "7. Use SQLiteStateTool with operation='write', key='value_chain_summary', "
            "agent_name='value_chain_mapper' to save a brief JSON summary: "
            "{\"activities\": [list of key activities identified], \"sector\": \"...\"}.\n"
            "8. Use HumanInputTool with prompt: 'Please review the value chain diagram. "
            "Reply \"approved\" to proceed, or provide revision notes.'\n"
            "9. If revision notes are received (response is not 'approved'), revise the diagram "
            "and call HumanInputTool again. Repeat at most 3 times total.\n"
            "10. Once the diagram is approved, use SQLiteStateTool with operation='write', "
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
            "11. Use DeriveRegistryTool with agent_name='value_chain_mapper' to automatically "
            "derive value_chain_registry from the tree you just wrote. "
            "This creates the permanent flat ID ledger — activities in the tree are marked "
            "active=true, and any entries that existed in a previous registry but are absent "
            "from the new tree are preserved as active=false. "
            "Do NOT write the registry manually — DeriveRegistryTool guarantees completeness.\n"
        ),
        expected_output=(
            "A Mermaid value chain diagram saved to outputs/value_chain.md, "
            "a JSON summary saved via SQLiteStateTool, "
            "a structured JSON tree with stable IDs saved to key='value_chain_tree', "
            "an updated activity registry saved to key='value_chain_registry', "
            "and confirmation that the diagram has been approved by a human reviewer."
        ),
        agent=agent,
    )
