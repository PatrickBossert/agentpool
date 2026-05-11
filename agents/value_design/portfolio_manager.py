# agents/value_design/portfolio_manager.py
from crewai import Agent, Task, LLM
from crewai.tools import BaseTool


def create_portfolio_manager(slug: str, llm: LLM, tools: list[BaseTool]) -> Agent:
    return Agent(
        role="Portfolio Manager",
        goal=(
            "Score and rank the approved value propositions into a prioritised portfolio "
            "using human-defined weighting criteria."
        ),
        backstory=(
            "You are a portfolio management specialist who helps organisations make "
            "evidence-based investment decisions. You apply structured scoring frameworks "
            "to rank initiatives objectively, then present the results in a clear register "
            "that senior stakeholders can act on."
        ),
        llm=llm,
        tools=tools,
        verbose=True,
        allow_delegation=False,
    )


def create_portfolio_manager_task(agent: Agent, context_tasks: list[Task]) -> Task:
    return Task(
        description=(
            "Score and rank the value propositions into a prioritised portfolio register "
            "using the IIRC Six Capitals framework plus Safety and Performance dimensions.\n\n"
            "Steps:\n"
            "1. Use SQLiteStateTool with operation='read', key='propositions', "
            "agent_name='portfolio_manager' to retrieve the approved value propositions.\n"
            "2. Score each proposition on all 8 dimensions below using a 0–10 scale where "
            "5 = neutral (no change from baseline), 0 = maximum depletion/risk/degradation, "
            "10 = transformational positive contribution. "
            "Provide one sentence of rationale and one reference unit per dimension.\n\n"
            "Dimension reference table (key | meaning | reference unit):\n"
            "  financial           | Net financial value relative to investment cost "
            "| NPV £M / IRR %\n"
            "  manufactured        | Impact on physical assets and infrastructure condition "
            "| Asset replacement value £M\n"
            "  intellectual        | Knowledge, IP, and data assets generated or consumed "
            "| R&D investment £M / IP count\n"
            "  human               | Workforce capability, capacity, and wellbeing "
            "| FTE-days / skills uplift\n"
            "  social_relationship | Stakeholder trust, community benefit, and partnerships "
            "| NPS / beneficiary count\n"
            "  natural             | Net environmental impact (depletion or regeneration) "
            "| CO₂e t / water ML / land ha\n"
            "  safety              | Risk reduction and ALARP compliance improvement "
            "| RIDDOR rate / safety risk score\n"
            "  performance         | Operational throughput, availability, and capacity "
            "| Throughput % / availability %\n\n"
            "3. Apply these fixed infrastructure weights (they sum to 100 — do not change them):\n"
            "   financial=20, manufactured=10, intellectual=5, human=5, "
            "social_relationship=5, natural=20, safety=20, performance=15\n"
            "4. Compute total_score using the formula:\n"
            "   total_score = (score_financial*20 + score_manufactured*10 "
            "+ score_intellectual*5 + score_human*5 + score_social_relationship*5 "
            "+ score_natural*20 + score_safety*20 + score_performance*15) / 100 * 10\n"
            "   Round to 1 decimal place. Result is on a 0–100 scale.\n"
            "   Example: scores 7,6,5,8,6,4,9,8 (in dimension order above) → "
            "(140+60+25+40+30+80+180+120)/100*10 = 67.5\n"
            "5. Rank propositions by total_score descending (rank 1 = highest). "
            "Break ties alphabetically by title.\n"
            "6. Build a JSON array where each item follows this schema exactly:\n"
            "   {\n"
            "     \"rank\": 1,\n"
            "     \"id\": \"VP-001\",\n"
            "     \"title\": \"...\",\n"
            "     \"change_articulation\": \"...\",\n"
            "     \"impacted_stakeholder_groups\": [...],\n"
            "     \"value_estimate\": \"High|Medium|Low\",\n"
            "     \"score_financial\": 7.5,\n"
            "     \"score_financial_rationale\": \"...\",\n"
            "     \"score_financial_unit\": \"NPV £M\",\n"
            "     \"score_manufactured\": 6.0,\n"
            "     \"score_manufactured_rationale\": \"...\",\n"
            "     \"score_manufactured_unit\": \"Asset replacement value £M\",\n"
            "     \"score_intellectual\": 5.5,\n"
            "     \"score_intellectual_rationale\": \"...\",\n"
            "     \"score_intellectual_unit\": \"R&D £M / IP count\",\n"
            "     \"score_human\": 8.0,\n"
            "     \"score_human_rationale\": \"...\",\n"
            "     \"score_human_unit\": \"FTE-days / skills uplift\",\n"
            "     \"score_social_relationship\": 6.5,\n"
            "     \"score_social_relationship_rationale\": \"...\",\n"
            "     \"score_social_relationship_unit\": \"NPS / beneficiary count\",\n"
            "     \"score_natural\": 4.0,\n"
            "     \"score_natural_rationale\": \"...\",\n"
            "     \"score_natural_unit\": \"CO₂e t / water ML / land ha\",\n"
            "     \"score_safety\": 9.0,\n"
            "     \"score_safety_rationale\": \"...\",\n"
            "     \"score_safety_unit\": \"RIDDOR rate / safety risk score\",\n"
            "     \"score_performance\": 8.5,\n"
            "     \"score_performance_rationale\": \"...\",\n"
            "     \"score_performance_unit\": \"Throughput % / availability %\",\n"
            "     \"total_score\": 74.5,\n"
            "     \"weights_used\": {\"financial\": 20, \"manufactured\": 10, "
            "\"intellectual\": 5, \"human\": 5, \"social_relationship\": 5, "
            "\"natural\": 20, \"safety\": 20, \"performance\": 15}\n"
            "   }\n"
            "7. Use SQLiteStateTool with operation='write', key='portfolio_register', "
            "agent_name='portfolio_manager' to save the JSON array.\n"
            "8. Use ExcelOutputTool with:\n"
            "    - rows: the portfolio register list\n"
            "    - columns: [\"rank\", \"id\", \"title\", \"value_estimate\", "
            "\"score_financial\", \"score_manufactured\", \"score_intellectual\", "
            "\"score_human\", \"score_social_relationship\", \"score_natural\", "
            "\"score_safety\", \"score_performance\", \"total_score\"]\n"
            "    - filename: 'portfolio_register.xlsx'\n"
            "    - agent_name: 'portfolio_manager'\n"
            "9. Use HumanInputTool with prompt: 'Portfolio register scored and saved to "
            "outputs/portfolio_register.xlsx. Please review the rankings. "
            "Reply \"approved\" to proceed, or provide notes.'\n"
            "10. If revision notes are received, revise scores or ranking and repeat "
            "steps 7–9. Maximum 3 revision cycles.\n"
        ),
        expected_output=(
            "A JSON portfolio register saved to outputs/portfolio_register.json "
            "and an Excel file at outputs/portfolio_register.xlsx, "
            "each containing all value propositions ranked by IIRC Six Capitals weighted score. "
            "Confirmed approved by a human reviewer."
        ),
        agent=agent,
        context=context_tasks,
    )
