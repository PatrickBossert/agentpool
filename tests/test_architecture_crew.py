# tests/test_architecture_crew.py
"""Unit tests for Architecture crew agents and crew assembly."""
import pytest
from unittest.mock import MagicMock, patch
from crewai import LLM


@pytest.fixture
def mock_llm():
    return MagicMock(spec=LLM)


# ── Enterprise Architect ──────────────────────────────────────────────────────

def test_ea_agent_role(mock_llm):
    from agents.architecture.enterprise_architect import create_enterprise_architect
    agent = create_enterprise_architect(slug="test", llm=mock_llm, tools=[])
    assert agent.role == "Enterprise Architect"


def test_ea_task_queries_chroma(mock_llm):
    from agents.architecture.enterprise_architect import (
        create_enterprise_architect,
        create_enterprise_architect_task,
    )
    agent = create_enterprise_architect(slug="test", llm=mock_llm, tools=[])
    task = create_enterprise_architect_task(agent=agent)
    assert "ChromaQueryTool" in task.description
    assert "collection='project'" in task.description


def test_ea_task_writes_architecture_register(mock_llm):
    from agents.architecture.enterprise_architect import (
        create_enterprise_architect,
        create_enterprise_architect_task,
    )
    agent = create_enterprise_architect(slug="test", llm=mock_llm, tools=[])
    task = create_enterprise_architect_task(agent=agent)
    assert "key='architecture_register'" in task.description
    assert "operation='write'" in task.description


def test_ea_task_renders_three_mermaid_diagrams(mock_llm):
    from agents.architecture.enterprise_architect import (
        create_enterprise_architect,
        create_enterprise_architect_task,
    )
    agent = create_enterprise_architect(slug="test", llm=mock_llm, tools=[])
    task = create_enterprise_architect_task(agent=agent)
    assert "architecture_data_layer" in task.description
    assert "architecture_technology_layer" in task.description
    assert "architecture_org_layer" in task.description


def test_ea_task_has_hitl(mock_llm):
    from agents.architecture.enterprise_architect import (
        create_enterprise_architect,
        create_enterprise_architect_task,
    )
    agent = create_enterprise_architect(slug="test", llm=mock_llm, tools=[])
    task = create_enterprise_architect_task(agent=agent)
    assert "HumanInputTool" in task.description
    assert "approved" in task.description


# ── Initiative Identifier ─────────────────────────────────────────────────────

def test_ii_agent_role(mock_llm):
    from agents.architecture.initiative_identifier import create_initiative_identifier
    agent = create_initiative_identifier(slug="test", llm=mock_llm, tools=[])
    assert agent.role == "Initiative Identifier"


def test_ii_task_reads_three_inputs(mock_llm):
    from agents.architecture.initiative_identifier import (
        create_initiative_identifier,
        create_initiative_identifier_task,
    )
    agent = create_initiative_identifier(slug="test", llm=mock_llm, tools=[])
    task = create_initiative_identifier_task(agent=agent, context_tasks=[])
    assert "key='propositions'" in task.description
    assert "key='architecture_register'" in task.description
    assert "key='requirements'" in task.description


def test_ii_task_writes_initiative_register(mock_llm):
    from agents.architecture.initiative_identifier import (
        create_initiative_identifier,
        create_initiative_identifier_task,
    )
    agent = create_initiative_identifier(slug="test", llm=mock_llm, tools=[])
    task = create_initiative_identifier_task(agent=agent, context_tasks=[])
    assert "key='initiative_register'" in task.description
    assert "operation='write'" in task.description


def test_ii_task_has_hitl(mock_llm):
    from agents.architecture.initiative_identifier import (
        create_initiative_identifier,
        create_initiative_identifier_task,
    )
    agent = create_initiative_identifier(slug="test", llm=mock_llm, tools=[])
    task = create_initiative_identifier_task(agent=agent, context_tasks=[])
    assert "HumanInputTool" in task.description
    assert "approved" in task.description


def test_ii_task_covers_all_categories(mock_llm):
    from agents.architecture.initiative_identifier import (
        create_initiative_identifier,
        create_initiative_identifier_task,
    )
    agent = create_initiative_identifier(slug="test", llm=mock_llm, tools=[])
    task = create_initiative_identifier_task(agent=agent, context_tasks=[])
    assert "enabling" in task.description
    assert "operating_model" in task.description
    assert "business_change" in task.description
