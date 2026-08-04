"""Every crew's declared primary output must be a type one of its own agents writes.

`CREW_OUTPUT_TYPE` in ui/src/components/crewOutputs.ts decides what the agent panel's Output
tab renders. It arrived from a place where a miss meant "no inline preview" and failed
silently; it is now load-bearing, and a value naming a type nothing produces leaves the tab
permanently empty with no error anywhere.

The allowed set is derived here from the agent modules and the tool registry rather than
hard-coded, so it tracks the agents instead of drifting from them. Two producers exist:

* SQLiteStateTool writes, instructed in an agent's task description as
  ``operation='write', key='<type>', agent_name='<agent>'`` - the key becomes the output_type
  (agents/tools/sqlite_state.py).
* Tools that record an output_type themselves (WordOutputTool, HtmlRoadmapTool, ...). Those
  are attributed to whichever agents hold the tool in agents/tools/registry.py.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from api.services.run_service import _CREW_AGENT_NAMES

REPO = Path(__file__).resolve().parent.parent
CREW_OUTPUTS_TS = REPO / "ui" / "src" / "components" / "crewOutputs.ts"
AGENTS_DIR = REPO / "agents"
TOOLS_DIR = AGENTS_DIR / "tools"
REGISTRY = TOOLS_DIR / "registry.py"


def _declared_primaries() -> dict[str, str]:
    """Parse CREW_OUTPUT_TYPE out of the TypeScript module that declares it."""
    text = CREW_OUTPUTS_TS.read_text()
    body = re.search(
        r"export const CREW_OUTPUT_TYPE:\s*Record<string,\s*string>\s*=\s*\{(.*?)\}",
        text,
        re.S,
    )
    assert body, "CREW_OUTPUT_TYPE not found in crewOutputs.ts"
    return dict(re.findall(r"(\w+):\s*'([\w]+)'", body.group(1)))


def _sqlite_state_writes() -> dict[str, set[str]]:
    """agent_name -> output types it is instructed to write via SQLiteStateTool.

    The instruction is a Python string built across several source lines, so the file is
    flattened (quotes and whitespace stripped) before matching rather than read line by line -
    agents/discovery/value_chain_mapper.py splits one such write across two lines.
    """
    writes: dict[str, set[str]] = {}
    for path in sorted(AGENTS_DIR.rglob("*.py")):
        if "tools" in path.parts or "__pycache__" in path.parts:
            continue
        flat = re.sub(r"\s+", "", path.read_text().replace('"', ""))
        for match in re.finditer(r"operation='write',key='(\w+)',agent_name='(\w+)'", flat):
            writes.setdefault(match.group(2), set()).add(match.group(1))
    return writes


def _tool_output_types() -> dict[str, set[str]]:
    """Tool class name -> the output types it hard-codes when it records an output."""
    types: dict[str, set[str]] = {}
    for path in sorted(TOOLS_DIR.glob("*.py")):
        text = path.read_text()
        recorded = set(re.findall(r'output_type="(\w+)"', text))
        if not recorded:
            continue
        for cls in re.findall(r"^class (\w+)\(BaseTool\)", text, re.M):
            types[cls] = recorded
    return types


def _tool_writes() -> dict[str, set[str]]:
    """agent_name -> output types produced by the tools the registry gives it."""
    tool_types = _tool_output_types()
    registry = REGISTRY.read_text()
    tool_map = registry[registry.index("tool_map: dict"):]
    writes: dict[str, set[str]] = {}
    for match in re.finditer(r'"(\w+)":\s*\[(.*?)\n        \]', tool_map, re.S):
        agent, block = match.group(1), match.group(2)
        produced: set[str] = set()
        for tool in set(re.findall(r"(\w+)\(", block)):
            produced |= tool_types.get(tool, set())
        writes[agent] = produced
    return writes


def _produced_by_agent() -> dict[str, set[str]]:
    state, tools = _sqlite_state_writes(), _tool_writes()
    agents = set(state) | set(tools)
    return {a: state.get(a, set()) | tools.get(a, set()) for a in agents}


def test_the_derivation_finds_producers_at_all():
    """Without this the assertions below hold vacuously the moment a regex stops matching -
    an empty allowed set would make every crew fail, but an empty *declared* map or a broken
    per-agent lookup would silently pass nothing at all."""
    produced = _produced_by_agent()
    assert len(_declared_primaries()) == len(_CREW_AGENT_NAMES)
    assert produced.get("requirements_analyst") == {"requirements_analysis"}
    assert "docx" in produced.get("business_plan_generator", set())


@pytest.mark.parametrize("crew", sorted(_declared_primaries()))
def test_a_crews_declared_primary_is_a_type_its_own_agents_write(crew):
    primary = _declared_primaries()[crew]
    agents = _CREW_AGENT_NAMES.get(crew)
    assert agents, f"{crew} is declared in CREW_OUTPUT_TYPE but has no agents"

    produced = _produced_by_agent()
    available: set[str] = set()
    for agent in agents:
        available |= produced.get(agent, set())

    assert primary in available, (
        f"{crew}'s primary output type {primary!r} is written by none of its agents "
        f"({', '.join(agents)}). They write: {', '.join(sorted(available)) or 'nothing'}."
    )
