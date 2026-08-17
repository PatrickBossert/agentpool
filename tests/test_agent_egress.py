# tests/test_agent_egress.py
"""What leaves the building, asserted against the registry and the resolver - never against a
second list.

`TOOL_EGRESS` is a declaration, so the temptation here is to write the same seventeen rows out
again and call the comparison a test. That would assert only that a list can be typed twice.
Every test below instead holds the declaration against something that is not it: the tools
`get_tools_for_agent` actually hands an agent, the tool classes that actually exist under
`agents/tools/`, the `LLM` `get_llm_for_agent` actually builds, or the resolver's own behaviour
in the two modes.
"""
import pytest

from agents.egress import (
    TOOL_EGRESS,
    Reach,
    agent_destinations,
    inference_destination,
    resolve_egress,
    tool_classes_on_disk,
)
from agents.graph import GraphInconsistent, build_graph

_MODES = ("standard", "sensitive", "fallback")


# --- Coverage: nothing an agent can hold is undeclared -----------------------------------------


def test_every_tool_an_agent_can_hold_declares_its_egress():
    graph = build_graph()
    from agents.egress import TOOL_EGRESS
    held = {t for node in graph.agents.values() for t in node.tools}
    assert held <= set(TOOL_EGRESS), f"undeclared: {sorted(held - set(TOOL_EGRESS))}"


def test_the_declaration_covers_every_tool_class_that_exists_and_invents_none():
    """The test above cannot see `ChainlitHumanInputTool`.

    `get_tools_for_agent` swaps it in for every `HumanInputTool` when the Chainlit app passes
    `hitl_tool`, but `tool_map` names only the base class, so the graph's tool lists never
    mention the substitute and a coverage guard drawn from them excuses it. Comparing the
    declaration with the classes that actually exist on disk closes that hole without an
    exception list, and catches the next tool written before it is declared as well.

    Equality rather than containment, so a declaration for a tool that has been deleted or
    misspelled fails here too.
    """
    assert set(TOOL_EGRESS) == tool_classes_on_disk()


def test_the_class_scan_finds_the_tools_the_registry_actually_hands_out():
    """Guard the guard. A scan that resolved nothing would make the test above pass by
    comparing two empty sets, which is the shape of a vacuous green."""
    held = {t for node in build_graph().agents.values() for t in node.tools}
    assert held, "the graph reports no tools at all - this guard has stopped exercising anything"
    assert held <= tool_classes_on_disk(), sorted(held - tool_classes_on_disk())


def test_the_substituted_hitl_tool_is_declared_where_the_registry_installs_it():
    """Asserted at the layer that does the substituting, not on the class in isolation.

    `test_the_declaration_covers_every_tool_class...` proves the name is declared; this proves
    the thing the registry actually returns under the substitution is a thing the resolver can
    answer for. The two-line vacuity check matters: if the substitution ever stopped happening,
    the assertion below would pass while testing the unsubstituted list.
    """
    from agents.tools.chainlit_human_input import ChainlitHumanInputTool
    from agents.tools.registry import get_tools_for_agent

    plain = [
        type(t).__name__
        for t in get_tools_for_agent("value_chain_mapper", slug="egress-probe", sector="probe")
    ]
    substituted = [
        type(t).__name__
        for t in get_tools_for_agent(
            "value_chain_mapper",
            slug="egress-probe",
            sector="probe",
            hitl_tool=ChainlitHumanInputTool(slug="egress-probe", run_id=0),
        )
    ]
    assert substituted != plain, (
        "the registry no longer substitutes the Chainlit tool, so this test is asserting "
        "against the ordinary tool list"
    )
    assert "ChainlitHumanInputTool" in substituted

    for mode in _MODES:
        for tool_name in substituted:
            resolve_egress(tool_name, mode)


# --- Resolution: one declaration, the mode dependency in the resolver --------------------------


def test_a_vector_store_resolves_to_a_different_place_in_each_mode():
    """The case the whole two-layer shape exists for. `ChromaQueryTool` reaches a vector store
    either way; which vector store is a property of the project."""
    standard = resolve_egress("ChromaQueryTool", "standard")
    sensitive = resolve_egress("ChromaQueryTool", "sensitive")

    assert standard != sensitive
    assert standard.leaves_deployment
    assert not sensitive.leaves_deployment


def test_a_tool_with_no_mode_check_resolves_to_the_same_place_in_both():
    """The uncomfortable half, and the reason this task was worth doing.

    `llm_mode` is consulted in `get_llm_for_agent` and in `get_chroma_client`, and nowhere in a
    tool that reaches out on its own. So the search tool, the fetch tool and the webhook tools
    resolve identically in both modes, and every one of those destinations leaves the building.

    The set is derived rather than typed, so gating one of them later changes this test's answer
    rather than leaving a stale list behind - and the two named members are named because they
    are the specific findings: `WebFetchTool` is unguarded, and Tavily is ungated.
    """
    ungated = {
        tool_name
        for tool_name in TOOL_EGRESS
        if resolve_egress(tool_name, "standard") == resolve_egress(tool_name, "sensitive")
        and resolve_egress(tool_name, "sensitive").leaves_deployment
    }
    assert "WebFetchTool" in ungated
    assert "TavilySearchTool" in ungated
    for tool_name in ungated:
        assert TOOL_EGRESS[tool_name].reaches is not Reach.NOTHING


def test_whether_a_tool_is_gated_by_mode_is_read_from_the_resolver():
    """`is_gated_by_mode` is what the privacy page will badge a row with, so the two findings it
    has to get right are asserted directly: Chroma moves with the mode, the fetch tool does
    not."""
    from agents.egress import is_gated_by_mode

    assert is_gated_by_mode("ChromaQueryTool")
    assert not is_gated_by_mode("WebFetchTool")
    assert not is_gated_by_mode("TavilySearchTool")
    assert not is_gated_by_mode("HumanInputTool")


def test_a_tool_that_reaches_nothing_says_so_in_both_modes():
    """The other mode-independent case, which must not be confused with the one above: equal in
    both modes *and* leaving nothing behind."""
    local_only = {
        tool_name
        for tool_name, egress in TOOL_EGRESS.items()
        if egress.reaches is Reach.NOTHING
    }
    assert local_only, "no tool reaches nothing - this test has stopped exercising the case"
    for tool_name in local_only:
        for mode in _MODES:
            assert not resolve_egress(tool_name, mode).leaves_deployment


def test_the_resolver_refuses_a_tool_it_has_no_declaration_for():
    """A default of "reaches nothing" would answer the auditor's question wrongly in the one
    direction nobody can notice."""
    with pytest.raises(KeyError):
        resolve_egress("SomeToolWrittenNextTuesday", "standard")


def test_every_reach_resolves_in_both_modes():
    """A reach added with only one mode's destination filled in would raise `KeyError` from
    whichever page happened to read the other mode first."""
    for reach in Reach:
        for mode in ("standard", "sensitive"):
            from agents.egress import _DESTINATION
            assert (reach, mode) in _DESTINATION, f"{reach.name} has no {mode} destination"


@pytest.mark.parametrize("mode", _MODES)
def test_the_inference_destination_agrees_with_the_llm_the_registry_builds(monkeypatch, mode):
    """The declaration held against the code that actually routes, for every agent.

    `inference_destination` restates a rule `get_llm_for_agent` already implements, and a
    restatement that is never compared is how the privacy page came to disagree with the
    codebase in the first place. A local model is reached by `base_url`; a hosted one has none,
    so `base_url is None` is exactly "it went to the provider".

    `"fallback"` is in the parametrisation on purpose. `ProjectSettings` accepts it as a third
    `llm_mode` and neither `get_llm_for_agent` nor `get_chroma_client` mentions it, so it routes
    hosted - and this asserts that against the routing rather than against my reading of it.
    """
    import agents.model_registry as model_registry

    monkeypatch.setattr(model_registry, "project_llm_mode", lambda slug: mode)
    hosted = inference_destination(mode).leaves_deployment

    for agent_id in model_registry.AGENT_TIER:
        llm = model_registry.get_llm_for_agent(agent_id, "egress-probe")
        assert (llm.base_url is None) == hosted, (
            f"{agent_id} in {mode} mode: base_url={llm.base_url!r}, model={llm.model!r}, "
            f"but egress says leaves_deployment={hosted}"
        )


def test_the_two_inference_destinations_are_not_the_same_answer_twice():
    """Guard the guard above: if both modes resolved to the same destination, the parametrised
    test would pass for whichever branch happened to be taken."""
    assert inference_destination("standard") != inference_destination("sensitive")
    assert inference_destination("standard").leaves_deployment
    assert not inference_destination("sensitive").leaves_deployment


# --- The graph carries the resolved set ------------------------------------------------------


@pytest.mark.parametrize("mode", _MODES)
def test_every_node_carries_what_the_resolver_gives_its_tools_in_that_mode(mode):
    """Recomputed from `resolve_egress` rather than from `agent_destinations`, so the assembly
    is held against the resolver rather than against the helper it happens to call."""
    nowhere = resolve_egress("SQLiteStateTool", mode)
    for node in build_graph(mode).agents.values():
        expected = {resolve_egress(t, mode) for t in node.tools} | {
            inference_destination(mode)
        }
        expected.discard(nowhere)
        assert set(node.egress) == expected, node.agent_id
        assert list(node.egress) == sorted(node.egress, key=lambda d: d.label)


def test_an_agent_whose_every_tool_stays_local_still_reaches_a_model():
    """The reason inference is in the set at all. An egress set assembled from tools alone would
    report that the Illustrator's work reaches nowhere, when in fact it is read by a model on
    every run - and the privacy page would have gone from naming Anthropic forty-four times to
    never."""
    graph = build_graph("standard")
    local_only = [
        node
        for node in graph.agents.values()
        if all(TOOL_EGRESS[t].reaches is Reach.NOTHING for t in node.tools)
    ]
    assert local_only, "every agent now holds a tool that reaches out - case no longer covered"
    for node in local_only:
        assert node.egress == (inference_destination("standard"),), node.agent_id


def test_a_sensitive_project_never_reaches_somewhere_a_standard_one_does_not():
    """The property that makes `build_graph()`'s default safe: standard is the fuller answer, so
    a caller that forgets the mode over-reports rather than under-reports."""
    standard, sensitive = build_graph("standard"), build_graph("sensitive")
    for agent_id, node in sensitive.agents.items():
        leaving = {d.label for d in node.egress if d.leaves_deployment}
        also_standard = {d.label for d in standard.agents[agent_id].egress if d.leaves_deployment}
        assert leaving <= also_standard, (
            f"{agent_id} reaches {sorted(leaving - also_standard)} on a sensitive project and "
            f"not on a standard one"
        )


def test_secure_mode_is_not_a_promise_that_nothing_leaves():
    """States the finding as a test, because it is the answer to the question the page asks and
    it should not be possible to lose it quietly.

    CLAUDE.md puts the secure-mode guarantee in absolute terms. It holds for the model and for
    Chroma. It does not hold for the search tool, the fetch tool, or the webhook the review gate
    posts to, none of which consults `llm_mode` at all.

    Slice 5 enforces. When it does, this test's expectation inverts - and it should be rewritten
    to say so rather than deleted, since the agents named here are the ones that were affected.
    """
    exposed = {
        agent_id: sorted(d.label for d in node.egress if d.leaves_deployment)
        for agent_id, node in build_graph("sensitive").agents.items()
        if any(d.leaves_deployment for d in node.egress)
    }
    assert exposed, (
        "nothing leaves the building on a sensitive project - if that is now true, this test "
        "should be rewritten to assert it rather than removed"
    )


def test_an_undeclared_tool_makes_assembly_raise_rather_than_dropping_the_destination():
    """Slice 1's rule, applied to the new fact: a graph that quietly omitted an undeclared
    tool's destination would under-report on the one page where under-reporting is the harm.

    Patched where the name is looked up - `agents.graph`'s own reference - which is the mistake
    four crew tests made and CLAUDE.md records.
    """
    from agents import graph as graph_module

    thinned = {
        tool_name: egress
        for tool_name, egress in graph_module._TOOL_EGRESS.items()
        if tool_name != "WebFetchTool"
    }
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(graph_module, "_TOOL_EGRESS", thinned)
        with pytest.raises(GraphInconsistent, match="WebFetchTool"):
            build_graph()


def test_the_resolved_set_is_shared_by_nothing_and_stable_to_compare():
    """`agent_destinations` is called once per agent per build; two builds must agree, or every
    equality assertion in this file and in `tests/test_agent_graph.py` is comparing addresses."""
    assert build_graph("sensitive").agents == build_graph("sensitive").agents
    assert agent_destinations(("WebFetchTool", "SQLiteStateTool"), "standard") == (
        agent_destinations(("SQLiteStateTool", "WebFetchTool"), "standard")
    )
