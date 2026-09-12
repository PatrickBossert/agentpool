# agents/discovery/interview_coordinator.py
#
# **Taylor does not choose a voice, and this file no longer contains a table of them.**
#
# It used to hold `VOICE_LOCALE_TABLE`: eight locales mapped to ElevenLabs voice ids, in prose
# inside the task description, naming the stock *Rachel* - a female voice - for `en/GB` and
# `en/US`, which are the two an English engagement actually hits. A dead TypeScript twin at
# `ui/src/utils/voiceLocale.ts` held the same idea with different ids and disagreed with it on
# four of the eight, so "the voice for a French interview" had two answers depending on who
# resolved it. Both are gone.
#
# The table was not corrected, and the difference matters. Correcting the ids would have left a
# fifth declaration of voice facts that happened to be right on the day it was written, which
# is precisely the state that produced four disagreeing copies. A voice is a project's
# configuration: `resolve_agent_config(slug, agent_id)` resolves it from
# `project_agent_config` over the defaults in `agents/identity.py`, and
# `InterviewSessionTool._create` stamps the resolved answer onto the session row.
#
# By the time this was removed the table had already stopped *reaching* anything - `_create`
# resolves the voice itself and ignores any `voice_config` in the plan, so this was prompt
# hygiene rather than a live wrong-voice defect. An instruction to produce something the code
# discards is still worth deleting: it costs tokens, it invites a reviewer to believe the model
# decides, and it is the surviving copy a future change would have "corrected" back into use.
from crewai import Agent, Task, LLM
from crewai.tools import BaseTool

# The **only** two places anything Taylor is given may mention a voice, and both of them say a
# voice is not his to choose. They are named rather than inlined so the guard in
# `tests/test_discovery_interviews_agents.py` can strip exactly these two and then assert that
# the vocabulary of voice-choosing - "voice", "ElevenLabs", an id, a locale pair, a stock voice
# name - appears nowhere else in his role, goal, backstory, task description or expected
# output.
#
# That inversion is the point, and it is the repair for a guard that was one field wide and one
# vocabulary deep. The first version searched the task description alone and matched only the
# shape of an id, and a reviewer reinstated the locale table three ways against a green suite:
# naming the voices by name, writing the same mapping as prose with no ids at all, and putting
# the four *correct* ids in the backstory. A guard that enumerates the ways a table can be
# written will always be one form behind whoever writes the next one; a guard that permits two
# sentences and forbids the subject everywhere else cannot be.
VOICE_IS_NOT_YOURS = (
    "Do not include a voice_config, and do not name an ElevenLabs voice id. "
    "Which interviewer takes each session, and what they sound like, is the "
    "project's configuration; it is resolved and recorded when the session is "
    "created, and anything you write here is discarded."
)

VOICE_IS_NOT_IN_THE_OUTPUT = (
    "Neither session_token nor voice_config is included - both are assigned in code "
    "when the session is created."
)

SANCTIONED_VOICE_MENTIONS = (VOICE_IS_NOT_YOURS, VOICE_IS_NOT_IN_THE_OUTPUT)


def create_interview_coordinator(slug: str, llm: LLM, tools: list[BaseTool]) -> Agent:
    return Agent(
        role="Interview Coordinator",
        goal=(
            "Plan the stakeholder interview programme by reading approved interview scripts "
            "and producing a session plan for each assigned stakeholder."
        ),
        backstory=(
            "You are a senior discovery consultant who orchestrates interview programmes "
            "for digital transformation engagements. You match each stakeholder to the "
            "right interview script so that sessions can be delivered via the self-serve "
            "interview portal. Who conducts each interview, and what they sound like, is "
            "the project's configuration and is resolved when the session is created - it "
            "is not yours to decide."
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
            "   b. Produce a session entry:\n"
            "      {\n"
            "        \"stakeholder_id\": 1,\n"
            # Renamed from "Alice Chen". The placeholder is arbitrary, and "Alice" is one of
            # the four verified default voices - so the guard below could not forbid a
            # locale table written under voice *names* without this example tripping it. A
            # throwaway name is the cheap side of that trade.
            "        \"name\": \"Priya Raman\",\n"
            "        \"node_label\": \"Goods-in Inspection\",\n"
            "        \"script_id\": \"SC-001\"\n"
            "      }\n"
            "   Do not invent a session_token: one is assigned in code when the session "
            "is created, not by you.\n"
            f"   {VOICE_IS_NOT_YOURS}\n"
            "3. Assemble all session entries into a JSON array called interview_plan.\n"
            "4. Use SQLiteStateTool with operation='write', key='interview_plan', "
            "agent_name='interview_coordinator' to save the array.\n"
        ),
        expected_output=(
            "A JSON interview_plan array saved via SQLiteStateTool, containing one session "
            f"entry per assigned stakeholder with script_id. {VOICE_IS_NOT_IN_THE_OUTPUT}"
        ),
        agent=agent,
        context=context,
    )
