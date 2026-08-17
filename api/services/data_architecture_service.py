# api/services/data_architecture_service.py
"""The data-architecture answer for one project, assembled from the declarations.

`ui/src/pages/DataArchitecture.tsx` is the page that answers "where does our material go?".
It was hand-typed, and it had drifted: it named Anthropic forty-four times and Tavily
seventeen, listed "Web fetch" as a tool while giving it no destination anywhere, showed a crew
called "Discovery" that has not existed for two sprints, and named seventeen personas in a list
of its own. This module is what the page reads instead, so that a change to a declaration is a
change to the page.

**Everything here is read, nothing is declared.** `agents/egress.py` owns what a tool reaches
and where that resolves to; `agents/reads.py` owns what an agent draws on; `agents/charter.py`
owns what a crew is for and what can start it; `agents/graph.py` assembles the three. The only
things this module adds are the joins the page needs - which agents hold a tool, which crews an
agent runs in - and each of those is computed from the graph rather than typed.

## The project's mode is read, never taken from the caller

`build_graph(llm_mode)` resolves the two mode-dependent reaches, and the mode comes from
`project_llm_mode(slug)`. CLAUDE.md is emphatic that nothing may hand a mode down a routing
path, and while this is a reading rather than a route, taking a mode from a query parameter
would let a page be shown a reassuring answer that no run would ever produce.

## Three things this page must not say, and how each is prevented here

- **It must not present nine crews as everything that runs.** PAM's own two crews -
  `create_pam_mapping_crew` and `create_pam_resume_crew` - are built by
  `api/services/orchestration_service.py` and are in no registry the graph reads, so the graph
  has nine crews while the deployment runs eleven, and `pam` is consequently the one agent in
  no crew. `scope` below carries that fact **derived** - the agents the graph places in no crew
  - rather than as a sentence somebody might forget to update, and the page states it.
- **It must not imply the Chainlit review channel is live.** `ChainlitHumanInputTool` is
  declared in `TOOL_EGRESS` and held by no agent in `tool_map`; its only caller sits in a
  Chainlit handler whose every branch fails. It therefore appears under `declared_not_held`,
  which the page renders as exactly that, rather than in the table of what this project reaches.
- **It must not let `sector_{sector}` read as project-scoped.** That collection carries no slug
  and six agents read it, so it is one store shared by every engagement in the sector.
  `shared_beyond_this_project` is set structurally - a vector collection whose name template
  has no `{slug}` in it - and the page badges it.

`Trigger` is not an access-control statement, and nothing here presents it as one. The charter
says what **can** start a crew, not who may; the two REST doors differ in authority from the
approval door, and that authority lives in `api/auth.py`, not in this graph.
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

from agents.charter import DISPATCH_PATHS
from agents.egress import (
    INFERENCE_EGRESS,
    TOOL_EGRESS,
    inference_destination,
    is_gated_by_mode,
    resolve_egress,
)
from agents.graph import build_graph
from agents.reads import CREW_DISPATCH_READS, Medium, Read, VIA_DISPATCH
from api.services.chroma_client import project_llm_mode

_RUN_SERVICE_SOURCE = Path(__file__).parent / "run_service.py"

# A dispatch path folds `CREW_DISPATCH_READS` into every task description only if it reaches
# `build_and_run_crew`. Two of the four paths name it directly (`VIA_DISPATCH` is that name, and
# it is the `via` every one of those six reads already declares); two name `dispatch_crew`, which
# is a wrapper around it. The wrapper is the one link that cannot be read off a declaration, so
# `test_dispatch_crew_still_reaches_build_and_run_crew` parses the function and fails if it ever
# stops calling it - rather than this pair quietly meaning something different.
_DISPATCH_WRAPPER = "dispatch_crew"


def dispatch_wrapper_reaches_build_and_run_crew() -> bool:
    """Whether `dispatch_crew`'s body still calls `build_and_run_crew`.

    Parsed rather than imported, for `agents/graph.py`'s reason: importing `run_service` pulls
    in the crew factories. Exported so the guard asserts the same reading this module uses.
    """
    tree = ast.parse(_RUN_SERVICE_SOURCE.read_text(), filename=str(_RUN_SERVICE_SOURCE))
    for node in ast.walk(tree):
        is_wrapper = (
            isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name == _DISPATCH_WRAPPER
        )
        if is_wrapper:
            return any(
                isinstance(call, ast.Call)
                and getattr(call.func, "id", getattr(call.func, "attr", None)) == VIA_DISPATCH
                for call in ast.walk(node)
            )
    return False


def _injecting_dispatchers() -> frozenset[str]:
    wrappers = {_DISPATCH_WRAPPER} if dispatch_wrapper_reaches_build_and_run_crew() else set()
    return frozenset({VIA_DISPATCH} | wrappers)


_DATABASE_SOURCE = Path(__file__).parent.parent / "database.py"
_CREATE_TABLE = re.compile(r"CREATE TABLE IF NOT EXISTS\s+(\w+)", re.IGNORECASE)


def system_database_tables() -> frozenset[str]:
    """Every table `init_system_db` creates, read from the source.

    The system database is the deployment's, not a project's: `users`, the organisations, the
    skills library. A table in it is shared by every engagement on the server, and two of them
    are read on every agent's behalf. Parsed rather than opened, because the answer must not
    depend on which databases happen to exist on the machine rendering the page - and parsed
    rather than declared, because a hand-kept list of "the shared tables" is precisely the kind
    of copy that goes quietly out of date beside the schema it describes.
    """
    tree = ast.parse(_DATABASE_SOURCE.read_text(), filename=str(_DATABASE_SOURCE))
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == "init_system_db":
            return frozenset(
                name
                for literal in ast.walk(node)
                if isinstance(literal, ast.Constant) and isinstance(literal.value, str)
                for name in _CREATE_TABLE.findall(literal.value)
            )
    return frozenset()


def is_shared_beyond_one_project(read: Read) -> bool:
    """Whether this source holds more than this engagement's material.

    Asked of **every** medium, not only of collections. The first version of this asked it of
    `Medium.VECTOR_COLLECTION` alone, so `agent_skill_notes` and `skills` - which are in the
    system database, are global across engagements, and are folded into every agent's
    instructions on every crew run - could never earn the badge whatever they were called. The
    page's sharing panel is where a reader goes with exactly that question, and it could not
    answer it for the two stores that most needed answering.

    There is no one predicate across the media, because a source's name is only meaningful
    inside its own namespace: a collection's name is built from the slug and the sector, a
    table's name says nothing at all and its database is what places it. So each medium is
    asked in its own terms and every medium is asked:

    - `VECTOR_COLLECTION` - shared when the name template carries no `{slug}`.
    - `DATABASE_TABLE` - shared when `init_system_db` creates it, read off the schema.
    - `ARTEFACT_JSON` and `UPLOADED_DOCUMENT` - never shared: both resolve under
      `projects/{slug}/`, so the slug is in the path rather than in the name.
    """
    if read.medium is Medium.VECTOR_COLLECTION:
        return "{slug}" not in read.source
    if read.medium is Medium.DATABASE_TABLE:
        return read.source in system_database_tables()
    return False


def _read(read: Read) -> dict:
    return {
        "source": read.source,
        "medium": read.medium.value,
        "via": read.via,
        "note": read.note,
        "shared_beyond_this_project": is_shared_beyond_one_project(read),
    }


def _shared_sources(graph) -> list[dict]:
    """Every source that is not this project's alone, whoever reaches it.

    One entry per source, not per reader: the point of the panel it feeds is that the store is
    shared, and repeating it under each reader would bury that under the readers.

    `CREW_DISPATCH_READS` is walked alongside the agents' own sources. Those six tables reach
    an agent without any agent asking, so a walk over `AGENT_READS` alone leaves the two shared
    ones out of the panel entirely - which is how the system database's global skills library
    came to appear only inside a note, several sections below the panel a reader consults for
    this exact question.

    `reachable_by` is the finding the declared list cannot carry. `AGENT_READS` says which
    agents are *instructed* to read a collection; `ChromaQueryTool` takes the collection as an
    argument, so any agent holding it can query any collection it names - and the sector store
    is the tool's fallback for an unrecognised value rather than a special case. Derived from
    the route: whoever holds the tool the read arrives through.
    """
    holders: dict[str, list[str]] = {}
    for node in graph.agents.values():
        for tool in node.tools:
            holders.setdefault(tool, []).append(node.display_name)

    rows: dict[tuple[str, str, str], set[str]] = {}
    for node in graph.agents.values():
        for source in node.sources:
            if is_shared_beyond_one_project(source):
                rows.setdefault(
                    (source.source, source.medium.value, source.via), set()
                ).add(node.display_name)
    for read in CREW_DISPATCH_READS:
        if is_shared_beyond_one_project(read):
            rows.setdefault((read.source, read.medium.value, read.via), set())

    return sorted(
        (
            {
                "source": source,
                "medium": medium,
                "via": via,
                "read_by": sorted(read_by),
                "reachable_by": sorted(holders.get(via, [])),
                "handed_to_every_agent": via == VIA_DISPATCH,
            }
            for (source, medium, via), read_by in rows.items()
        ),
        key=lambda row: row["source"],
    )


def _tool_row(tool: str, llm_mode: str, held_by: list[str]) -> dict:
    destination = resolve_egress(tool, llm_mode)
    return {
        "tool": tool,
        "reaches": TOOL_EGRESS[tool].reaches.value,
        "sends": TOOL_EGRESS[tool].sends,
        "destination": destination.label,
        "leaves_deployment": destination.leaves_deployment,
        "gated_by_mode": is_gated_by_mode(tool),
        "held_by": held_by,
    }


def data_architecture(slug: str) -> dict:
    """Everything the privacy page renders, resolved for this project's own mode."""
    llm_mode = project_llm_mode(slug)
    graph = build_graph(llm_mode)

    crews_of: dict[str, list[str]] = {agent_id: [] for agent_id in graph.agents}
    for crew in graph.crews.values():
        for agent_id in crew.agent_ids:
            crews_of[agent_id].append(crew.display_name)

    holders: dict[str, list[str]] = {}
    for node in graph.agents.values():
        for tool in node.tools:
            holders.setdefault(tool, []).append(node.display_name)

    inference = inference_destination(llm_mode)

    return {
        "slug": slug,
        "llm_mode": llm_mode,
        "inference": {
            "reaches": INFERENCE_EGRESS.reaches.value,
            "sends": INFERENCE_EGRESS.sends,
            "destination": inference.label,
            "leaves_deployment": inference.leaves_deployment,
            # Every agent runs on a model, so this is gated on the project's mode by
            # construction rather than by a lookup - `inference_destination` is the same
            # `(reach, mode)` table `resolve_egress` reads, and the two entries differ.
            "gated_by_mode": (
                inference_destination("standard") != inference_destination("sensitive")
            ),
        },
        # What leaves the building first, then alphabetically: an auditor reads this table for
        # the egress, and a stable order keeps a re-read comparable.
        "tools": sorted(
            (
                _tool_row(tool, llm_mode, sorted(held_by))
                for tool, held_by in holders.items()
            ),
            key=lambda row: (not row["leaves_deployment"], row["tool"]),
        ),
        # Declared, and held by nobody. Rendered so the page cannot be read as claiming a tool
        # is in use, and cannot silently drop one either.
        #
        # "Held by nobody" is read off `tool_map`'s source, which by construction cannot see the
        # one substitution that happens at run time: `get_tools_for_agent` swaps
        # `ChainlitHumanInputTool` in for every `HumanInputTool` when the Chainlit app passes
        # `hitl_tool`. That is sound today only because the Chainlit path can start nothing -
        # all five of its branches raise - and it is `tests/test_crew_charter.py`'s
        # `CHAINLIT_CONSOLE` defect guard that keeps it so: the guard derives the breakage from
        # the call sites and the factory signatures, so repairing any branch fails it. Whoever
        # repairs one must make this page stop saying "nothing here is in use" in the same
        # change. The dependency is one-way and invisible from here, hence this note.
        "declared_not_held": sorted(
            (
                {
                    "tool": tool,
                    "reaches": TOOL_EGRESS[tool].reaches.value,
                    "sends": TOOL_EGRESS[tool].sends,
                    "destination": resolve_egress(tool, llm_mode).label,
                }
                for tool in set(TOOL_EGRESS) - set(holders)
            ),
            key=lambda row: row["tool"],
        ),
        "agents": [
            {
                "agent_id": node.agent_id,
                "display_name": node.display_name,
                "tier": node.tier,
                "crews": crews_of[node.agent_id],
                "tools": list(node.tools),
                "writes": list(node.writes),
                "destinations": [
                    {"label": d.label, "leaves_deployment": d.leaves_deployment}
                    for d in node.egress
                ],
                "sources": [_read(source) for source in node.sources],
            }
            for node in graph.agents.values()
        ],
        "crews": [
            {
                "crew_id": crew.crew_id,
                "display_name": crew.display_name,
                "purpose": crew.purpose,
                "note": crew.note,
                "defect": crew.defect,
                "depends_on": [graph.crews[dep].display_name for dep in crew.depends_on],
                "agents": [graph.agents[a].display_name for a in crew.agent_ids],
                "triggers": [DISPATCH_PATHS[t].label for t in crew.triggers],
            }
            for crew in graph.crews.values()
        ],
        "dispatch_paths": [
            {
                "trigger": path.trigger.value,
                "label": path.label,
                "note": path.note,
                "defect": path.defect,
                "injects_dispatch_reads": path.dispatcher in _injecting_dispatchers(),
            }
            for path in DISPATCH_PATHS.values()
        ],
        "dispatch_reads": [_read(read) for read in CREW_DISPATCH_READS],
        # Lifted to the top level as well as sitting on each agent, because a badge on row
        # eleven of a per-agent list is not where a reader learns that a store is not theirs
        # alone. Derived from the same predicate, so the two cannot say different things.
        "shared_sources": _shared_sources(graph),
        "scope": {
            "crew_count": len(graph.crews),
            "agents_in_no_crew": [
                {"agent_id": agent_id, "display_name": graph.agents[agent_id].display_name}
                for agent_id, crews in crews_of.items()
                if not crews
            ],
        },
    }
