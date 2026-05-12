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
            f"AI strategy consulting. You use RunCrewTool to run each crew and "
            f"SlackNotifyTool to post progress updates."
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
            f"Then use SlackNotifyTool to send: "
            f"'✓ Value chain mapping complete for {slug}. Awaiting stakeholder assignment.'"
        ),
        expected_output="Confirmation that discovery_mapping crew completed and Slack notified.",
        agent=agent,
    )


def create_run_discovery_interviews_task(agent: Agent, slug: str, context_tasks: list) -> Task:
    return Task(
        description=(
            f"Use RunCrewTool with crew_name='discovery_interviews' to run the "
            f"Discovery Interviews crew for project '{slug}'. Wait for it to complete. "
            f"Then use SlackNotifyTool to send: "
            f"'✓ Discovery interviews complete for {slug}. Starting Value Design.'"
        ),
        expected_output="Confirmation that discovery_interviews crew completed and Slack notified.",
        agent=agent,
        context=context_tasks,
    )


def create_run_value_design_task(agent: Agent, slug: str, context_tasks: list) -> Task:
    return Task(
        description=(
            f"Use RunCrewTool with crew_name='value_design' to run the Value Design crew "
            f"for project '{slug}'. Wait for it to complete. "
            f"Then use SlackNotifyTool to send: "
            f"'✓ Value Design complete for {slug}. Starting Architecture.'"
        ),
        expected_output="Confirmation that value_design crew completed and Slack notified.",
        agent=agent,
        context=context_tasks,
    )


def create_run_architecture_task(agent: Agent, slug: str, context_tasks: list) -> Task:
    return Task(
        description=(
            f"Use RunCrewTool with crew_name='architecture' to run the Architecture crew "
            f"for project '{slug}'. Wait for it to complete. "
            f"Then use SlackNotifyTool to send: "
            f"'✓ Architecture complete for {slug}. Starting Delivery Planning.'"
        ),
        expected_output="Confirmation that architecture crew completed and Slack notified.",
        agent=agent,
        context=context_tasks,
    )


def create_run_delivery_task(agent: Agent, slug: str, context_tasks: list) -> Task:
    return Task(
        description=(
            f"Use RunCrewTool with crew_name='delivery' to run the Delivery Planning crew "
            f"for project '{slug}'. Wait for it to complete. "
            f"Then use SlackNotifyTool to send: "
            f"'✓ Delivery Planning complete for {slug}. Starting Business Plan.'"
        ),
        expected_output="Confirmation that delivery crew completed and Slack notified.",
        agent=agent,
        context=context_tasks,
    )


def create_run_business_plan_task(agent: Agent, slug: str, context_tasks: list) -> Task:
    return Task(
        description=(
            f"Use RunCrewTool with crew_name='business_plan' to run the Business Plan crew "
            f"for project '{slug}'. Wait for it to complete. "
            f"Then use SlackNotifyTool to send: "
            f"'✓ {slug} pipeline complete. All outputs ready.'"
        ),
        expected_output="Confirmation that business_plan crew completed and full pipeline notified.",
        agent=agent,
        context=context_tasks,
    )
