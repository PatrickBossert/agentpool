# agents/architecture/enterprise_architect.py
from crewai import Agent, Task, LLM
from crewai.tools import BaseTool


def create_enterprise_architect(slug: str, llm: LLM, tools: list[BaseTool]) -> Agent:
    return Agent(
        role="Enterprise Architect",
        goal=(
            "Extract and structure the client's current-state enterprise architecture "
            "across data, technology, and organisation layers from uploaded documents."
        ),
        backstory=(
            "You are a principal enterprise architect who specialises in current-state "
            "assessment. You read architecture documents, org charts, system inventories, "
            "and technology registers to produce clear, structured architecture registers "
            "that reveal capability gaps and modernisation opportunities."
        ),
        llm=llm,
        tools=tools,
        verbose=True,
        allow_delegation=False,
    )


def create_enterprise_architect_task(agent: Agent) -> Task:
    return Task(
        description=(
            "Extract the current-state enterprise architecture from uploaded client documents.\n\n"
            "Steps:\n"
            "1. Use ChromaQueryTool with collection='project', "
            "query='systems platforms technology infrastructure organisation teams roles' "
            "to retrieve architecture-related document chunks. Retrieve at least top_k=10.\n"
            "2. Use ChromaQueryTool with collection='project', "
            "query='data entities sources flows ownership master data' "
            "to retrieve data-layer content.\n"
            "3. Use ChromaQueryTool with collection='project', "
            "query='organisational structure teams capabilities reporting lines' "
            "to retrieve organisation-layer content.\n"
            "4. Extract the three architecture layers. For each layer, produce a list of "
            "named entities. If a layer has no identifiable entities from the documents, "
            "produce a list with a single placeholder: "
            "{\"name\": \"Unknown\", \"description\": \"No information found in uploaded documents.\"}.\n\n"
            "   Data layer — each entity:\n"
            "   {\"name\": \"...\", \"description\": \"...\", \"source\": \"...\", \"owner\": \"...\"}\n\n"
            "   Technology layer — each entity:\n"
            "   {\"name\": \"...\", \"description\": \"...\", "
            "\"category\": \"platform|integration|infrastructure|application\", "
            "\"status\": \"current|planned|legacy\"}\n\n"
            "   Organisation layer — each entity:\n"
            "   {\"name\": \"...\", \"type\": \"team|role|capability\", \"description\": \"...\"}\n\n"
            "5. Assemble the three layers into a single JSON object:\n"
            "   {\"data_layer\": [...], \"technology_layer\": [...], \"organisation_layer\": [...]}\n"
            "6. Use SQLiteStateTool with operation='write', key='architecture_register', "
            "agent_name='enterprise_architect' to save the JSON object.\n"
            "7. Use MermaidRenderTool to save a Mermaid diagram for each layer:\n"
            "   - Data layer: flowchart LR diagram showing entities and their relationships. "
            "filename='architecture_data_layer', agent_name='enterprise_architect'.\n"
            "   - Technology layer: flowchart TB diagram grouping systems by category. "
            "filename='architecture_technology_layer', agent_name='enterprise_architect'.\n"
            "   - Organisation layer: graph TB diagram showing hierarchy. "
            "filename='architecture_org_layer', agent_name='enterprise_architect'.\n"
            "8. Use HumanInputTool with prompt: 'Please review the architecture register saved at "
            "outputs/architecture_register.json and the three Mermaid diagrams "
            "(architecture_data_layer.md, architecture_technology_layer.md, architecture_org_layer.md). "
            "Reply \"approved\" to proceed to initiative identification, or provide notes.'\n"
            "9. If revision notes are received, revise the register and diagrams and call "
            "HumanInputTool again. Maximum 3 revision cycles.\n"
        ),
        expected_output=(
            "A JSON architecture register with data_layer, technology_layer, and organisation_layer "
            "saved to outputs/architecture_register.json. "
            "Three Mermaid diagrams saved to outputs/architecture_data_layer.md, "
            "outputs/architecture_technology_layer.md, and outputs/architecture_org_layer.md. "
            "Confirmed approved by a human reviewer."
        ),
        agent=agent,
    )
