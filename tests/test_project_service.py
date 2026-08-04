import pytest
from pathlib import Path


@pytest.mark.asyncio
async def test_create_project_creates_db_and_dirs(tmp_path, monkeypatch):
    import api.config as cfg
    cfg.get_settings.cache_clear()
    monkeypatch.setenv("DATABASE_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("PROJECTS_DIR", str(tmp_path / "projects"))
    cfg.get_settings.cache_clear()

    from api.services.project_service import create_project
    from api.models import ProjectCreate
    req = ProjectCreate(
        client_slug="test-co",
        llm_mode="standard",
        sector="finance",
        stakeholder_groups=["Finance", "Ops"],
        value_stream_labels=["Revenue"],
        crews_enabled=["requirements"],
    )
    result = await create_project(req)
    assert result["slug"] == "test-co"
    assert (tmp_path / "data" / "test-co.db").exists()
    assert (tmp_path / "projects" / "test-co" / "config.yaml").exists()
    assert (tmp_path / "projects" / "test-co" / "docs").is_dir()
    assert (tmp_path / "projects" / "test-co" / "outputs").is_dir()
    cfg.get_settings.cache_clear()


@pytest.mark.asyncio
async def test_create_project_idempotent(tmp_path, monkeypatch):
    import api.config as cfg
    cfg.get_settings.cache_clear()
    monkeypatch.setenv("DATABASE_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("PROJECTS_DIR", str(tmp_path / "projects"))
    cfg.get_settings.cache_clear()

    from api.services.project_service import create_project
    from api.models import ProjectCreate
    req = ProjectCreate(
        client_slug="test-co",
        llm_mode="standard",
        sector="finance",
        stakeholder_groups=["Finance"],
        value_stream_labels=["Revenue"],
        crews_enabled=["requirements"],
    )
    r1 = await create_project(req)
    r2 = await create_project(req)
    assert r1["id"] == r2["id"]
    cfg.get_settings.cache_clear()


@pytest.mark.asyncio
async def test_create_project_registers_a_daily_report_job(tmp_path, monkeypatch):
    """Without this, a project created while the server is running has no
    scheduled_jobs row until someone restarts the process - a new engagement
    would silently produce no daily report, potentially for weeks."""
    import api.config as cfg
    cfg.get_settings.cache_clear()
    monkeypatch.setenv("DATABASE_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("PROJECTS_DIR", str(tmp_path / "projects"))
    cfg.get_settings.cache_clear()

    from api.services.project_service import create_project
    from api.services.pam_report_job import JOB_NAME
    from api.database import get_system_connection
    from api.models import ProjectCreate
    req = ProjectCreate(client_slug="sched-on-create", sector="rail")
    await create_project(req)

    async with get_system_connection() as conn:
        async with conn.execute(
            "SELECT COUNT(*) FROM scheduled_jobs WHERE job_name=? AND slug=?",
            (JOB_NAME, "sched-on-create"),
        ) as cur:
            assert (await cur.fetchone())[0] == 1
    cfg.get_settings.cache_clear()


@pytest.mark.asyncio
async def test_get_project_status_includes_latest_orchestration_run_none(tmp_path, monkeypatch):
    import api.config as cfg
    cfg.get_settings.cache_clear()
    monkeypatch.setenv("DATABASE_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("PROJECTS_DIR", str(tmp_path / "projects"))
    cfg.get_settings.cache_clear()

    from api.services.project_service import create_project, get_project_status
    from api.models import ProjectCreate
    req = ProjectCreate(client_slug="orch-status-test", sector="rail")
    await create_project(req)
    status = await get_project_status("orch-status-test")
    assert status is not None
    assert "latest_orchestration_run" in status
    assert status["latest_orchestration_run"] is None
    cfg.get_settings.cache_clear()
