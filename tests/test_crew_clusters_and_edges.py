# tests/test_crew_clusters_and_edges.py
"""Clusters and crew edges: the two things the graph derives so that a picture can be drawn.

Both are new shapes over old declarations, and neither may be asserted against a list typed
here - that would be the restatement `agents/graph.py` exists to end, wearing a test's clothes.
Every expectation below is computed from the registry that owns the fact: `CLUSTERS`,
`Charter.cluster`, `CREW_DEPENDENCIES`, `OUTPUT_OWNERS` and `AGENT_READS`.

**The question these tests are written against is "would this fail if the code were wrong?"**
For a derivation that is easy to get half right, the sharpest form is a mutation: change one
declaration, rebuild, and assert the derived answer moved. Several tests below do that by
patching the name **where `agents/graph.py` looks it up** - `agents.graph._CLUSTERS`, not
`agents.clusters.CLUSTERS` - which is the mistake CLAUDE.md records four crew tests making.

`build_graph` is called rather than `GRAPH` read, because `GRAPH` is assembled once at import
and a patched declaration would not reach it.
"""
from __future__ import annotations

import dataclasses

import pytest

from agents.charter import CREW_CHARTER, DISPATCH_PATHS, Charter, Trigger
from agents.clusters import Cluster
from agents.egress import TOOL_EGRESS
from agents.graph import EdgeKind, GraphInconsistent, build_graph


# ── Clusters ──────────────────────────────────────────────────────────────────


def test_every_crew_belongs_to_a_declared_cluster():
    from agents.clusters import CLUSTERS

    graph = build_graph()
    assert {crew.cluster for crew in graph.crews.values()} <= set(CLUSTERS)


def test_a_cluster_holds_exactly_the_crews_whose_charter_names_it():
    """Membership is inverted from the crews, so this is the inversion held against the source.

    The failure it guards is a cluster carrying its own crew list: that would pass an
    "every crew is in some cluster" check while quietly disagreeing with the charters.
    """
    graph = build_graph()
    for cluster_id, cluster in graph.clusters.items():
        expected = [
            crew_id
            for crew_id in graph.crews
            if CREW_CHARTER[crew_id].cluster == cluster_id
        ]
        assert list(cluster.crew_ids) == expected


def test_a_clusters_crews_are_in_the_graphs_own_topological_order():
    """The clockwise order of the ring is the order the graph already computes.

    A viewer that sorted them itself - alphabetically, or by declaration order - would put a
    crew before one it waits on, and "the third node clockwise" would stop meaning anything.
    """
    graph = build_graph()
    order = list(graph.crews)
    for cluster in graph.clusters.values():
        positions = [order.index(crew_id) for crew_id in cluster.crew_ids]
        assert positions == sorted(positions)


def test_a_band_holds_only_crews_that_wait_on_nothing_in_it():
    """What a band claims, held to the dependency map.

    A band says "these could run at the same moment". That is false the instant one crew in a
    band waits on another in the same band, or on a crew in a later one - and a picture drawn
    from bands would then show as parallel two crews the board runs in sequence. Checked
    transitively, because an indirect dependency inside a band is the same lie told at one
    remove.
    """
    graph = build_graph()
    upstream: dict[str, set[str]] = {}
    for crew_id, crew in graph.crews.items():
        upstream[crew_id] = {d for dep in crew.depends_on for d in {dep} | upstream[dep]}

    for cluster in graph.clusters.values():
        seen: set[str] = set()
        for band in cluster.crew_bands:
            for crew_id in band:
                assert not upstream[crew_id] & set(band), (
                    f"{crew_id} is banded with a crew it waits on"
                )
                assert upstream[crew_id] & set(cluster.crew_ids) <= seen, (
                    f"{crew_id} is banded above a crew it waits on"
                )
            seen |= set(band)


def test_two_crews_that_wait_on_the_same_crew_share_a_band():
    """The property the view is being taught to draw, on the graph as it stands.

    `assessment_design` and `stakeholder_management` both wait on the value chain and on
    nothing else. A layout given a flat order cannot tell that from a sequence, so the grouping
    is what has to carry it.
    """
    bands = build_graph().clusters["pmo"].crew_bands
    holding = [band for band in bands if "assessment_design" in band]
    assert len(holding) == 1
    assert set(holding[0]) == {"assessment_design", "stakeholder_management"}


def test_the_bands_move_when_a_dependency_moves(monkeypatch):
    """The mutation, because the grouping above would also hold for a hard-coded pair.

    Put `stakeholder_management` back behind `assessment_design` - the declaration this branch
    corrected - and the two must fall into different bands, with the crews below shifted down
    by one. A test that only read today's grouping would pass against a table of it.
    """
    from agents import graph as graph_module

    before = build_graph().clusters["pmo"].crew_bands
    monkeypatch.setattr(
        graph_module,
        "_CREW_DEPENDENCIES",
        {**graph_module._CREW_DEPENDENCIES, "stakeholder_management": ["assessment_design"]},
    )
    after = build_graph().clusters["pmo"].crew_bands

    def band_of(bands, crew_id: str) -> int:
        return next(i for i, band in enumerate(bands) if crew_id in band)

    assert band_of(before, "assessment_design") == band_of(before, "stakeholder_management")
    assert band_of(after, "assessment_design") < band_of(after, "stakeholder_management")
    assert len(after) == len(before) + 1


def test_a_clusters_crew_ids_are_exactly_its_bands_flattened():
    """One set of crews, not two. `crew_ids` is derived, and this is what makes it safe to read
    beside `crew_bands` in the same payload."""
    for cluster in build_graph().clusters.values():
        assert list(cluster.crew_ids) == [
            crew_id for band in cluster.crew_bands for crew_id in band
        ]


def test_an_orchestrator_runs_in_none_of_its_own_crews():
    graph = build_graph()
    for cluster in graph.clusters.values():
        for crew_id in cluster.crew_ids:
            assert cluster.orchestrator_id not in graph.crews[crew_id].agent_ids


def test_dispatches_is_exactly_the_crews_the_orchestrator_can_start():
    """Derived from the tool the orchestrator holds and the triggers each crew declares.

    `DispatchPath.entrypoint` for the orchestration path is a tool class; an agent takes that
    path by holding it. The expectation is rebuilt here from `DISPATCH_PATHS` and `TOOL_EGRESS`
    rather than from the graph's own helper, so the two readings are compared.
    """
    graph = build_graph()
    by_tool = {
        trigger: path.entrypoint.split(":")[-1]
        for trigger, path in DISPATCH_PATHS.items()
        if path.entrypoint.split(":")[-1] in TOOL_EGRESS
    }
    for cluster in graph.clusters.values():
        held = set(graph.agents[cluster.orchestrator_id].tools)
        expected = [
            crew_id
            for crew_id in cluster.crew_ids
            if any(by_tool.get(t) in held for t in graph.crews[crew_id].triggers)
        ]
        assert list(cluster.dispatches) == expected


def test_an_orchestrator_cannot_start_every_crew_it_owns():
    """A spoke to every crew on the ring would assert a dispatch that does not exist.

    Three of the nine crews declare no trigger PAM can take - they are reachable by a REST call
    or by an approval cascade alone - so `dispatches` is strictly narrower than `crew_ids`, and
    a view drawing one spoke per crew would be making a false claim about the orchestrator's
    reach. Asserted as a strict subset rather than as a count, so it stays true as crews change.
    """
    graph = build_graph()
    for cluster in graph.clusters.values():
        assert set(cluster.dispatches) < set(cluster.crew_ids)


def test_a_crew_naming_an_undeclared_cluster_is_refused(monkeypatch):
    charter = dict(CREW_CHARTER)
    first = next(iter(charter))
    charter[first] = dataclasses.replace(charter[first], cluster="no_such_cluster")
    monkeypatch.setattr("agents.graph._CREW_CHARTER", charter)
    with pytest.raises(GraphInconsistent, match="no_such_cluster"):
        build_graph()


def test_a_cluster_owning_no_crew_is_refused(monkeypatch):
    from agents.clusters import CLUSTERS

    monkeypatch.setattr(
        "agents.graph._CLUSTERS",
        {
            **CLUSTERS,
            "empty": Cluster("empty", "Empty", "pam", "owns nothing"),
        },
    )
    with pytest.raises(GraphInconsistent, match="own no crew"):
        build_graph()


def test_an_orchestrator_no_registry_knows_is_refused(monkeypatch):
    monkeypatch.setattr(
        "agents.graph._CLUSTERS",
        {"pmo": Cluster("pmo", "Consulting PMO", "nobody", "")},
    )
    with pytest.raises(GraphInconsistent, match="nobody"):
        build_graph()


def test_an_orchestrator_who_runs_in_one_of_its_own_crews_is_refused(monkeypatch):
    """The centre cannot also be a point on the circle.

    `value_chain_mapper` runs in `discovery_mapping`, which is in the `pmo` cluster, so naming
    him its orchestrator is exactly that contradiction.
    """
    monkeypatch.setattr(
        "agents.graph._CLUSTERS",
        {"pmo": Cluster("pmo", "Consulting PMO", "value_chain_mapper", "")},
    )
    with pytest.raises(GraphInconsistent, match="also"):
        build_graph()


def test_an_orchestrator_that_can_start_nothing_is_refused(monkeypatch):
    """Ownership the dispatch paths do not support.

    `synthesis_analyst` is in `discovery_interviews`, so she must first be taken out of every
    crew - otherwise the previous guard fires and this one is never reached, which is how a
    guard comes to be believed rather than checked. She holds `ChromaQueryTool` and no
    dispatching tool, so with that removed the cluster's centre can start none of its ring.
    """
    from agents.clusters import CLUSTERS

    from agents.clusters import CLUSTERS

    monkeypatch.setattr("agents.graph._CREW_AGENT_NAMES", _crews_without("synthesis_analyst"))
    monkeypatch.setattr(
        "agents.graph._CLUSTERS",
        {"pmo": dataclasses.replace(CLUSTERS["pmo"], orchestrator="synthesis_analyst")},
    )
    with pytest.raises(GraphInconsistent, match="start none of"):
        build_graph()


def test_two_clusters_sharing_one_orchestrator_are_refused(monkeypatch):
    """Both clusters own a crew, so the earlier guards pass and this one is what fires.

    A second cluster left empty would be refused for being empty, and the test would then be
    asserting a guard it never reached.
    """
    from agents.clusters import CLUSTERS

    monkeypatch.setattr("agents.graph._CREW_CHARTER", _charter_moving("business_plan", "second"))
    monkeypatch.setattr(
        "agents.graph._CLUSTERS",
        {
            **CLUSTERS,
            "second": Cluster("second", "Second PMO", "pam", "the same agent again"),
        },
    )
    with pytest.raises(GraphInconsistent, match="more than one cluster"):
        build_graph()


def _crews_without(agent_id: str) -> dict[str, list[str]]:
    from api.services.run_service import _CREW_AGENT_NAMES

    return {
        crew_id: [a for a in agents if a != agent_id]
        for crew_id, agents in _CREW_AGENT_NAMES.items()
    }


def _charter_moving(crew_id: str, cluster_id: str) -> dict[str, Charter]:
    charter = dict(CREW_CHARTER)
    charter[crew_id] = dataclasses.replace(charter[crew_id], cluster=cluster_id)
    return charter


# ── Edges ─────────────────────────────────────────────────────────────────────


def test_every_declared_dependency_appears_exactly_once_as_an_edge():
    from api.services.crew_graph import CREW_DEPENDENCIES

    graph = build_graph()
    declared = {
        (source, target)
        for target, sources in CREW_DEPENDENCIES.items()
        for source in sources
    }
    from_edges = [(e.source, e.target) for e in graph.edges if e.declared]
    assert sorted(from_edges) == sorted(declared)
    assert len(from_edges) == len(set(from_edges))


def test_a_declared_edge_is_information_exactly_when_an_artefact_travels():
    """The distinction the ordering alone cannot make, held to the writes and the reads."""
    graph = build_graph()
    for edge in graph.edges:
        if not edge.declared:
            continue
        travels = graph.crew_writes(edge.source) & graph.crew_reads(edge.target)
        assert set(edge.artefacts) == travels
        expected = EdgeKind.INFORMATION if travels else EdgeKind.SEQUENCING
        assert edge.kind is expected, f"{edge.source} -> {edge.target}"


def test_a_sequencing_edge_really_shares_nothing():
    """Named separately because it is the claim an auditor reads off the picture.

    Two of the nine declared edges are sequencing today. If either of them in fact carried an
    artefact, the view would be telling a reader that no material passes between two crews when
    it does - the one direction of error this page cannot afford.
    """
    graph = build_graph()
    sequencing = [e for e in graph.edges if e.kind is EdgeKind.SEQUENCING]
    assert sequencing, "no sequencing edge to check - the distinction has stopped being drawn"
    for edge in sequencing:
        assert not graph.crew_writes(edge.source) & graph.crew_reads(edge.target)


def test_an_inherited_edge_carries_an_artefact_and_no_declared_dependency():
    graph = build_graph()
    inherited = [e for e in graph.edges if e.kind is EdgeKind.INHERITED]
    assert inherited
    for edge in inherited:
        assert edge.artefacts
        assert not edge.declared
        assert edge.source not in graph.crews[edge.target].depends_on


def test_an_inherited_edge_is_transitively_ordered():
    """`EdgeKind.INHERITED` says the ordering comes from further back in the chain.

    That sentence is a claim about `CREW_DEPENDENCIES`, so it is checked against it rather than
    believed. A flow whose writer is not upstream at all would be a crew reading an artefact
    nothing guarantees exists yet - a genuine finding, and one this label would hide.
    """
    graph = build_graph()
    upstream: dict[str, set[str]] = {}
    for crew_id, crew in graph.crews.items():
        reach: set[str] = set()
        for dep in crew.depends_on:
            reach |= {dep} | upstream[dep]
        upstream[crew_id] = reach
    for edge in graph.edges:
        if edge.kind is EdgeKind.INHERITED:
            assert edge.source in upstream[edge.target], (
                f"{edge.target} reads {list(edge.artefacts)} from {edge.source}, which nothing "
                f"orders before it"
            )


def test_an_edge_appears_when_a_read_is_declared_and_goes_when_it_is_not(monkeypatch):
    """The mutation that proves the edges are derived rather than drawn.

    `requirements -> delivery` is a sequencing edge: the roadmap generator reads nothing the
    requirements crew writes. Give him one of its outputs and the same edge must become an
    information flow naming that artefact. A test that only read today's classification would
    pass against a hard-coded table.
    """
    from agents.reads import AGENT_READS, Medium, Read

    assert _edge(build_graph(), "requirements", "delivery").kind is EdgeKind.SEQUENCING

    written_by_requirements = build_graph().crew_writes("requirements")
    artefact = sorted(written_by_requirements)[0]
    reads = dict(AGENT_READS)
    reads["roadmap_generator"] = reads["roadmap_generator"] + (
        Read(artefact, Medium.ARTEFACT_JSON, "SQLiteStateTool", "invented for this test"),
    )
    monkeypatch.setattr("agents.graph._AGENT_READS", reads)

    moved = _edge(build_graph(), "requirements", "delivery")
    assert moved.kind is EdgeKind.INFORMATION
    assert artefact in moved.artefacts


def test_the_stakeholder_dependency_names_the_crew_whose_artefact_it_reads():
    """The consequence of correcting the declaration, read off the derived edges.

    Both halves matter and neither implies the other: the value chain edge must now be a
    declared information flow naming the artefact that travels, and the edge that carried
    nothing must be gone rather than merely relabelled. Asserted through `build_graph()` rather
    than against `CREW_DEPENDENCIES`, because the map is where the change was made and the
    edges are what the board and the picture are drawn from.
    """
    graph = build_graph()

    real = _edge(graph, "discovery_mapping", "stakeholder_management")
    assert real.declared is True
    assert real.kind is EdgeKind.INFORMATION
    assert "value_chain_registry" in real.artefacts

    assert not [
        e for e in graph.edges
        if (e.source, e.target) == ("assessment_design", "stakeholder_management")
    ], "the edge that carried nothing is still drawn"


def test_the_interviews_still_wait_on_the_stakeholder_crew_for_no_artefact():
    """Recorded rather than quietly fixed.

    `stakeholder_management -> discovery_interviews` carries nothing and is meant to: the
    mapping that connects them is `stakeholder_assignments`, a table neither crew writes as an
    artefact. Inventing a flow to make the arrow look busier would be the failure the whole
    derivation exists to prevent, so this asserts the edge stays declared, stays sequencing, and
    stays empty.
    """
    edge = _edge(build_graph(), "stakeholder_management", "discovery_interviews")
    assert edge.declared is True
    assert edge.kind is EdgeKind.SEQUENCING
    assert edge.artefacts == ()


def test_an_edge_crosses_clusters_when_its_crews_are_in_different_ones(monkeypatch):
    """What passes between clusters, with the second cluster added as data alone.

    Nothing declares an inter-cluster edge. Moving `business_plan` into a second cluster - one
    charter field, one `CLUSTERS` entry, and an orchestrator holding the dispatching tool, which
    is exactly what adding a second PMO would be - must turn every edge into it into a crossing
    without anything else being written.

    `stakeholder_manager` is the second centre: he runs in `stakeholder_management`, which stays
    in the first cluster, so he is in none of his own. He is handed `RunCrewTool` because
    `business_plan` declares the orchestration trigger and a centre that can start nothing is
    refused - which is the guard doing its job rather than an obstacle to route around.
    """
    from agents.clusters import CLUSTERS

    assert not any(e.crosses_clusters for e in build_graph().edges)

    tools = dict(_tools_by_agent())
    tools["stakeholder_manager"] = tools["stakeholder_manager"] + ("RunCrewTool",)
    monkeypatch.setattr("agents.graph._tools_by_agent", lambda: tools)
    monkeypatch.setattr("agents.graph._CREW_CHARTER", _charter_moving("business_plan", "second"))
    monkeypatch.setattr(
        "agents.graph._CLUSTERS",
        {
            **CLUSTERS,
            "second": Cluster("second", "Second PMO", "stakeholder_manager", "a second cluster"),
        },
    )

    graph = build_graph()
    assert set(graph.clusters["second"].crew_ids) == {"business_plan"}
    crossing = {(e.source, e.target) for e in graph.edges if e.crosses_clusters}
    assert crossing == {
        (e.source, e.target) for e in graph.edges if e.target == "business_plan"
    }
    assert crossing, "moving a crew into its own cluster produced no inter-cluster edge"
    # And the derivation is unchanged in every other respect: the same artefacts travel.
    plain = {(e.source, e.target): e.artefacts for e in build_graph().edges}
    assert all(plain[(e.source, e.target)] == e.artefacts for e in graph.edges)


def _tools_by_agent() -> dict[str, tuple[str, ...]]:
    from agents.graph import _tools_by_agent as read_them

    return read_them()


def test_the_same_declarations_produce_the_same_picture(monkeypatch):
    """Same input, same edges, in the same order.

    The page is shown to clients and auditors, and the view is drawn straight off this tuple:
    if its order moved between calls, so would the picture. Set iteration is the usual culprit,
    and the derivation intersects sets in two places.
    """
    first = build_graph()
    second = build_graph()
    assert first.edges == second.edges
    assert [c.crew_bands for c in first.clusters.values()] == [
        c.crew_bands for c in second.clusters.values()
    ]
    for edge in first.edges:
        assert list(edge.artefacts) == sorted(edge.artefacts)


def _edge(graph, source: str, target: str):
    found = [e for e in graph.edges if e.source == source and e.target == target]
    assert len(found) == 1, f"expected one {source} -> {target} edge, found {len(found)}"
    return found[0]
