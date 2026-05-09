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
            "Steps:\n"
            "1. Use DocumentIngestionTool with filename=None to ingest all client documents.\n"
            "2. Use ChromaQueryTool with collection='project' to understand the client's operations.\n"
            "3. Use TavilySearchTool to research the sector's typical value chain structure.\n"
            "4. Use ChromaQueryTool with collection='sector' for additional sector benchmarks.\n"
            "5. Produce a Mermaid diagram showing primary activities (left to right: Inbound Logistics, "
            "Operations, Outbound Logistics, Marketing & Sales, Service) and support activities, "
            "labelled with client-specific process names where known.\n"
            "6. Use MermaidRenderTool to save the diagram with filename='value_chain'.\n"
            "7. Use SQLiteStateTool with operation='write', key='value_chain_summary', "
            "agent_name='value_chain_mapper' to save a brief JSON summary: "
            "{\"activities\": [list of key activities identified], \"sector\": \"...\"}.\n"
            "8. Use HumanInputTool with prompt: 'Please review the value chain diagram saved at "
            "outputs/value_chain.md. Reply \"approved\" to proceed, or provide revision notes.'\n"
            "9. If revision notes are received (response is not 'approved'), revise the diagram "
            "and call HumanInputTool again. Repeat at most 3 times total.\n"
        ),
        expected_output=(
            "A Mermaid value chain diagram saved to outputs/value_chain.md, "
            "a JSON summary saved via SQLiteStateTool, "
            "and confirmation that the diagram has been approved by a human reviewer."
        ),
        agent=agent,
    )
