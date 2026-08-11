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


def test_the_prompt_states_the_ledger_is_cumulative_and_keyed_by_script_id():
    """Two rules that only became load-bearing once Maya emitted the differential.

    While she regenerated everything, both were implicit: the ledger she sent already
    held every id, and re-emitting every script made the top-level key academic. Now a
    run sends a partial batch: a ledger that repeated only this run's ids used to be
    REFUSED by validate_script_registry_succession (deleted with the retired
    interview_script_registry door - script-ledger-as-a-table Task 3, code review round 1,
    Important 2), and the same guarantee now holds structurally instead - the
    interview_script_ledger table only ever grows. A batch keyed by node_label still files
    every existing script a second time under a key _merge_with_current does not recognise,
    which this prompt line also guards against.

    Asserted here because both live in prompt prose, which nothing else guards - and the
    defect that made this branch necessary was two instructions in this same file
    disagreeing with each other.
    """
    src = _src()
    assert "THE LEDGER IS CUMULATIVE" in src, (
        "Maya emits only the differential, so a ledger carrying just this run's ids "
        "drops every earlier one and the succession guard refuses the write"
    )
    assert "keyed by script_id" in src
    assert "keyed by node_label" not in src, (
        "the artefact and _merge_with_current both key on script_id: filing by "
        "node_label double-writes every script that already exists"
    )
