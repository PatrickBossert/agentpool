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
            "Score and rank the value propositions into a prioritised portfolio register.\n\n"
            "Steps:\n"
            "1. Use SQLiteStateTool with operation='read', key='propositions', "
            "agent_name='portfolio_manager' to retrieve the approved value propositions.\n"
            "2. Use HumanInputTool with prompt: 'Please provide ranking weights for portfolio "
            "scoring as a JSON object. Weights are integers 1–10. Example: "
            "{\"value\": 5, \"feasibility\": 3, \"strategic_fit\": 2}. "
            "These will be normalised to sum to 100%.'\n"
            "3. Parse the human's JSON response to extract value, feasibility, and "
            "strategic_fit weights. Accept numeric values (integer or float). "
            "If the response cannot be parsed as JSON, or if a key is missing from the parsed "
            "object, substitute that key's default value: value=5, feasibility=3, strategic_fit=2. "
            "Zero weights are valid but note they remove a dimension from the ranking.\n"
            "4. Normalise weights so they sum to 1.0: "
            "w_value = value / total, w_feasibility = feasibility / total, "
            "w_strategic_fit = strategic_fit / total.\n"
            "5. Score each proposition on a 0–10 scale for each dimension "
            "(value impact, feasibility of delivery, strategic fit to company direction). "
            "Justify each score with one sentence. "
            "Scores: 0 = no benefit/impossible/no fit; 10 = transformational/trivial/perfect fit.\n"
            "6. Compute total_score = (score_value * w_value + score_feasibility * w_feasibility "
            "+ score_strategic_fit * w_strategic_fit) * 10, rounded to 1 decimal place. "
            "This converts the 0–10 weighted average to a 0–100 percentage scale. "
            "Example: if score_value=8, score_feasibility=6, score_strategic_fit=9, "
            "weights normalised to value=0.5, feasibility=0.3, strategic_fit=0.2, "
            "then total_score = (8*0.5 + 6*0.3 + 9*0.2) * 10 = (4.0+1.8+1.8) * 10 = 76.0.\n"
            "7. Rank propositions by total_score descending (rank 1 = highest). "
            "Break ties alphabetically by title.\n"
            "8. Build a JSON array where each item follows this schema exactly:\n"
            "   {\n"
            "     \"rank\": 1,\n"
            "     \"id\": \"VP-001\",\n"
            "     \"title\": \"...\",\n"
            "     \"change_articulation\": \"...\",\n"
            "     \"impacted_stakeholder_groups\": [...],\n"
            "     \"value_estimate\": \"High|Medium|Low\",\n"
            "     \"score_value\": 8.5,\n"
            "     \"score_feasibility\": 6.0,\n"
            "     \"score_strategic_fit\": 9.0,\n"
            "     \"score_value_rationale\": \"...\",\n"
            "     \"score_feasibility_rationale\": \"...\",\n"
            "     \"score_strategic_fit_rationale\": \"...\",\n"
            "     \"total_score\": 82.5,\n"
            "     \"weights_used\": {\"value\": 5, \"feasibility\": 3, \"strategic_fit\": 2}\n"
            "   }\n"
            "9. Use SQLiteStateTool with operation='write', key='portfolio_register', "
            "agent_name='portfolio_manager' to save the JSON array.\n"
            "10. Use ExcelOutputTool with:\n"
            "    - rows: the portfolio register list\n"
            "    - columns: [\"rank\", \"id\", \"title\", \"value_estimate\", \"score_value\", "
            "\"score_feasibility\", \"score_strategic_fit\", \"total_score\"]\n"
            "    - filename: 'portfolio_register.xlsx'\n"
            "    - agent_name: 'portfolio_manager'\n"
            "11. Use HumanInputTool with prompt: 'Portfolio register scored and saved to "
            "outputs/portfolio_register.xlsx. Please review the rankings. "
            "Reply \"approved\" to proceed, or provide notes.'\n"
            "12. If revision notes are received, revise scores or ranking and repeat "
            "steps 9–11. Maximum 3 revision cycles.\n"
        ),
        expected_output=(
            "A JSON portfolio register saved to outputs/portfolio_register.json "
            "and an Excel file at outputs/portfolio_register.xlsx, "
            "each containing all value propositions ranked by weighted score. "
            "Confirmed approved by a human reviewer."
        ),
        agent=agent,
        context=context_tasks,
    )
