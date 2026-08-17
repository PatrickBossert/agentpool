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
