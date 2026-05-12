# agents/value_design/value_proposition_generator.py
from crewai import Agent, Task, LLM
from crewai.tools import BaseTool


def create_value_proposition_generator(slug: str, llm: LLM, tools: list[BaseTool]) -> Agent:
    return Agent(
        role="Value Proposition Generator",
        goal=(
            "Synthesise the Discovery crew outputs into a clear, evidence-backed set of value "
            "propositions that articulate the business case for digital modernisation."
        ),
        backstory=(
            "You are a senior strategy consultant who specialises in translating analytical "
            "findings into compelling value propositions. You connect the dots between "
            "pain points, capability gaps, and quantifiable business outcomes to build "
            "a prioritised case for change."
        ),
        llm=llm,
        tools=tools,
        verbose=True,
        allow_delegation=False,
    )


def create_value_proposition_generator_task(agent: Agent) -> Task:
    return Task(
        description=(
            "Synthesise the Discovery crew outputs into a set of value propositions.\n\n"
            "Steps:\n"
            "1. Use SQLiteStateTool with operation='read', key='requirements', "
            "agent_name='value_proposition_generator' to retrieve the requirements register.\n"
            "2. Use SQLiteStateTool with operation='read', key='value_levers', "
            "agent_name='value_proposition_generator' to retrieve the value levers.\n"
            "3. Use SQLiteStateTool with operation='read', key='value_chain_summary', "
            "agent_name='value_proposition_generator' to retrieve the value chain summary.\n"
            "4. Use SQLiteStateTool with operation='read', key='user_journeys', "
            "agent_name='value_proposition_generator' to check for a user journey register. "
            "If the result starts with 'Error:', the register does not exist — skip it.\n"
            "4b. Use SQLiteStateTool with operation='read', key='activity_insights', "
            "agent_name='value_proposition_generator' to check for activity-level insights "
            "(actors, needs, frustrations per process activity). "
            "If the result starts with 'Error:', activity_insights do not exist — skip it and "
            "infer activity_refs from the value_chain_summary activities list instead.\n"
            "5. Identify 3–7 distinct value propositions by grouping related requirements, "
            "levers, pain points, and journey/activity opportunities. Each proposition should "
            "represent a coherent area of change with a clear business outcome.\n"
            "6. Produce a JSON array where each item follows this schema exactly:\n"
            "   {\n"
            "     \"id\": \"VP-001\",\n"
            "     \"title\": \"Short label (max 6 words)\",\n"
            "     \"change_articulation\": \"2–3 sentences describing what changes and why it matters\",\n"
            "     \"activity_refs\": [\"L3:Goods-in Inspection\", \"L3:Invoice Processing\"],\n"
            "     \"impacted_stakeholder_groups\": [\"...\"],\n"
            "     \"beneficiaries\": [\n"
            "       {\n"
            "         \"group\": \"Warehouse Operative\",\n"
            "         \"benefit_types\": [\"time_saving\", \"experience\"]\n"
            "       }\n"
            "     ],\n"
            "     \"value_estimate\": \"High|Medium|Low\",\n"
            "     \"value_estimate_rationale\": \"1–2 sentences justifying the estimate\",\n"
            "     \"supporting_evidence\": [\n"
            "       {\"type\": \"requirement|lever|pain_point|journey|activity\", \"ref\": \"...\", \"summary\": \"...\"}\n"
            "     ]\n"
            "   }\n"
            "   IDs must be sequential: VP-001, VP-002, etc.\n"
            "   activity_refs: list of strings in the format 'L3:<node_label>' "
            "(use 'L2:<node_label>' if no L3 nodes are available for this proposition). "
            "If activity_insights were absent, infer from the value chain summary activities.\n"
            "   beneficiaries: list one entry per distinct stakeholder group that benefits. "
            "Valid benefit_types: time_saving, cost_reduction, quality_improvement, "
            "risk_reduction, experience. A beneficiary may have multiple benefit_types.\n"
            "7. Use SQLiteStateTool with operation='write', key='propositions', "
            "agent_name='value_proposition_generator' to save the JSON array.\n"
            "8. Use HumanInputTool with prompt: 'Please review the value propositions saved at "
            "outputs/propositions.json. Reply \"approved\" to proceed to portfolio scoring, "
            "or provide revision notes.'\n"
            "9. If revision notes are received (not 'approved'), revise the propositions and "
            "call HumanInputTool again. Repeat at most 3 times total.\n"
        ),
        expected_output=(
            "A JSON array of 3–7 value propositions saved to outputs/propositions.json, "
            "each with id, title, change_articulation, activity_refs, beneficiaries, "
            "impacted_stakeholder_groups, value_estimate, value_estimate_rationale, and "
            "supporting_evidence. Confirmed approved by a human reviewer."
        ),
        agent=agent,
    )
