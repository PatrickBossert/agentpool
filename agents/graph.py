# agents/graph.py
"""One graph of the agents and crews, assembled from the registries that already hold them.

Nothing here is declared. Every fact is read from the one place that owns it:

| Fact | Source |
|------|--------|
| Which agents exist, and each one's tier | `AGENT_TIER` - `agents/model_registry.py` |
| What an agent is called, and its face | `AGENT_IDENTITY` - `agents/identity.py` |
| Which tools an agent holds | `tool_map` - `agents/tools/registry.py` |
| Which output types an agent writes | `OUTPUT_OWNERS` inverted - `agents/tools/ownership.py` |
| What each agent draws on | `AGENT_READS` - `agents/reads.py` |
| Which agents a crew dispatches | `_CREW_AGENT_NAMES` - `api/services/run_service.py` |
| What a crew is called | `CREW_LABEL` - `agents/identity.py` |
| What a crew waits on | `CREW_DEPENDENCIES` - `api/services/crew_graph.py` |
| What a crew is for, what can start it, and whose cluster it is in | `CREW_CHARTER` - `agents/charter.py` |
| Which agent orchestrates a cluster | `CLUSTERS` - `agents/clusters.py` |
| What each tool reaches | `TOOL_EGRESS` - `agents/egress.py` |

Two things this module derives rather than reads, because no registry holds either and both are
intersections of registries that do: a cluster's crews (`Charter.cluster` inverted) and the
edges between crews (`OUTPUT_OWNERS` inverted, met with `AGENT_READS`, against
`CREW_DEPENDENCIES`). Both exist so that a picture of this graph can be drawn without a single
hand-placed node or hand-written arrow label - see `ClusterNode` and `CrewEdge`.

A literal list of agent names or crew names in this file would make it one more restatement of
what that table already says, which is the thing it exists to end - the slice that built this
module deleted ten crew-to-agent maps, five disagreeing crew-label maps, two of the six persona
lists, two of the three `OUTPUT_TYPE_LABELS`, and `crews_enabled`, a settings toggle naming five
of the nine crews that no dispatch path had ever read. The disagreements were live:
`RunCrewTool`'s description offered PAM `discovery` and `architecture`, neither of which any
dispatch map knew, and `build_and_run_crew` answers an unknown crew name with an empty string -
so a dispatch that did nothing reports as a result.

That is why assembly raises rather than dropping an edge it cannot resolve. A graph that
silently omitted a broken edge would be the same failure in a new place, and the failure is
worth having at import time, where a developer sees it, rather than at dispatch time, where PAM
reads it as an answer.
"""
from __future__ import annotations

import ast
from dataclasses import dataclass, replace
from enum import Enum
from functools import lru_cache
from pathlib import Path

from agents.charter import CREW_CHARTER as _CREW_CHARTER
from agents.charter import DISPATCH_PATHS as _DISPATCH_PATHS
from agents.charter import Trigger
from agents.clusters import CLUSTERS as _CLUSTERS
from agents.egress import TOOL_EGRESS as _TOOL_EGRESS
from agents.egress import ALL_GRANTS, Destination, agent_destinations
from agents.identity import AGENT_IDENTITY as _AGENT_IDENTITY
from agents.reads import AGENT_READS as _AGENT_READS
from agents.reads import Medium, Read
from agents.identity import CREW_LABEL as _CREW_LABEL
from agents.model_registry import AGENT_TIER as _AGENT_TIER
from agents.tools.ownership import OUTPUT_OWNERS as _OUTPUT_OWNERS
from api.services.crew_graph import CREW_DEPENDENCIES as _CREW_DEPENDENCIES
from api.services.deployment_modes import Capability
from api.services.run_service import _CREW_AGENT_NAMES

# Every source in the table above is bound to a module-level name so that this is the single place
# any of them is looked up. It also means a test can substitute one here - which is where the
# name is looked up - rather than at its definition, the mistake four crew tests made and
# CLAUDE.md records.

_REGISTRY_SOURCE = Path(__file__).parent / "tools" / "registry.py"
_TOOL_MAP_NAME = "tool_map"


class GraphInconsistent(RuntimeError):
    """Two registries disagree, or one names something no other knows.

    Raised while the graph is being assembled, at import time. Returning a partial graph would
    hide exactly the class of drift this module was built to surface.
    """


@dataclass(frozen=True)
class AgentNode:
    """One agent, as the registries describe it.

    `agent_id` is the permanent half and the only thing anything may key on or store -
    `agent_outputs.agent_name` holds it on every row. `display_name` and `image` are the mutable
    half, resolved through `AGENT_IDENTITY`, and neither is derivable from the id.

    `egress` is everywhere this agent's work can reach on the project the graph was built for -
    its tools' destinations resolved through `agents/egress.py`, plus the model it runs on,
    which is the largest thing that leaves the building and is held by no tool. It is a
    property of the graph rather than of the agent because the same agent reaches Chroma Cloud
    on one project and a local Chroma on the next; `resolve_egress` is the thing to ask about a
    single tool, since a union cannot say which tool put a member in it.
    """

    agent_id: str
    tier: str
    tools: tuple[str, ...]
    writes: tuple[str, ...]
    display_name: str
    image: str | None
    egress: tuple[Destination, ...]
    sources: tuple[Read, ...]

    @property
    def reads(self) -> tuple[str, ...]:
        """The output types this agent reads: the artefact projection of `sources`.

        A property rather than a second field, so there is exactly one declaration and the two
        cannot drift. It is deliberately narrower than `sources` - `writes` is the inversion of
        `OUTPUT_OWNERS`, which knows only artefacts, so `reads` is the half of an agent's inputs
        that can be held against it. A Chroma collection or a database table has no owner in that
        map and would fail a guard that means nothing about it.
        """
        return tuple(
            source.source for source in self.sources if source.medium is Medium.ARTEFACT_JSON
        )


@dataclass(frozen=True)
class CrewNode:
    """One crew: who runs in it, what it is for, what can start it, and what it waits on.

    `crew_id` is the permanent half - `crew_runs.crew_name` stores it and PAM dispatches by it.
    `display_name` is the mutable half, resolved through `CREW_LABEL`, and is not derivable
    from the id: `discovery_mapping` reads as "Value Chain Mapping".

    `triggers` is what **can** start this crew, not what will. `depends_on` beside it is the
    condition on one of them - `Trigger.APPROVAL_CASCADE` reaches a crew only once every crew it
    depends on has been committed - so the two fields are read together and neither restates the
    other.

    `defect` is set only when every one of this crew's triggers currently fails, in which case
    the triggers above it are nominal: the paths exist and taking any of them raises. One crew
    has one.
    """

    crew_id: str
    agent_ids: tuple[str, ...]
    depends_on: tuple[str, ...]
    display_name: str
    purpose: str
    triggers: tuple[Trigger, ...]
    cluster: str
    note: str
    defect: str | None


class EdgeKind(Enum):
    """What one crew actually gets from another.

    The distinction the ordering alone cannot make. `CREW_DEPENDENCIES` says a crew waits on
    another; it does not say whether anything travels between them, and two of the nine
    declared edges carry nothing at all. An unlabelled arrow presents those two as if they
    were the same relationship as `discovery_mapping -> assessment_design`, which hands over
    three artefacts, and that is a materially different claim to anyone reading the page to
    find out where a client's material goes.

    It is also the distinction that finds a dependency declared against the wrong crew. A
    sequencing edge into a crew that has an inherited edge from somewhere else is the shape of
    exactly that error, and it was one: `stakeholder_management` waited on `assessment_design`,
    which writes nothing it reads, while reading the value chain from `discovery_mapping`, which
    it did not wait on. Not every sequencing edge is a mistake - `stakeholder_management ->
    discovery_interviews` is ordering that genuinely carries no artefact - so the shape is a
    question to ask of the declarations rather than a rule to enforce here.
    """

    INFORMATION = "information"
    """Waits on it, and reads an artefact it wrote."""

    SEQUENCING = "sequencing"
    """Waits on it, and reads nothing it wrote. Ordering only - no material passes."""

    INHERITED = "inherited"
    """Reads an artefact it wrote without waiting on it directly.

    The ordering is transitive rather than declared: the writer is upstream somewhere further
    back in the chain, so the artefact exists by the time it is read.
    `test_an_inherited_edge_is_transitively_ordered` holds that sentence to the dependency
    graph, so a flow that nothing orders would fail rather than be labelled as this.
    """


@dataclass(frozen=True)
class CrewEdge:
    """One relationship between two crews, derived from what they write and read.

    Nothing declares these. `source` writes, `target` reads, and `artefacts` is the
    intersection - the output types that genuinely travel. `declared` says whether
    `CREW_DEPENDENCIES` also holds the pair, which is what separates an ordering the system
    enforces from a flow it merely permits.

    `crosses_clusters` is the whole of what an inter-cluster edge needs: the same derivation
    run over crews in two clusters rather than one. A second orchestrator therefore brings its
    edges with it without anything here changing.
    """

    source: str
    target: str
    kind: EdgeKind
    artefacts: tuple[str, ...]
    declared: bool
    crosses_clusters: bool


@dataclass(frozen=True)
class ClusterNode:
    """One orchestrator, and the crews it owns.

    `crew_bands` is the cluster's crews grouped by how deep in the pipeline they sit: one band
    is a set of crews that could run at the same moment, because every crew any of them waits
    on is in an earlier band. It is the graph's own topological order with the ties kept rather
    than flattened away, and it is what a viewer needs to draw parallel work as parallel -
    `assessment_design` and `stakeholder_management` both wait on the value chain and nothing
    else, so putting one at position two and the other at position three would assert an
    ordering between them that no declaration makes.

    `crew_ids` is that same grouping flattened, so it is still the order a reader sees in a
    table and still consistent with the picture. A property rather than a second field: two
    orderings of one set of crews is exactly the drift this module exists to end, and the
    flattening cannot disagree with what it flattens.

    `dispatches` is narrower than `crew_ids` and deliberately so: it is the crews this
    orchestrator can itself start, derived from the tool it holds and the triggers each crew
    declares. Six of the nine crews in the one cluster today; the other three are reachable
    only by a REST call or by an approval cascade. Drawing a spoke from the centre to all nine
    would assert a dispatch that does not exist.
    """

    cluster_id: str
    label: str
    orchestrator_id: str
    note: str
    crew_bands: tuple[tuple[str, ...], ...]
    dispatches: tuple[str, ...]

    @property
    def crew_ids(self) -> tuple[str, ...]:
        """Every crew this cluster owns, in the graph's own topological order."""
        return tuple(crew_id for band in self.crew_bands for crew_id in band)


@dataclass(frozen=True)
class Graph:
    """The assembled whole, keyed by id in both directions.

    `crews` is ordered so that no crew precedes one it waits on, which is what makes
    `list(graph.crews)` a display order as well as a lookup. Iterating it is the reason
    nothing needs a hand-typed `CREW_ORDER`: an order typed beside the dependency map can
    contradict it, and did - a crew shown as next while the graph would refuse to run it.

    `clusters` and `edges` are what a picture of this graph is drawn from, and both are
    derived. Neither is a second rendering of anything above: a cluster is the inversion of
    `Charter.cluster`, and an edge is the intersection of one crew's writes with another's
    reads. A viewer that placed a node or labelled an arrow by hand would be re-declaring what
    these two already say.
    """

    agents: dict[str, AgentNode]
    crews: dict[str, CrewNode]
    clusters: dict[str, ClusterNode]
    edges: tuple[CrewEdge, ...]

    def crew_writes(self, crew_id: str) -> frozenset[str]:
        """The output types this crew's agents own, from `OUTPUT_OWNERS` inverted."""
        return frozenset(
            output for agent_id in self.crews[crew_id].agent_ids
            for output in self.agents[agent_id].writes
        )

    def crew_reads(self, crew_id: str) -> frozenset[str]:
        """The output types this crew's agents are declared to read.

        `AgentNode.reads` rather than `sources`, so this is the artefact half alone. A Chroma
        collection or a database table has no writing crew, and an edge derived from one would
        be an arrow drawn from nowhere.
        """
        return frozenset(
            source for agent_id in self.crews[crew_id].agent_ids
            for source in self.agents[agent_id].reads
        )


@lru_cache(maxsize=1)
def _tools_by_agent() -> dict[str, tuple[str, ...]]:
    """Agent id to the class names of the tools it holds, read from `tool_map`'s own source.

    `tool_map` is a local inside `get_tools_for_agent` whose values are live tool instances built
    against a project slug, so it can be neither imported nor evaluated cheaply. Calling the
    function instead would import all sixteen tool modules, and one of them is `run_crew`, whose
    description this graph is about to generate - assembly would then depend on the module that
    depends on assembly.

    Reading the assignment is the same fact at no import cost, and
    `test_tools_match_what_the_registry_actually_hands_the_agent` holds this reading against what
    the function returns at run time for every agent, so the two cannot drift apart quietly.

    Cached because the file does not change within a process; `build_graph` still returns fresh
    containers to every caller.
    """
    tree = ast.parse(_REGISTRY_SOURCE.read_text(), filename=str(_REGISTRY_SOURCE))

    literal: ast.Dict | None = None
    for node in ast.walk(tree):
        targets = (
            [node.target] if isinstance(node, ast.AnnAssign)
            else node.targets if isinstance(node, ast.Assign)
            else []
        )
        named = any(
            isinstance(t, ast.Name) and t.id == _TOOL_MAP_NAME for t in targets
        )
        if named and isinstance(node.value, ast.Dict):
            literal = node.value
            break

    if literal is None:
        raise GraphInconsistent(
            f"No `{_TOOL_MAP_NAME} = {{...}}` assignment found in {_REGISTRY_SOURCE}. "
            f"The graph reads an agent's tools from that literal; if it has been renamed or "
            f"restructured, point this reader at its new form rather than restating the map."
        )

    tools: dict[str, tuple[str, ...]] = {}
    for key, value in zip(literal.keys, literal.values):
        if not isinstance(key, ast.Constant) or not isinstance(key.value, str):
            raise GraphInconsistent(
                f"`{_TOOL_MAP_NAME}` in {_REGISTRY_SOURCE} has a key that is not a plain "
                f"string, so the agent it belongs to cannot be read."
            )
        if not isinstance(value, ast.List):
            raise GraphInconsistent(
                f"`{_TOOL_MAP_NAME}['{key.value}']` in {_REGISTRY_SOURCE} is not a list "
                f"literal, so the tools it holds cannot be read."
            )
        tools[key.value] = tuple(
            _tool_class_name(entry, key.value) for entry in value.elts
        )
    return tools


def _tool_class_name(entry: ast.expr, agent_id: str) -> str:
    """The class name of one entry in an agent's tool list."""
    func = entry.func if isinstance(entry, ast.Call) else entry
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    raise GraphInconsistent(
        f"`{_TOOL_MAP_NAME}['{agent_id}']` holds an entry that is not a tool construction, "
        f"so the tool's name cannot be read."
    )


def _build_agents(grants: frozenset[Capability]) -> dict[str, AgentNode]:
    """Every agent `AGENT_TIER` declares, with its tools, the outputs it owns, and its identity.

    `AGENT_TIER` is the roll: `test_every_dispatched_agent_has_a_tier` already holds it equal to
    `tool_map`'s keys, and that guard is the only cross-registry check the codebase had before
    this module. The equality is re-checked here as an assembly failure rather than assumed,
    because assembling from one of two maps held equal elsewhere is only safe while the other
    guard exists.
    """
    tools = _tools_by_agent()

    without_tools = sorted(set(_AGENT_TIER) - set(tools))
    without_tier = sorted(set(tools) - set(_AGENT_TIER))
    if without_tools or without_tier:
        raise GraphInconsistent(
            f"AGENT_TIER and tool_map disagree about which agents exist - "
            f"tier but no tools: {without_tools}; tools but no tier: {without_tier}. "
            f"An agent in one and not the other cannot be built: visual_illustrator was in "
            f"AGENT_TIER alone, and create_business_plan_crew raised before its first task."
        )

    unnamed = sorted(set(_AGENT_TIER) - set(_AGENT_IDENTITY))
    unknown_named = sorted(set(_AGENT_IDENTITY) - set(_AGENT_TIER))
    if unnamed or unknown_named:
        raise GraphInconsistent(
            f"AGENT_TIER and AGENT_IDENTITY disagree about which agents exist - "
            f"no identity: {unnamed}; identity but no agent: {unknown_named}. "
            f"Falling back to the id as a name is how the id becomes a label again, and an "
            f"identity for an agent that does not run is a name nothing answers to."
        )

    unknown_owners = sorted(set(_OUTPUT_OWNERS.values()) - set(_AGENT_TIER))
    if unknown_owners:
        raise GraphInconsistent(
            f"OUTPUT_OWNERS gives an output to {unknown_owners}, which no registry knows as "
            f"an agent. An output whose owner cannot run is an output nothing can write."
        )

    unread = sorted(set(_AGENT_TIER) - set(_AGENT_READS))
    reads_for_nobody = sorted(set(_AGENT_READS) - set(_AGENT_TIER))
    if unread or reads_for_nobody:
        raise GraphInconsistent(
            f"AGENT_TIER and AGENT_READS disagree about which agents exist - "
            f"no reads declared: {unread}; reads but no agent: {reads_for_nobody}. "
            f"An empty tuple is the answer for an agent that reads nothing, and two agents "
            f"have one. Defaulting a missing entry to empty would make an agent nobody has "
            f"read yet look identical to one that genuinely draws on nothing, on a page whose "
            f"whole job is to say where the client's material goes."
        )

    undeclared = sorted(
        {tool for held in tools.values() for tool in held} - set(_TOOL_EGRESS)
    )
    if undeclared:
        raise GraphInconsistent(
            f"These tools do not declare what they reach: {undeclared}. Add an entry to "
            f"TOOL_EGRESS in agents/egress.py. Assembling the graph without one would leave "
            f"the tool out of every egress set silently, and the page that answers 'what "
            f"leaves the building?' would under-report by exactly the tool nobody had read."
        )

    writes: dict[str, list[str]] = {agent_id: [] for agent_id in _AGENT_TIER}
    for output_type, owner in _OUTPUT_OWNERS.items():
        writes[owner].append(output_type)

    return {
        agent_id: AgentNode(
            agent_id=agent_id,
            tier=tier,
            tools=tools[agent_id],
            writes=tuple(writes[agent_id]),
            display_name=_AGENT_IDENTITY[agent_id].display_name,
            image=_AGENT_IDENTITY[agent_id].image,
            egress=agent_destinations(tools[agent_id], grants),
            sources=tuple(_AGENT_READS[agent_id]),
        )
        for agent_id, tier in _AGENT_TIER.items()
    }


def _build_crews(agents: dict[str, AgentNode]) -> dict[str, CrewNode]:
    """Every crew, with its agents and the crews it waits on.

    Two hand-maintained maps describe the same set of crews. A crew in one and not the other is
    either undispatchable or unschedulable, and both are silent conditions today, so the
    disagreement is raised rather than papered over by a union or an intersection.
    """
    undeclared_deps = sorted(set(_CREW_AGENT_NAMES) - set(_CREW_DEPENDENCIES))
    undispatchable = sorted(set(_CREW_DEPENDENCIES) - set(_CREW_AGENT_NAMES))
    if undeclared_deps or undispatchable:
        raise GraphInconsistent(
            f"_CREW_AGENT_NAMES and CREW_DEPENDENCIES disagree about which crews exist - "
            f"agents but no dependencies: {undeclared_deps}; dependencies but no agents: "
            f"{undispatchable}. A crew with no agent list dispatches nothing; a crew with no "
            f"dependency entry is never released by a commit."
        )

    broken = {
        crew_id: sorted(set(agent_ids) - set(agents))
        for crew_id, agent_ids in _CREW_AGENT_NAMES.items()
        if set(agent_ids) - set(agents)
    }
    if broken:
        raise GraphInconsistent(
            f"A crew names an agent no registry knows: {broken}. Dropping the edge is what "
            f"this graph replaces - build_and_run_crew answers an unknown name with an empty "
            f"string, so the dispatch that did nothing reports as a result."
        )

    unlabelled = sorted(set(_CREW_AGENT_NAMES) - set(_CREW_LABEL))
    unknown_labelled = sorted(set(_CREW_LABEL) - set(_CREW_AGENT_NAMES))
    if unlabelled or unknown_labelled:
        raise GraphInconsistent(
            f"_CREW_AGENT_NAMES and CREW_LABEL disagree about which crews exist - "
            f"no label: {unlabelled}; label but no crew: {unknown_labelled}. Falling back to "
            f"the id would show `discovery_mapping` where a reader expects Value Chain "
            f"Mapping, and a label for a crew nothing dispatches is a row that never fills."
        )

    uncharted = sorted(set(_CREW_AGENT_NAMES) - set(_CREW_CHARTER))
    charter_for_nobody = sorted(set(_CREW_CHARTER) - set(_CREW_AGENT_NAMES))
    if uncharted or charter_for_nobody:
        raise GraphInconsistent(
            f"_CREW_AGENT_NAMES and CREW_CHARTER disagree about which crews exist - "
            f"no purpose or triggers declared: {uncharted}; charter but no crew: "
            f"{charter_for_nobody}. There is no default for either: an empty purpose is a blank "
            f"row on the page a client is shown, and an empty trigger set says a crew cannot be "
            f"started, which of a crew nobody has read yet is a guess rather than an answer."
        )

    return {
        crew_id: CrewNode(
            crew_id=crew_id,
            agent_ids=tuple(_CREW_AGENT_NAMES[crew_id]),
            depends_on=tuple(_CREW_DEPENDENCIES[crew_id]),
            display_name=_CREW_LABEL[crew_id],
            purpose=_CREW_CHARTER[crew_id].purpose,
            triggers=tuple(_CREW_CHARTER[crew_id].triggers),
            cluster=_CREW_CHARTER[crew_id].cluster,
            note=_CREW_CHARTER[crew_id].note,
            defect=_CREW_CHARTER[crew_id].defect,
        )
        for crew_id in _runnable_order()
    }


def _tool_dispatched_triggers() -> dict[Trigger, str]:
    """The triggers an agent takes by holding a tool, and the tool class that is that trigger.

    `DispatchPath.entrypoint` is `module.py:Symbol`. Two of the three paths name a function in
    a router; one names `RunCrewTool`, a tool class - and an agent takes that path by holding
    it. That is the only link between an agent and a dispatch path anywhere in the
    declarations, and it is what lets `Cluster.orchestrator` be checked rather than believed.

    A symbol is read as a tool when `TOOL_EGRESS` declares it, which is the roll of tools; a
    router function is not in it and so cannot be mistaken for one.
    """
    return {
        trigger: path.entrypoint.split(":")[-1]
        for trigger, path in _DISPATCH_PATHS.items()
        if path.entrypoint.split(":")[-1] in _TOOL_EGRESS
    }


def _build_clusters(
    agents: dict[str, AgentNode], crews: dict[str, CrewNode]
) -> dict[str, ClusterNode]:
    """Every cluster `CLUSTERS` declares, with the crews whose charters name it.

    Membership is inverted from the crews rather than read from the cluster, so there is one
    declaration of it and the two halves cannot drift - the same reason `AgentNode.writes` is
    `OUTPUT_OWNERS` inverted rather than a second list.

    Four disagreements are raised rather than tolerated, and each is a picture that would draw
    itself wrongly rather than fail:

    - A crew naming a cluster nothing declares would vanish from every cluster and from the
      ring drawn around one, while still appearing in the crew table - the view silently
      shorter than the tables it is meant to summarise.
    - A cluster with no crews is a centre with nothing around it.
    - An orchestrator no registry knows as an agent is a centre with no name, tier or egress.
    - An orchestrator that runs inside one of its own crews is both the centre and a point on
      the circle.

    A fifth is derived rather than declared: an orchestrator that can start none of its own
    crews. `dispatches` is what the orchestrator can itself reach, and a cluster where that is
    empty is one whose centre is decorative - so `CLUSTERS` cannot assert an ownership the
    dispatch paths do not support.
    """
    bands = _runnable_bands()
    unknown = sorted({crew.cluster for crew in crews.values()} - set(_CLUSTERS))
    if unknown:
        raise GraphInconsistent(
            f"A crew names a cluster that agents/clusters.py does not declare: {unknown}. "
            f"A crew in no cluster has no orchestrator, and would be missing from any view "
            f"drawn per cluster while still appearing in the crew table."
        )

    # A cluster's bands are the graph's bands with everyone else's crews taken out. A band that
    # holds none of this cluster's crews is dropped rather than kept empty: it is a moment when
    # this orchestrator has nothing to run, which is a fact about another cluster and would
    # otherwise put a gap in this one's ring.
    members: dict[str, list[tuple[str, ...]]] = {cluster_id: [] for cluster_id in _CLUSTERS}
    for band in bands:
        for cluster_id in _CLUSTERS:
            held = tuple(c for c in band if crews[c].cluster == cluster_id)
            if held:
                members[cluster_id].append(held)

    empty = sorted(cluster_id for cluster_id, held in members.items() if not held)
    if empty:
        raise GraphInconsistent(
            f"These clusters own no crew: {empty}. A cluster is an orchestrator and the crews "
            f"it owns; one with no crews is a centre with nothing around it, and naming it "
            f"would put an empty ring on the page."
        )

    unknown_orchestrators = sorted(
        cluster.orchestrator for cluster in _CLUSTERS.values()
        if cluster.orchestrator not in agents
    )
    if unknown_orchestrators:
        raise GraphInconsistent(
            f"A cluster names an orchestrator no registry knows as an agent: "
            f"{unknown_orchestrators}. The orchestrator is drawn like any other agent - name, "
            f"tier and everywhere its work reaches - and none of that exists for an id "
            f"AGENT_TIER has never heard of."
        )

    orchestrators = [cluster.orchestrator for cluster in _CLUSTERS.values()]
    if len(set(orchestrators)) != len(orchestrators):
        raise GraphInconsistent(
            f"One agent orchestrates more than one cluster: {sorted(orchestrators)}. An agent "
            f"is drawn once, at one centre, so two clusters sharing an orchestrator is one "
            f"cluster whose crews have been split in two."
        )

    by_tool = _tool_dispatched_triggers()
    nodes: dict[str, ClusterNode] = {}
    for cluster_id, cluster in _CLUSTERS.items():
        crew_bands = tuple(members[cluster_id])
        crew_ids = tuple(crew_id for band in crew_bands for crew_id in band)
        inside = [c for c in crew_ids if cluster.orchestrator in crews[c].agent_ids]
        if inside:
            raise GraphInconsistent(
                f"Cluster '{cluster_id}' is orchestrated by '{cluster.orchestrator}', who also "
                f"runs inside {inside}. An orchestrator dispatches its crews rather than "
                f"working in them, and one that is both the centre and a point on its own ring "
                f"cannot be placed."
            )
        held = set(agents[cluster.orchestrator].tools)
        dispatches = tuple(
            crew_id for crew_id in crew_ids
            if any(by_tool.get(t) in held for t in crews[crew_id].triggers)
        )
        if not dispatches:
            raise GraphInconsistent(
                f"Cluster '{cluster_id}' is orchestrated by '{cluster.orchestrator}', who can "
                f"start none of {list(crew_ids)}: no crew declares a trigger whose entrypoint "
                f"is a tool that agent holds. Ownership the dispatch paths do not support is a "
                f"centre nothing radiates from."
            )
        nodes[cluster_id] = ClusterNode(
            cluster_id=cluster_id,
            label=cluster.label,
            orchestrator_id=cluster.orchestrator,
            note=cluster.note,
            crew_bands=crew_bands,
            dispatches=dispatches,
        )
    return nodes


def _build_edges(graph: Graph) -> tuple[CrewEdge, ...]:
    """Every relationship between two crews, derived from the writes, the reads and the order.

    Three kinds fall out of two questions asked of every ordered pair - does the target wait on
    the source, and does the target read anything the source wrote - and the pair that answers
    no to both is not an edge at all.

    Emitted in the graph's own topological order, source then target, so the same declarations
    produce the same tuple in the same order on every call. A viewer that drew edges in
    dictionary-iteration order would be stable only by accident.
    """
    order = list(graph.crews)
    position = {crew_id: index for index, crew_id in enumerate(order)}
    edges: list[CrewEdge] = []
    for target in order:
        node = graph.crews[target]
        reads = graph.crew_reads(target)
        candidates = sorted(
            set(node.depends_on) | {
                source for source in order
                if source != target and graph.crew_writes(source) & reads
            },
            key=lambda crew_id: position[crew_id],
        )
        for source in candidates:
            artefacts = tuple(sorted(graph.crew_writes(source) & reads))
            declared = source in node.depends_on
            if declared:
                kind = EdgeKind.INFORMATION if artefacts else EdgeKind.SEQUENCING
            else:
                kind = EdgeKind.INHERITED
            edges.append(
                CrewEdge(
                    source=source,
                    target=target,
                    kind=kind,
                    artefacts=artefacts,
                    declared=declared,
                    crosses_clusters=node.cluster != graph.crews[source].cluster,
                )
            )
    return tuple(edges)


def _runnable_bands() -> tuple[tuple[str, ...], ...]:
    """The crews in bands: everything in one band could run the moment the band above commits.

    Kahn's algorithm, keeping each round rather than flattening it. A round is exactly the set
    of crews whose every upstream is already behind them, which is the definition of work that
    can proceed in parallel - so the bands are not a second computation beside the order, they
    are the shape the order was always being read out of.

    Within a band the order is the order `_CREW_AGENT_NAMES` declares them rather than
    alphabetical - the declaration is a human's reading of the pipeline - but it is an order
    only in the sense that a list has one. Two crews in a band wait on nothing of each other's,
    and anything drawing them must say so.

    A cycle is raised rather than truncated. `crew_graph.py` releases a crew when its
    upstreams are committed, so a cycle is a set of crews none of which can ever start - and
    a partial order would hide most of them from the board instead of naming the problem.
    """
    remaining = {crew_id: set(_CREW_DEPENDENCIES[crew_id]) for crew_id in _CREW_AGENT_NAMES}
    ordered: list[str] = []
    bands: list[tuple[str, ...]] = []
    while remaining:
        ready = [crew_id for crew_id in remaining if not remaining[crew_id] - set(ordered)]
        if not ready:
            stuck = {
                crew_id: sorted(deps - set(ordered)) for crew_id, deps in remaining.items()
            }
            raise GraphInconsistent(
                f"No crew in {sorted(remaining)} can ever be released by a commit - each is "
                f"still waiting: {stuck}. Either CREW_DEPENDENCIES has a cycle, or one of "
                f"these waits on a crew that is never committed because it does not exist."
            )
        bands.append(tuple(ready))
        for crew_id in ready:
            ordered.append(crew_id)
            del remaining[crew_id]
    return tuple(bands)


def _runnable_order() -> tuple[str, ...]:
    """The crews arranged so none precedes a crew it waits on - the bands, flattened.

    Derived from `_runnable_bands` rather than computed beside it, so the table's order and
    the picture's bands cannot answer the same question differently. Deterministic, which
    matters because this order is displayed.
    """
    return tuple(crew_id for band in _runnable_bands() for crew_id in band)


def build_graph(grants: frozenset[Capability] = ALL_GRANTS) -> Graph:
    """Assemble the graph, raising `GraphInconsistent` on any edge that does not resolve.

    Fresh containers each call, so a caller that mutates what it is given cannot corrupt the
    next reader. Assembly is cheap - the only file read is cached.

    `grants` decides only where each agent's egress resolves to; everything else in the graph is
    the same for every project. It is the resolved capability set rather than a mode name or a
    slug, for the reason `agents/egress.py` gives at length: a mode is not the last word once a
    project can narrow what its mode grants, and a slug would put a database read inside a
    declaration. Resolve it with `api.services.deployment_modes.project_grants(slug)`.

    It defaults to `ALL_GRANTS` deliberately, and the direction matters. Every grant held
    resolves both gated reaches to their off-premises destinations, so a caller that forgets the
    argument over-reports what leaves the building and never under-reports it - the safe way
    round for a page an auditor reads. It used to default to `"standard"`, which was the same
    answer only for as long as `standard` remained the fullest mode; the fullest set is now the
    default by construction. Enforcement should still pass the project's real grants.
    """
    agents = _build_agents(grants)
    crews = _build_crews(agents)
    graph = Graph(
        agents=agents,
        crews=crews,
        clusters=_build_clusters(agents, crews),
        edges=(),
    )
    # Assembled in two steps so that edge derivation asks the graph its own questions -
    # `crew_writes` and `crew_reads` - rather than a private pair of helpers computing the same
    # intersection beside them. There is one definition of what a crew writes and one of what it
    # reads, and the picture and the tables are both drawn from it.
    return replace(graph, edges=_build_edges(graph))


# Assembled once at import so that a disagreement between the six registries is a loud failure
# where a developer meets it, rather than a quiet gap in whatever reads the graph later.
GRAPH = build_graph()
