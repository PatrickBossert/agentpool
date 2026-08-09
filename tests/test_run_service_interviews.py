# tests/test_run_service_interviews.py
"""Tests for the discovery_interviews branch in build_and_run_crew."""
import pytest
import pytest_asyncio
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


# ── Standalone Casey refuses while interviews are live ─────────────────────────
#
# Casey (synthesis_analyst) saturates the reasoning model while the fast model answers live
# follow-ups on the same machine. Inside the discovery_interviews crew this collision cannot
# happen: Process.sequential, Casey's task takes context_tasks=[t2], and Avery (the Stakeholder
# Interviewer) blocks on HumanInputTool until a consultant confirms every interview is complete.
# The standalone dispatch bypasses all of that - it builds Casey's task with context_tasks=[]
# and runs immediately - so it is the only reachable path and the only place a guard belongs.

async def _seed_project_with_sessions(slug: str, statuses: list[str]) -> None:
    """Insert a project, one stakeholder, and one interview session per status given."""
    from api.database import (
        get_connection, insert_project, fetch_project, insert_stakeholder,
        insert_interview_session, update_interview_session_status,
    )
    async with get_connection(slug) as conn:
        await insert_project(
            conn, slug=slug, llm_mode="standard", sector="rail", config_json="{}"
        )
        project = await fetch_project(conn, slug=slug)
        stakeholder_id = await insert_stakeholder(conn, project_id=project["id"], name="Alice")
        for i, status in enumerate(statuses):
            token = f"{slug}-session-{i}"
            await insert_interview_session(
                conn,
                project_id=project["id"],
                orchestration_run_id=None,
                stakeholder_id=stakeholder_id,
                node_label="exec_interview",
                session_token=token,
            )
            # insert_interview_session always starts a session as 'pending' — only move it on
            # if the fixture wants something else.
            if status != "pending":
                await update_interview_session_status(conn, token, status)


@pytest_asyncio.fixture
async def live_campaign(tmp_path, monkeypatch):
    """One project with a pending session and an active session - Casey must refuse."""
    import api.config as cfg
    cfg.get_settings.cache_clear()
    monkeypatch.setenv("DATABASE_DIR", str(tmp_path))
    cfg.get_settings.cache_clear()

    slug = "live-campaign"
    await _seed_project_with_sessions(slug, ["pending", "active"])
    yield slug
    cfg.get_settings.cache_clear()


@pytest_asyncio.fixture
async def completed_campaign(tmp_path, monkeypatch):
    """One project whose only sessions are completed/abandoned - Casey must be allowed to run."""
    import api.config as cfg
    cfg.get_settings.cache_clear()
    monkeypatch.setenv("DATABASE_DIR", str(tmp_path))
    cfg.get_settings.cache_clear()

    slug = "completed-campaign"
    await _seed_project_with_sessions(slug, ["completed", "abandoned"])
    yield slug
    cfg.get_settings.cache_clear()


@pytest.mark.asyncio
async def test_standalone_casey_refuses_while_interviews_are_live(live_campaign):
    """Driven through build_and_run_agent, not by calling a guard helper.

    A guard the dispatch does not consult is worthless, which this codebase has recorded seven
    times. The crew path already expresses "wait for interviews" correctly via Avery's HITL gate;
    this is the only path that bypasses it.
    """
    from api.services.run_service import build_and_run_agent
    with pytest.raises(ValueError, match="interview"):
        await build_and_run_agent(live_campaign, "synthesis_analyst", run_id=1)


@pytest.mark.asyncio
async def test_standalone_casey_runs_once_interviews_are_done(completed_campaign):
    """The guard must not block the normal case.

    Only completed/abandoned sessions exist, so the guard must pass through and the dispatch
    must reach crew.kickoff_async(). load_project_config, get_llm_for_agent and
    get_tools_for_agent are mocked the same way test_standalone_agent_dispatch.py mocks them for
    every other agent key - that file is the precedent for exercising build_and_run_agent without
    touching real Chroma/tool wiring, which is orthogonal to what this guard is about.
    """
    from crewai import LLM
    from api.services import run_service

    fake_crew = MagicMock()
    fake_crew.kickoff_async = AsyncMock(return_value="done")

    with patch("api.services.run_service.load_project_config", return_value={
                "llm_mode": "standard", "sector": "rail",
            }), \
         patch("agents.model_registry.get_llm_for_agent", return_value=MagicMock(spec=LLM)), \
         patch("agents.tools.registry.get_tools_for_agent", return_value=[]), \
         patch("api.services.run_service.make_step_callback", return_value=None), \
         patch("crewai.Crew", return_value=fake_crew):
        result = await run_service.build_and_run_agent(
            completed_campaign, "synthesis_analyst", run_id=1
        )

    assert result == "done"
    fake_crew.kickoff_async.assert_awaited_once()
