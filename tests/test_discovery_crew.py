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
