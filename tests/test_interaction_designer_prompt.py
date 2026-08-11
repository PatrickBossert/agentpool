"""Maya's brief must describe the batching she is already doing, and the coverage contract.

She batched in run 26 because the whole set cannot fit in one response, but the brief told
her to produce it all at once - so the batching was improvisation, and the batches were
erratic.

The brief also used to tell her to select which nodes warranted a script, on the reasoning
that one script per node was a programme nobody would run. That is no longer the contract:
she owes one script per active node, the coverage validator counts against exactly that, and
the selection rule this file once asserted was what kept the two in disagreement. Interview
economy is answered by Jordan assigning stakeholders to scripts separately, not by writing
fewer instruments.
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


def test_the_prompt_states_the_one_script_per_active_node_rule():
    """Without a stated target Maya selects arbitrarily and the set differs every run.

    Checked over the whole module source rather than the assembled description, so
    sampling language reintroduced anywhere in the file - a step, a template, or
    expected_output - is caught here too.
    """
    src = _src()
    assert "One interview script per active node" in src
    assert "every L0 and every L1" not in src, (
        "the old selection rule is back: it contradicts the coverage validator, which "
        "counts one script per active node and warns until every one has one"
    )
    assert "not every L3" not in src, "the old selection rule is back"
