# agents/discovery/interaction_designer.py
"""Interaction Designer — designs interview scripts and maturity questionnaires together."""
from crewai import Agent, Task, LLM
from crewai.tools import BaseTool


def create_interaction_designer(slug: str, llm: LLM, tools: list[BaseTool]) -> Agent:
    return Agent(
        role="Interaction Designer",
        goal=(
            "Design a coherent set of interview scripts and maturity assessment questionnaires "
            "for every active L1 and L2 value chain node, ensuring both instruments cover the "
            "same assessment dimensions so findings can be triangulated."
        ),
        backstory=(
            "You are a specialist in organisational assessment design. You combine management "
            "consulting interview technique with structured questionnaire design and deep "
            "knowledge of asset management standards (ISO 55001, IIMM, PAS 55) and the IIRC "
            "Six Capitals framework. You design instruments as a system: the interview script "
            "probes for qualitative insight and narrative while the questionnaire captures "
            "structured maturity ratings — both anchored to the same dimensions so the two "
            "data sources can be compared and synthesised. You distinguish clearly between "
            "L1 strategic instruments (for senior leaders: GMs, value stream owners) and L2 "
            "operational instruments (for process stage managers and practitioners)."
        ),
        llm=llm,
        tools=tools,
        verbose=True,
        allow_delegation=False,
    )


def create_interaction_designer_task(
    agent: Agent,
    standards_references: str = "",
    preferred_sections: int = 4,
    preferred_questions: int = 3,
) -> Task:
    standards_block = (
        f"Standards and frameworks to draw on:\n{standards_references}\n\n"
        if standards_references
        else "Draw on ISO 55001, IIMM, PAS 55, IIRC Six Capitals, and sector best-practice.\n\n"
    )

    return Task(
        description=(
            "Design interview scripts AND maturity questionnaires for every active L1 and L2 "
            "value chain node. Both instruments must cover the same assessment dimensions per node "
            "so qualitative interview data and quantitative maturity ratings can be triangulated.\n\n"
            f"{standards_block}"
            f"Questionnaire preferences: {preferred_sections} sections, "
            f"{preferred_questions} questions per section.\n\n"
            "Steps:\n"
            "1. Use SQLiteStateTool with operation='read', key='value_chain_registry', "
            "agent_name='interaction_designer' to load the activity registry. "
            "Collect every entry where active=true and level is 'L1' or 'L2'.\n"
            "2. Use SQLiteStateTool with operation='read', key='value_chain_summary', "
            "agent_name='interaction_designer' to understand the client's operations.\n"
            "3. Use ChromaQueryTool with collection='project' to gather corporate context "
            "(governance posture, known capability gaps, adopted standards, language used).\n"
            "4. For each L1 node (strategic/portfolio level — owned by a GM or value stream leader):\n"
            "   a) Identify 3–5 strategic assessment dimensions (e.g. Vision & Strategy, "
            "Portfolio Governance, Resource Allocation, Performance Culture, Stakeholder Value).\n"
            "   b) Design an INTERVIEW SCRIPT with:\n"
            "      - 3–4 sections aligned to the strategic dimensions\n"
            "      - 2–3 questions per section (open, exploratory)\n"
            "      - welcome_message and closing_message (warm, senior-level tone)\n"
            "      - research_brief and study_objectives framed at portfolio level\n"
            "      - follow_up_branches and evasion_signals per question\n"
            "   c) Design a QUESTIONNAIRE with:\n"
            "      - Same 3–5 dimensions as sections\n"
            "      - 2–3 maturity questions per section (0=nothing in place, 4=fully optimised)\n"
            "      - Section titles reference the relevant framework dimension\n"
            "5. For each L2 node (operational/process stage level — owned by a process manager):\n"
            "   a) Identify 3–5 operational assessment dimensions aligned to the standards "
            "relevant to that process stage (e.g. Process Definition, Data Quality, "
            "Tool Effectiveness, Compliance, Improvement Maturity).\n"
            "   b) Design an INTERVIEW SCRIPT with:\n"
            "      - 4–5 sections aligned to the operational dimensions\n"
            "      - 2–3 questions per section (probing, specific)\n"
            "      - welcome_message and closing_message (professional, process-focused tone)\n"
            "      - research_brief and study_objectives framed at process stage level\n"
            "      - follow_up_branches and evasion_signals per question\n"
            "   c) Design a QUESTIONNAIRE with:\n"
            "      - Same operational dimensions as sections\n"
            "      - 2–4 maturity questions per section\n"
            "      - Section titles reference the relevant standard clause where applicable\n"
            "6. Output the INTERVIEW SCRIPTS as a JSON object keyed by node_label:\n"
            "   {\n"
            "     \"<node_label>\": {\n"
            "       \"node_label\": \"<node_label>\",\n"
            "       \"level\": \"L1\",\n"
            "       \"research_brief\": \"...\",\n"
            "       \"study_objectives\": [\"...\"],\n"
            "       \"welcome_message\": \"...\",\n"
            "       \"closing_message\": \"...\",\n"
            "       \"sections\": [\n"
            "         { \"title\": \"...\", \"questions\": [\n"
            "           { \"id\": \"Q1\", \"text\": \"...\", \"follow_up_count\": 2,\n"
            "             \"probing_instructions\": \"...\",\n"
            "             \"follow_up_branches\": [\"...\"],\n"
            "             \"evasion_signals\": [\"not sure\", \"it varies\"] }\n"
            "         ]}\n"
            "       ]\n"
            "     }\n"
            "   }\n"
            "   Use SQLiteStateTool with operation='write', key='interview_scripts', "
            "agent_name='interaction_designer' to save this.\n"
            "7. Output the QUESTIONNAIRES as a JSON object keyed by node_label:\n"
            "   {\n"
            "     \"<node_label>\": {\n"
            "       \"level\": \"L1\",\n"
            "       \"scale\": { \"min\": 0, \"max\": 4,\n"
            "         \"labels\": { \"0\": \"Not Accounted For\", \"1\": \"Initial\",\n"
            "           \"2\": \"Developing\", \"3\": \"Managed\", \"4\": \"Optimised\" }\n"
            "       },\n"
            "       \"sections\": [\n"
            "         { \"id\": \"s1\", \"title\": \"...\", \"description\": \"...\",\n"
            "           \"questions\": [ { \"id\": \"q1\", \"text\": \"...\" } ]\n"
            "         }\n"
            "       ]\n"
            "     }\n"
            "   }\n"
            "   Use SQLiteStateTool with operation='write', key='questionnaire_scripts', "
            "agent_name='interaction_designer' to save this.\n"
            "8. Use HumanInputTool with prompt: 'Assessment instruments saved. Please review "
            "outputs/interview_scripts.json and outputs/questionnaire_scripts.json. "
            "Reply \"approved\" to proceed, or provide revision notes.'\n"
            "9. If revision notes received, revise both files and call HumanInputTool again. "
            "Repeat at most 3 times total.\n"
        ),
        expected_output=(
            "Two JSON files saved via SQLiteStateTool: interview_scripts.json containing one "
            "structured interview script per L1 and L2 node, and questionnaire_scripts.json "
            "containing one maturity questionnaire per L1 and L2 node, both keyed by node_label "
            "and covering the same assessment dimensions per node. Approved by human reviewer."
        ),
        agent=agent,
    )
