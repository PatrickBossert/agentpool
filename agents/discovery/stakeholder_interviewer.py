# agents/discovery/stakeholder_interviewer.py
from crewai import Agent, Task, LLM
from crewai.tools import BaseTool


def create_stakeholder_interviewer(slug: str, llm: LLM, tools: list[BaseTool]) -> Agent:
    return Agent(
        role="Stakeholder Interviewer",
        goal=(
            "Conduct text-based interviews with each assigned stakeholder, "
            "capturing their responses verbatim to build a rich discovery transcript."
        ),
        backstory=(
            "You are an experienced discovery interviewer who builds rapport quickly "
            "and asks probing follow-up questions. You faithfully record responses "
            "without interpretation, preserving the stakeholder's own language."
        ),
        llm=llm,
        tools=tools,
        verbose=True,
        allow_delegation=False,
    )


def create_stakeholder_interviewer_task(
    agent: Agent,
    context_tasks: list[Task],
) -> Task:
    return Task(
        description=(
            "Conduct text-based interviews with each stakeholder listed in the interview plan.\n\n"
            "Steps:\n"
            "1. Use SQLiteStateTool with operation='read', key='interview_plan', "
            "agent_name='stakeholder_interviewer' to retrieve the interview plan.\n"
            "2. For each stakeholder in the plan, conduct their interview:\n"
            "   a. Use HumanInputTool with a prompt that introduces yourself and the purpose "
            "of the interview, then asks the first question. Example:\n"
            "      'Hi [Name], I'm conducting a discovery interview for this engagement. "
            "I'd like to ask you about [node_labels]. "
            "First question: [questions[0]]'\n"
            "   b. Record the response, then ask each subsequent question in turn using "
            "HumanInputTool. Adapt follow-up phrasing naturally based on prior answers.\n"
            "   c. Once all questions are asked, thank the stakeholder and move to the next.\n"
            "3. Compile all Q&A pairs into a JSON array where each element is:\n"
            "   {\n"
            "     \"stakeholder_id\": 1,\n"
            "     \"name\": \"Alice Chen\",\n"
            "     \"node_labels\": [\"Order Fulfilment\"],\n"
            "     \"qa_pairs\": [\n"
            "       {\"question\": \"Walk me through how an order is processed.\", "
            "\"answer\": \"We receive orders via email...\"}\n"
            "     ]\n"
            "   }\n"
            "4. Use SQLiteStateTool with operation='write', key='interview_transcripts', "
            "agent_name='stakeholder_interviewer' to save the JSON array.\n"
        ),
        expected_output=(
            "A JSON transcript file saved to outputs/interview_transcripts.json containing "
            "all Q&A pairs for every interviewed stakeholder."
        ),
        agent=agent,
        context=context_tasks,
    )
