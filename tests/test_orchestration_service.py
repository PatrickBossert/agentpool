# tests/test_orchestration_service.py
"""Unit tests for orchestration service and /orchestrate endpoint."""
import pytest
from unittest.mock import patch, AsyncMock


PROJECT_PAYLOAD = {
    "client_slug": "orch-api-test",
    "llm_mode": "standard",
    "sector": "transport",
    "stakeholder_groups": ["Ops"],
    "value_stream_labels": ["Ops"],
    "crews_enabled": ["discovery"],
    "review_gates": True,
    "slack_channel": "",
}


@pytest.mark.asyncio
async def test_start_orchestration_creates_db_record():
    """start_orchestration inserts a row in orchestration_runs and returns an integer id."""
    with patch("api.services.orchestration_service.run_pam_phase1", new_callable=AsyncMock):
        with patch("asyncio.create_task"):
            from api.database import get_connection, insert_project
            async with get_connection("orch-svc-test") as conn:
                await insert_project(
                    conn, slug="orch-svc-test",
                    llm_mode="standard", sector="rail", config_json="{}"
                )
            from api.services.orchestration_service import start_orchestration
            run_id = await start_orchestration("orch-svc-test")

    assert isinstance(run_id, int)
    assert run_id > 0


@pytest.mark.asyncio
async def test_start_orchestration_returns_run_id():
    """The returned int is the primary key of the new orchestration_runs row."""
    with patch("asyncio.create_task"):
        with patch("api.services.orchestration_service.run_pam_phase1", new_callable=AsyncMock):
            from api.database import get_connection, insert_project, fetch_orchestration_run
            async with get_connection("orch-return-test") as conn:
                await insert_project(
                    conn, slug="orch-return-test",
                    llm_mode="standard", sector="rail", config_json="{}"
                )
            from api.services.orchestration_service import start_orchestration
            run_id = await start_orchestration("orch-return-test")

    async with get_connection("orch-return-test") as conn:
        row = await fetch_orchestration_run(conn, run_id=run_id)

    assert row is not None
    assert row["id"] == run_id
    assert row["status"] == "running"


@pytest.mark.asyncio
async def test_start_orchestration_fires_background_task():
    """start_orchestration calls asyncio.create_task."""
    with patch("asyncio.create_task") as mock_task, \
         patch("api.services.orchestration_service.run_pam_phase1", new_callable=AsyncMock):
        from api.database import get_connection, insert_project
        async with get_connection("orch-bg-test") as conn:
            await insert_project(
                conn, slug="orch-bg-test",
                llm_mode="standard", sector="rail", config_json="{}"
            )
        from api.services.orchestration_service import start_orchestration
        await start_orchestration("orch-bg-test")

    mock_task.assert_called_once()


@pytest.mark.asyncio
async def test_run_pam_phase1_sets_awaiting_assignment_on_success():
    """run_pam_phase1 sets status to 'awaiting_assignment' when crew succeeds."""
    from api.database import get_connection, insert_project, fetch_orchestration_run, insert_orchestration_run, fetch_project

    async with get_connection("orch-phase1-test") as conn:
        await insert_project(
            conn, slug="orch-phase1-test",
            llm_mode="standard", sector="rail", config_json="{}"
        )
        project = await fetch_project(conn, slug="orch-phase1-test")
        run_id = await insert_orchestration_run(conn, project_id=project["id"])

    mock_crew = AsyncMock()
    mock_crew.kickoff_async = AsyncMock(return_value=None)

    with patch("api.services.orchestration_service.load_project_config", return_value={"llm_mode": "standard"}), \
         patch("agents.crews.pam_crew.create_pam_mapping_crew", return_value=mock_crew):
        from api.services.orchestration_service import run_pam_phase1
        await run_pam_phase1("orch-phase1-test", run_id)

    async with get_connection("orch-phase1-test") as conn:
        row = await fetch_orchestration_run(conn, run_id=run_id)

    assert row["status"] == "awaiting_assignment"


@pytest.mark.asyncio
async def test_run_pam_phase1_sets_failed_on_exception():
    """run_pam_phase1 updates status to 'failed' when the crew raises."""
    from api.database import get_connection, insert_project, fetch_orchestration_run, insert_orchestration_run, fetch_project

    async with get_connection("orch-fail-test") as conn:
        await insert_project(
            conn, slug="orch-fail-test",
            llm_mode="standard", sector="rail", config_json="{}"
        )
        project = await fetch_project(conn, slug="orch-fail-test")
        run_id = await insert_orchestration_run(conn, project_id=project["id"])

    with patch("agents.crews.pam_crew.create_pam_mapping_crew", side_effect=RuntimeError("boom")):
        from api.services.orchestration_service import run_pam_phase1
        await run_pam_phase1("orch-fail-test", run_id)

    async with get_connection("orch-fail-test") as conn:
        row = await fetch_orchestration_run(conn, run_id=run_id)

    assert row["status"] == "failed"


@pytest.mark.asyncio
async def test_run_pam_phase2_sets_completed_on_success():
    """run_pam_phase2 sets status to 'completed' when resume crew succeeds."""
    from api.database import get_connection, insert_project, fetch_orchestration_run, insert_orchestration_run, fetch_project

    async with get_connection("orch-phase2-test") as conn:
        await insert_project(
            conn, slug="orch-phase2-test",
            llm_mode="standard", sector="rail", config_json="{}"
        )
        project = await fetch_project(conn, slug="orch-phase2-test")
        run_id = await insert_orchestration_run(conn, project_id=project["id"])

    mock_crew = AsyncMock()
    mock_crew.kickoff_async = AsyncMock(return_value=None)

    with patch("api.services.orchestration_service.load_project_config", return_value={"llm_mode": "standard"}), \
         patch("agents.crews.pam_crew.create_pam_resume_crew", return_value=mock_crew):
        from api.services.orchestration_service import run_pam_phase2
        await run_pam_phase2("orch-phase2-test", run_id)

    async with get_connection("orch-phase2-test") as conn:
        row = await fetch_orchestration_run(conn, run_id=run_id)

    assert row["status"] == "completed"


@pytest.mark.asyncio
async def test_resume_orchestration_sets_status_running_and_fires_phase2():
    """resume_orchestration updates DB to 'running' and creates a task for phase2."""
    from api.database import get_connection, insert_project, fetch_orchestration_run, insert_orchestration_run, fetch_project

    async with get_connection("orch-resume-test") as conn:
        await insert_project(
            conn, slug="orch-resume-test",
            llm_mode="standard", sector="rail", config_json="{}"
        )
        project = await fetch_project(conn, slug="orch-resume-test")
        run_id = await insert_orchestration_run(conn, project_id=project["id"])

    with patch("asyncio.create_task") as mock_task:
        from api.services.orchestration_service import resume_orchestration
        await resume_orchestration("orch-resume-test", run_id)

    async with get_connection("orch-resume-test") as conn:
        row = await fetch_orchestration_run(conn, run_id=run_id)

    assert row["status"] == "running"
    mock_task.assert_called_once()
