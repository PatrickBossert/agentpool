# tests/test_database.py
import pytest
import pytest_asyncio
import aiosqlite
from pathlib import Path


@pytest_asyncio.fixture
async def db(tmp_path):
    from api.database import init_db, _migrate_human_reviews, _migrate_crew_runs
    db_path = tmp_path / "test.db"
    async with aiosqlite.connect(db_path) as conn:
        conn.row_factory = aiosqlite.Row
        await conn.execute("PRAGMA foreign_keys = ON")
        await init_db(conn)
        await _migrate_human_reviews(conn)
        await _migrate_crew_runs(conn)
        yield conn


@pytest.mark.asyncio
async def test_init_db_creates_tables(db):
    async with db.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    ) as cursor:
        tables = {row[0] async for row in cursor}
    assert {"projects", "crew_runs", "agent_outputs", "human_reviews"}.issubset(tables)


@pytest.mark.asyncio
async def test_insert_and_fetch_project(db):
    from api.database import insert_project, fetch_project
    result = await insert_project(db, slug="acme", llm_mode="standard", sector="rail", config_json='{}')
    assert result is True
    project = await fetch_project(db, slug="acme")
    assert project["slug"] == "acme"
    assert project["llm_mode"] == "standard"
    assert project["status"] == "created"


@pytest.mark.asyncio
async def test_insert_project_duplicate_slug_returns_false(db):
    from api.database import insert_project
    first = await insert_project(db, slug="dup", llm_mode="standard", sector="rail", config_json='{}')
    second = await insert_project(db, slug="dup", llm_mode="standard", sector="rail", config_json='{}')
    assert first is True
    assert second is False


@pytest.mark.asyncio
async def test_get_connection_context_manager(tmp_path, monkeypatch):
    import api.config as cfg
    cfg.get_settings.cache_clear()
    monkeypatch.setenv("DATABASE_DIR", str(tmp_path))
    cfg.get_settings.cache_clear()
    from api.database import get_connection
    async with get_connection("conn-test") as conn:
        async with conn.execute("SELECT name FROM sqlite_master WHERE type='table'") as cur:
            tables = {row[0] async for row in cur}
    assert "projects" in tables
    cfg.get_settings.cache_clear()


@pytest.mark.asyncio
async def test_insert_crew_run(db):
    from api.database import insert_project, insert_crew_run, fetch_crew_runs, fetch_project
    await insert_project(db, slug="acme", llm_mode="standard", sector="rail", config_json='{}')
    project = await fetch_project(db, slug="acme")
    await insert_crew_run(db, project_id=project["id"], crew_name="discovery", status="running")
    runs = await fetch_crew_runs(db, project_id=project["id"])
    assert len(runs) == 1
    assert runs[0]["crew_name"] == "discovery"
    assert runs[0]["status"] == "running"


@pytest.mark.asyncio
async def test_insert_agent_output(db):
    from api.database import insert_project, insert_agent_output, fetch_agent_outputs, fetch_project
    await insert_project(db, slug="acme", llm_mode="standard", sector="rail", config_json='{}')
    project = await fetch_project(db, slug="acme")
    await insert_agent_output(
        db, project_id=project["id"],
        agent_name="value_chain_mapper",
        output_type="value_chain",
        file_path="/tmp/vc.json",
        version=1,
    )
    outputs = await fetch_agent_outputs(db, project_id=project["id"])
    assert outputs[0]["agent_name"] == "value_chain_mapper"
    assert outputs[0]["version"] == 1


@pytest.mark.asyncio
async def test_init_db_creates_orchestration_runs_table(db):
    async with db.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    ) as cur:
        tables = {row[0] async for row in cur}
    assert "orchestration_runs" in tables


@pytest.mark.asyncio
async def test_insert_and_fetch_orchestration_run(db):
    from api.database import insert_project, insert_orchestration_run, fetch_orchestration_run
    await insert_project(db, slug="orch-test", llm_mode="standard", sector="rail", config_json='{}')
    project_row = await db.execute("SELECT id FROM projects WHERE slug='orch-test'")
    project_id = (await project_row.fetchone())[0]

    run_id = await insert_orchestration_run(db, project_id=project_id)
    assert isinstance(run_id, int)

    run = await fetch_orchestration_run(db, run_id=run_id)
    assert run is not None
    assert run["status"] == "running"
    assert run["project_id"] == project_id


@pytest.mark.asyncio
async def test_update_orchestration_run_status_sets_completed_at(db):
    from api.database import insert_project, insert_orchestration_run, update_orchestration_run_status, fetch_orchestration_run
    await insert_project(db, slug="orch-update-test", llm_mode="standard", sector="rail", config_json='{}')
    project_row = await db.execute("SELECT id FROM projects WHERE slug='orch-update-test'")
    project_id = (await project_row.fetchone())[0]

    run_id = await insert_orchestration_run(db, project_id=project_id)
    await update_orchestration_run_status(db, run_id=run_id, status="completed")

    run = await fetch_orchestration_run(db, run_id=run_id)
    assert run["status"] == "completed"
    assert run["completed_at"] is not None


@pytest.mark.asyncio
async def test_update_orchestration_run_status_running_leaves_completed_at_null(db):
    from api.database import insert_project, insert_orchestration_run, update_orchestration_run_status, fetch_orchestration_run
    await insert_project(db, slug="orch-null-test", llm_mode="standard", sector="rail", config_json='{}')
    project_row = await db.execute("SELECT id FROM projects WHERE slug='orch-null-test'")
    project_id = (await project_row.fetchone())[0]

    run_id = await insert_orchestration_run(db, project_id=project_id)
    # Explicitly call with non-terminal status — should NOT set completed_at
    await update_orchestration_run_status(db, run_id=run_id, status="running")
    run = await fetch_orchestration_run(db, run_id=run_id)
    assert run["completed_at"] is None


@pytest.mark.asyncio
async def test_fetch_latest_orchestration_run_returns_none_when_empty(db):
    from api.database import insert_project, fetch_latest_orchestration_run
    await insert_project(db, slug="orch-none", llm_mode="standard", sector="rail", config_json="{}")
    async with db.execute("SELECT id FROM projects WHERE slug='orch-none'") as cur:
        project_id = (await cur.fetchone())["id"]
    result = await fetch_latest_orchestration_run(db, project_id=project_id)
    assert result is None


@pytest.mark.asyncio
async def test_fetch_latest_orchestration_run_returns_most_recent(db):
    from api.database import insert_project, fetch_latest_orchestration_run
    await insert_project(db, slug="orch-latest", llm_mode="standard", sector="rail", config_json="{}")
    async with db.execute("SELECT id FROM projects WHERE slug='orch-latest'") as cur:
        project_id = (await cur.fetchone())["id"]
    await db.execute(
        "INSERT INTO orchestration_runs (project_id, status, started_at) VALUES (?, 'completed', '2026-01-01 10:00:00')",
        (project_id,),
    )
    await db.execute(
        "INSERT INTO orchestration_runs (project_id, status, started_at) VALUES (?, 'running', '2026-01-02 10:00:00')",
        (project_id,),
    )
    await db.commit()
    result = await fetch_latest_orchestration_run(db, project_id=project_id)
    assert result is not None
    assert result["status"] == "running"


@pytest.mark.asyncio
async def test_update_document_ingested(db):
    from api.database import insert_project, insert_document, update_document_ingested
    await insert_project(db, slug="ingest-flag", llm_mode="standard", sector="rail", config_json="{}")
    async with db.execute("SELECT id FROM projects WHERE slug='ingest-flag'") as cur:
        project_id = (await cur.fetchone())["id"]
    doc_id = await insert_document(
        db,
        project_id=project_id,
        filename="test.txt",
        original_name="test.txt",
        file_path="/tmp/test.txt",
        content_type="text/plain",
        size_bytes=10,
    )
    await update_document_ingested(db, doc_id=doc_id)
    async with db.execute("SELECT ingested FROM client_documents WHERE id=?", (doc_id,)) as cur:
        row = await cur.fetchone()
    assert row["ingested"] == 1


@pytest.mark.asyncio
async def test_update_project_config(db):
    from api.database import insert_project, fetch_project, update_project_config
    await insert_project(db, slug="cfg-test", llm_mode="standard", sector="rail", config_json='{"sector":"rail"}')
    project = await fetch_project(db, slug="cfg-test")
    await update_project_config(
        db,
        project_id=project["id"],
        llm_mode="sensitive",
        sector="energy",
        config_json='{"sector":"energy","llm_mode":"sensitive"}',
    )
    updated = await fetch_project(db, slug="cfg-test")
    assert updated["llm_mode"] == "sensitive"
    assert updated["sector"] == "energy"
    assert updated["config_json"] == '{"sector":"energy","llm_mode":"sensitive"}'
