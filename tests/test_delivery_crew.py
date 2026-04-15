# tests/test_delivery_crew.py
"""Unit tests for Delivery Planning crew agent and crew assembly."""
import pytest
from unittest.mock import MagicMock, patch
from crewai import LLM


@pytest.fixture
def mock_llm():
    return MagicMock(spec=LLM)


_VALUE_STREAMS = ["Operations", "IT"]
_STAKEHOLDER_GROUPS = ["Investor", "Customer", "Operations", "IT"]
_TIME_AXIS = "quarters"


# ── Roadmap Generator ─────────────────────────────────────────────────────────

def test_rg_agent_role(mock_llm):
    from agents.delivery.roadmap_generator import create_roadmap_generator
    agent = create_roadmap_generator(slug="test", llm=mock_llm, tools=[])
    assert agent.role == "Roadmap Generator"


def test_rg_task_reads_initiative_register(mock_llm):
    from agents.delivery.roadmap_generator import (
        create_roadmap_generator,
        create_roadmap_generator_task,
    )
    agent = create_roadmap_generator(slug="test", llm=mock_llm, tools=[])
    task = create_roadmap_generator_task(
        agent=agent,
        value_stream_labels=_VALUE_STREAMS,
        stakeholder_groups=_STAKEHOLDER_GROUPS,
        roadmap_time_axis=_TIME_AXIS,
    )
    assert "key='initiative_register'" in task.description


def test_rg_task_reads_propositions(mock_llm):
    from agents.delivery.roadmap_generator import (
        create_roadmap_generator,
        create_roadmap_generator_task,
    )
    agent = create_roadmap_generator(slug="test", llm=mock_llm, tools=[])
    task = create_roadmap_generator_task(
        agent=agent,
        value_stream_labels=_VALUE_STREAMS,
        stakeholder_groups=_STAKEHOLDER_GROUPS,
        roadmap_time_axis=_TIME_AXIS,
    )
    assert "key='propositions'" in task.description


def test_rg_task_reads_value_levers(mock_llm):
    from agents.delivery.roadmap_generator import (
        create_roadmap_generator,
        create_roadmap_generator_task,
    )
    agent = create_roadmap_generator(slug="test", llm=mock_llm, tools=[])
    task = create_roadmap_generator_task(
        agent=agent,
        value_stream_labels=_VALUE_STREAMS,
        stakeholder_groups=_STAKEHOLDER_GROUPS,
        roadmap_time_axis=_TIME_AXIS,
    )
    assert "key='value_levers'" in task.description


def test_rg_task_writes_roadmap_data(mock_llm):
    from agents.delivery.roadmap_generator import (
        create_roadmap_generator,
        create_roadmap_generator_task,
    )
    agent = create_roadmap_generator(slug="test", llm=mock_llm, tools=[])
    task = create_roadmap_generator_task(
        agent=agent,
        value_stream_labels=_VALUE_STREAMS,
        stakeholder_groups=_STAKEHOLDER_GROUPS,
        roadmap_time_axis=_TIME_AXIS,
    )
    assert "key='roadmap_data'" in task.description
    assert "operation='write'" in task.description


def test_rg_task_calls_html_roadmap_tool(mock_llm):
    from agents.delivery.roadmap_generator import (
        create_roadmap_generator,
        create_roadmap_generator_task,
    )
    agent = create_roadmap_generator(slug="test", llm=mock_llm, tools=[])
    task = create_roadmap_generator_task(
        agent=agent,
        value_stream_labels=_VALUE_STREAMS,
        stakeholder_groups=_STAKEHOLDER_GROUPS,
        roadmap_time_axis=_TIME_AXIS,
    )
    assert "HtmlRoadmapTool" in task.description


def test_rg_task_has_hitl(mock_llm):
    from agents.delivery.roadmap_generator import (
        create_roadmap_generator,
        create_roadmap_generator_task,
    )
    agent = create_roadmap_generator(slug="test", llm=mock_llm, tools=[])
    task = create_roadmap_generator_task(
        agent=agent,
        value_stream_labels=_VALUE_STREAMS,
        stakeholder_groups=_STAKEHOLDER_GROUPS,
        roadmap_time_axis=_TIME_AXIS,
    )
    assert "HumanInputTool" in task.description
    assert "approved" in task.description


def test_rg_task_embeds_config_values(mock_llm):
    """Task description embeds value_stream_labels, stakeholder_groups, and time axis."""
    from agents.delivery.roadmap_generator import (
        create_roadmap_generator,
        create_roadmap_generator_task,
    )
    agent = create_roadmap_generator(slug="test", llm=mock_llm, tools=[])
    task = create_roadmap_generator_task(
        agent=agent,
        value_stream_labels=["Logistics", "Finance"],
        stakeholder_groups=["CEO", "CFO"],
        roadmap_time_axis="horizons",
    )
    assert "Logistics" in task.description
    assert "Finance" in task.description
    assert "CEO" in task.description
    assert "horizons" in task.description
