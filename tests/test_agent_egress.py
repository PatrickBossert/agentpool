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
from api.services.deployment_modes import EGRESS_GRANTS, Capability, granted_to

_MODES = ("standard", "sensitive", "fallback")

# The resolver is handed the capabilities a project holds, not the name of its mode - a mode is
# not the last word once `force_local_inference` can narrow one. `granted_to(mode)` is the
# translation of the mode names these tests are written in; every property below is the one it
# was before. The one thing it is *not* is `project_grants(slug)`, which subtracts a project's
# own narrowing as well - that is asserted where it belongs, against the page, in
# `tests/test_data_architecture_page.py`.


# --- Coverage: nothing an agent can hold is undeclared -----------------------------------------


def test_every_tool_an_agent_can_hold_declares_its_egress():
    graph = build_graph()
    from agents.egress import TOOL_EGRESS
    held = {t for node in graph.agents.values() for t in node.tools}
    assert held <= set(TOOL_EGRESS), f"undeclared: {sorted(held - set(TOOL_EGRESS))}"


def test_the_declaration_covers_every_tool_class_that_exists_and_invents_none():
    """The test above can only see what an agent holds.

    A tool class that exists and is declared but reaches no agent is invisible to a coverage
    guard drawn from the graph's tool lists - which is how `ChainlitHumanInputTool` stayed
    declared, and swapped in at run time for every `HumanInputTool`, while `tool_map` named
    only the base class. Comparing the declaration with the classes that actually exist on
    disk closes that hole without an exception list, and catches the next tool written before
    it is declared as well.

    Equality rather than containment, so a declaration for a tool that has been deleted or
    misspelled fails here too - which is what held the declaration to the deletion when the
    Chainlit tool went.
    """
    assert set(TOOL_EGRESS) == tool_classes_on_disk()


def test_the_class_scan_finds_the_tools_the_registry_actually_hands_out():
    """Guard the guard. A scan that resolved nothing would make the test above pass by
    comparing two empty sets, which is the shape of a vacuous green."""
    held = {t for node in build_graph().agents.values() for t in node.tools}
    assert held, "the graph reports no tools at all - this guard has stopped exercising anything"
    assert held <= tool_classes_on_disk(), sorted(held - tool_classes_on_disk())


def test_the_registry_hands_out_nothing_the_resolver_cannot_answer_for():
    """Asserted on what the registry actually returns, not on the graph's reading of it.

    The graph reads `tool_map` from source, so it reports the classes the dict *names*. This
    instantiates the tools instead and asks the resolver about each one by its real class name,
    which is the only reading a run-time substitution could ever have moved - and a
    substitution is exactly what `hitl_tool` was.
    """
    from agents.tools.registry import get_tools_for_agent

    handed = {
        type(tool).__name__
        for agent_id in build_graph().agents
        for tool in get_tools_for_agent(agent_id, slug="egress-probe", sector="probe")
    }
    assert handed, "the registry handed out no tools at all - this guard proves nothing"

    for mode in _MODES:
        for tool_name in sorted(handed):
            resolve_egress(tool_name, granted_to(mode))


# --- Resolution: one declaration, the mode dependency in the resolver --------------------------


def test_a_vector_store_resolves_to_a_different_place_in_each_mode():
    """The case the whole two-layer shape exists for. `ChromaQueryTool` reaches a vector store
    either way; which vector store is a property of the project."""
    standard = resolve_egress("ChromaQueryTool", granted_to("standard"))
    sensitive = resolve_egress("ChromaQueryTool", granted_to("sensitive"))

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
        if resolve_egress(tool_name, granted_to("standard"))
        == resolve_egress(tool_name, granted_to("sensitive"))
        and resolve_egress(tool_name, granted_to("sensitive")).leaves_deployment
    }
    assert "WebFetchTool" in ungated
    assert "TavilySearchTool" in ungated
    for tool_name in ungated:
        assert TOOL_EGRESS[tool_name].reaches is not Reach.NOTHING


def test_whether_a_tool_is_gated_by_a_grant_is_read_from_the_resolver():
    """`is_gated_by_grant` is what the privacy page badges a row with, so the two findings it
    has to get right are asserted directly: Chroma moves with what the project is granted, the
    fetch tool does not.

    It was `is_gated_by_mode`, comparing two mode names. Same four answers, and the rename is
    the point rather than a tidy-up: on a `standard` project forcing local inference the *mode*
    moves the model calls nowhere at all, so a badge derived from two mode names would have gone
    on claiming it did - on the page where that sentence is read as a statement about where the
    client's prompts go.
    """
    from agents.egress import is_gated_by_grant

    assert is_gated_by_grant("ChromaQueryTool")
    assert not is_gated_by_grant("WebFetchTool")
    assert not is_gated_by_grant("TavilySearchTool")
    assert not is_gated_by_grant("HumanInputTool")


def test_a_project_forcing_local_inference_is_described_by_the_same_table(monkeypatch):
    """The independence of the two badges, asserted at the table that decides them.

    `_DESTINATION` is keyed on `(Reach, granted)` precisely so that a project holding one grant
    and not the other is describable, and this branch builds one: `standard` minus
    `HOSTED_INFERENCE` is local models over a cloud vector store. Driven through
    `project_grants` rather than through a hand-built set, so what is asserted is that the
    resolver and the narrowing agree - a set typed out here would pass while `project_grants`
    subtracted the wrong capability.

    The mirror shape - a cloud vector store withheld while hosted inference is kept - is the
    deferred sovereign mode, and `tests/test_deployment_modes.py` drives it through a
    hypothetical grants row. Between them both diagonals of the table are covered.
    """
    from api.services import chroma_client
    from api.services.deployment_modes import project_grants

    monkeypatch.setattr(chroma_client, "project_llm_mode", lambda slug: "standard")
    monkeypatch.setattr(chroma_client, "project_forces_local_inference", lambda slug: True)
    grants = project_grants("forced-probe")

    assert grants == frozenset({Capability.CLOUD_VECTOR_STORE})
    assert not inference_destination(grants).leaves_deployment
    assert resolve_egress("ChromaQueryTool", grants).leaves_deployment
    assert resolve_egress("DocumentIngestionTool", grants).leaves_deployment


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
            assert not resolve_egress(tool_name, granted_to(mode)).leaves_deployment


def test_the_resolver_refuses_a_tool_it_has_no_declaration_for():
    """A default of "reaches nothing" would answer the auditor's question wrongly in the one
    direction nobody can notice."""
    with pytest.raises(KeyError):
        resolve_egress("SomeToolWrittenNextTuesday", granted_to("standard"))


def test_every_reach_resolves_whether_or_not_its_grant_is_held():
    """A reach added with only one column filled in would raise `KeyError` from whichever page
    happened to read the other one first.

    The key is now "does this project's mode hold the grant this reach depends on", not a mode
    name - see `_REACH_GRANT`. Both answers are required for every reach, including the reaches
    no grant moves, because a reach that is gated later must not need a new row at the same time.
    """
    from agents.egress import _DESTINATION

    for reach in Reach:
        for granted in (True, False):
            assert (reach, granted) in _DESTINATION, (
                f"{reach.name} has no destination for granted={granted}"
            )


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

    The mode is stubbed **on `api.services.chroma_client`**, which is where the routing decision
    looks it up: `get_llm_for_agent` asks `deployment_modes.project_permits(slug, ...)`, and that
    resolver reads the project's mode and its `force_local_inference` override from
    `chroma_client`. Stubbed on `agents.model_registry` instead - as it was until the override
    landed - the stub reached only the wording of a refusal, and every mode routed hosted while
    this test went on asserting against a name that no longer decided anything.
    """
    import agents.model_registry as model_registry
    from api.services import chroma_client

    monkeypatch.setattr(chroma_client, "project_llm_mode", lambda slug: mode)
    hosted = inference_destination(granted_to(mode)).leaves_deployment

    for agent_id in model_registry.AGENT_TIER:
        llm = model_registry.get_llm_for_agent(agent_id, "egress-probe")
        assert (llm.base_url is None) == hosted, (
            f"{agent_id} in {mode} mode: base_url={llm.base_url!r}, model={llm.model!r}, "
            f"but egress says leaves_deployment={hosted}"
        )


def test_the_two_inference_destinations_are_not_the_same_answer_twice():
    """Guard the guard above: if both modes resolved to the same destination, the parametrised
    test would pass for whichever branch happened to be taken."""
    assert inference_destination(granted_to("standard")) != (
        inference_destination(granted_to("sensitive"))
    )
    assert inference_destination(granted_to("standard")).leaves_deployment
    assert not inference_destination(granted_to("sensitive")).leaves_deployment


# --- The graph carries the resolved set ------------------------------------------------------


@pytest.mark.parametrize("mode", _MODES)
def test_every_node_carries_what_the_resolver_gives_its_tools_in_that_mode(mode):
    """Recomputed from `resolve_egress` rather than from `agent_destinations`, so the assembly
    is held against the resolver rather than against the helper it happens to call."""
    nowhere = resolve_egress("SQLiteStateTool", granted_to(mode))
    for node in build_graph(granted_to(mode)).agents.values():
        expected = {resolve_egress(t, granted_to(mode)) for t in node.tools} | {
            inference_destination(granted_to(mode))
        }
        expected.discard(nowhere)
        assert set(node.egress) == expected, node.agent_id
        assert list(node.egress) == sorted(node.egress, key=lambda d: d.label)


def test_an_agent_whose_every_tool_stays_local_still_reaches_a_model():
    """The reason inference is in the set at all. An egress set assembled from tools alone would
    report that the Illustrator's work reaches nowhere, when in fact it is read by a model on
    every run - and the privacy page would have gone from naming Anthropic forty-four times to
    never."""
    graph = build_graph(granted_to("standard"))
    local_only = [
        node
        for node in graph.agents.values()
        if all(TOOL_EGRESS[t].reaches is Reach.NOTHING for t in node.tools)
    ]
    assert local_only, "every agent now holds a tool that reaches out - case no longer covered"
    for node in local_only:
        assert node.egress == (inference_destination(granted_to("standard")),), node.agent_id


def test_build_graphs_default_over_reports_rather_than_under_reports():
    """`build_graph()` called with no grants must answer at least what every declared mode does.

    The test below states this property and cannot see it: it passes both graphs explicitly, so
    the default is never exercised. Changing the default to `frozenset()` - the under-reporting
    extreme, and the one wrong direction for an auditor's page - left the whole suite green.

    The property is over-reporting **egress**, not destinations: a sensitive project reaches
    the local model, which the fullest grant does not name, so a plain superset of labels is
    the wrong assertion - my first draft made it and this test caught it. Asserted against
    `EGRESS_GRANTS` rather than the two modes somebody thought of, so a mode added to the
    table is covered without anybody remembering this test exists.
    """
    default = build_graph()
    for mode in EGRESS_GRANTS:
        declared = build_graph(granted_to(mode))
        for agent_id, node in declared.agents.items():
            leaving = {d.label for d in node.egress if d.leaves_deployment}
            by_default = {
                d.label for d in default.agents[agent_id].egress if d.leaves_deployment
            }
            assert leaving <= by_default, (
                f"build_graph() omits {sorted(leaving - by_default)} for {agent_id}, which "
                f"leaves the deployment on a {mode!r} project - the default under-reports "
                f"where it must over-report"
            )


def test_a_sensitive_project_never_reaches_somewhere_a_standard_one_does_not():
    """The property that makes `build_graph()`'s default safe: standard is the fuller answer, so
    a caller that forgets the mode over-reports rather than under-reports."""
    standard = build_graph(granted_to("standard"))
    sensitive = build_graph(granted_to("sensitive"))
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
        for agent_id, node in build_graph(granted_to("sensitive")).agents.items()
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
    assert build_graph(granted_to("sensitive")).agents == (
        build_graph(granted_to("sensitive")).agents
    )
    assert agent_destinations(("WebFetchTool", "SQLiteStateTool"), granted_to("standard")) == (
        agent_destinations(("SQLiteStateTool", "WebFetchTool"), granted_to("standard"))
    )
