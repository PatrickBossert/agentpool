"""Casey's theme schema must let a theme anchor where its insight lives.

The schema offered activity_ids and nothing else, so even a well-instructed Casey had
nowhere to put a governance theme except on an arbitrary L3 child. That does not merely
lose resolution: it systematically biases downstream value proposition generation toward
L3 efficiency, because that is the only altitude the evidence is ever expressed at.
"""
import inspect
from agents.discovery import synthesis_analyst


def _src():
    """Module source with escaped quotes unescaped - the prompt is a string literal."""
    return inspect.getsource(synthesis_analyst).replace('\\"', '"')


def test_themes_carry_anchors_not_activity_ids():
    src = _src()
    assert '"anchors"' in src
    assert '"activity_ids"' not in src, \
        "activity_ids is what confined every theme to an activity-level node"


def test_the_prompt_states_the_level_expectation():
    src = _src()
    for token in ("L0", "L1", "L2", "L3", "governance", "maturity", "tactical"):
        assert token in src, f"the level expectation never mentions {token}"


def test_the_prompt_says_an_anchor_may_be_any_registry_node():
    assert "any registry node" in _src().lower()


def test_the_prompt_names_the_downstream_consequence():
    """A rule whose reason is stated is one an agent can apply to a case nobody foresaw."""
    src = _src().lower()
    assert "skew" in src or "bias" in src


def test_the_existing_evidence_rules_survive():
    """answer_id citation, unprompted weighting and two-stakeholder evidence are unchanged -
    this task replaces the anchor field, not the evidence discipline."""
    src = _src()
    assert "answer_id" in src
    assert "unprompted" in src
    assert "two evidence entries" in src
