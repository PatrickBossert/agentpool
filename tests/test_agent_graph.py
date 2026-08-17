# tests/test_agent_graph.py
"""The graph is assembled from the registries, so every test here asserts against a registry.

A graph is unusually easy to test against itself. An `EXPECTED_AGENTS = [...]` here would assert
only that the same list can be typed twice - which is the tenth restatement this module exists to
remove, wearing a test's clothes. Every assertion below therefore names the source the fact
derives from: `AGENT_TIER`, `tool_map` as `get_tools_for_agent` actually returns it,
`OUTPUT_OWNERS`, `_CREW_AGENT_NAMES`, or `CREW_DEPENDENCIES`.
"""
import pytest

from agents.graph import GraphInconsistent, build_graph


def test_the_tool_offers_pam_exactly_the_crews_that_exist():
    from agents.tools.run_crew import RunCrewTool
    tool = RunCrewTool(slug="any", orchestration_run_id=1)
    offered = {c.strip() for c in tool.description.split("one of:")[1].split(",")}
    assert offered == set(build_graph().crews)


def test_every_agent_in_a_crew_exists_in_the_registries():
    graph = build_graph()
    for crew in graph.crews.values():
        for agent_id in crew.agent_ids:
            assert agent_id in graph.agents, (
                f"crew {crew.crew_id} names {agent_id}, which no registry knows"
            )


def test_the_graph_agrees_with_the_registry_it_derives_from():
    from agents.model_registry import AGENT_TIER
    assert set(build_graph().agents) == set(AGENT_TIER)


def test_each_agent_carries_the_tier_the_registry_gives_it():
    from agents.model_registry import AGENT_TIER
    graph = build_graph()
    assert {a.agent_id: a.tier for a in graph.agents.values()} == AGENT_TIER


def test_tools_match_what_the_registry_actually_hands_the_agent():
    """The graph reads `tool_map` out of its own source, because the map is a local holding
    live instances built against a slug. That reading is only worth anything if it agrees with
    what the function returns at run time, so this compares the two for every agent rather than
    re-reading the source a second way.
    """
    from agents.model_registry import AGENT_TIER
    from agents.tools.registry import get_tools_for_agent

    graph = build_graph()
    for agent_id in AGENT_TIER:
        instantiated = tuple(
            type(t).__name__
            for t in get_tools_for_agent(agent_id, slug="graph-probe", sector="probe")
        )
        assert graph.agents[agent_id].tools == instantiated, (
            f"{agent_id}: graph says {graph.agents[agent_id].tools}, "
            f"the registry hands it {instantiated}"
        )


def test_writes_are_the_inversion_of_output_owners():
    from agents.tools.ownership import OUTPUT_OWNERS
    graph = build_graph()

    from_graph = {
        (output_type, agent.agent_id)
        for agent in graph.agents.values()
        for output_type in agent.writes
    }
    assert from_graph == set(OUTPUT_OWNERS.items())


def test_an_agent_that_owns_no_output_writes_nothing():
    """PAM orchestrates and is in no `OUTPUT_OWNERS` value, so an empty tuple is the honest
    answer. Inverting a map is easy to get wrong in the direction that invents an entry."""
    from agents.tools.ownership import OUTPUT_OWNERS
    graph = build_graph()
    unowning = set(graph.agents) - set(OUTPUT_OWNERS.values())
    assert unowning, "no agent owns nothing - this test has stopped exercising the empty case"
    for agent_id in unowning:
        assert graph.agents[agent_id].writes == ()


def test_crew_membership_is_the_dispatch_map():
    from api.services.run_service import _CREW_AGENT_NAMES
    graph = build_graph()
    assert {c.crew_id: list(c.agent_ids) for c in graph.crews.values()} == _CREW_AGENT_NAMES


def test_crew_dependencies_are_the_readiness_map():
    from api.services.crew_graph import CREW_DEPENDENCIES
    graph = build_graph()
    assert {c.crew_id: list(c.depends_on) for c in graph.crews.values()} == CREW_DEPENDENCIES


def test_every_dependency_names_a_crew_the_graph_holds():
    graph = build_graph()
    for crew in graph.crews.values():
        for upstream in crew.depends_on:
            assert upstream in graph.crews, (
                f"crew {crew.crew_id} waits on {upstream}, which is not a crew"
            )


def test_a_crew_naming_an_unknown_agent_raises_rather_than_dropping_the_edge():
    """The defect this module replaces: `RunCrewTool` offering PAM a crew that does not exist,
    `build_and_run_crew` returning "" for it, and a dispatch that did nothing reporting as a
    result. A graph that quietly omitted the broken edge would be the same failure again.
    """
    from agents import graph as graph_module

    broken = dict(graph_module._CREW_AGENT_NAMES)
    broken["discovery"] = ["archivist"]
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(graph_module, "_CREW_AGENT_NAMES", broken)
        mp.setattr(
            graph_module,
            "_CREW_DEPENDENCIES",
            {**graph_module._CREW_DEPENDENCIES, "discovery": []},
        )
        with pytest.raises(GraphInconsistent, match="archivist"):
            build_graph()


def test_a_crew_known_to_one_map_and_not_the_other_raises():
    """`_CREW_AGENT_NAMES` and `CREW_DEPENDENCIES` are two hand-maintained lists of the same
    crews. A crew in one and not the other is either undispatchable or unschedulable, and both
    are silent today."""
    from agents import graph as graph_module

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(
            graph_module,
            "_CREW_DEPENDENCIES",
            {**graph_module._CREW_DEPENDENCIES, "architecture": []},
        )
        with pytest.raises(GraphInconsistent, match="architecture"):
            build_graph()


def test_an_output_owned_by_an_unknown_agent_raises():
    from agents import graph as graph_module

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(
            graph_module,
            "_OUTPUT_OWNERS",
            {**graph_module._OUTPUT_OWNERS, "field_notes": "archivist"},
        )
        with pytest.raises(GraphInconsistent, match="archivist"):
            build_graph()


def test_an_agent_with_a_tier_and_no_tools_raises():
    """The direction `test_every_dispatched_agent_has_a_tier` catches by set equality, restated
    as a failure of assembly rather than of comparison - `visual_illustrator` was in `AGENT_TIER`
    and absent from `tool_map`, and `create_business_plan_crew` raised before its first task."""
    from agents import graph as graph_module

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(
            graph_module, "_AGENT_TIER", {**graph_module._AGENT_TIER, "archivist": "fast"}
        )
        with pytest.raises(GraphInconsistent, match="archivist"):
            build_graph()


def test_building_the_graph_twice_gives_independent_dictionaries():
    """The module builds one at import to fail loudly on drift. A caller that mutated a shared
    dict would corrupt every later reader, and Tasks 3 and 4 both read it."""
    first, second = build_graph(), build_graph()
    assert first.agents == second.agents
    assert first.agents is not second.agents
    first.agents.pop(next(iter(first.agents)))
    assert set(build_graph().agents) == set(second.agents)


# --- Identity: a permanent id, a mutable name -------------------------------------------------
#
# The id is the snake key every registry and every stored row already uses. The display name and
# the image are what a human reads, and both may change without anything having to migrate. The
# tests below therefore never compare identity with a list written beside them: they hold it
# against `build_graph()` and `AGENT_TIER`, and they check the one property that proves the two
# halves are actually separate - that the name cannot be computed from the id.


def test_every_agent_has_an_identity_and_no_identity_is_orphaned():
    graph = build_graph()
    from agents.identity import AGENT_IDENTITY
    assert set(AGENT_IDENTITY) == set(graph.agents)


def test_a_display_name_is_never_used_as_a_key():
    from agents.model_registry import AGENT_TIER
    graph = build_graph()
    for node in graph.agents.values():
        assert node.agent_id in AGENT_TIER
        assert node.display_name not in graph.agents


def test_a_display_name_is_not_a_formatting_of_the_id():
    """The trap this task exists to avoid.

    `_SNAKE_TO_DISPLAY` in `run_service.py` maps every one of its fifteen agents to exactly
    `id.replace("_", " ").title()`, so it is a formatting function wearing a registry's clothes -
    rename an agent there and the id changes with it. A display name that can be computed from
    the id has not been separated from the id; it has been spelled differently.
    """
    for node in build_graph().agents.values():
        spaced = node.agent_id.replace("_", " ")
        derivations = {
            node.agent_id, spaced, spaced.title(), spaced.upper(), node.agent_id.title(),
        }
        assert node.display_name not in derivations, (
            f"{node.agent_id}: '{node.display_name}' is derivable from the id, so renaming "
            f"the agent would still mean renaming its key"
        )


def test_a_node_carries_the_identity_the_registry_gives_it():
    """Asserted on the node rather than on the map, because the node is what every reader holds.
    A test that only compared `AGENT_IDENTITY` with itself would pass with `AgentNode` never
    having been wired to it at all."""
    from agents.identity import AGENT_IDENTITY
    for node in build_graph().agents.values():
        assert node.display_name == AGENT_IDENTITY[node.agent_id].display_name
        assert node.image == AGENT_IDENTITY[node.agent_id].image


def test_every_image_names_a_file_that_exists():
    """The seventeen filenames are transcribed, and a transcription error is silent - the browser
    shows a broken image and nothing raises. The files are the source, so ask them."""
    from pathlib import Path

    from agents.identity import AGENT_IDENTITY

    public = Path(__file__).resolve().parent.parent / "ui" / "public"
    missing = sorted(
        f"{agent_id} -> {identity.image}"
        for agent_id, identity in AGENT_IDENTITY.items()
        if identity.image and not (public / identity.image.lstrip("/")).is_file()
    )
    assert not missing, f"identity names images that are not in ui/public: {missing}"


def test_an_agent_with_no_identity_raises_rather_than_going_unnamed():
    """Assembly refuses a partial answer here as it does everywhere else. An agent silently
    falling back to its id as a name is how the id becomes a label again."""
    from agents import graph as graph_module

    thinned = {
        agent_id: identity
        for agent_id, identity in graph_module._AGENT_IDENTITY.items()
        if agent_id != "pam"
    }
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(graph_module, "_AGENT_IDENTITY", thinned)
        with pytest.raises(GraphInconsistent, match="pam"):
            build_graph()


# --- A crew's label, and the order the crews are shown in -------------------------------------
#
# Same split as an agent's: `crew_id` is stored on `crew_runs.crew_name` and dispatched by PAM,
# the label is what a reader sees. The order is not declared at all - it is derived from
# `CREW_DEPENDENCIES`, because an order typed beside the dependency map can contradict it, and
# a crew shown as next while the graph would refuse to run it is acted on by the reader.


def test_every_crew_has_a_label_and_no_label_is_orphaned():
    from agents.identity import CREW_LABEL
    assert set(CREW_LABEL) == set(build_graph().crews)


def test_a_node_carries_the_label_the_registry_gives_it():
    """On the node, not on the map: comparing `CREW_LABEL` with itself would pass with
    `CrewNode` never having been wired to it."""
    from agents.identity import CREW_LABEL
    for crew in build_graph().crews.values():
        assert crew.display_name == CREW_LABEL[crew.crew_id]


def test_a_crew_label_is_not_a_formatting_of_the_crew_id():
    """At least one label must be un-derivable, or the map is a `.title()` in disguise and the
    id and the name are still the same string. `discovery_mapping` reads Value Chain Mapping."""
    derivable = {
        crew.crew_id
        for crew in build_graph().crews.values()
        if crew.display_name == crew.crew_id.replace("_", " ").title()
    }
    assert "discovery_mapping" not in derivable


def test_a_crew_with_no_label_raises_rather_than_showing_its_id():
    from agents import graph as graph_module

    thinned = {
        crew_id: label
        for crew_id, label in graph_module._CREW_LABEL.items()
        if crew_id != "delivery"
    }
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(graph_module, "_CREW_LABEL", thinned)
        with pytest.raises(GraphInconsistent, match="delivery"):
            build_graph()


def test_a_label_for_a_crew_nothing_dispatches_raises():
    from agents import graph as graph_module

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(
            graph_module, "_CREW_LABEL", {**graph_module._CREW_LABEL, "architecture": "Arch"}
        )
        with pytest.raises(GraphInconsistent, match="architecture"):
            build_graph()


def test_no_crew_is_ordered_before_one_it_waits_on():
    """`list(graph.crews)` is a display order as well as a lookup, and this is the property
    that makes it one. Asserted against `depends_on` as the node carries it, so a reordering
    that ignored the dependency map fails here rather than on a board a user is reading."""
    order = list(build_graph().crews)
    for position, crew_id in enumerate(order):
        for upstream in build_graph().crews[crew_id].depends_on:
            assert order.index(upstream) < position, (
                f"{crew_id} is ordered before its dependency {upstream}"
            )


def test_the_order_follows_the_dependency_map_rather_than_the_declaration_order():
    """The weaker test above passes for any order that happens to be legal, including the
    order `_CREW_AGENT_NAMES` happens to be typed in. This one moves a dependency and checks
    the sequence moves with it - otherwise the ordering is a coincidence, not a derivation.
    """
    from agents import graph as graph_module

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(
            graph_module,
            "_CREW_DEPENDENCIES",
            {**graph_module._CREW_DEPENDENCIES, "delivery": [], "business_plan": []},
        )
        order = list(build_graph().crews)
    assert order.index("delivery") < order.index("value_design"), order


def test_a_cycle_in_the_dependency_map_raises_rather_than_returning_a_partial_order():
    from agents import graph as graph_module

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(
            graph_module,
            "_CREW_DEPENDENCIES",
            {**graph_module._CREW_DEPENDENCIES, "discovery_mapping": ["business_plan"]},
        )
        with pytest.raises(GraphInconsistent, match="business_plan"):
            build_graph()
