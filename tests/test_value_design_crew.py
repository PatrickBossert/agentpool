# tests/test_value_design_crew.py
"""Unit tests for Value Design crew agents and crew assembly."""
import pytest
from unittest.mock import MagicMock
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
