# tests/test_pam_crew.py
"""Unit tests for the PAM orchestration crew."""
import pytest
from unittest.mock import MagicMock, patch
from crewai import LLM, Process


@pytest.fixture
def mock_llm():
    return MagicMock(spec=LLM)


def _build_crew(mock_llm):
    with patch("agents.crews.pam_crew.get_tools_for_agent", return_value=[]):
        from agents.crews.pam_crew import create_pam_crew
        return create_pam_crew(
            slug="test",
            orchestration_run_id=1,
            llm_mode="standard",
            llm=mock_llm,
        )


def test_pam_crew_has_one_agent(mock_llm):
    crew = _build_crew(mock_llm)
    assert len(crew.agents) == 1


def test_pam_crew_has_five_tasks(mock_llm):
    crew = _build_crew(mock_llm)
    assert len(crew.tasks) == 5


def test_pam_crew_sequential_process(mock_llm):
    crew = _build_crew(mock_llm)
    assert crew.process == Process.sequential


def test_pam_crew_tasks_reference_all_five_crews(mock_llm):
    """Each of the 5 sub-crew names appears somewhere in the task descriptions."""
    crew = _build_crew(mock_llm)
    all_descriptions = " ".join(t.description for t in crew.tasks)
    for crew_name in ("discovery", "value_design", "architecture", "delivery", "business_plan"):
        assert crew_name in all_descriptions, f"'{crew_name}' missing from task descriptions"


def test_pam_crew_tools_come_from_registry(mock_llm):
    """get_tools_for_agent is called with 'pam' and the orchestration_run_id as run_id."""
    with patch("agents.crews.pam_crew.get_tools_for_agent", return_value=[]) as mock_reg:
        from agents.crews.pam_crew import create_pam_crew
        create_pam_crew(
            slug="myslug",
            orchestration_run_id=77,
            llm_mode="standard",
            llm=mock_llm,
        )
    assert mock_reg.call_args_list, "get_tools_for_agent was never called"
    call = mock_reg.call_args_list[0]
    assert call.args[0] == "pam"
    assert call.kwargs.get("slug") == "myslug"
    assert call.kwargs.get("run_id") == 77
