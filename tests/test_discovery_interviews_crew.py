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


def _write_project_row(tmp_path, slug: str, llm_mode: str) -> None:
    """Write a project row the way get_llm_for_agent actually reads mode - a real sqlite
    row, not a mocked return value. This is what makes these two tests exercise the crew's
    real wiring into agents/model_registry.py rather than trusting a factory-level llm_mode
    argument the factory no longer even consults."""
    import json
    import sqlite3
    conn = sqlite3.connect(tmp_path / f"{slug}.db")
    conn.execute(
        "CREATE TABLE projects (id INTEGER PRIMARY KEY, slug TEXT, llm_mode TEXT, "
        "sector TEXT, config_json TEXT)"
    )
    conn.execute(
        "INSERT INTO projects (slug, llm_mode, sector, config_json) VALUES (?,?,?,?)",
        (slug, llm_mode, "rail", json.dumps({})),
    )
    conn.commit()
    conn.close()


def _build_crew_for_project(slug: str):
    """Build the crew the way run_service does - no llm override, so each agent asks the
    registry, which reads the real project row set up by _write_project_row. The llm_mode
    argument below is a required parameter the factory no longer reads at all; its value is
    irrelevant to which model is resolved, which is the point of this test."""
    with patch("agents.crews.discovery_interviews_crew.get_tools_for_agent", return_value=[]):
        from agents.crews.discovery_interviews_crew import create_discovery_interviews_crew
        return create_discovery_interviews_crew(
            slug=slug, run_id=1, llm_mode="standard", sector="rail",
            stakeholder_assignments=[],
        )


def test_a_sensitive_project_gets_no_hosted_model_in_this_crew(monkeypatch, tmp_path):
    """The branch's headline guarantee, at the one crew that reads interview answers.

    This crew used to take one shared get_crew_llm(llm_mode) call for all three agents, and
    llm_mode was, at one point, a declared parameter this factory never read at all - it
    called get_pam_llm() unconditionally, putting all three agents, including the Synthesis
    Analyst, which holds ChromaQueryTool over {slug}_interviews, on a hosted Anthropic model.
    Each agent now asks agents/model_registry.get_llm_for_agent for its own model, which reads
    the project's real llm_mode from its own row rather than trusting a caller-supplied one -
    so this test drives a real sensitive project row rather than passing "sensitive" to the
    factory, which the factory no longer even looks at.
    """
    from api.config import get_settings
    from api.services import chroma_client

    monkeypatch.setenv("DATABASE_DIR", str(tmp_path))
    get_settings.cache_clear()
    chroma_client._MODE_CACHE.clear()
    _write_project_row(tmp_path, "sec-crew", "sensitive")

    crew = _build_crew_for_project("sec-crew")
    assert len(crew.agents) == 3
    for agent in crew.agents:
        assert agent.llm.base_url is not None, (
            f"{agent.role} has no base_url - not routed to a local model"
        )
        assert "anthropic" not in str(agent.llm.model).lower(), (
            f"{agent.role} is on {agent.llm.model} - a sensitive project's interview answers "
            "must never reach a hosted model"
        )
    get_settings.cache_clear()


def test_a_standard_project_asks_the_registry_per_agent(monkeypatch, tmp_path):
    """The other side: standard still routes hosted, and each agent now asks for its own
    tier rather than sharing one factory-wide model - the Synthesis Analyst is deep, the
    Coordinator and Interviewer are fast. A shared-model implementation would pass a test
    that only checked "hosted", so this also proves the two tiers differ.
    """
    from api.config import get_settings
    from api.services import chroma_client

    monkeypatch.setenv("DATABASE_DIR", str(tmp_path))
    get_settings.cache_clear()
    chroma_client._MODE_CACHE.clear()
    _write_project_row(tmp_path, "std-crew", "standard")

    crew = _build_crew_for_project("std-crew")
    by_role = {agent.role: agent.llm for agent in crew.agents}
    for role, llm in by_role.items():
        # crewai.LLM strips the "anthropic/" prefix into llm_type and stores the bare model
        # name on .model, so the hosted signal is llm_type, not a substring of .model.
        assert llm.base_url is None, f"{role} is routed local on a standard project"
        assert llm.llm_type == "anthropic", f"{role} is on {llm.llm_type}:{llm.model}, not hosted"
    assert by_role["Synthesis Analyst"].model != by_role["Interview Coordinator"].model, (
        "the deep-tier Analyst and the fast-tier Coordinator resolved to the same model"
    )
    get_settings.cache_clear()


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
