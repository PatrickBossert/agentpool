# tests/test_no_end_of_phase_gates.py
"""A crew's last act is finishing.

Approval is recorded in approval_commits, outside the run. An agent instructed to call
HumanInputTool and wait for "approved" blocks for up to 24 hours and then proceeds on
the string "timeout" as though it had an answer.
"""
from pathlib import Path

import pytest

GATED = [
    "discovery/value_chain_mapper",
    "discovery/requirements_analyst",
    "discovery/value_lever_analyst",
    "discovery/interview_coordinator",
    "discovery/interview_script_designer",
    "discovery/synthesis_analyst",
    "value_design/value_proposition_generator",
    "architecture/enterprise_architect",
    "architecture/initiative_identifier",
    "delivery/roadmap_generator",
    "delivery/visual_illustrator",
    "business_plan/business_plan_generator",
]

# These use the tool to ask a question, not to seek a sign-off. They are project 5's
# problem, and removing them here would silently disable the interview path.
KEEPS_A_GENUINE_USE = [
    "discovery/stakeholder_interviewer",
    "discovery/requirements_capture",
    "business_plan/business_plan_generator",
]


def _source(module: str) -> str:
    return Path("agents", f"{module}.py").read_text()


@pytest.mark.parametrize("module", GATED)
def test_no_module_asks_the_reviewer_to_reply_approved(module):
    """The gate's signature phrase, whatever wording surrounds it."""
    source = _source(module).lower()
    assert 'reply "approved"' not in source and "reply 'approved'" not in source, (
        f"{module} still gates on a typed approval"
    )


@pytest.mark.parametrize("module", GATED)
def test_no_module_loops_on_revision_notes(module):
    source = _source(module).lower()
    assert "call humaninputtool again" not in source, (
        f"{module} still loops waiting for revisions"
    )


@pytest.mark.parametrize("module", KEEPS_A_GENUINE_USE)
def test_the_genuine_uses_survive(module):
    """business_plan_generator appears in both lists deliberately: its gate goes and
    its context-gathering step stays, which a per-file count could not express."""
    assert "HumanInputTool" in _source(module), (
        f"{module} lost a use that is not an approval gate"
    )


def test_the_tool_itself_is_untouched():
    source = Path("agents/tools/human_input.py").read_text()
    assert "class HumanInputTool" in source
    assert "time.sleep" in source
