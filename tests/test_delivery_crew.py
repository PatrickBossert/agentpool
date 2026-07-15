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


# ── Visual Illustrator ────────────────────────────────────────────────────────

def test_vi_agent_role(mock_llm):
    from agents.delivery.visual_illustrator import create_visual_illustrator
    agent = create_visual_illustrator(slug="test", llm=mock_llm, tools=[])
    assert agent.role == "Visual Illustrator"


def test_vi_task_reads_value_chain_registry(mock_llm):
    from agents.delivery.visual_illustrator import (
        create_visual_illustrator,
        create_visual_illustrator_task,
    )
    agent = create_visual_illustrator(slug="test", llm=mock_llm, tools=[])
    task = create_visual_illustrator_task(agent=agent, sector="energy", client_name="Acme")
    assert "key='value_chain_registry'" in task.description


def test_vi_task_reads_propositions(mock_llm):
    from agents.delivery.visual_illustrator import (
        create_visual_illustrator,
        create_visual_illustrator_task,
    )
    agent = create_visual_illustrator(slug="test", llm=mock_llm, tools=[])
    task = create_visual_illustrator_task(agent=agent, sector="energy", client_name="Acme")
    assert "key='propositions'" in task.description


def test_vi_task_writes_illustration_briefs(mock_llm):
    from agents.delivery.visual_illustrator import (
        create_visual_illustrator,
        create_visual_illustrator_task,
    )
    agent = create_visual_illustrator(slug="test", llm=mock_llm, tools=[])
    task = create_visual_illustrator_task(agent=agent, sector="energy", client_name="Acme")
    assert "key='illustration_briefs'" in task.description
    assert "operation='write'" in task.description


def test_vi_task_embeds_client_and_sector(mock_llm):
    from agents.delivery.visual_illustrator import (
        create_visual_illustrator,
        create_visual_illustrator_task,
    )
    agent = create_visual_illustrator(slug="test", llm=mock_llm, tools=[])
    task = create_visual_illustrator_task(agent=agent, sector="utilities", client_name="ScottishPower")
    assert "ScottishPower" in task.description
    assert "utilities" in task.description


def test_vi_task_has_hitl(mock_llm):
    from agents.delivery.visual_illustrator import (
        create_visual_illustrator,
        create_visual_illustrator_task,
    )
    agent = create_visual_illustrator(slug="test", llm=mock_llm, tools=[])
    task = create_visual_illustrator_task(agent=agent, sector="energy", client_name="Acme")
    assert "HumanInputTool" in task.description
    assert "approved" in task.description


# ── Crew wiring ───────────────────────────────────────────────────────────────

def test_delivery_crew_has_two_agents(mock_llm):
    with patch("agents.tools.registry.get_tools_for_agent", return_value=[]):
        from agents.crews.delivery_crew import create_delivery_crew
        crew = create_delivery_crew(
            slug="test", run_id=1, llm_mode="standard", sector="logistics",
            value_stream_labels=_VALUE_STREAMS, stakeholder_groups=_STAKEHOLDER_GROUPS,
            roadmap_time_axis=_TIME_AXIS, llm=mock_llm,
        )
    assert len(crew.agents) == 2


def test_delivery_crew_agent_roles(mock_llm):
    with patch("agents.tools.registry.get_tools_for_agent", return_value=[]):
        from agents.crews.delivery_crew import create_delivery_crew
        crew = create_delivery_crew(
            slug="test", run_id=1, llm_mode="standard", sector="logistics",
            value_stream_labels=_VALUE_STREAMS, stakeholder_groups=_STAKEHOLDER_GROUPS,
            roadmap_time_axis=_TIME_AXIS, llm=mock_llm,
        )
    roles = [a.role for a in crew.agents]
    assert "Roadmap Generator" in roles
    assert "Visual Illustrator" in roles


def test_delivery_crew_sequential_process(mock_llm):
    from crewai import Process
    with patch("agents.tools.registry.get_tools_for_agent", return_value=[]):
        from agents.crews.delivery_crew import create_delivery_crew
        crew = create_delivery_crew(
            slug="test", run_id=1, llm_mode="standard", sector="logistics",
            value_stream_labels=_VALUE_STREAMS, stakeholder_groups=_STAKEHOLDER_GROUPS,
            roadmap_time_axis=_TIME_AXIS, llm=mock_llm,
        )
    assert crew.process == Process.sequential


def test_delivery_crew_sensitive_mode_uses_local_llm(mock_llm):
    """In sensitive mode, get_crew_llm is called with 'sensitive'."""
    with patch("agents.tools.registry.get_tools_for_agent", return_value=[]), \
         patch("agents.crews.delivery_crew.get_crew_llm") as mock_get_llm:
        mock_get_llm.return_value = mock_llm
        from agents.crews.delivery_crew import create_delivery_crew
        create_delivery_crew(
            slug="test", run_id=1, llm_mode="sensitive", sector="logistics",
            value_stream_labels=_VALUE_STREAMS, stakeholder_groups=_STAKEHOLDER_GROUPS,
            roadmap_time_axis=_TIME_AXIS,
        )
    mock_get_llm.assert_called_once_with("sensitive")


def test_delivery_crew_accepts_hitl_tool_override(mock_llm):
    """hitl_tool is forwarded to get_tools_for_agent."""
    mock_hitl = MagicMock()
    with patch("agents.crews.delivery_crew.get_tools_for_agent", return_value=[]) as mock_reg:
        from agents.crews.delivery_crew import create_delivery_crew
        create_delivery_crew(
            slug="test", run_id=1, llm_mode="standard", sector="logistics",
            value_stream_labels=["A", "B"], stakeholder_groups=["X"],
            roadmap_time_axis="quarters", llm=mock_llm, hitl_tool=mock_hitl,
        )
    assert mock_reg.call_args_list, "get_tools_for_agent was never called"
    for call in mock_reg.call_args_list:
        assert call.kwargs.get("hitl_tool") == mock_hitl, \
            f"Expected hitl_tool in call: {call}"
