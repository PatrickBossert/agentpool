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
            "You are an expert in Porter's Value Chain framework with deep experience in digital "
            "transformation across multiple sectors. You have analysed hundreds of organisations "
            "and can quickly identify primary and support activities, key interfaces, and "
            "digitisation opportunities. You produce clean Mermaid diagrams that clearly "
            "communicate complex value chains to non-technical stakeholders."
        ),
        tools=tools,
        llm=llm,
        verbose=True,
        allow_delegation=False,
    )


def create_value_chain_task(slug: str, sector: str, value_streams: list[str]) -> Task:
    streams_str = ", ".join(value_streams) if value_streams else "to be identified"
    return Task(
        description=(
            f"Map the value chain for a {sector} organisation.\n\n"
            "Steps:\n"
            "1. Use DocumentIngestionTool to ingest all documents in the project docs/ directory.\n"
            "2. Use ChromaQueryTool (collection='project') to retrieve relevant content about "
            "   the organisation's operations and processes.\n"
            "3. Use TavilySearchTool to research typical value chains for {sector} organisations.\n"
            f"4. The client's known value streams are: {streams_str}.\n"
            "5. Draft a Mermaid diagram of the full value chain using graph LR syntax.\n"
            "6. Use HumanInputTool with the Mermaid diagram to request stakeholder review.\n"
            "   If the response is 'approved', proceed. If it contains revision notes, "
            "   revise the diagram and call HumanInputTool again (maximum 3 revision cycles).\n"
            "7. Once approved, use MermaidRenderTool to save the final diagram with "
            "   filename='value_chain'.\n"
            "8. Use SQLiteStateTool to write the final Mermaid markdown with key='value_chain'.\n"
        ),
        expected_output=(
            "A JSON string with keys 'mermaid_md' (the final Mermaid diagram) and "
            "'summary' (2-3 sentence description of the value chain)."
        ),
    )
