"""Maya's brief must describe the batching she is already doing, and how to select nodes.

She batched in run 26 because the whole set cannot fit in one response, but the brief told
her to produce it all at once - so the batching was improvisation, and the batches were
erratic. The brief also asks for one script per node: registry v5 holds 78 active nodes,
which taken literally is ~1.7MB. She was already selecting, with no rule to select by.
"""
import inspect
from agents.discovery import interaction_designer


def _src():
    return inspect.getsource(interaction_designer)


def test_the_prompt_describes_batching():
    src = _src()
    assert "BATCHES" in src
    assert "merged into" in src


def test_the_prompt_says_omission_is_not_deletion():
    assert "active: false" in _src()


def test_the_prompt_states_a_coverage_rule():
    """Without one Maya selects arbitrarily and the set differs every run."""
    src = _src()
    assert "every L0 and every L1" in src
    assert "not every L3" in src
