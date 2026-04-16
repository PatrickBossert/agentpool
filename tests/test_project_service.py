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
        crews_enabled=["discovery"],
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
        crews_enabled=["discovery"],
    )
    r1 = await create_project(req)
    r2 = await create_project(req)
    assert r1["id"] == r2["id"]
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
