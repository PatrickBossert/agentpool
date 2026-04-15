# tests/test_value_design_crew.py
"""Unit tests for Value Design crew agents and crew assembly."""
import pytest
from unittest.mock import MagicMock, patch
from crewai import LLM


@pytest.fixture
def mock_llm():
    return MagicMock(spec=LLM)


# ── Value Proposition Generator ───────────────────────────────────────────────

def test_vpg_agent_role(mock_llm):
    from agents.value_design.value_proposition_generator import create_value_proposition_generator
    agent = create_value_proposition_generator(slug="test", llm=mock_llm, tools=[])
    assert agent.role == "Value Proposition Generator"


def test_vpg_task_reads_discovery_outputs(mock_llm):
    """Task description instructs the agent to read all four Discovery output keys."""
    from agents.value_design.value_proposition_generator import (
        create_value_proposition_generator,
        create_value_proposition_generator_task,
    )
    agent = create_value_proposition_generator(slug="test", llm=mock_llm, tools=[])
    task = create_value_proposition_generator_task(agent=agent)
    desc = task.description
    assert "key='requirements'" in desc
    assert "key='value_levers'" in desc
    assert "key='value_chain_summary'" in desc
    assert "key='user_journeys'" in desc


def test_vpg_task_writes_propositions(mock_llm):
    from agents.value_design.value_proposition_generator import (
        create_value_proposition_generator,
        create_value_proposition_generator_task,
    )
    agent = create_value_proposition_generator(slug="test", llm=mock_llm, tools=[])
    task = create_value_proposition_generator_task(agent=agent)
    assert "key='propositions'" in task.description
    assert "operation='write'" in task.description


def test_vpg_task_has_hitl(mock_llm):
    from agents.value_design.value_proposition_generator import (
        create_value_proposition_generator,
        create_value_proposition_generator_task,
    )
    agent = create_value_proposition_generator(slug="test", llm=mock_llm, tools=[])
    task = create_value_proposition_generator_task(agent=agent)
    assert "HumanInputTool" in task.description
    assert "approved" in task.description


# ── Portfolio Manager ─────────────────────────────────────────────────────────

def test_pm_agent_role(mock_llm):
    from agents.value_design.portfolio_manager import create_portfolio_manager
    agent = create_portfolio_manager(slug="test", llm=mock_llm, tools=[])
    assert agent.role == "Portfolio Manager"


def test_pm_task_reads_propositions(mock_llm):
    from agents.value_design.portfolio_manager import (
        create_portfolio_manager,
        create_portfolio_manager_task,
    )
    agent = create_portfolio_manager(slug="test", llm=mock_llm, tools=[])
    task = create_portfolio_manager_task(agent=agent, context_tasks=[])
    assert "key='propositions'" in task.description
    assert "operation='read'" in task.description


def test_pm_task_requests_weights_via_hitl(mock_llm):
    from agents.value_design.portfolio_manager import (
        create_portfolio_manager,
        create_portfolio_manager_task,
    )
    agent = create_portfolio_manager(slug="test", llm=mock_llm, tools=[])
    task = create_portfolio_manager_task(agent=agent, context_tasks=[])
    assert "HumanInputTool" in task.description
    assert "weights" in task.description.lower()
    assert "approved" in task.description


def test_pm_task_uses_excel_output_tool(mock_llm):
    from agents.value_design.portfolio_manager import (
        create_portfolio_manager,
        create_portfolio_manager_task,
    )
    agent = create_portfolio_manager(slug="test", llm=mock_llm, tools=[])
    task = create_portfolio_manager_task(agent=agent, context_tasks=[])
    assert "ExcelOutputTool" in task.description
    assert "portfolio_register.xlsx" in task.description


def test_pm_task_writes_portfolio_register(mock_llm):
    from agents.value_design.portfolio_manager import (
        create_portfolio_manager,
        create_portfolio_manager_task,
    )
    agent = create_portfolio_manager(slug="test", llm=mock_llm, tools=[])
    task = create_portfolio_manager_task(agent=agent, context_tasks=[])
    assert "key='portfolio_register'" in task.description
    assert "operation='write'" in task.description


def test_pm_task_context_is_wired(mock_llm):
    """context_tasks list is passed through to Task.context for crew chaining."""
    from crewai import Task
    from agents.value_design.portfolio_manager import (
        create_portfolio_manager,
        create_portfolio_manager_task,
    )
    agent = create_portfolio_manager(slug="test", llm=mock_llm, tools=[])
    sentinel = Task(description="sentinel task", expected_output="output", agent=agent)
    task = create_portfolio_manager_task(agent=agent, context_tasks=[sentinel])
    assert task.context == [sentinel]


# ── Crew wiring ───────────────────────────────────────────────────────────────

def test_value_design_crew_has_two_agents(mock_llm):
    with patch("agents.tools.registry.get_tools_for_agent", return_value=[]):
        from agents.crews.value_design_crew import create_value_design_crew
        crew = create_value_design_crew(
            slug="test", run_id=1, llm_mode="standard", sector="logistics", llm=mock_llm
        )
    assert len(crew.agents) == 2


def test_value_design_crew_agent_roles(mock_llm):
    with patch("agents.tools.registry.get_tools_for_agent", return_value=[]):
        from agents.crews.value_design_crew import create_value_design_crew
        crew = create_value_design_crew(
            slug="test", run_id=1, llm_mode="standard", sector="logistics", llm=mock_llm
        )
    roles = {a.role for a in crew.agents}
    assert "Value Proposition Generator" in roles
    assert "Portfolio Manager" in roles


def test_value_design_crew_sequential_process(mock_llm):
    from crewai import Process
    with patch("agents.tools.registry.get_tools_for_agent", return_value=[]):
        from agents.crews.value_design_crew import create_value_design_crew
        crew = create_value_design_crew(
            slug="test", run_id=1, llm_mode="standard", sector="logistics", llm=mock_llm
        )
    assert crew.process == Process.sequential


def test_value_design_crew_sensitive_mode_uses_local_llm(mock_llm):
    """In sensitive mode, a single local LLM is used (not the test override)."""
    with patch("agents.tools.registry.get_tools_for_agent", return_value=[]), \
         patch("agents.crews.value_design_crew.get_crew_llm") as mock_local:
        mock_local.return_value = mock_llm
        from agents.crews.value_design_crew import create_value_design_crew
        crew = create_value_design_crew(
            slug="test", run_id=1, llm_mode="sensitive", sector="logistics"
        )
    mock_local.assert_called_once_with("sensitive")


def test_value_design_crew_accepts_hitl_tool_override(mock_llm):
    """hitl_tool is forwarded to every get_tools_for_agent call."""
    mock_hitl = MagicMock()
    with patch("agents.crews.value_design_crew.get_tools_for_agent", return_value=[]) as mock_reg:
        from agents.crews.value_design_crew import create_value_design_crew
        create_value_design_crew(
            slug="test", run_id=1, llm_mode="standard", sector="logistics",
            llm=mock_llm, hitl_tool=mock_hitl,
        )
    assert mock_reg.call_args_list, "get_tools_for_agent was never called"
    for call in mock_reg.call_args_list:
        assert call.kwargs.get("hitl_tool") == mock_hitl, \
            f"Expected hitl_tool in call: {call}"
