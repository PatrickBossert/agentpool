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
    for key in ("requirements", "value_levers", "propositions", "initiative_register", "roadmap_data"):
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


def test_bpg_task_has_review_hitl(mock_llm):
    """Second HumanInputTool call asks for approval of generated artefacts."""
    from agents.business_plan.business_plan_generator import (
        create_business_plan_generator,
        create_business_plan_generator_task,
    )
    agent = create_business_plan_generator(slug="test", llm=mock_llm, tools=[])
    task = create_business_plan_generator_task(agent=agent)
    assert "approved" in task.description
