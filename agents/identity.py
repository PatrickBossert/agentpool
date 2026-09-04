# agents/identity.py
"""Permanent ids, and the names and faces they may change without breaking anything.

`agent_id` is the snake key - `interaction_designer`, `pam`. It is what `AGENT_TIER` is keyed by,
what `tool_map` is keyed by, what the crews dispatch, and what `agent_outputs.agent_name` has
stored on every row for the life of the project. It is a permanent contract: the roll may grow
and may retire, but may never redefine or forget. This project has reached that same answer
twice before, for interview scripts (`script_id`, never displayed) and for the value chain
ledger, and this is the third instance.

`display_name` and `image` are the opposite. They are what a human reads, they belong to the
persona rather than to the machinery, and either may be rewritten in this file alone.

**Neither half may be derived from the other.** That is the whole point, and it is easy to miss,
because a derivation looks like a registry from a distance. `_SNAKE_TO_DISPLAY` in
`api/services/run_service.py` maps fifteen agents to their "display names", and every one of the
fifteen is exactly `agent_id.replace("_", " ").title()` - so it does not decouple anything.
Rename its agent and you rename its key, which is the condition this module exists to end.
`test_a_display_name_is_not_a_formatting_of_the_id` holds that line.

Why the names are declared here rather than read from somewhere that owns them, when `graph.py`
is built on the rule of declaring nothing already declared: no Python module owns them. Research
found six persona lists and all six are in the front end or derived from it - `AGENT_HUMAN_NAME`
and `AGENT_AVATAR_IMAGE` in `ui/src/components/agentStatus.ts`, `AGENT_BACKSTORY` beside them,
`AGENT_PERSONAS` in `api/services/agent_chat_service.py` (first names only), and bare lists in
`ui/src/pages/PitchDeck.tsx` and `ui/src/pages/DataArchitecture.tsx`. They already disagree: the
pitch deck still calls Maya the "Assessment Designer", a role no registry has held since the
`interview_script_designer` era. The values below are transcribed from `AGENT_HUMAN_NAME` and
`AGENT_AVATAR_IMAGE`, which are the only two that cover all seventeen agents and carry a full
name and a face, so nothing here is invented. This file is now where that fact lives, and the
six restatements are Task 4's to collapse into it.

Eighteen, not seventeen: `pam` is in no crew, so anything enumerating agents by walking the crew
map omits the orchestrator. The roll is `AGENT_TIER`, and `graph.py` refuses to assemble if this
map and that one disagree.

`image` is a path under `ui/public`, the form `ui/src/pages/VoiceInterview.tsx` already uses for
these files; the front end prefixes its configured base. It is nullable because an agent without
a headshot is a legitimate state, and Laura Nelson is the first agent actually in that state -
seventeen have a headshot and she does not, so the front end falls back to her avatar until one
is drawn. `test_every_image_names_a_file_that_exists` asks the directory rather than trusting
this list, and skips the agents whose image is `None`.

`voice_id`, `language` and `country_code` are the third piece of the mutable half, and they moved
here from `DEFAULT_VOICE_CONFIG` in `ui/src/pages/VoiceInterview.tsx`. A default living inside a
component is a default no server can read, no project can override, and nobody reviews - which is
how Avery, described as male everywhere he is described at all, came to conduct the first
completed interview in `21m00Tcm4TlvDq8ikWAM`, ElevenLabs' stock *Rachel*. The voice heard was
never a fallback for his; it was a hardcoded stranger. It is corrected below, in the one place
`resolve_agent_config` reads defaults from.

`voice_id` is nullable and is `None` for every agent that does not speak. Only the interviewers
are synthesised today; the others carry the field because the shape is the same and a special
case would be the expensive half. `language` and `country_code` are not nullable - a voice always
has a locale, and `en`/`GB` is the pair the interview portal has always sent.
"""
from __future__ import annotations

from dataclasses import dataclass

# ElevenLabs' stock "Daniel" - a British male voice, and the correction to the defect above.
# Named as a constant so the id appears once and the test that asserts Avery is not Rachel can
# name the wrong id without also naming the right one from the same source it is checking.
AVERY_VOICE_ID = "onwK4e9ZLuTAKqWW03F9"

# ElevenLabs' "Alice - Clear, Engaging Educator" - British, female, middle-aged, professional.
# Chosen from the three British or Scottish female voices already in the account because its
# register mirrors Daniel's: two interviewers are only interchangeable if a participant meets
# the same kind of person either way, and "animated", "casual" and "actress" are not that at a
# board-level interview. A default, not a decision - a project changes it through the picker.
LAURA_VOICE_ID = "Xb7hH8MSUJpSbSDYk0k2"


@dataclass(frozen=True)
class Identity:
    """The mutable half of an agent: what to call it, what to show for it, how it sounds."""

    display_name: str
    image: str | None = None
    voice_id: str | None = None
    language: str = "en"
    country_code: str = "GB"


AGENT_IDENTITY: dict[str, Identity] = {
    "pam":                         Identity("Pamela Reid",     "/agents/pam.jpg"),
    "value_chain_mapper":          Identity("Alex Chen",       "/agents/alex-chen.jpg"),
    "interaction_designer":        Identity("Maya Patel",      "/agents/maya-patel.jpg"),
    "stakeholder_manager":         Identity("Jordan Williams", "/agents/jordan-williams.jpg"),
    "requirements_capture":        Identity("Sam Torres",      "/agents/sam-torres.jpg"),
    "requirements_analyst":        Identity("Riley Kim",       "/agents/riley-kim.jpg"),
    "value_lever_analyst":         Identity("Morgan Davis",    "/agents/morgan-davis.jpg"),
    "interview_coordinator":       Identity("Taylor Brooks",   "/agents/taylor-brooks.jpg"),
    "stakeholder_interviewer":     Identity("Avery Singh",     "/agents/avery-singh.jpg",
                                            voice_id=AVERY_VOICE_ID),
    # The second interviewer. The id says where she sits on the roster and nothing else: it
    # names neither her voice nor her sex, both of which are the mutable half this file exists
    # to keep separable - an id like `female_interviewer` would be a fact about the voice
    # written into the one thing that may never change. Which interviewer a project gets is
    # decided from the voices' own metadata, not from an id spelled to encode the answer.
    "second_interviewer":          Identity("Laura Nelson",    None,
                                            voice_id=LAURA_VOICE_ID),
    "synthesis_analyst":           Identity("Casey Liu",       "/agents/casey-liu.jpg"),
    "value_proposition_generator": Identity("Quinn Harper",    "/agents/quinn-harper.jpg"),
    "portfolio_manager":           Identity("Blake Anderson",  "/agents/blake-anderson.jpg"),
    "enterprise_architect":        Identity("Drew Mitchell",   "/agents/drew-mitchell.jpg"),
    "initiative_identifier":       Identity("Sage Thompson",   "/agents/sage-thompson.jpg"),
    "roadmap_generator":           Identity("River Martinez",  "/agents/river-martinez.jpg"),
    "visual_illustrator":          Identity("Luca Romano",     "/agents/luca-romano.jpg"),
    "business_plan_generator":     Identity("Finley Cooper",   "/agents/finley-cooper.jpg"),
}


# A crew's id is permanent in exactly the way an agent's is - `crew_runs.crew_name` stores it,
# `CREW_DEPENDENCIES` keys on it, and PAM dispatches by it - and its label is the mutable half.
#
# The label is not a formatting of the id and must never become one: `discovery_mapping` is
# shown as "Value Chain Mapping", `capabilities` as "Capabilities", and titling the id would
# quietly rename the first while appearing to work for the second.
#
# Transcribed from `CREW_LABELS` in `ui/src/components/agentStatus.ts`, the only one of the
# five crew-label maps that named the nine crews that actually exist. The other four were
# stale in different directions - `api/services/pam_report_service.py` still labelled
# `discovery` and `architecture`, crews no dispatch map has known for two sprints, and
# `ui/src/pages/Dashboard.tsx` showed `discovery_mapping` as "Value Chain Mapper", the agent
# rather than the crew. `test_the_frontend_and_the_backend_agree_about_crew_labels` now holds
# the remaining front-end copy against this one.
CREW_LABEL: dict[str, str] = {
    "discovery_mapping":      "Value Chain Mapping",
    "assessment_design":      "Assessment Design",
    "stakeholder_management": "Stakeholder Management",
    "discovery_interviews":   "Discovery Interviews",
    "value_design":           "Value Design",
    "capabilities":           "Capabilities",
    "requirements":           "Requirements",
    "delivery":               "Delivery",
    "business_plan":          "Business Plan",
}
