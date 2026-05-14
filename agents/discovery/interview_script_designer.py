# agents/discovery/interview_script_designer.py
from crewai import Agent, Task, LLM
from agents.tools.registry import get_tools_for_agent


def create_interview_script_designer_agent(
    slug: str,
    run_id: int,
    llm_mode: str,
    sector: str,
    llm=None,
    tools=None,
) -> Agent:
    if tools is None:
        tools = get_tools_for_agent(
            "interview_script_designer",
            slug=slug,
            run_id=run_id,
            sector=sector,
        )
    return Agent(
        role="Interview Script Designer",
        goal=(
            "Produce one structured interview script per value chain node that has "
            "stakeholder assignments, ensuring each script is rich, section-based, "
            "and includes pre-scripted follow-up branches and evasion signals."
        ),
        backstory=(
            "You are an expert qualitative researcher who designs precise, structured "
            "interview guides. You read the value chain context and produce scripts that "
            "are rich, section-based, and include pre-scripted follow-up branches and "
            "evasion signals for each question."
        ),
        llm=llm,
        tools=tools,
        verbose=True,
        allow_delegation=False,
    )


def create_interview_script_designer_task(
    agent: Agent,
    discovery_brief: str = "",
    stakeholder_assignments_block: str = "",
    node_templates_block: str = "",   # NEW
) -> Task:
    brief_block = (
        f"Discovery brief:\n{discovery_brief}\n\n"
        if discovery_brief
        else ""
    )
    assignments_block = (
        f"Stakeholder assignments by node:\n{stakeholder_assignments_block}\n\n"
        if stakeholder_assignments_block
        else ""
    )
    templates_block = (
        f"Assigned interview templates by node (use as starting point if provided):\n"
        f"{node_templates_block}\n\n"
        "For nodes that have an assigned template, adapt the template questions to fit this "
        "specific value chain node and engagement context. You may add, remove, or rephrase "
        "questions, but preserve the overall structure and follow-up branch pattern.\n"
        "For nodes without an assigned template, design from scratch as before.\n\n"
        if node_templates_block
        else ""
    )
    return Task(
        description=(
            "Design one structured interview script for every value chain node that "
            "appears in the stakeholder assignments below.\n\n"
            f"{brief_block}"
            f"{assignments_block}"
            f"{templates_block}"
            "Steps:\n"
            "1. Use SQLiteStateTool with operation='read', key='value_chain_tree', "
            "agent_name='interview_script_designer' to retrieve the approved value chain structure.\n"
            "2. Use SQLiteStateTool with operation='read', key='value_chain_summary', "
            "agent_name='interview_script_designer' to retrieve the value chain summary.\n"
            "3. For each node_label that appears in the stakeholder assignments block above, "
            "design one complete interview script following the structure guidelines:\n"
            "   - 4–6 thematic sections per script (e.g. Role & Context, Current Process & "
            "Pain Points, Data & Decision-Making, Tools & Systems, Modernisation Priorities)\n"
            "   - 2–4 questions per section; 8–14 questions total\n"
            "   - Each question has 1–3 pre-generated follow_up_branches and a list of "
            "evasion_signals\n"
            "   - welcome_message and closing_message are warm, professional, referencing "
            "the engagement purpose\n"
            "   - research_brief (2-3 sentences) and study_objectives are tailored to the "
            "node's position in the value chain\n"
            "4. Output the scripts as a single JSON object keyed by node_label, where each "
            "value follows this schema:\n"
            "   {\n"
            "     \"<node_label>\": {\n"
            "       \"node_label\": \"<node_label>\",\n"
            "       \"level\": \"L3\",\n"
            "       \"research_brief\": \"2-3 sentences on the purpose of this interview "
            "for this node\",\n"
            "       \"study_objectives\": [\n"
            "         \"Identify biggest pain points at this stage\",\n"
            "         \"Understand data requirements\"\n"
            "       ],\n"
            "       \"welcome_message\": \"Hi [name], thank you for joining...\",\n"
            "       \"closing_message\": \"Thank you for your time and insights...\",\n"
            "       \"sections\": [\n"
            "         {\n"
            "           \"title\": \"Role & Context\",\n"
            "           \"questions\": [\n"
            "             {\n"
            "               \"id\": \"Q1\",\n"
            "               \"text\": \"Tell me about your role...\",\n"
            "               \"follow_up_count\": 2,\n"
            "               \"probing_instructions\": \"Probe for day-to-day responsibilities...\",\n"
            "               \"follow_up_branches\": [\n"
            "                 \"Could you walk me through a specific example?\",\n"
            "                 \"What does that look like on a typical day?\"\n"
            "               ],\n"
            "               \"evasion_signals\": [\"not sure\", \"it varies\", \"it's fine\", "
            "\"I don't know\"]\n"
            "             }\n"
            "           ]\n"
            "         }\n"
            "       ]\n"
            "     }\n"
            "   }\n"
            "5. Use SQLiteStateTool with operation='write', key='interview_scripts', "
            "agent_name='interview_script_designer' to save the complete JSON object.\n"
            "6. Use HumanInputTool with prompt: 'Please review the interview scripts saved at "
            "outputs/interview_scripts.json. Reply \"approved\" to proceed, or provide revision "
            "notes.'\n"
            "7. If revision notes are received, revise the scripts and call HumanInputTool again. "
            "Repeat at most 3 times total.\n"
        ),
        expected_output=(
            "A JSON object saved to outputs/interview_scripts.json containing one structured "
            "interview script per value chain node, keyed by node_label. Confirmed approved "
            "by a human reviewer."
        ),
        agent=agent,
    )
