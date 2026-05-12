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
    assert "initiative_type='enabler'" in task.description
    assert "initiative_type='change_activity'" in task.description


# ── Crew wiring ───────────────────────────────────────────────────────────────

def test_architecture_crew_has_two_agents(mock_llm):
    with patch("agents.tools.registry.get_tools_for_agent", return_value=[]):
        from agents.crews.architecture_crew import create_architecture_crew
        crew = create_architecture_crew(
            slug="test", run_id=1, llm_mode="standard", sector="logistics", llm=mock_llm
        )
    assert len(crew.agents) == 2


def test_architecture_crew_agent_roles(mock_llm):
    with patch("agents.tools.registry.get_tools_for_agent", return_value=[]):
        from agents.crews.architecture_crew import create_architecture_crew
        crew = create_architecture_crew(
            slug="test", run_id=1, llm_mode="standard", sector="logistics", llm=mock_llm
        )
    roles = {a.role for a in crew.agents}
    assert "Enterprise Architect" in roles
    assert "Initiative Identifier" in roles


def test_architecture_crew_sequential_process(mock_llm):
    from crewai import Process
    with patch("agents.tools.registry.get_tools_for_agent", return_value=[]):
        from agents.crews.architecture_crew import create_architecture_crew
        crew = create_architecture_crew(
            slug="test", run_id=1, llm_mode="standard", sector="logistics", llm=mock_llm
        )
    assert crew.process == Process.sequential


def test_architecture_crew_accepts_hitl_tool_override(mock_llm):
    """hitl_tool is forwarded to every get_tools_for_agent call."""
    mock_hitl = MagicMock()
    with patch("agents.crews.architecture_crew.get_tools_for_agent", return_value=[]) as mock_reg:
        from agents.crews.architecture_crew import create_architecture_crew
        create_architecture_crew(
            slug="test", run_id=1, llm_mode="standard", sector="logistics",
            llm=mock_llm, hitl_tool=mock_hitl,
        )
    assert mock_reg.call_args_list, "get_tools_for_agent was never called"
    for call in mock_reg.call_args_list:
        assert call.kwargs.get("hitl_tool") == mock_hitl, \
            f"Expected hitl_tool in call: {call}"
