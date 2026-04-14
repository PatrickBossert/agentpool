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
