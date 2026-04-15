# tests/test_registry.py
"""Unit tests for tool registry hitl_tool injection."""
from unittest.mock import MagicMock


def test_hitl_tool_injection_replaces_human_input_tool():
    """When hitl_tool is provided, all HumanInputTool instances in the list are replaced."""
    from agents.tools.human_input import HumanInputTool
    from agents.tools.registry import get_tools_for_agent

    mock_hitl = MagicMock()
    tools = get_tools_for_agent(
        "initiative_identifier", slug="test", run_id=1, sector="test",
        hitl_tool=mock_hitl,
    )

    tool_types = [type(t) for t in tools]
    assert HumanInputTool not in tool_types, "HumanInputTool should have been replaced"
    assert mock_hitl in tools, "mock_hitl should be in the tool list"


def test_hitl_tool_none_uses_default_human_input_tool():
    """When hitl_tool is None (default), HumanInputTool is used as normal."""
    from agents.tools.human_input import HumanInputTool
    from agents.tools.registry import get_tools_for_agent

    tools = get_tools_for_agent(
        "initiative_identifier", slug="test", run_id=1, sector="test",
    )

    tool_types = [type(t) for t in tools]
    assert HumanInputTool in tool_types, "HumanInputTool should be present when no override given"
