# tests/test_discovery_interviews_crew.py
"""Unit tests for the discovery interviews crew factory."""
import pytest
from unittest.mock import MagicMock, patch
from crewai import LLM, Process


@pytest.fixture
def mock_llm():
    return MagicMock(spec=LLM)


def _build_crew(mock_llm, stakeholder_assignments=None, discovery_brief=""):
    with patch("agents.crews.discovery_interviews_crew.get_tools_for_agent", return_value=[]):
        from agents.crews.discovery_interviews_crew import create_discovery_interviews_crew
        return create_discovery_interviews_crew(
            slug="test",
            run_id=1,
            llm_mode="standard",
            sector="logistics",
            stakeholder_assignments=stakeholder_assignments or [],
            discovery_brief=discovery_brief,
            llm=mock_llm,
        )


def test_discovery_interviews_crew_has_three_agents(mock_llm):
    """Coordinator, interviewer, analyst.

    The interview_script_designer agent was removed from this crew in 6dab668;
    script design moved to the template-driven API path (239e469).
    """
    crew = _build_crew(mock_llm)
    assert len(crew.agents) == 3


def test_discovery_interviews_crew_has_three_tasks(mock_llm):
    crew = _build_crew(mock_llm)
    assert len(crew.tasks) == 3


def test_discovery_interviews_crew_sequential(mock_llm):
    crew = _build_crew(mock_llm)
    assert crew.process == Process.sequential


def test_discovery_interviews_crew_injects_assignments(mock_llm):
    """The Coordinator task description includes the formatted stakeholder string."""
    assignments = [
        {"name": "Alice Chen", "job_title": "Head of Ops", "level": "L2", "node_label": "Order Fulfilment"},
    ]
    crew = _build_crew(mock_llm, stakeholder_assignments=assignments)
    coordinator_task = crew.tasks[0]
    assert "Alice Chen" in coordinator_task.description


def test_discovery_interviews_crew_uses_registry(mock_llm):
    """get_tools_for_agent is called for each of the three agent roles."""
    with patch(
        "agents.crews.discovery_interviews_crew.get_tools_for_agent", return_value=[]
    ) as mock_reg:
        from agents.crews.discovery_interviews_crew import create_discovery_interviews_crew
        create_discovery_interviews_crew(
            slug="myslug", run_id=5, llm_mode="standard", sector="rail",
            stakeholder_assignments=[], llm=mock_llm,
        )
    called_agents = {c.args[0] for c in mock_reg.call_args_list}
    assert "interview_coordinator" in called_agents
    assert "stakeholder_interviewer" in called_agents
    assert "synthesis_analyst" in called_agents


def test_discovery_interviews_crew_accepts_discovery_brief(mock_llm):
    """discovery_brief reaches the Coordinator task (task index 0).

    It previously reached nothing: the parameter was accepted and silently
    discarded after the Script Designer task that consumed it was removed,
    so run_service passed the project brief into a black hole.
    """
    crew = _build_crew(mock_llm, discovery_brief="Test brief text")
    assert "Test brief text" in crew.tasks[0].description


def test_discovery_interviews_crew_accepts_node_templates(mock_llm):
    """node_templates_block reaches the Coordinator task too.

    run_service assembles this block from the project's node templates, so
    dropping it silently wasted that work.
    """
    with patch("agents.crews.discovery_interviews_crew.get_tools_for_agent", return_value=[]):
        from agents.crews.discovery_interviews_crew import create_discovery_interviews_crew
        crew = create_discovery_interviews_crew(
            slug="test", run_id=1, llm_mode="standard", sector="logistics",
            stakeholder_assignments=[], llm=mock_llm,
            node_templates_block='{"Goods-in Inspection": {"questions": []}}',
        )
    assert "Goods-in Inspection" in crew.tasks[0].description


def test_registry_has_interview_coordinator_entry():
    with patch("agents.tools.registry.get_settings") as ms, \
         patch("agents.tools.registry.load_project_config", return_value={"sector": "rail"}):
        ms.return_value.projects_dir = "/tmp"
        from agents.tools.registry import get_tools_for_agent
        tools = get_tools_for_agent("interview_coordinator", slug="t", run_id=1, sector="rail")
    assert len(tools) > 0


def test_registry_has_stakeholder_interviewer_entry():
    with patch("agents.tools.registry.get_settings") as ms, \
         patch("agents.tools.registry.load_project_config", return_value={"sector": "rail"}):
        ms.return_value.projects_dir = "/tmp"
        from agents.tools.registry import get_tools_for_agent
        tools = get_tools_for_agent("stakeholder_interviewer", slug="t", run_id=1, sector="rail")
    assert len(tools) > 0


def test_registry_has_synthesis_analyst_entry():
    with patch("agents.tools.registry.get_settings") as ms, \
         patch("agents.tools.registry.load_project_config", return_value={"sector": "rail"}):
        ms.return_value.projects_dir = "/tmp"
        from agents.tools.registry import get_tools_for_agent
        tools = get_tools_for_agent("synthesis_analyst", slug="t", run_id=1, sector="rail")
    assert len(tools) > 0
