# tests/test_pam_crew.py
"""Unit tests for the PAM orchestration crews."""
import pytest
from unittest.mock import MagicMock, patch
from crewai import LLM, Process


@pytest.fixture
def mock_llm():
    return MagicMock(spec=LLM)


def _build_mapping_crew(mock_llm):
    with patch("agents.crews.pam_crew.get_tools_for_agent", return_value=[]):
        from agents.crews.pam_crew import create_pam_mapping_crew
        return create_pam_mapping_crew(
            slug="test",
            orchestration_run_id=1,
            llm_mode="standard",
            llm=mock_llm,
        )


def _build_resume_crew(mock_llm):
    with patch("agents.crews.pam_crew.get_tools_for_agent", return_value=[]):
        from agents.crews.pam_crew import create_pam_resume_crew
        return create_pam_resume_crew(
            slug="test",
            orchestration_run_id=1,
            llm_mode="standard",
            llm=mock_llm,
        )


# ── mapping crew ──────────────────────────────────────────────────────────────

def test_pam_mapping_crew_has_one_agent(mock_llm):
    crew = _build_mapping_crew(mock_llm)
    assert len(crew.agents) == 1


def test_pam_mapping_crew_has_one_task(mock_llm):
    crew = _build_mapping_crew(mock_llm)
    assert len(crew.tasks) == 1


def test_pam_mapping_crew_task_references_discovery_mapping(mock_llm):
    crew = _build_mapping_crew(mock_llm)
    assert "discovery_mapping" in crew.tasks[0].description


def test_pam_mapping_crew_sequential_process(mock_llm):
    crew = _build_mapping_crew(mock_llm)
    assert crew.process == Process.sequential


# ── resume crew ───────────────────────────────────────────────────────────────

def test_pam_resume_crew_has_one_agent(mock_llm):
    crew = _build_resume_crew(mock_llm)
    assert len(crew.agents) == 1


def test_pam_resume_crew_has_four_tasks(mock_llm):
    crew = _build_resume_crew(mock_llm)
    assert len(crew.tasks) == 4


def test_pam_resume_crew_tasks_reference_all_four_crews(mock_llm):
    crew = _build_resume_crew(mock_llm)
    all_descriptions = " ".join(t.description for t in crew.tasks)
    for name in ("value_design", "architecture", "delivery", "business_plan"):
        assert name in all_descriptions, f"'{name}' missing from task descriptions"


def test_pam_resume_crew_sequential_process(mock_llm):
    crew = _build_resume_crew(mock_llm)
    assert crew.process == Process.sequential


def test_pam_crews_use_registry(mock_llm):
    """get_tools_for_agent is called with 'pam' for both crews."""
    with patch("agents.crews.pam_crew.get_tools_for_agent", return_value=[]) as mock_reg:
        from agents.crews.pam_crew import create_pam_mapping_crew
        create_pam_mapping_crew(slug="myslug", orchestration_run_id=77, llm_mode="standard", llm=mock_llm)
    call = mock_reg.call_args_list[0]
    assert call.args[0] == "pam"
    assert call.kwargs.get("slug") == "myslug"
    assert call.kwargs.get("run_id") == 77
