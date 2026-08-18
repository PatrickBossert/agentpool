# tests/test_agent_graph.py
"""The graph is assembled from the registries, so every test here asserts against a registry.

A graph is unusually easy to test against itself. An `EXPECTED_AGENTS = [...]` here would assert
only that the same list can be typed twice - which is the tenth restatement this module exists to
remove, wearing a test's clothes. Every assertion below therefore names the source the fact
derives from: `AGENT_TIER`, `tool_map` as `get_tools_for_agent` actually returns it,
`OUTPUT_OWNERS`, `_CREW_AGENT_NAMES`, or `CREW_DEPENDENCIES`.
"""
from pathlib import Path

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


# --- What an agent reads ----------------------------------------------------------------------
#
# `writes` costs nothing - it is `OUTPUT_OWNERS` inverted. `reads` is the half no registry held,
# so it is declared, and a declaration is only worth having if something can refuse it. The
# guards below therefore never compare `AGENT_READS` with a list written beside them: they hold
# it against `OUTPUT_OWNERS`, against the tools `get_tools_for_agent` actually hands the agent,
# and - for the three reads that do not work - against what `SQLiteStateTool` really returns.


def test_every_artefact_read_is_written_by_someone():
    graph = build_graph()
    written = {w for node in graph.agents.values() for w in node.writes}
    for node in graph.agents.values():
        unwritable = set(node.reads) - written
        assert not unwritable, f"{node.agent_id} reads what nobody writes: {sorted(unwritable)}"


def test_an_agent_with_no_reads_declared_raises_rather_than_reading_nothing():
    """An empty tuple is a real answer here - PAM and the Enterprise Architect read no artefact
    at all - so a missing entry cannot be defaulted to empty without making the two cases
    identical on a page whose job is to say where the client's material goes."""
    from agents import graph as graph_module

    thinned = {
        agent_id: reads
        for agent_id, reads in graph_module._AGENT_READS.items()
        if agent_id != "synthesis_analyst"
    }
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(graph_module, "_AGENT_READS", thinned)
        with pytest.raises(GraphInconsistent, match="synthesis_analyst"):
            build_graph()


def test_reads_declared_for_an_agent_that_does_not_exist_raises():
    from agents import graph as graph_module

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(
            graph_module, "_AGENT_READS", {**graph_module._AGENT_READS, "archivist": ()}
        )
        with pytest.raises(GraphInconsistent, match="archivist"):
            build_graph()


def test_a_read_arrives_by_a_tool_the_agent_actually_holds():
    """The route is the half that breaks, so it is the half that is checked against the registry.

    `interview_sessions` is a real read for the Stakeholder Interviewer and an unresolvable one
    for the Stakeholder Manager, and the only difference between them is which tool carries it.
    A `via` naming a tool the agent does not hold is that same mistake written down as fact.
    """
    from agents.egress import tool_classes_on_disk
    from agents.reads import VIA_DISPATCH

    on_disk = tool_classes_on_disk()
    for node in build_graph().agents.values():
        for source in node.sources:
            if source.via == VIA_DISPATCH:
                continue
            assert source.via in on_disk, (
                f"{node.agent_id} reads {source.source} via {source.via}, which is not a tool "
                f"class under agents/tools/"
            )
            assert source.via in node.tools, (
                f"{node.agent_id} reads {source.source} via {source.via}, which the registry "
                f"does not hand it - it holds {sorted(node.tools)}"
            )


def test_reads_is_the_artefact_half_of_what_an_agent_draws_on():
    """`reads` is narrower than `sources` on purpose, and the difference must be real.

    `writes` inverts `OUTPUT_OWNERS`, which knows only artefacts, so a Chroma collection or a
    database table in `reads` would fail the guard above while being perfectly correct. This
    checks the projection drops exactly the non-artefact sources and nothing else - a `reads`
    that returned everything would make the guard unsatisfiable, and one that returned nothing
    would make it vacuous.
    """
    from agents.reads import Medium

    graph = build_graph()
    dropped = 0
    for node in graph.agents.values():
        artefacts = [s for s in node.sources if s.medium is Medium.ARTEFACT_JSON]
        assert node.reads == tuple(s.source for s in artefacts)
        dropped += len(node.sources) - len(artefacts)
    assert dropped, (
        "no source is held in anything but an artefact, so this projection has stopped "
        "distinguishing anything"
    )


def test_the_node_carries_the_reads_the_declaration_gives_it():
    """On the node, not on the map. Comparing `AGENT_READS` with itself would pass with
    `AgentNode` never having been wired to it - the mistake `test_a_node_carries_the_identity`
    exists to avoid one field along."""
    from agents.reads import AGENT_READS
    for node in build_graph().agents.values():
        assert node.sources == tuple(AGENT_READS[node.agent_id])


def test_an_unresolvable_read_is_not_also_declared_as_one_that_works():
    """The two lists describe the same instruction, so an entry may not sit in both. A source
    recorded as unreadable while also being declared as read would let the finding be quietly
    cancelled by the declaration next to it."""
    from agents.reads import AGENT_READS, UNRESOLVABLE_READS

    for entry in UNRESOLVABLE_READS:
        declared = {source.source for source in AGENT_READS[entry.agent_id]}
        assert entry.source not in declared, (
            f"{entry.agent_id} both declares {entry.source} as a read and records it as "
            f"unresolvable"
        )


def _all_declared_reads():
    """Every `Read` the module declares, whoever it reaches, as (owner, read) pairs."""
    from agents.reads import AGENT_READS, CREW_DISPATCH_READS, UNINSTRUCTED_READS

    pairs = [(agent_id, read) for agent_id, reads in AGENT_READS.items() for read in reads]
    pairs += [("CREW_DISPATCH_READS", read) for read in CREW_DISPATCH_READS]
    pairs += [("UNINSTRUCTED_READS", read) for read in UNINSTRUCTED_READS]
    return pairs


def test_every_collection_read_names_the_tier_that_builds_it():
    """The tier is held equal to the resolver, not merely typed beside the collection name.

    `collection_for` is the one place a collection name is built, so rebuilding each declared
    `source` from its declared tier is what makes the declaration a fact rather than a label. A
    template typed here that the resolver would never produce - `{slug}_documents`, which the
    design document actually says, or a tier moved onto the wrong collection - fails here
    instead of appearing on the privacy page as a store that does not exist.

    Driven with the templates themselves as the keys, which is what the declarations hold:
    `collection_for` interpolates nothing, so `slug="{slug}"` comes back as `{slug}_docs`.
    """
    from agents.reads import Medium
    from api.services.knowledge_tiers import collection_for

    checked = 0
    for owner, read in _all_declared_reads():
        if read.medium is not Medium.VECTOR_COLLECTION:
            continue
        assert read.tier, f"{owner} declares {read.source} with no knowledge tier"
        assert read.source == collection_for(
            read.tier, slug="{slug}", sector="{sector}", org_slug="{org_slug}"
        ), (
            f"{owner} declares {read.source} at the {read.tier!r} tier, but that tier resolves "
            f"to a different collection"
        )
        checked += 1
    assert checked, "no collection read found - this test would assert nothing"


def test_only_a_collection_read_carries_a_tier():
    """A tier is a property of the knowledge store and of nothing else.

    An artefact resolves under `projects/{slug}/outputs/` and a table lives in a database; there
    is no tier that would be true of either, and giving one a tier to fill the field in would
    make the word mean two things on the page that renders it.
    """
    from agents.reads import Medium

    for owner, read in _all_declared_reads():
        if read.medium is not Medium.VECTOR_COLLECTION:
            assert read.tier is None, (
                f"{owner} gives {read.source} the {read.tier!r} tier, but it is held in "
                f"{read.medium.value}"
            )


def test_every_tier_the_store_has_is_one_the_graph_can_name():
    """A tier the deployment writes and the graph cannot describe is a hole in the page.

    The organisation tier was exactly that until this change: writable since Tasks 2 and 3,
    declared by no read, and therefore absent from the privacy page altogether rather than
    present with nobody reading it.
    """
    from agents.reads import Medium
    from api.services.knowledge_tiers import KNOWLEDGE_TIERS

    declared = {
        read.tier
        for _, read in _all_declared_reads()
        if read.medium is Medium.VECTOR_COLLECTION
    }
    assert declared == set(KNOWLEDGE_TIERS), (
        f"the knowledge store has tiers the graph declares nothing for: "
        f"{set(KNOWLEDGE_TIERS) - declared}"
    )


def test_no_uninstructed_read_is_also_a_declared_one():
    """The two lists say opposite things, so a source may not sit in both.

    `UNINSTRUCTED_READS` means "the tool offers it and no task description asks for it". The
    moment an agent is instructed to read the organisation store, the entry moves into that
    agent's `AGENT_READS` tuple - leaving it here as well would have the page report a store as
    read by somebody and read by nobody at the same time.
    """
    from agents.reads import AGENT_READS, UNINSTRUCTED_READS

    declared = {read.source for reads in AGENT_READS.values() for read in reads}
    for read in UNINSTRUCTED_READS:
        assert read.source not in declared, (
            f"{read.source} is recorded as instructed to nobody and declared as an agent read"
        )


def test_no_task_description_instructs_the_uninstructed_tier():
    """The claim `UNINSTRUCTED_READS` makes, checked against the prompts rather than believed.

    This is the half a declaration cannot self-certify: the entry says no agent is told to query
    the organisation store, and the agents' task descriptions are where that is either true or
    not. When somebody writes `collection='organisation'` into a prompt, this fails and points
    at the entry that has to move.
    """
    from agents.reads import UNINSTRUCTED_READS
    from api.services.knowledge_tiers import KNOWLEDGE_TIERS

    uninstructed = {read.tier for read in UNINSTRUCTED_READS}
    assert uninstructed <= set(KNOWLEDGE_TIERS)

    # The agent and crew modules, which is where a task description lives. Not `agents/*.py`
    # itself: the declarations there discuss the tiers in prose, and a sweep that read them
    # would be answering a question about its own commentary.
    agents_dir = Path(__file__).resolve().parent.parent / "agents"
    prompts = "\n".join(
        path.read_text()
        for path in sorted(agents_dir.rglob("*.py"))
        if path.parent != agents_dir and "tools" not in path.parts
    )
    for tier in uninstructed:
        assert f"collection='{tier}'" not in prompts, (
            f"an agent is now instructed to read the {tier!r} tier - move its entry out of "
            f"UNINSTRUCTED_READS and into that agent's AGENT_READS tuple"
        )
    # The negative control: the phrase this searches for is one the prompts really do use, so a
    # rewording that made every search miss would fail here rather than pass everything above.
    assert "collection='sector'" in prompts


def test_what_the_dispatch_path_reads_names_tables_that_exist(tmp_path, monkeypatch):
    """`CREW_DISPATCH_READS` is the one declaration here with no consumer yet - Task 4 renders
    it - so it is the one most easily wrong and least easily noticed. Asked of the schema rather
    than of a list: the first draft said `skill_notes`, and the table is `agent_skill_notes`.
    """
    import asyncio

    from api.config import get_settings
    from api.database import get_connection, get_system_connection
    from agents.reads import CREW_DISPATCH_READS, Medium

    get_settings.cache_clear()
    monkeypatch.setenv("DATABASE_DIR", str(tmp_path))
    monkeypatch.setenv("PROJECTS_DIR", str(tmp_path / "projects"))
    try:
        async def _tables() -> set[str]:
            found: set[str] = set()
            async with get_connection("dispatch-probe") as conn:
                async with conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ) as cur:
                    found |= {row[0] async for row in cur}
            async with get_system_connection() as conn:
                async with conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ) as cur:
                    found |= {row[0] async for row in cur}
            return found

        tables = asyncio.run(_tables())
        for read in CREW_DISPATCH_READS:
            assert read.medium is Medium.DATABASE_TABLE, read
            assert read.source in tables, (
                f"the dispatch path is declared to read {read.source}, which is neither a "
                f"project table nor a system one"
            )
    finally:
        get_settings.cache_clear()


def test_an_unresolvable_read_really_cannot_be_served(tmp_path, monkeypatch):
    """The exclusions are proved by driving the tool, not by reasoning about the tool.

    Each entry is instructed through `SQLiteStateTool`, which resolves a key through the
    `agent_outputs` ledger and can therefore only ever see an output type. Asserting that from
    `OUTPUT_OWNERS` would be a statement about a map; this asks the tool, on a real project
    database, and asserts the positive control in the same fixture so that a test where
    everything errors cannot pass for the wrong reason.
    """
    import asyncio
    import json

    from api.config import get_settings
    from api.database import get_connection, insert_project
    from agents.reads import UNRESOLVABLE_READS

    slug = "reads-probe"
    get_settings.cache_clear()
    monkeypatch.setenv("DATABASE_DIR", str(tmp_path))
    monkeypatch.setenv("PROJECTS_DIR", str(tmp_path / "projects"))
    try:
        async def _make() -> None:
            async with get_connection(slug) as conn:
                await insert_project(
                    conn, slug=slug, llm_mode="standard", sector="probe", config_json="{}"
                )

        asyncio.run(_make())

        from agents.tools.sqlite_state import SQLiteStateTool

        # The positive control, written through the same door the agents use, so this fixture
        # is demonstrably one in which a real read succeeds.
        writer = SQLiteStateTool(slug=slug, agent_name="value_lever_analyst", run_id=0)
        written = writer._run(
            operation="write", key="value_levers", agent_name="value_lever_analyst",
            value=json.dumps([{"lever": "Probe"}]),
        )
        assert written.startswith("Written to"), written
        served = writer._run(
            operation="read", key="value_levers", agent_name="value_lever_analyst"
        )
        assert "Probe" in served, served

        for entry in UNRESOLVABLE_READS:
            assert entry.instructed_via == "SQLiteStateTool", (
                f"{entry.source} is instructed via {entry.instructed_via}, which this test "
                f"does not drive - it must be proved against the door it names"
            )
            reader = SQLiteStateTool(slug=slug, agent_name=entry.agent_id, run_id=0)
            result = reader._run(
                operation="read", key=entry.source, agent_name=entry.agent_id
            )
            assert result == f"Error: no state found for key '{entry.source}'", (
                f"{entry.agent_id}'s read of {entry.source} is not unresolvable after all: "
                f"{result}"
            )
    finally:
        get_settings.cache_clear()


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
