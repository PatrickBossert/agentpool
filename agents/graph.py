# agents/graph.py
"""One graph of the agents and crews, assembled from the registries that already hold them.

Nothing here is declared. Every fact is read from the one place that owns it:

| Fact | Source |
|------|--------|
| Which agents exist, and each one's tier | `AGENT_TIER` - `agents/model_registry.py` |
| What an agent is called, and its face | `AGENT_IDENTITY` - `agents/identity.py` |
| Which tools an agent holds | `tool_map` - `agents/tools/registry.py` |
| Which output types an agent writes | `OUTPUT_OWNERS` inverted - `agents/tools/ownership.py` |
| Which agents a crew dispatches | `_CREW_AGENT_NAMES` - `api/services/run_service.py` |
| What a crew is called | `CREW_LABEL` - `agents/identity.py` |
| What a crew waits on | `CREW_DEPENDENCIES` - `api/services/crew_graph.py` |

A literal list of agent names or crew names in this file would make it one more restatement of
what those six already say, which is the thing it exists to end - the slice that built this
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
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from agents.identity import AGENT_IDENTITY as _AGENT_IDENTITY
from agents.identity import CREW_LABEL as _CREW_LABEL
from agents.model_registry import AGENT_TIER as _AGENT_TIER
from agents.tools.ownership import OUTPUT_OWNERS as _OUTPUT_OWNERS
from api.services.crew_graph import CREW_DEPENDENCIES as _CREW_DEPENDENCIES
from api.services.run_service import _CREW_AGENT_NAMES

# The six sources are bound to module-level names above so that this module is the single place
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
    """

    agent_id: str
    tier: str
    tools: tuple[str, ...]
    writes: tuple[str, ...]
    display_name: str
    image: str | None


@dataclass(frozen=True)
class CrewNode:
    """One crew: who runs in it, what it is called, and what must be committed before it runs.

    `crew_id` is the permanent half - `crew_runs.crew_name` stores it and PAM dispatches by it.
    `display_name` is the mutable half, resolved through `CREW_LABEL`, and is not derivable
    from the id: `discovery_mapping` reads as "Value Chain Mapping".
    """

    crew_id: str
    agent_ids: tuple[str, ...]
    depends_on: tuple[str, ...]
    display_name: str


@dataclass(frozen=True)
class Graph:
    """The assembled whole, keyed by id in both directions.

    `crews` is ordered so that no crew precedes one it waits on, which is what makes
    `list(graph.crews)` a display order as well as a lookup. Iterating it is the reason
    nothing needs a hand-typed `CREW_ORDER`: an order typed beside the dependency map can
    contradict it, and did - a crew shown as next while the graph would refuse to run it.
    """

    agents: dict[str, AgentNode]
    crews: dict[str, CrewNode]


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


def _build_agents() -> dict[str, AgentNode]:
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

    return {
        crew_id: CrewNode(
            crew_id=crew_id,
            agent_ids=tuple(_CREW_AGENT_NAMES[crew_id]),
            depends_on=tuple(_CREW_DEPENDENCIES[crew_id]),
            display_name=_CREW_LABEL[crew_id],
        )
        for crew_id in _runnable_order()
    }


def _runnable_order() -> tuple[str, ...]:
    """The crews arranged so none precedes a crew it waits on.

    Kahn's algorithm, with ties broken by the order `_CREW_AGENT_NAMES` declares them rather
    than alphabetically - the declaration is a human's reading of the pipeline, and today's
    dependencies happen to admit exactly one order anyway, so the tie-break only decides what
    a future fork looks like. Deterministic either way, which matters because this order is
    displayed.

    A cycle is raised rather than truncated. `crew_graph.py` releases a crew when its
    upstreams are committed, so a cycle is a set of crews none of which can ever start - and
    a partial order would hide most of them from the board instead of naming the problem.
    """
    remaining = {crew_id: set(_CREW_DEPENDENCIES[crew_id]) for crew_id in _CREW_AGENT_NAMES}
    ordered: list[str] = []
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
        for crew_id in ready:
            ordered.append(crew_id)
            del remaining[crew_id]
    return tuple(ordered)


def build_graph() -> Graph:
    """Assemble the graph, raising `GraphInconsistent` on any edge that does not resolve.

    Fresh containers each call, so a caller that mutates what it is given cannot corrupt the
    next reader. Assembly is cheap - the only file read is cached.
    """
    agents = _build_agents()
    return Graph(agents=agents, crews=_build_crews(agents))


# Assembled once at import so that a disagreement between the six registries is a loud failure
# where a developer meets it, rather than a quiet gap in whatever reads the graph later.
GRAPH = build_graph()
