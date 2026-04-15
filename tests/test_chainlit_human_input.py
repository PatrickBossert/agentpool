# tests/test_chainlit_human_input.py
"""Unit tests for ChainlitHumanInputTool."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


@pytest.fixture
def tool():
    from agents.tools.chainlit_human_input import ChainlitHumanInputTool
    return ChainlitHumanInputTool(slug="test-proj", run_id=42)


@pytest.mark.asyncio
async def test_arun_returns_user_response(tool):
    with patch("chainlit.AskUserMessage") as mock_ask, \
         patch("agents.tools.chainlit_human_input.insert_hitl_review", return_value=1), \
         patch("agents.tools.chainlit_human_input.complete_hitl_review"):
        mock_ask.return_value.send = AsyncMock(return_value={"output": "approved"})
        result = await tool._arun("Please approve the value chain.")
    assert result == "approved"


@pytest.mark.asyncio
async def test_arun_writes_audit_record(tool):
    with patch("chainlit.AskUserMessage") as mock_ask, \
         patch("agents.tools.chainlit_human_input.insert_hitl_review", return_value=1) as mock_insert, \
         patch("agents.tools.chainlit_human_input.complete_hitl_review"):
        mock_ask.return_value.send = AsyncMock(return_value={"output": "ok"})
        await tool._arun("Review this output.")
    mock_insert.assert_called_once_with(slug="test-proj", run_id=42, prompt="Review this output.")


@pytest.mark.asyncio
async def test_arun_completes_audit_record(tool):
    with patch("chainlit.AskUserMessage") as mock_ask, \
         patch("agents.tools.chainlit_human_input.insert_hitl_review", return_value=7), \
         patch("agents.tools.chainlit_human_input.complete_hitl_review") as mock_complete:
        mock_ask.return_value.send = AsyncMock(return_value={"output": "approved"})
        await tool._arun("Approve?")
    mock_complete.assert_called_once_with(slug="test-proj", review_id=7, decision="approved")


@pytest.mark.asyncio
async def test_arun_on_timeout_returns_timeout_string(tool):
    with patch("chainlit.AskUserMessage") as mock_ask, \
         patch("agents.tools.chainlit_human_input.insert_hitl_review", return_value=1), \
         patch("agents.tools.chainlit_human_input.complete_hitl_review"):
        mock_ask.return_value.send = AsyncMock(return_value=None)
        result = await tool._arun("Approve?")
    assert result.startswith("timeout:")


@pytest.mark.asyncio
async def test_arun_db_error_returns_error_string(tool):
    with patch("agents.tools.chainlit_human_input.insert_hitl_review",
               side_effect=RuntimeError("db down")):
        result = await tool._arun("Approve?")
    assert result.startswith("Error:")


def test_tool_name_is_HumanInputTool(tool):
    assert tool.name == "HumanInputTool"
