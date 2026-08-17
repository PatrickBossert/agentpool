# tests/test_no_restated_crew_maps.py
"""Which agents a crew runs is declared in one place. A second copy is how the drift starts.

Research for this slice found nine crew-to-agent maps across the codebase, five of them stale,
and every stale one failed silently rather than loudly:

- `agents/tools/_db.py` still named `discovery` and `architecture`, so a reviewer's revision
  note never reached `requirements` or `capabilities`.
- `api/services/pam_report_service.py` listed the same two dead crews and neither live one, so
  four agents' work was missing from Pamela's report.
- `api/database.py` covered fifteen of seventeen agents, so reverting the Illustrator's brief
  dismissed no review and the board stayed blocked.
- `RunCrewTool`'s description offered PAM two crews that do not exist, and `build_and_run_crew`
  answers an unknown crew name with an empty string.

This module walks the importable modules of `api/` and `agents/`, looks at the objects they
actually hold, and fails on any dict that maps a crew to its agents or an agent to its crew.
It reads values, not source text: a grep guard breaks on a reformatting and passes on a rename.
"""
from __future__ import annotations

import importlib
import pkgutil
from pathlib import Path

import pytest

from agents.graph import build_graph

REPO = Path(__file__).resolve().parent.parent

# The two declarations that are allowed to exist, and why.
#
# An allowlist rather than a name filter, because "it is called _CREW_AGENT_NAMES" is exactly
# what a tenth copy would also be called. Each entry is a decision on the record; a new one
# has to be argued for rather than typed.
PERMITTED: dict[tuple[str, str], str] = {
    # The source of record. Everything else reads the graph, which reads this.
    ("api.services.run_service", "_CREW_AGENT_NAMES"): "the one declaration",
    # Bound into the graph so the graph is the single place the name is looked up. Same
    # object, not a copy - asserted below.
    ("agents.graph", "_CREW_AGENT_NAMES"): "the graph's reference to the declaration",
    # Derived by inverting the declaration at import, restricted to the agents that may be
    # dispatched alone. test_standalone_agent_dispatch.py holds it against the graph.
    ("api.services.run_service", "AGENT_CREW_NAME"): "derived from the declaration",
}


def _modules() -> list[str]:
    """Every importable module under `api/` and `agents/`."""
    names: list[str] = []
    for package in ("api", "agents"):
        for info in pkgutil.walk_packages([str(REPO / package)], prefix=f"{package}."):
            names.append(info.name)
    return sorted(names)


def _importable() -> list[object]:
    modules = []
    for name in _modules():
        try:
            modules.append(importlib.import_module(name))
        except Exception:
            # A module that will not import cannot be holding a live copy of the map either.
            # Recorded as a count below so this cannot quietly swallow the whole codebase.
            continue
    return modules


CREW_IDS = frozenset(build_graph().crews)
AGENT_IDS = frozenset(build_graph().agents)


def _is_crew_to_agents(value: object) -> bool:
    """A mapping from a crew this project runs to a collection naming its agents."""
    if not isinstance(value, dict) or not value:
        return False
    if not any(key in CREW_IDS for key in value if isinstance(key, str)):
        return False
    return any(
        isinstance(members, (list, tuple, set, frozenset))
        and any(member in AGENT_IDS for member in members if isinstance(member, str))
        for members in value.values()
    )


def _is_agent_to_crew(value: object) -> bool:
    """A mapping from an agent to the crew it runs in - the same fact, inverted."""
    if not isinstance(value, dict) or not value:
        return False
    return any(
        isinstance(key, str) and key in AGENT_IDS
        and isinstance(crew, str) and crew in CREW_IDS
        for key, crew in value.items()
    )


def _declarations() -> list[tuple[str, str]]:
    found = []
    for module in _importable():
        for attribute, value in vars(module).items():
            if _is_crew_to_agents(value) or _is_agent_to_crew(value):
                found.append((module.__name__, attribute))
    return sorted(set(found))


def test_the_walk_actually_imports_the_codebase():
    """Guard the guard. An import sweep that silently caught everything would make the test
    below pass by finding nothing at all, which is the shape of a vacuous pass."""
    assert len(_importable()) > 60, "the module walk is importing almost nothing"
    assert ("api.services.run_service", "_CREW_AGENT_NAMES") in _declarations(), (
        "the detector does not even find the declaration it is built around"
    )


def test_no_module_declares_its_own_crew_to_agent_map():
    """The graph is the only place this mapping lives. A second copy is how RunCrewTool came
    to name two crews that do not exist."""
    unexpected = [where for where in _declarations() if where not in PERMITTED]
    assert not unexpected, (
        f"{len(unexpected)} module-level maps restate which agents a crew runs: "
        f"{unexpected}. Read `agents.graph.GRAPH` instead - every copy this slice deleted "
        f"had drifted, and each one failed silently rather than raising."
    )


def test_the_graph_holds_the_declaration_itself_and_not_a_copy():
    """The one permitted duplicate name is permitted because it is the same object. A copy
    taken at import would satisfy the allowlist while being free to diverge."""
    import agents.graph as graph_module
    import api.services.run_service as run_service

    assert graph_module._CREW_AGENT_NAMES is run_service._CREW_AGENT_NAMES


@pytest.mark.parametrize("where", sorted(PERMITTED))
def test_every_permitted_declaration_still_exists(where):
    """An allowlist that has rotted is an allowlist that excuses nothing and hides the fact.
    If one of these is gone, the entry should go with it rather than sit there unread."""
    module_name, attribute = where
    assert hasattr(importlib.import_module(module_name), attribute), (
        f"{module_name}.{attribute} is allowlisted and no longer exists"
    )
