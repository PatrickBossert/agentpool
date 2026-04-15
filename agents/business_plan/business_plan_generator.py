# agents/business_plan/business_plan_generator.py
from crewai import Agent, Task, LLM
from crewai.tools import BaseTool


def create_business_plan_generator(slug: str, llm: LLM, tools: list[BaseTool]) -> Agent:
    return Agent(
        role="Business Plan Generator",
        goal=(
            "Produce a complete, board-ready business plan that synthesises all prior "
            "analysis into a compelling investment case — with executive narrative, "
            "financial model, and presentation deck."
        ),
        backstory=(
            "You are a management consultant and business writer who transforms strategic "
            "analysis into compelling investment proposals. You draw on requirements, value "
            "propositions, initiative roadmaps, and financial modelling to build business "
            "cases that secure executive sponsorship and funding approval."
        ),
        llm=llm,
        tools=tools,
        verbose=True,
        allow_delegation=False,
    )


def create_business_plan_generator_task(agent: Agent) -> Task:
    return Task(
        description=(
            "Generate a complete business plan from all prior crew outputs.\n\n"
            "Steps:\n"
            "1. Read all five inputs via SQLiteStateTool:\n"
            "   - operation='read', key='requirements', agent_name='business_plan_generator'\n"
            "   - operation='read', key='value_levers', agent_name='business_plan_generator'\n"
            "   - operation='read', key='propositions', agent_name='business_plan_generator'\n"
            "   - operation='read', key='initiative_register', agent_name='business_plan_generator'\n"
            "   - operation='read', key='roadmap_data', agent_name='business_plan_generator'\n\n"
            "2. Pre-populate financial estimates from the data:\n"
            "   Initiative costs by complexity_score: 1=£50k, 2=£100k, 3=£200k, 4=£400k, 5=£800k\n"
            "   Annual benefits by value_estimate: High=£500k/yr, Medium=£200k/yr, Low=£100k/yr\n"
            "   Default discount rate: 8%\n"
            "   Period duration from roadmap_data.time_axis: quarters=3 months, years=12 months, "
            "horizons=18 months\n\n"
            "3. Use HumanInputTool to gather business context and confirm financial assumptions.\n"
            "   Prompt: 'To complete the business plan, please provide:\n"
            "   (1) Organisation name\n"
            "   (2) Financial year (e.g. FY2026)\n"
            "   (3) Primary business sponsor name and title\n"
            "   (4) Any additional context for the executive summary.\n"
            "   I have also pre-populated financial estimates — please confirm or adjust:\n"
            "   [List each initiative with estimated cost, each proposition with estimated "
            "annual benefit, and the default 8% discount rate.]\n"
            "   Reply with your details and \"confirmed\" or provide adjustments.'\n\n"
            "4. Generate all six business plan sections using LLM reasoning:\n"
            "   - Executive Summary (incorporating organisation name, sponsor, financial year, "
            "business context provided)\n"
            "   - Case for Change (from requirements + value_levers)\n"
            "   - Value Propositions (from propositions register)\n"
            "   - Initiative Roadmap (from roadmap_data — periods, initiatives by period)\n"
            "   - Investment & Benefits (from financial model — costs by period, benefits from "
            "realisation, NPV/IRR summary)\n"
            "   - Governance & Next Steps\n\n"
            "5. Use WordOutputTool with:\n"
            "   - sections: list of {title, content} dicts for all six sections\n"
            "   - metadata: {org_name, financial_year, sponsor, date}\n"
            "   - filename: 'business_plan.docx'\n"
            "   - agent_name: 'business_plan_generator'\n\n"
            "6. Assemble 8-10 slides and use PowerPointOutputTool with:\n"
            "   - slides: list of {title, content, notes} dicts\n"
            "   - metadata: {org_name, financial_year, sponsor, date}\n"
            "   - filename: 'executive_presentation.pptx'\n"
            "   - agent_name: 'business_plan_generator'\n\n"
            "7. Use FinancialModelTool with confirmed financial inputs:\n"
            "   - periods: list from roadmap_data.periods\n"
            "   - initiatives: list of {id, title, period, cost_gbp}\n"
            "   - propositions: list of {id, title, realisation_period, annual_benefit_gbp}\n"
            "   - discount_rate: confirmed or default 0.08\n"
            "   - period_duration_months: inferred from roadmap_data.time_axis\n"
            "   - filename: 'cost_benefit_model.xlsx'\n"
            "   - agent_name: 'business_plan_generator'\n\n"
            "8. Use HumanInputTool with prompt: 'Please review the outputs:\n"
            "   outputs/business_plan.docx\n"
            "   outputs/executive_presentation.pptx\n"
            "   outputs/cost_benefit_model.xlsx\n"
            "   Reply \"approved\" to conclude Business Plan generation, or provide "
            "revision notes.'\n\n"
            "9. If revision notes are received, revise the content and repeat steps 5-8. "
            "Maximum 3 revision cycles.\n"
        ),
        expected_output=(
            "Three artefacts saved to the outputs directory: "
            "business_plan.docx (6-section word document), "
            "executive_presentation.pptx (8-10 slide deck), "
            "cost_benefit_model.xlsx (3-sheet financial model with NPV, IRR, max borrowing). "
            "Confirmed approved by a human reviewer."
        ),
        agent=agent,
    )
