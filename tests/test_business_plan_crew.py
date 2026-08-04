# tests/test_business_plan_crew.py
"""Unit tests for Business Plan Generator crew agent and crew assembly."""
import pytest
from unittest.mock import MagicMock, patch
from crewai import LLM


@pytest.fixture
def mock_llm():
    return MagicMock(spec=LLM)


# ── Business Plan Generator agent ─────────────────────────────────────────────

def test_bpg_agent_role(mock_llm):
    from agents.business_plan.business_plan_generator import create_business_plan_generator
    agent = create_business_plan_generator(slug="test", llm=mock_llm, tools=[])
    assert agent.role == "Business Plan Generator"


def test_bpg_task_reads_all_inputs(mock_llm):
    """Task description references all five required SQLite keys."""
    from agents.business_plan.business_plan_generator import (
        create_business_plan_generator,
        create_business_plan_generator_task,
    )
    agent = create_business_plan_generator(slug="test", llm=mock_llm, tools=[])
    task = create_business_plan_generator_task(agent=agent)
    # Both requirement levels by name: it runs last and is the one consumer that wants
    # the strategic framing and the delivery detail rather than whichever ran last.
    for key in ("strategic_requirements", "requirements_analysis", "value_levers",
                "propositions", "initiative_register", "roadmap_data"):
        assert f"key='{key}'" in task.description, f"Missing key='{key}' in task description"


def test_bpg_task_calls_word_output_tool(mock_llm):
    from agents.business_plan.business_plan_generator import (
        create_business_plan_generator,
        create_business_plan_generator_task,
    )
    agent = create_business_plan_generator(slug="test", llm=mock_llm, tools=[])
    task = create_business_plan_generator_task(agent=agent)
    assert "WordOutputTool" in task.description


def test_bpg_task_calls_powerpoint_output_tool(mock_llm):
    from agents.business_plan.business_plan_generator import (
        create_business_plan_generator,
        create_business_plan_generator_task,
    )
    agent = create_business_plan_generator(slug="test", llm=mock_llm, tools=[])
    task = create_business_plan_generator_task(agent=agent)
    assert "PowerPointOutputTool" in task.description


def test_bpg_task_calls_financial_model_tool(mock_llm):
    from agents.business_plan.business_plan_generator import (
        create_business_plan_generator,
        create_business_plan_generator_task,
    )
    agent = create_business_plan_generator(slug="test", llm=mock_llm, tools=[])
    task = create_business_plan_generator_task(agent=agent)
    assert "FinancialModelTool" in task.description


def test_bpg_task_has_context_gathering_hitl(mock_llm):
    """First HumanInputTool call asks for org name and financial confirmation."""
    from agents.business_plan.business_plan_generator import (
        create_business_plan_generator,
        create_business_plan_generator_task,
    )
    agent = create_business_plan_generator(slug="test", llm=mock_llm, tools=[])
    task = create_business_plan_generator_task(agent=agent)
    assert "HumanInputTool" in task.description
    assert "organisation name" in task.description.lower()


def test_bpg_task_has_no_review_gate(mock_llm):
    """The second HumanInputTool call — the end-of-phase approval gate — is gone.
    Approval is now recorded outside the run, in approval_commits."""
    from agents.business_plan.business_plan_generator import (
        create_business_plan_generator,
        create_business_plan_generator_task,
    )
    agent = create_business_plan_generator(slug="test", llm=mock_llm, tools=[])
    task = create_business_plan_generator_task(agent=agent)
    assert "approved" not in task.description.lower()


# ── Crew wiring ───────────────────────────────────────────────────────────────

def test_business_plan_crew_carries_the_writer_and_the_illustrator(mock_llm):
    with patch("agents.tools.registry.get_tools_for_agent", return_value=[]):
        from agents.crews.business_plan_crew import create_business_plan_crew
        crew = create_business_plan_crew(
            slug="test", run_id=1, llm_mode="standard", sector="logistics", llm=mock_llm
        )
    # Named rather than counted: a count of two is equally true of the wrong two. The
    # Illustrator moved here from delivery, where he could see only the roadmap.
    assert [a.role for a in crew.agents] == ['Business Plan Generator', 'Visual Illustrator']


def test_business_plan_crew_sequential_process(mock_llm):
    from crewai import Process
    with patch("agents.tools.registry.get_tools_for_agent", return_value=[]):
        from agents.crews.business_plan_crew import create_business_plan_crew
        crew = create_business_plan_crew(
            slug="test", run_id=1, llm_mode="standard", sector="logistics", llm=mock_llm
        )
    assert crew.process == Process.sequential


def test_business_plan_crew_sensitive_mode_uses_local_llm(mock_llm):
    """In sensitive mode, get_crew_llm is called with 'sensitive'."""
    with patch("agents.tools.registry.get_tools_for_agent", return_value=[]), \
         patch("agents.crews.business_plan_crew.get_crew_llm") as mock_get_llm:
        mock_get_llm.return_value = mock_llm
        from agents.crews.business_plan_crew import create_business_plan_crew
        create_business_plan_crew(
            slug="test", run_id=1, llm_mode="sensitive", sector="logistics"
        )
    mock_get_llm.assert_called_once_with("sensitive")


def test_business_plan_crew_standard_mode_uses_opus(mock_llm):
    """Standard mode calls get_pam_llm (Opus 4.6), not get_crew_llm."""
    with patch("agents.tools.registry.get_tools_for_agent", return_value=[]), \
         patch("agents.crews.business_plan_crew.get_pam_llm") as mock_pam:
        mock_pam.return_value = mock_llm
        from agents.crews.business_plan_crew import create_business_plan_crew
        create_business_plan_crew(
            slug="test", run_id=1, llm_mode="standard", sector="logistics"
        )
    mock_pam.assert_called_once()


def test_business_plan_crew_accepts_hitl_tool_override(mock_llm):
    """hitl_tool is forwarded to get_tools_for_agent."""
    mock_hitl = MagicMock()
    with patch("agents.crews.business_plan_crew.get_tools_for_agent", return_value=[]) as mock_reg:
        from agents.crews.business_plan_crew import create_business_plan_crew
        create_business_plan_crew(
            slug="test", run_id=1, llm_mode="standard", sector="logistics",
            llm=mock_llm, hitl_tool=mock_hitl,
        )
    # Both agents, not just the writer. Asserting a single call was only ever true because
    # the crew held one agent, and an Illustrator that could not raise a review gate would
    # be a quiet gap rather than a visible one.
    for agent in ("business_plan_generator", "visual_illustrator"):
        mock_reg.assert_any_call(
            agent, slug="test", run_id=1, sector="logistics", hitl_tool=mock_hitl,
        )
    assert mock_reg.call_count == 2
