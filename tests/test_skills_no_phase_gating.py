# tests/test_skills_no_phase_gating.py
"""A crew's last act is finishing.

Gating used to live in the agents' instructions, backed by a blocking 24-hour poll.
It now lives in approval_commits, so the instructions must stop telling agents to wait.
"""
import pytest

from api.services.skills_service import BASELINE_SKILLS


def _skill(name: str) -> dict:
    for skill in BASELINE_SKILLS:
        if skill["name"] == name:
            return skill
    raise AssertionError(f"skill {name!r} not found")


@pytest.mark.parametrize("skill_name", ["Phase Gating", "Human Review Gate"])
def test_the_skill_no_longer_tells_agents_to_block(skill_name):
    description = _skill(skill_name)["description"].lower()
    for phrase in ("halt", "do not allow downstream", "block every downstream",
                   "never proceed", "pause and request human review"):
        assert phrase not in description, (
            f"{skill_name} still instructs the agent to wait: {phrase!r}"
        )


@pytest.mark.parametrize("skill_name", ["Phase Gating", "Human Review Gate"])
def test_the_skill_still_asks_for_a_reviewable_summary(skill_name):
    """Removing the block must not remove the reason a reviewer can act at all."""
    description = _skill(skill_name)["description"].lower()
    assert "summar" in description or "review" in description
