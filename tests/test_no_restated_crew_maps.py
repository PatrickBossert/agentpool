# tests/test_no_restated_crew_maps.py
"""Which agents a crew runs is declared in one place. A second copy is how the drift starts.

This branch deleted ten crew-to-agent maps, five of them stale, and every stale one failed
silently rather than loudly:

- `agents/tools/_db.py` still named `discovery` and `architecture`, so a reviewer's revision
  note never reached `requirements` or `capabilities`.
- `api/services/pam_report_service.py` listed the same two dead crews and neither live one, so
  four agents' work was missing from Pamela's report.
- `api/database.py` covered fifteen of seventeen agents, so reverting the Illustrator's brief
  dismissed no review and the board stayed blocked.
- `RunCrewTool`'s description offered PAM two crews that do not exist, and `build_and_run_crew`
  answers an unknown crew name with an empty string.

Two passes over `api/` and `agents/`, because neither alone sees everything:

**Runtime.** Imports each module and reads `vars(module)`, so it catches a map however it was
built - a comprehension, a merge, a value assembled at import. It sees module-level names only.

**Source.** Parses each file and inspects every dict *literal* assigned to a name, at any depth,
so it catches one written inside a function body. This pass is not decoration: `CREW_AGENT_KEYS`,
one of the five stale maps deleted here, was a local inside `build_pam_report` - the runtime
pass cannot see it, and a reviewer proved that by re-adding it in place and watching this file
pass. It reads structure and values, not text, so a reformatting does not break it and a rename
does not slip past it.

Between them: a literal anywhere, or anything at all at module level. What neither sees is a map
built at run time inside a function, which no copy this branch deleted ever was.
"""
from __future__ import annotations

import ast
import importlib
import pkgutil
from pathlib import Path

import pytest

from agents.graph import build_graph

REPO = Path(__file__).resolve().parent.parent

# The declarations the runtime pass is allowed to find, and why.
#
# An allowlist rather than a name filter, because "it is called _CREW_AGENT_NAMES" is exactly
# what an eleventh copy would also be called. Each entry is a decision on the record; a new one
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


# --- The source pass: dict literals at any depth, including inside a function ------------------

# Allowed by the source pass, and why. Only the one literal: `AGENT_CREW_NAME` is a
# comprehension rather than a literal, and `agents/graph.py` holds an import rather than a dict.
PERMITTED_LITERALS: dict[tuple[str, str], str] = {
    ("api/services/run_service.py", "_CREW_AGENT_NAMES"): "the one declaration",
}


def _source_files() -> list[Path]:
    return sorted(
        path
        for package in ("api", "agents")
        for path in (REPO / package).rglob("*.py")
        if "__pycache__" not in path.parts
    )


def _static_value(node: ast.expr) -> object:
    """The literal a node describes, or a sentinel object when it is not a literal.

    `ast.literal_eval` on the whole dict is no good here: one non-literal value - a function
    call, a name - raises and takes the entire map with it, which is a silent way to stop
    looking. Each key and value is resolved on its own instead, so a map that is mostly
    literal is still read.
    """
    try:
        return ast.literal_eval(node)
    except (ValueError, SyntaxError, TypeError, MemoryError, RecursionError):
        return _NOT_A_LITERAL


_NOT_A_LITERAL = object()


def _dict_literals(tree: ast.AST) -> list[tuple[str, dict]]:
    """Every `name = {...}` in the tree, at any depth, as (name, partially-resolved dict)."""
    found: list[tuple[str, dict]] = []
    for node in ast.walk(tree):
        targets = (
            [node.target] if isinstance(node, ast.AnnAssign)
            else node.targets if isinstance(node, ast.Assign)
            else []
        )
        if not isinstance(getattr(node, "value", None), ast.Dict):
            continue
        resolved = {
            key: value
            for raw_key, raw_value in zip(node.value.keys, node.value.values)
            if raw_key is not None
            and (key := _static_value(raw_key)) is not _NOT_A_LITERAL
            and isinstance(key, str)
            and (value := _static_value(raw_value)) is not _NOT_A_LITERAL
        }
        if not resolved:
            continue
        for target in targets:
            if isinstance(target, ast.Name):
                found.append((target.id, resolved))
    return found


def _literal_declarations() -> list[tuple[str, str]]:
    found = []
    for path in _source_files():
        tree = ast.parse(path.read_text(), filename=str(path))
        for name, value in _dict_literals(tree):
            if _is_crew_to_agents(value) or _is_agent_to_crew(value):
                found.append((str(path.relative_to(REPO)), name))
    return sorted(set(found))


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
    to name two crews that do not exist.

    Module-level objects only - see the source pass below for the half this cannot reach.
    """
    unexpected = [where for where in _declarations() if where not in PERMITTED]
    assert not unexpected, (
        f"{len(unexpected)} module-level maps restate which agents a crew runs: "
        f"{unexpected}. Read `agents.graph.GRAPH` instead - every copy this slice deleted "
        f"had drifted, and each one failed silently rather than raising."
    )


def test_the_source_pass_finds_the_declaration_it_is_built_around():
    """Guard the guard, for the second pass. A parser that stopped resolving dict literals
    would report nothing and excuse every file."""
    found = _literal_declarations()
    assert ("api/services/run_service.py", "_CREW_AGENT_NAMES") in found, found
    assert len(_source_files()) > 60, "the source walk is reading almost nothing"


def test_no_function_declares_its_own_crew_to_agent_map():
    """The half the runtime pass cannot see, and it is not hypothetical.

    `CREW_AGENT_KEYS` - one of the five stale maps this branch deleted - was a local inside
    `build_pam_report`, not a module attribute. `vars(module)` never held it. A reviewer
    re-added it in place, indented inside the function, and every test in this file passed.
    """
    unexpected = [where for where in _literal_declarations() if where not in PERMITTED_LITERALS]
    assert not unexpected, (
        f"{len(unexpected)} dict literals restate which agents a crew runs: {unexpected}. "
        f"Read `agents.graph.GRAPH` instead. Indentation is not an exemption - the copy that "
        f"cost Pamela's report two whole crews was written inside a function."
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


@pytest.mark.parametrize("where", sorted(PERMITTED_LITERALS))
def test_every_permitted_literal_still_exists(where):
    assert where in _literal_declarations(), f"{where} is allowlisted and no longer exists"
