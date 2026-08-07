# tests/test_visual_illustrator.py
"""The Illustrator's task names the keys he reads, and every one has to be real.

He reads five upstream outputs and writes one. A key named in the task but absent from
OUTPUT_OWNERS is not a validation failure - reads are open, so nothing refuses it. The tool
resolves it through the ledger, finds no row, and returns "Error: no state found", which the
agent is free to interpret as "that input does not exist yet" and carry on. The brief comes
out thinner and nothing reports why.

`architecture_blueprint` was exactly that: a key no agent has ever written, sitting in step 4
of the task. The real output type is `architecture_register`, owned by enterprise_architect.
"""
import re

import pytest
from unittest.mock import MagicMock
from crewai import LLM

from agents.tools.ownership import OUTPUT_OWNERS


@pytest.fixture
def mock_llm():
    return MagicMock(spec=LLM)


def _task_description(sector: str = "energy", client_name: str = "Acme") -> str:
    from agents.delivery.visual_illustrator import (
        create_visual_illustrator,
        create_visual_illustrator_task,
    )
    agent = create_visual_illustrator(slug="test", llm=MagicMock(spec=LLM), tools=[])
    return create_visual_illustrator_task(
        agent=agent, sector=sector, client_name=client_name
    ).description


def test_every_key_the_task_names_is_a_declared_output():
    """Both directions of the task's traffic, read and write, in one assertion.

    Extracting the keys rather than listing them is deliberate: a hardcoded list would have
    to be edited in step with the task, and the version that drifts is the test.
    """
    keys = set(re.findall(r"key='([^']+)'", _task_description()))
    assert keys, "no key='...' references found - has the task been rewritten?"
    undeclared = keys - set(OUTPUT_OWNERS)
    assert not undeclared, (
        f"the task reads or writes {sorted(undeclared)}, which no agent produces. A read of "
        f"an undeclared key returns 'Error: no state found' and the run continues quietly."
    )


def test_the_task_reads_the_architecture_register_by_its_real_name():
    """Named on its own, because the generic test above passes if the step is deleted.

    Losing the architecture input entirely would satisfy 'every key is declared'. This says
    the input is still there.
    """
    description = _task_description()
    assert "key='architecture_register'" in description
    assert "architecture_blueprint" not in description


def test_the_task_only_names_tools_that_exist():
    """Step 9 told the agent to use FileWriteTool, which has never existed in this codebase.

    SQLiteStateTool's write already puts the JSON in outputs/ and records the ledger row, so
    the step was redundant as well as impossible - an agent that believed it would either
    fail the step or invent something to satisfy it.
    """
    import agents.tools as tools_pkg
    from pathlib import Path

    described = set(re.findall(r"\b([A-Z][A-Za-z]*Tool)\b", _task_description()))
    available = {
        m.group(1)
        for path in Path(tools_pkg.__file__).parent.glob("*.py")
        for m in re.finditer(r"^class ([A-Za-z]+Tool)\(", path.read_text(), re.M)
    }
    missing = described - available
    assert not missing, f"the task names tools that do not exist: {sorted(missing)}"


def test_the_illustrator_has_the_tool_his_task_tells_him_to_use():
    """The registry gap this file was written for.

    get_tools_for_agent raised ValueError for visual_illustrator, so create_business_plan_crew
    could not be built at all - the crew raised before its first task, on master, for as long
    as the Illustrator had been wired into it.
    """
    from agents.tools.registry import get_tools_for_agent

    tools = get_tools_for_agent("visual_illustrator", slug="x", run_id=1, sector="energy")
    assert {type(t).__name__ for t in tools} >= {"SQLiteStateTool"}


def test_the_illustrator_holds_no_human_input_tool():
    """He has no approval gate - test_vi_task_has_no_hitl_gate says so of the task, and the
    tool list has to agree. A tool an agent holds is a tool it can decide to call."""
    from agents.tools.registry import get_tools_for_agent

    tools = get_tools_for_agent("visual_illustrator", slug="x", run_id=1, sector="energy")
    assert "HumanInputTool" not in {type(t).__name__ for t in tools}


def test_the_business_plan_crew_builds(mock_llm):
    """The consequence, asserted where it bit: the crew assembles both agents."""
    from agents.crews.business_plan_crew import create_business_plan_crew

    crew = create_business_plan_crew(
        slug="x", run_id=1, llm_mode="standard", sector="logistics", llm=mock_llm,
    )
    assert [a.role for a in crew.agents] == ["Business Plan Generator", "Visual Illustrator"]
