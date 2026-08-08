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


def _build_crew_without_an_llm(llm_mode):
    """Build the crew the way run_service does - no llm override, so the factory chooses."""
    with patch("agents.crews.discovery_interviews_crew.get_tools_for_agent", return_value=[]):
        from agents.crews.discovery_interviews_crew import create_discovery_interviews_crew
        return create_discovery_interviews_crew(
            slug="test", run_id=1, llm_mode=llm_mode, sector="rail",
            stakeholder_assignments=[],
        )


def test_a_sensitive_project_gets_no_hosted_model_in_this_crew():
    """The branch's headline guarantee, at the one crew that reads interview answers.

    llm_mode was a declared parameter this factory never read: it called get_pam_llm()
    unconditionally, putting all three agents - including the Synthesis Analyst, which holds
    ChromaQueryTool over {slug}_interviews - on a hosted Anthropic model. Chroma routing was
    fixed to keep a sensitive project's answers local, and this crew then read them back out
    and sent them to Anthropic anyway.

    Asserted on every agent's actual LLM rather than on the factory's choice, because two of
    the three agents take their llm from the same local and one is the one that matters.
    """
    from api.config import get_settings

    crew = _build_crew_without_an_llm("sensitive")
    assert len(crew.agents) == 3
    for agent in crew.agents:
        assert agent.llm.model == f"openai/{get_settings().local_llm_model}", (
            f"{agent.role} is on {agent.llm.model} - a sensitive project's interview answers "
            "must never reach a hosted model"
        )
        assert agent.llm.base_url == get_settings().llamacpp_base_url
        assert "anthropic" not in str(agent.llm.model).lower()


def test_a_standard_project_gets_the_shared_crew_model():
    """The other side of the branch: standard must still route hosted, and to the crew model.

    Pinned to get_crew_llm's choice rather than merely "not local" - the defect it replaced
    put these three agents on PAM's Opus, which is not local either and would pass a
    negative-only assertion.
    """
    from agents.llm import get_crew_llm

    expected = get_crew_llm("standard").model
    crew = _build_crew_without_an_llm("standard")
    for agent in crew.agents:
        assert agent.llm.model == expected


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
