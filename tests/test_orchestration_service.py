# tests/test_orchestration_service.py
"""Unit tests for start_orchestration service and the /orchestrate endpoint."""
import pytest
from unittest.mock import patch, AsyncMock, MagicMock


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
    import aiosqlite
    from pathlib import Path
    import api.config as cfg
    cfg.get_settings.cache_clear()

    with patch("api.services.orchestration_service.run_pam_crew", new_callable=AsyncMock):
        with patch("asyncio.create_task") as mock_task:
            # We need a real DB with a project row
            from api.database import get_connection, insert_project, fetch_project
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
        with patch("api.services.orchestration_service.run_pam_crew", new_callable=AsyncMock):
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
    """start_orchestration calls asyncio.create_task (fires PAM crew asynchronously)."""
    import asyncio
    with patch("asyncio.create_task") as mock_task, \
         patch("api.services.orchestration_service.run_pam_crew", new_callable=AsyncMock):
        from api.database import get_connection, insert_project
        async with get_connection("orch-bg-test") as conn:
            await insert_project(
                conn, slug="orch-bg-test",
                llm_mode="standard", sector="rail", config_json="{}"
            )

        from api.services.orchestration_service import start_orchestration
        await start_orchestration("orch-bg-test")

    mock_task.assert_called_once()


# ── run_pam_crew failure path ─────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_run_pam_crew_sets_failed_on_exception():
    """run_pam_crew updates status to 'failed' when the crew raises."""
    from api.database import get_connection, insert_project, fetch_orchestration_run, insert_orchestration_run, fetch_project

    async with get_connection("orch-fail-test") as conn:
        await insert_project(
            conn, slug="orch-fail-test",
            llm_mode="standard", sector="rail", config_json="{}"
        )
        project = await fetch_project(conn, slug="orch-fail-test")
        run_id = await insert_orchestration_run(conn, project_id=project["id"])

    # create_pam_crew is imported inside run_pam_crew (deferred), so patch at the source.
    import agents.crews.pam_crew  # ensure module is in sys.modules before patching
    with patch("agents.crews.pam_crew.create_pam_crew", side_effect=RuntimeError("boom")):
        from api.services.orchestration_service import run_pam_crew
        await run_pam_crew("orch-fail-test", run_id)

    async with get_connection("orch-fail-test") as conn:
        row = await fetch_orchestration_run(conn, run_id=run_id)

    assert row["status"] == "failed"


# ── /orchestrate endpoint ─────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_orchestrate_endpoint_returns_202(client):
    await client.post("/projects", json=PROJECT_PAYLOAD)
    with patch("api.routers.orchestrate.start_orchestration", new_callable=AsyncMock, return_value=5):
        resp = await client.post("/projects/orch-api-test/orchestrate")
    assert resp.status_code == 202
    data = resp.json()
    assert data["orchestration_run_id"] == 5
    assert data["status"] == "running"


@pytest.mark.asyncio
async def test_orchestrate_endpoint_returns_404_for_unknown_project(client):
    resp = await client.post("/projects/nonexistent/orchestrate")
    assert resp.status_code == 404
