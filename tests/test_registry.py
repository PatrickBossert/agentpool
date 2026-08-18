# tests/test_registry.py
"""What the tool registry hands an agent is a property of the agent, not of the caller.

It was not always. `get_tools_for_agent` took a `hitl_tool` and substituted it for every
`HumanInputTool` in the list it was about to return, and the Chainlit console was the only
thing that ever passed one. Both tests here were about that parameter: one that a substitute
replaced the base tool, one that omitting it did not. The parameter is gone with the console,
so what is left to assert is the property the substitution could break - that two callers
asking for the same agent are handed the same classes.
"""
from agents.tools.registry import get_tools_for_agent


def _classes(agent_name: str, **kwargs) -> list[str]:
    return [
        type(tool).__name__
        for tool in get_tools_for_agent(agent_name, **kwargs)
    ]


def test_an_agent_with_a_review_gate_is_handed_the_review_tool():
    """The concrete case the substitution used to move.

    `initiative_identifier` is one of the eleven agents `tool_map` gives a `HumanInputTool`,
    and under the old parameter a caller could be handed something else entirely under that
    same name - `ChainlitHumanInputTool` set `name = "HumanInputTool"` precisely so the task
    descriptions would still resolve.
    """
    assert "HumanInputTool" in _classes(
        "initiative_identifier", slug="test", run_id=1, sector="test"
    )


def test_two_callers_asking_for_the_same_agent_are_handed_the_same_classes():
    """No caller can vary the list any more, which is what makes the graph's reading exact.

    `agents/graph.py` reads the tool classes out of `tool_map`'s source. That reading is only
    the truth if nothing rewrites the list on the way out, and for as long as `hitl_tool`
    existed it was not: the graph reported `HumanInputTool` for eleven agents while a live
    console handed them a subclass the graph never named.
    """
    first = _classes("initiative_identifier", slug="one", run_id=1, sector="test")
    second = _classes("initiative_identifier", slug="two", run_id=2, sector="test")

    assert first, "the registry handed out no tools - this proves nothing"
    assert first == second


def test_an_agent_with_no_review_gate_is_handed_no_review_tool():
    """The other direction, so the test above cannot pass by the registry handing out
    everything to everyone. The Illustrator has no approval gate, which
    `test_vi_task_has_no_hitl_gate` states of his task and this states of his tool list."""
    assert "HumanInputTool" not in _classes(
        "visual_illustrator", slug="test", run_id=1, sector="test"
    )
