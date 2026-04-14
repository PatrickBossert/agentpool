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
            "7. Categorise each initiative:\n"
            "   - 'enabling': primarily technology or data infrastructure change\n"
            "   - 'operating_model': changes to processes, roles, or organisational structure\n"
            "   - 'business_change': strategic or customer-facing change requiring significant "
            "stakeholder engagement\n"
            "8. Produce a JSON array where each item follows this schema exactly:\n"
            "   {\n"
            "     \"id\": \"INIT-001\",\n"
            "     \"title\": \"Short initiative title (max 8 words)\",\n"
            "     \"description\": \"2–3 sentences describing what this initiative delivers\",\n"
            "     \"proposition_ids\": [\"VP-001\", \"VP-002\"],\n"
            "     \"capability_gaps\": [\"Gap description 1\", \"Gap description 2\"],\n"
            "     \"category\": \"enabling|operating_model|business_change\",\n"
            "     \"complexity_score\": 3,\n"
            "     \"complexity_rationale\": \"One sentence justifying the score\",\n"
            "     \"related_requirements\": [\"REQ-001\"]\n"
            "   }\n"
            "   IDs must be sequential: INIT-001, INIT-002, etc.\n"
            "9. Use SQLiteStateTool with operation='write', key='initiative_register', "
            "agent_name='initiative_identifier' to save the JSON array.\n"
            "10. Use HumanInputTool with prompt: 'Please review the initiative register "
            "(key=initiative_register in the project database). Reply \"approved\" to conclude "
            "the Architecture phase, or provide notes.'\n"
            "11. If revision notes are received, revise and call HumanInputTool again. "
            "Maximum 3 revision cycles.\n"
        ),
        expected_output=(
            "A JSON initiative register written to the project database under key='initiative_register', "
            "containing at least 1 initiative per approved value proposition, "
            "each with id, title, description, proposition_ids, capability_gaps, "
            "category, complexity_score, complexity_rationale, and related_requirements. "
            "Confirmed approved by a human reviewer."
        ),
        agent=agent,
        context=context_tasks,
    )
