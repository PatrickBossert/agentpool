"""Unit tests for the Interview Script Designer agent module."""
from unittest.mock import MagicMock, patch
import pytest


def _mock_agent():
    return MagicMock()


# ── Agent tests ───────────────────────────────────────────────────────────────

def test_interview_script_designer_agent_role():
    """Agent role contains 'Script Designer' or 'script'."""
    with patch(
        "agents.discovery.interview_script_designer.get_tools_for_agent",
        return_value=[],
    ):
        from agents.discovery.interview_script_designer import (
            create_interview_script_designer_agent,
        )
        with patch("agents.discovery.interview_script_designer.Agent") as MockAgent:
            MockAgent.return_value = MagicMock()
            create_interview_script_designer_agent(
                slug="test-slug",
                run_id=1,
                llm_mode="fast",
                sector="logistics",
            )
    _, kwargs = MockAgent.call_args
    role = kwargs["role"].lower()
    assert "script designer" in role or "script" in role


def test_interview_script_designer_agent_tools_from_registry():
    """get_tools_for_agent is called with 'interview_script_designer'."""
    with patch(
        "agents.discovery.interview_script_designer.get_tools_for_agent",
        return_value=[],
    ) as mock_reg:
        with patch("agents.discovery.interview_script_designer.Agent"):
            from agents.discovery.interview_script_designer import (
                create_interview_script_designer_agent,
            )
            create_interview_script_designer_agent(
                slug="test-slug",
                run_id=42,
                llm_mode="fast",
                sector="rail",
            )
    assert mock_reg.called, "get_tools_for_agent was never called"
    call_args = mock_reg.call_args
    assert call_args[0][0] == "interview_script_designer"


# ── Task tests ────────────────────────────────────────────────────────────────

def test_interview_script_designer_task_reads_value_chain_tree():
    """Task description contains 'value_chain_tree'."""
    from agents.discovery.interview_script_designer import (
        create_interview_script_designer_task,
    )
    agent = _mock_agent()
    with patch("agents.discovery.interview_script_designer.Task") as MockTask:
        MockTask.return_value = MagicMock()
        create_interview_script_designer_task(agent=agent)
    _, kwargs = MockTask.call_args
    assert "value_chain_tree" in kwargs["description"]


def test_interview_script_designer_task_reads_value_chain_summary():
    """Task description contains 'value_chain_summary'."""
    from agents.discovery.interview_script_designer import (
        create_interview_script_designer_task,
    )
    agent = _mock_agent()
    with patch("agents.discovery.interview_script_designer.Task") as MockTask:
        MockTask.return_value = MagicMock()
        create_interview_script_designer_task(agent=agent)
    _, kwargs = MockTask.call_args
    assert "value_chain_summary" in kwargs["description"]


def test_interview_script_designer_task_injects_discovery_brief():
    """Task description contains the injected discovery brief."""
    from agents.discovery.interview_script_designer import (
        create_interview_script_designer_task,
    )
    agent = _mock_agent()
    brief = "Retail logistics transformation focusing on last-mile delivery."
    with patch("agents.discovery.interview_script_designer.Task") as MockTask:
        MockTask.return_value = MagicMock()
        create_interview_script_designer_task(agent=agent, discovery_brief=brief)
    _, kwargs = MockTask.call_args
    assert brief in kwargs["description"]


def test_interview_script_designer_task_injects_assignments():
    """Task description contains the injected stakeholder assignments block."""
    from agents.discovery.interview_script_designer import (
        create_interview_script_designer_task,
    )
    agent = _mock_agent()
    assignments = "Goods-in Inspection: Head of Warehouse, Logistics Manager"
    with patch("agents.discovery.interview_script_designer.Task") as MockTask:
        MockTask.return_value = MagicMock()
        create_interview_script_designer_task(
            agent=agent,
            stakeholder_assignments_block=assignments,
        )
    _, kwargs = MockTask.call_args
    assert assignments in kwargs["description"]


def test_interview_script_designer_task_writes_interview_scripts():
    """Task description contains 'interview_scripts'."""
    from agents.discovery.interview_script_designer import (
        create_interview_script_designer_task,
    )
    agent = _mock_agent()
    with patch("agents.discovery.interview_script_designer.Task") as MockTask:
        MockTask.return_value = MagicMock()
        create_interview_script_designer_task(agent=agent)
    _, kwargs = MockTask.call_args
    assert "interview_scripts" in kwargs["description"]
