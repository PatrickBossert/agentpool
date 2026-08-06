"""Alex's brief must describe the role nodes, not only the root.

The root instruction has been in this prompt since 4 August and trees v10 and v12 both
came out as a bare list of L1 entities. The prompt change is necessary and is not the
mechanism - tree_validation is, because it makes the omission visible whether or not the
instruction is followed.

Asserted against the module source: the task factory needs a live Agent to build, and the
artefact under test is the prompt text itself.
"""
import inspect
from agents.discovery import value_chain_mapper


def _src():
    """The module source with escaped quotes unescaped.

    The prompt is a Python string literal, so the raw source spells id "0" as id \\"0\\".
    Comparing against the unescaped form keeps these assertions readable as the sentences
    Alex is actually given."""
    return inspect.getsource(value_chain_mapper).replace('\\"', '"')


def test_the_prompt_still_requires_the_root():
    src = _src()
    assert "single root" in src
    assert 'id "0"' in src


def test_the_prompt_names_the_role_node_scheme():
    """Alex cannot emit nodes nobody described to him."""
    src = _src()
    for token in ('"0.A"', '"0.S"', '<L1>.C', '<L1>.F'):
        assert token in src, f"the prompt never mentions {token}"
    assert "role node" in src.lower()


def test_the_prompt_says_role_nuance_belongs_on_the_stakeholder():
    """One F programme serves both 1.F and 2.F because the nuance rides on the person,
    not the node."""
    assert "stakeholder" in _src().lower()
