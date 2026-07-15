# agents/discovery/questionnaire_builder.py
from crewai import Agent, Task, LLM
from crewai.tools import BaseTool

_DEFAULT_SCALE = {
    "min": 0,
    "max": 4,
    "labels": {
        "0": "Not Accounted For",
        "1": "Initial",
        "2": "Developing",
        "3": "Managed",
        "4": "Optimised",
    },
}


def create_questionnaire_builder(slug: str, llm: LLM, tools: list[BaseTool]) -> Agent:
    return Agent(
        role="Maturity Assessment Questionnaire Builder",
        goal=(
            "Design a comprehensive maturity assessment questionnaire for each L2 process stage "
            "in the value chain, grounded in the client's corporate context and relevant "
            "industry standards and references."
        ),
        backstory=(
            "You are a management consultant and maturity model expert with deep knowledge of "
            "ISO 55001 (asset management), IIMM, PAS 55, IIRC Six Capitals, and sector-specific "
            "frameworks. You translate value chain process stages into actionable maturity "
            "assessments that organisations can self-assess against a 0–4 scale."
        ),
        llm=llm,
        tools=tools,
        verbose=True,
        allow_delegation=False,
    )


def create_questionnaire_builder_task(
    agent: Agent,
    standards_references: str = "",
    preferred_sections: int = 4,
    preferred_questions: int = 3,
) -> Task:
    standards_block = (
        f"Relevant standards and references to use as the basis for questionnaire content:\n"
        f"{standards_references}\n\n"
        if standards_references
        else "Use ISO 55001 (asset management), IIRC Six Capitals, and sector best-practice frameworks.\n\n"
    )

    return Task(
        description=(
            "Design maturity assessment questionnaires for every active L1 and L2 node "
            "in the value chain. L1 questionnaires target senior leaders (GMs, value stream owners) "
            "with a strategic/portfolio lens. L2 questionnaires target process stage managers "
            "with an operational lens.\n\n"
            f"{standards_block}"
            f"Questionnaire structure preferences: {preferred_sections} sections per questionnaire, "
            f"{preferred_questions} questions per section.\n\n"
            "Steps:\n"
            "1. Use SQLiteStateTool with operation='read', key='value_chain_registry', "
            "agent_name='questionnaire_builder' to load the activity registry. "
            "Collect every entry where active=true and level is either 'L1' or 'L2'. "
            "These are all the nodes you must cover.\n"
            "2. Use SQLiteStateTool with operation='read', key='value_chain_summary', "
            "agent_name='questionnaire_builder' to understand the client's operations.\n"
            "3. Use ChromaQueryTool with collection='project' to gather additional corporate "
            "context relevant to maturity assessment (governance, standards adopted, known gaps).\n"
            "4. For each node, design a maturity assessment questionnaire suited to its level:\n"
            "   L1 questionnaires (for senior leaders):\n"
            "   - Focus on strategic intent, portfolio oversight, resource allocation, governance\n"
            "   - Questions are answerable by a GM or value stream owner in 2–3 sentences\n"
            "   - Section titles reference strategic framework dimensions (e.g. IIRC Six Capitals)\n"
            "   L2 questionnaires (for process stage managers):\n"
            "   - Focus on process control, standard adherence, data quality, improvement culture\n"
            "   - Questions are answerable by a process owner in 1–2 sentences\n"
            "   - Section titles reference relevant standard clauses where applicable\n"
            "   Both levels:\n"
            "   - Each question has a clear maturity framing (level 0=nothing in place; "
            "level 4=fully optimised and continually improved)\n"
            "5. Output a single JSON object keyed by the node_label (exactly as it appears "
            "in the registry), where each value is a questionnaire object:\n"
            "   {\n"
            "     \"<node_label>\": {\n"
            "       \"level\": \"L1\",\n"
            "       \"scale\": {\n"
            "         \"min\": 0, \"max\": 4,\n"
            "         \"labels\": {\n"
            "           \"0\": \"Not Accounted For\",\n"
            "           \"1\": \"Initial\",\n"
            "           \"2\": \"Developing\",\n"
            "           \"3\": \"Managed\",\n"
            "           \"4\": \"Optimised\"\n"
            "         }\n"
            "       },\n"
            "       \"sections\": [\n"
            "         {\n"
            "           \"id\": \"s1\",\n"
            "           \"title\": \"Strategic Direction & Governance\",\n"
            "           \"description\": \"Degree to which the value stream is strategically directed\",\n"
            "           \"questions\": [\n"
            "             {\"id\": \"q1\", \"text\": \"Is there a documented strategy for this value stream "
            "aligned to corporate objectives?\"},\n"
            "             {\"id\": \"q2\", \"text\": \"How are investment priorities within this value "
            "stream determined and reviewed?\"}\n"
            "           ]\n"
            "         }\n"
            "       ]\n"
            "     }\n"
            "   }\n"
            "6. Use SQLiteStateTool with operation='write', key='questionnaire_scripts', "
            "agent_name='questionnaire_builder' to save the complete JSON object.\n"
        ),
        expected_output=(
            "A JSON object saved to outputs/questionnaire_scripts.json containing one maturity "
            "assessment questionnaire per L1 and L2 node (keyed by node_label), with L1 "
            "questionnaires targeting senior leaders at a strategic level and L2 questionnaires "
            "targeting process stage managers at an operational level."
        ),
        agent=agent,
    )
