# tests/test_discovery_crew.py
"""Unit tests for Discovery crew assembly."""
import pytest
from unittest.mock import MagicMock, patch
from crewai import LLM


@pytest.fixture
def mock_llm():
    return MagicMock(spec=LLM)


def test_discovery_crew_accepts_hitl_tool_override(mock_llm):
    """hitl_tool is forwarded to every get_tools_for_agent call."""
    mock_hitl = MagicMock()
    with patch("agents.crews.discovery_crew.get_tools_for_agent", return_value=[]) as mock_reg:
        from agents.crews.discovery_crew import create_discovery_crew
        create_discovery_crew(
            slug="test", run_id=1, llm_mode="standard", sector="logistics",
            llm=mock_llm, hitl_tool=mock_hitl,
        )
    assert mock_reg.call_args_list, "get_tools_for_agent was never called"
    for call in mock_reg.call_args_list:
        assert call.kwargs.get("hitl_tool") == mock_hitl, \
            f"Expected hitl_tool in call: {call}"


def test_value_chain_mapper_task_includes_discovery_brief():
    """Task description includes the discovery brief when provided."""
    from agents.discovery.value_chain_mapper import create_value_chain_mapper_task
    from unittest.mock import MagicMock, patch
    agent = MagicMock()
    with patch("agents.discovery.value_chain_mapper.Task") as MockTask:
        instance = MagicMock()
        MockTask.return_value = instance
        create_value_chain_mapper_task(
            agent=agent,
            discovery_brief="Focus on passenger services.",
            discovery_links=[{"url": "https://rsp.com", "label": "RSP"}],
            priority_doc_names=["strategy_2025.pdf"],
        )
    _, kwargs = MockTask.call_args
    desc = kwargs["description"]
    assert "Focus on passenger services." in desc
    assert "https://rsp.com" in desc
    assert "strategy_2025.pdf" in desc


def test_value_chain_mapper_task_unchanged_when_no_inputs():
    """Task description has no extra preamble when all inputs are empty."""
    from agents.discovery.value_chain_mapper import create_value_chain_mapper_task
    from unittest.mock import MagicMock, patch
    agent = MagicMock()
    with patch("agents.discovery.value_chain_mapper.Task") as MockTask:
        instance = MagicMock()
        MockTask.return_value = instance
        create_value_chain_mapper_task(agent=agent)
    _, kwargs = MockTask.call_args
    desc = kwargs["description"]
    assert "Research brief:" not in desc


def test_discovery_mapping_crew_carries_alex_and_morgan():
    from agents.crews.discovery_mapping_crew import create_discovery_mapping_crew
    mock_llm = MagicMock(spec=LLM)
    with patch("agents.crews.discovery_mapping_crew.get_tools_for_agent", return_value=[]):
        crew = create_discovery_mapping_crew(
            slug="test", run_id=1, llm_mode="standard", sector="rail", llm=mock_llm
        )
    # Named rather than counted: a count of two is equally true of the wrong two.
    assert [a.role for a in crew.agents] == ['Value Chain Mapper', 'Value Lever Analyst']


def test_discovery_mapping_crew_runs_a_task_for_each_of_them():
    from agents.crews.discovery_mapping_crew import create_discovery_mapping_crew
    mock_llm = MagicMock(spec=LLM)
    with patch("agents.crews.discovery_mapping_crew.get_tools_for_agent", return_value=[]):
        crew = create_discovery_mapping_crew(
            slug="test", run_id=1, llm_mode="standard", sector="rail", llm=mock_llm
        )
    assert len(crew.tasks) == 2


def test_discovery_mapping_crew_task_mentions_value_chain_model_and_tree():
    """Alex now saves the structured model, but keeps saving the tree and derived registry
    too - DeriveRegistryTool is deterministic code that guarantees IDs are never reused, and
    an LLM instruction cannot replace that guarantee. Losing either the model or the tree
    step here means either the editor has nothing to edit, or the ID ledger silently stops
    being maintained."""
    from agents.crews.discovery_mapping_crew import create_discovery_mapping_crew
    mock_llm = MagicMock(spec=LLM)
    with patch("agents.crews.discovery_mapping_crew.get_tools_for_agent", return_value=[]):
        crew = create_discovery_mapping_crew(
            slug="test", run_id=1, llm_mode="standard", sector="rail", llm=mock_llm
        )
    description = crew.tasks[0].description
    assert "value_chain_model" in description
    assert "value_chain_tree" in description
    assert "DeriveRegistryTool" in description
