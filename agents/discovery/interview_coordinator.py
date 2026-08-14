# agents/discovery/interview_coordinator.py
from crewai import Agent, Task, LLM
from crewai.tools import BaseTool

VOICE_LOCALE_TABLE = """Voice locale lookup table (language/country_code → ElevenLabs voice ID):
  en/GB → 21m00Tcm4TlvDq8ikWAM  (Rachel)
  en/US → 21m00Tcm4TlvDq8ikWAM  (Rachel)
  en/AU → AZnzlk1XvdvUeBnXmlld  (Domi)
  en/NZ → MF3mGyEYCl7XYWbV9V6O  (Elli)
  en/CA → TxGEqnHWrfWFTfGW9XjX  (Josh)
  fr/FR → pNInz6obpgDQGcFmaJgB  (Adam)
  de/DE → yoZ06aMxZJJ28mfd3POQ  (Sam)
  es/ES → ErXwobaYiN019PkySvjV  (Antoni)
  (default / no match) → 21m00Tcm4TlvDq8ikWAM  (Rachel, en/GB)"""


def create_interview_coordinator(slug: str, llm: LLM, tools: list[BaseTool]) -> Agent:
    return Agent(
        role="Interview Coordinator",
        goal=(
            "Plan the stakeholder interview programme by reading approved interview scripts "
            "and producing a voice-configured session plan for each assigned stakeholder."
        ),
        backstory=(
            "You are a senior discovery consultant who orchestrates interview programmes "
            "for digital transformation engagements. You match each stakeholder to the "
            "right interview script and configure voice settings for their locale so that "
            "sessions can be delivered via the self-serve interview portal."
        ),
        llm=llm,
        tools=tools,
        verbose=True,
        allow_delegation=False,
    )


def create_interview_coordinator_task(
    agent: Agent,
    stakeholder_assignments: str = "",
    context: list | None = None,
    discovery_brief: str = "",
    node_templates_block: str = "",
) -> Task:
    assignments_block = (
        f"Stakeholder assignments:\n{stakeholder_assignments}\n\n"
        if stakeholder_assignments
        else ""
    )
    # Both of these were previously consumed by the Script Designer task, which
    # was removed from this crew. They are planning context for the programme,
    # so the Coordinator is now their reader.
    brief_block = (
        f"Discovery brief for this engagement:\n{discovery_brief}\n\n"
        if discovery_brief
        else ""
    )
    templates_block = (
        f"Node templates (question schemas keyed by node_label):\n{node_templates_block}\n\n"
        if node_templates_block
        else ""
    )
    return Task(
        description=(
            f"{brief_block}"
            f"{templates_block}"
            f"{assignments_block}"
            "Build the interview session plan for this project.\n\n"
            f"{VOICE_LOCALE_TABLE}\n\n"
            "Steps:\n"
            "1. Use SQLiteStateTool with operation='read', key='interview_scripts', "
            "agent_name='interview_coordinator' to retrieve the scripts written by the "
            "Interaction Designer. The map is keyed by script_id (e.g. 'SC-001'), and each "
            "script carries its own node_label.\n"
            "2. For each stakeholder listed in the assignments above:\n"
            "   a. Find the script whose node_label matches theirs, and keep the key it is "
            "held under - that key is the script_id, and it is what every answer from this "
            "session will be cited by. Two scripts can carry the same node_label, so the id "
            "must be recorded now: it cannot be recovered from the label afterwards.\n"
            "   b. Resolve their voice_config using the lookup table above "
            "(match on language + country_code; fall back to en/GB if no entry matches).\n"
            "   c. Produce a session entry:\n"
            "      {\n"
            "        \"stakeholder_id\": 1,\n"
            "        \"name\": \"Alice Chen\",\n"
            "        \"node_label\": \"Goods-in Inspection\",\n"
            "        \"script_id\": \"SC-001\",\n"
            "        \"voice_config\": {\n"
            "          \"language\": \"en\",\n"
            "          \"country_code\": \"NZ\",\n"
            "          \"elevenlabs_voice_id\": \"MF3mGyEYCl7XYWbV9V6O\"\n"
            "        }\n"
            "      }\n"
            "   Do not invent a session_token: one is assigned in code when the session "
            "is created, not by you.\n"
            "3. Assemble all session entries into a JSON array called interview_plan.\n"
            "4. Use SQLiteStateTool with operation='write', key='interview_plan', "
            "agent_name='interview_coordinator' to save the array.\n"
        ),
        expected_output=(
            "A JSON interview_plan array saved via SQLiteStateTool, containing one session entry "
            "per assigned stakeholder with script_id and voice_config. session_token is not "
            "included - it is assigned in code when the session is created."
        ),
        agent=agent,
        context=context,
    )
