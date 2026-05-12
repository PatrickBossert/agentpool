# agents/architecture/initiative_identifier.py
from crewai import Agent, Task, LLM
from crewai.tools import BaseTool


def create_initiative_identifier(slug: str, llm: LLM, tools: list[BaseTool]) -> Agent:
    return Agent(
        role="Initiative Identifier",
        goal=(
            "Identify the discrete initiatives required to deliver the approved value propositions "
            "by performing gap analysis between the propositions and the current-state architecture."
        ),
        backstory=(
            "You are a transformation programme architect who specialises in translating "
            "strategic intent into actionable initiatives. You analyse where value propositions "
            "demand capabilities the current architecture does not provide, and define the "
            "initiatives needed to close those gaps."
        ),
        llm=llm,
        tools=tools,
        verbose=True,
        allow_delegation=False,
    )


def create_initiative_identifier_task(
    agent: Agent, context_tasks: list[Task]
) -> Task:
    return Task(
        description=(
            "Identify the initiatives required to deliver the value propositions "
            "given the current-state architecture.\n\n"
            "Steps:\n"
            "1. Use SQLiteStateTool with operation='read', key='propositions', "
            "agent_name='initiative_identifier' to retrieve the value propositions.\n"
            "2. Use SQLiteStateTool with operation='read', key='architecture_register', "
            "agent_name='initiative_identifier' to retrieve the architecture register.\n"
            "3. Use SQLiteStateTool with operation='read', key='requirements', "
            "agent_name='initiative_identifier' to retrieve the requirements register.\n"
            "4. For each value proposition, analyse what capabilities it requires and compare "
            "against the technology_layer and organisation_layer in the architecture register "
            "to identify specific capability gaps.\n"
            "5. Define one or more initiatives per proposition to close identified gaps. "
            "One initiative can address gaps from multiple propositions — avoid duplicates.\n"
            "6. Score each initiative on complexity (1 = simple configuration change, "
            "5 = multi-year organisational transformation) with a rationale.\n"
            "7. Classify each initiative:\n"
            "   - initiative_type='enabler': primarily technology, data, or infrastructure "
            "change that unlocks other change. Populate enabler_dependencies with the IDs of "
            "other enabler initiatives this one depends on (empty list if none).\n"
            "   - initiative_type='change_activity': process, organisational, or "
            "strategic change that requires enablers to be in place first. Populate "
            "change_dependencies with the IDs of enabler initiatives that must complete "
            "before this one can run (empty list if none).\n"
            "8. For each initiative, identify the capability uplifts required across one or "
            "more of these dimensions: people, data, systems, organisation, partnership, "
            "architectural, operating_model. Each uplift should be a distinct, actionable "
            "statement of what the organisation needs to be able to do.\n"
            "9. Estimate the cost range for each initiative in GBP. Provide a low and high "
            "estimate with a brief rationale based on complexity_score and capability_uplifts.\n"
            "10. Produce a JSON array where each item follows this schema exactly:\n"
            "   {\n"
            "     \"id\": \"INIT-001\",\n"
            "     \"title\": \"Short initiative title (max 8 words)\",\n"
            "     \"description\": \"2–3 sentences describing what this initiative delivers\",\n"
            "     \"proposition_ids\": [\"VP-001\", \"VP-002\"],\n"
            "     \"capability_uplifts\": [\n"
            "       {\n"
            "         \"dimension\": \"systems\",\n"
            "         \"description\": \"Implement warehouse management system with real-time tracking\"\n"
            "       },\n"
            "       {\n"
            "         \"dimension\": \"people\",\n"
            "         \"description\": \"Train warehouse operatives on digital receipt processes\"\n"
            "       }\n"
            "     ],\n"
            "     \"initiative_type\": \"enabler\",\n"
            "     \"enabler_dependencies\": [],\n"
            "     \"change_dependencies\": [],\n"
            "     \"complexity_score\": 3,\n"
            "     \"complexity_rationale\": \"One sentence justifying the score\",\n"
            "     \"cost_estimate\": {\n"
            "       \"low\": 50000,\n"
            "       \"high\": 150000,\n"
            "       \"currency\": \"GBP\",\n"
            "       \"rationale\": \"Mid-complexity system integration with training uplift\"\n"
            "     },\n"
            "     \"related_requirements\": [\"REQ-001\"]\n"
            "   }\n"
            "   IDs must be sequential: INIT-001, INIT-002, etc.\n"
            "   Rules:\n"
            "   - enabler initiatives: set enabler_dependencies (other enablers required first), "
            "set change_dependencies to [].\n"
            "   - change_activity initiatives: set change_dependencies (enabler IDs required first), "
            "set enabler_dependencies to [].\n"
            "   - Valid dimensions: people, data, systems, organisation, partnership, "
            "architectural, operating_model.\n"
            "11. Use SQLiteStateTool with operation='write', key='initiative_register', "
            "agent_name='initiative_identifier' to save the JSON array.\n"
            "12. Use HumanInputTool with prompt: 'Please review the initiative register saved at "
            "outputs/initiative_register.json. Reply \"approved\" to conclude the Architecture "
            "phase, or provide notes.'\n"
            "13. If revision notes are received, revise and call HumanInputTool again. "
            "Maximum 3 revision cycles.\n"
        ),
        expected_output=(
            "A JSON initiative register saved to outputs/initiative_register.json "
            "containing at least 1 initiative per approved value proposition, "
            "each with id, title, description, proposition_ids, capability_uplifts "
            "(with dimension and description), initiative_type (enabler or change_activity), "
            "enabler_dependencies, change_dependencies, complexity_score, complexity_rationale, "
            "cost_estimate (low, high, currency, rationale), and related_requirements. "
            "Confirmed approved by a human reviewer."
        ),
        agent=agent,
        context=context_tasks,
    )
