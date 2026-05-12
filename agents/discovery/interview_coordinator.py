# agents/discovery/interview_coordinator.py
from crewai import Agent, Task, LLM
from crewai.tools import BaseTool


def create_interview_coordinator(slug: str, llm: LLM, tools: list[BaseTool]) -> Agent:
    return Agent(
        role="Interview Coordinator",
        goal=(
            "Plan the stakeholder interview programme by designing tailored questions "
            "for each assigned stakeholder based on their value chain node and role."
        ),
        backstory=(
            "You are a senior discovery consultant who designs interview programmes "
            "for digital transformation engagements. You craft questions that surface "
            "process pain points, actors, needs, and capability gaps at each node of "
            "the value chain."
        ),
        llm=llm,
        tools=tools,
        verbose=True,
        allow_delegation=False,
    )


def create_interview_coordinator_task(
    agent: Agent,
    stakeholder_assignments: str = "",
) -> Task:
    assignments_block = (
        f"Stakeholder assignments:\n{stakeholder_assignments}\n\n"
        if stakeholder_assignments
        else ""
    )
    return Task(
        description=(
            f"{assignments_block}"
            "Design the stakeholder interview programme for this project.\n\n"
            "Steps:\n"
            "1. Use SQLiteStateTool with operation='read', key='value_chain_tree', "
            "agent_name='interview_coordinator' to retrieve the approved value chain structure.\n"
            "2. For each stakeholder listed in the assignments above, design 5–8 tailored "
            "interview questions. Base the questions on:\n"
            "   - The value chain node(s) they are assigned to (their operational domain)\n"
            "   - Their job title and inferred responsibilities\n"
            "   - What actors, needs, and frustrations are likely at that node\n"
            "3. Structure your output as a JSON array where each element is:\n"
            "   {\n"
            "     \"stakeholder_id\": 1,\n"
            "     \"name\": \"Alice Chen\",\n"
            "     \"job_title\": \"Head of Ops\",\n"
            "     \"node_labels\": [\"Order Fulfilment\"],\n"
            "     \"questions\": [\n"
            "       \"Walk me through how an order is received and processed today.\",\n"
            "       \"What are the most common causes of delay in this process?\"\n"
            "     ]\n"
            "   }\n"
            "4. Use SQLiteStateTool with operation='write', key='interview_plan', "
            "agent_name='interview_coordinator' to save the JSON array.\n"
            "5. Use HumanInputTool with prompt: 'Please review the interview plan saved at "
            "outputs/interview_plan.json. Reply \"approved\" to proceed, or provide revision notes.'\n"
            "6. If revision notes are received, revise the plan and call HumanInputTool again. "
            "Repeat at most 3 times total.\n"
        ),
        expected_output=(
            "A JSON interview plan saved to outputs/interview_plan.json containing one entry "
            "per assigned stakeholder with tailored questions. Confirmed approved by a human reviewer."
        ),
        agent=agent,
    )
