# agents/pam/pam_agent.py
"""PAM agent factory and task factories for the orchestration crew."""
from crewai import Agent, Task, LLM
from agents.pam import PAM_ROLE, PAM_GOAL


def create_pam_agent(slug: str, llm: LLM, tools: list) -> Agent:
    return Agent(
        role=PAM_ROLE,
        goal=PAM_GOAL,
        backstory=(
            f"You are PAM, the Programme Architecture Manager for AgentPool. "
            f"You are orchestrating project '{slug}'. "
            f"You orchestrate specialist crews in sequence to deliver end-to-end "
            f"AI strategy consulting. You use RunCrewTool to run each crew."
        ),
        llm=llm,
        tools=tools,
        verbose=True,
    )


def create_run_discovery_mapping_task(agent: Agent, slug: str) -> Task:
    return Task(
        description=(
            f"Use RunCrewTool with crew_name='discovery_mapping' to run the Discovery Mapping crew "
            f"for project '{slug}'. Wait for it to complete. "
            f"Report that the crew completed and that {slug} awaits stakeholder assignment."
        ),
        expected_output="Confirmation that the discovery_mapping crew completed.",
        agent=agent,
    )


def create_run_discovery_interviews_task(agent: Agent, slug: str, context_tasks: list) -> Task:
    return Task(
        description=(
            f"Use RunCrewTool with crew_name='discovery_interviews' to run the "
            f"Discovery Interviews crew for project '{slug}'. Wait for it to complete. "
            f"Report that the crew completed and that Value Design is next for {slug}."
        ),
        expected_output="Confirmation that the discovery_interviews crew completed.",
        agent=agent,
        context=context_tasks,
    )


def create_run_value_design_task(agent: Agent, slug: str, context_tasks: list) -> Task:
    return Task(
        description=(
            f"Use RunCrewTool with crew_name='value_design' to run the Value Design crew "
            f"for project '{slug}'. Wait for it to complete. "
            f"Report that the crew completed and that Capabilities is next for {slug}."
        ),
        expected_output="Confirmation that the value_design crew completed.",
        agent=agent,
        context=context_tasks,
    )


def create_run_capabilities_task(agent: Agent, slug: str, context_tasks: list) -> Task:
    return Task(
        description=(
            f"Use RunCrewTool with crew_name='capabilities' to run the Capabilities crew "
            f"for project '{slug}'. Wait for it to complete. "
            f"Report that the crew completed and that Delivery Planning is next for {slug}."
        ),
        expected_output="Confirmation that the capabilities crew completed.",
        agent=agent,
        context=context_tasks,
    )


def create_run_delivery_task(agent: Agent, slug: str, context_tasks: list) -> Task:
    return Task(
        description=(
            f"Use RunCrewTool with crew_name='delivery' to run the Delivery Planning crew "
            f"for project '{slug}'. Wait for it to complete. "
            f"Report that the crew completed and that the Business Plan is next for {slug}."
        ),
        expected_output="Confirmation that the delivery crew completed.",
        agent=agent,
        context=context_tasks,
    )


def create_run_business_plan_task(agent: Agent, slug: str, context_tasks: list) -> Task:
    return Task(
        description=(
            f"Use RunCrewTool with crew_name='business_plan' to run the Business Plan crew "
            f"for project '{slug}'. Wait for it to complete. "
            f"Report that the crew completed and that the {slug} pipeline is finished."
        ),
        expected_output="Confirmation that the business_plan crew completed, ending the pipeline.",
        agent=agent,
        context=context_tasks,
    )
