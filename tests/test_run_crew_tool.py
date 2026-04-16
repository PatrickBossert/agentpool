# tests/test_run_crew_tool.py
"""Unit tests for RunCrewTool."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch, call


def _make_tool(slug="acme", orchestration_run_id=99):
    from agents.tools.run_crew import RunCrewTool
    return RunCrewTool(slug=slug, orchestration_run_id=orchestration_run_id)


@pytest.mark.asyncio
async def test_arun_creates_crew_run_record(monkeypatch, tmp_path):
    """insert_crew_run is called before kickoff_async."""
    mock_project = {"id": 1}
    mock_run_id = 42

    with patch("api.database.get_connection") as mock_ctx, \
         patch("api.database.fetch_project", new_callable=AsyncMock, return_value=mock_project), \
         patch("api.database.insert_crew_run", new_callable=AsyncMock, return_value=mock_run_id) as mock_insert, \
         patch("api.database.update_crew_run_status", new_callable=AsyncMock), \
         patch("api.services.run_service.build_and_run_crew", new_callable=AsyncMock, return_value="ok"):

        mock_conn = AsyncMock()
        mock_conn.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_conn.__aexit__ = AsyncMock(return_value=False)
        mock_ctx.return_value = mock_conn

        tool = _make_tool()
        await tool._arun("discovery")

    mock_insert.assert_awaited()


@pytest.mark.asyncio
async def test_arun_marks_completed_on_success():
    """On success, update_crew_run_status is called with status='completed'."""
    mock_project = {"id": 1}

    with patch("api.database.get_connection") as mock_ctx, \
         patch("api.database.fetch_project", new_callable=AsyncMock, return_value=mock_project), \
         patch("api.database.insert_crew_run", new_callable=AsyncMock, return_value=10), \
         patch("api.database.update_crew_run_status", new_callable=AsyncMock) as mock_update, \
         patch("api.services.run_service.build_and_run_crew", new_callable=AsyncMock, return_value="done"):

        mock_conn = AsyncMock()
        mock_conn.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_conn.__aexit__ = AsyncMock(return_value=False)
        mock_ctx.return_value = mock_conn

        tool = _make_tool()
        result = await tool._arun("discovery")

    calls = mock_update.call_args_list
    statuses = [c.kwargs.get("status") for c in calls]
    assert "completed" in statuses
    assert result == "done"


@pytest.mark.asyncio
async def test_arun_marks_failed_on_exception():
    """On exception, update_crew_run_status is called with status='failed' and error string returned."""
    mock_project = {"id": 1}

    with patch("api.database.get_connection") as mock_ctx, \
         patch("api.database.fetch_project", new_callable=AsyncMock, return_value=mock_project), \
         patch("api.database.insert_crew_run", new_callable=AsyncMock, return_value=10), \
         patch("api.database.update_crew_run_status", new_callable=AsyncMock) as mock_update, \
         patch("api.services.run_service.build_and_run_crew", new_callable=AsyncMock, side_effect=RuntimeError("boom")):

        mock_conn = AsyncMock()
        mock_conn.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_conn.__aexit__ = AsyncMock(return_value=False)
        mock_ctx.return_value = mock_conn

        tool = _make_tool()
        result = await tool._arun("discovery")

    calls = mock_update.call_args_list
    statuses = [c.kwargs.get("status") for c in calls]
    assert "failed" in statuses
    assert "Error running discovery" in result
    assert "boom" in result


@pytest.mark.asyncio
@pytest.mark.parametrize("crew_name", [
    "discovery", "value_design", "architecture", "delivery", "business_plan"
])
async def test_arun_calls_build_and_run_crew_with_correct_name(crew_name):
    """build_and_run_crew is called with the crew_name argument passed to _arun."""
    mock_project = {"id": 1}

    with patch("api.database.get_connection") as mock_ctx, \
         patch("api.database.fetch_project", new_callable=AsyncMock, return_value=mock_project), \
         patch("api.database.insert_crew_run", new_callable=AsyncMock, return_value=1), \
         patch("api.database.update_crew_run_status", new_callable=AsyncMock), \
         patch("api.services.run_service.build_and_run_crew", new_callable=AsyncMock, return_value="ok") as mock_build:

        mock_conn = AsyncMock()
        mock_conn.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_conn.__aexit__ = AsyncMock(return_value=False)
        mock_ctx.return_value = mock_conn

        tool = _make_tool()
        await tool._arun(crew_name)

    first_call_args = mock_build.call_args
    assert first_call_args.args[1] == crew_name


@pytest.mark.asyncio
async def test_arun_returns_result_string():
    """The string result of build_and_run_crew is returned."""
    mock_project = {"id": 1}

    with patch("api.database.get_connection") as mock_ctx, \
         patch("api.database.fetch_project", new_callable=AsyncMock, return_value=mock_project), \
         patch("api.database.insert_crew_run", new_callable=AsyncMock, return_value=1), \
         patch("api.database.update_crew_run_status", new_callable=AsyncMock), \
         patch("api.services.run_service.build_and_run_crew", new_callable=AsyncMock, return_value="my result"):

        mock_conn = AsyncMock()
        mock_conn.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_conn.__aexit__ = AsyncMock(return_value=False)
        mock_ctx.return_value = mock_conn

        tool = _make_tool()
        result = await tool._arun("business_plan")

    assert result == "my result"
