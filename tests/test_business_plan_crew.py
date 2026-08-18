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

# Every patch below targets agents.crews.business_plan_crew.get_tools_for_agent - the module
# that *looks the name up* - not agents.tools.registry, where it is defined. The crew module
# binds the function into its own namespace with `from ... import`, so patching the registry
# leaves that binding pointing at the real function.
#
# These four tests used to patch the registry and still passed, which is the part worth
# remembering. The `import` sits inside the with-block, so the first test to run imported the
# crew module while the mock was installed and the module kept that MagicMock for the rest of
# the session - one test poisoning the module made the next three pass. Alone: 12 passed.
# Behind any suite member that imports the crew module first: 4 failed.


def test_business_plan_crew_carries_the_writer_and_the_illustrator(mock_llm):
    with patch("agents.crews.business_plan_crew.get_tools_for_agent", return_value=[]):
        from agents.crews.business_plan_crew import create_business_plan_crew
        crew = create_business_plan_crew(
            slug="test", run_id=1, sector="logistics", llm=mock_llm
        )
    # Named rather than counted: a count of two is equally true of the wrong two. The
    # Illustrator moved here from delivery, where he could see only the roadmap.
    assert [a.role for a in crew.agents] == ['Business Plan Generator', 'Visual Illustrator']


def test_business_plan_crew_sequential_process(mock_llm):
    from crewai import Process
    with patch("agents.crews.business_plan_crew.get_tools_for_agent", return_value=[]):
        from agents.crews.business_plan_crew import create_business_plan_crew
        crew = create_business_plan_crew(
            slug="test", run_id=1, sector="logistics", llm=mock_llm
        )
    assert crew.process == Process.sequential


def test_business_plan_crew_asks_the_registry_per_agent(mock_llm):
    """No llm override: both the Writer and the Illustrator must ask
    agents/model_registry.py by their own agent name, not share one factory-resolved model.
    Patched where the name is looked up - agents.crews.business_plan_crew binds its own
    reference via `from ... import` - not agents.model_registry, where it is defined."""
    with patch("agents.crews.business_plan_crew.get_tools_for_agent", return_value=[]), \
         patch("agents.crews.business_plan_crew.get_llm_for_agent") as mock_get_llm:
        mock_get_llm.return_value = mock_llm
        from agents.crews.business_plan_crew import create_business_plan_crew
        create_business_plan_crew(
            slug="test", run_id=1, sector="logistics"
        )
    mock_get_llm.assert_any_call("business_plan_generator", "test")
    mock_get_llm.assert_any_call("visual_illustrator", "test")
    assert mock_get_llm.call_count == 2


def test_every_agent_in_the_crew_is_given_the_registry_tools_for_its_own_name(mock_llm):
    """Both agents, not just the writer.

    Asserting a single call was only ever true because the crew held one agent, and an agent
    built with a tool list assembled for a different name would be a quiet gap rather than a
    visible one. What was asserted alongside it - that a caller's own review tool was forwarded
    into every call - went with the registry parameter that allowed it, and the keywords below
    are now the whole call.
    """
    with patch("agents.crews.business_plan_crew.get_tools_for_agent", return_value=[]) as mock_reg:
        from agents.crews.business_plan_crew import create_business_plan_crew
        create_business_plan_crew(slug="test", run_id=1, sector="logistics", llm=mock_llm)

    for agent in ("business_plan_generator", "visual_illustrator"):
        mock_reg.assert_any_call(agent, slug="test", run_id=1, sector="logistics")
    assert mock_reg.call_count == 2
