# tests/test_run_service_interviews.py
"""Tests for the discovery_interviews branch in build_and_run_crew."""
import pytest
from unittest.mock import patch, AsyncMock, MagicMock


@pytest.mark.asyncio
async def test_build_and_run_crew_raises_for_non_agent_interview_method():
    """If interview_method != 'agent', discovery_interviews raises ValueError."""
    from api.database import get_connection, insert_project, insert_crew_run, fetch_project
    async with get_connection("rsi-test") as conn:
        await insert_project(
            conn, slug="rsi-test", llm_mode="standard", sector="rail",
            config_json='{"interview_method": "none"}'
        )
        project = await fetch_project(conn, slug="rsi-test")
        crew_run_id = await insert_crew_run(
            conn, project_id=project["id"], crew_name="discovery_interviews", status="running"
        )

    with patch("api.services.run_service.load_project_config",
               return_value={"llm_mode": "standard", "sector": "rail", "interview_method": "none"}):
        from api.services.run_service import build_and_run_crew
        with pytest.raises(ValueError, match="interview_method"):
            await build_and_run_crew("rsi-test", "discovery_interviews", crew_run_id)


@pytest.mark.asyncio
async def test_build_and_run_crew_calls_interviews_crew_when_agent():
    """If interview_method='agent', discovery_interviews crew is created and kicked off."""
    from api.database import get_connection, insert_project, insert_crew_run, fetch_project, insert_orchestration_run
    async with get_connection("rsi-agent-test") as conn:
        await insert_project(
            conn, slug="rsi-agent-test", llm_mode="standard", sector="rail",
            config_json='{"interview_method": "agent"}'
        )
        project = await fetch_project(conn, slug="rsi-agent-test")
        orch_run_id = await insert_orchestration_run(conn, project_id=project["id"])
        crew_run_id = await insert_crew_run(
            conn, project_id=project["id"], crew_name="discovery_interviews",
            status="running", orchestration_run_id=orch_run_id
        )

    mock_crew = MagicMock()
    mock_crew.kickoff_async = AsyncMock(return_value="done")

    with patch("api.services.run_service.load_project_config",
               return_value={"llm_mode": "standard", "sector": "rail", "interview_method": "agent"}), \
         patch("agents.crews.discovery_interviews_crew.create_discovery_interviews_crew",
               return_value=mock_crew) as mock_factory:
        from api.services.run_service import build_and_run_crew
        await build_and_run_crew("rsi-agent-test", "discovery_interviews", crew_run_id)

    mock_crew.kickoff_async.assert_awaited_once()
