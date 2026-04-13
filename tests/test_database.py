# tests/test_database.py
import pytest
import pytest_asyncio
import aiosqlite
from pathlib import Path


@pytest_asyncio.fixture
async def db(tmp_path):
    from api.database import init_db
    db_path = tmp_path / "test.db"
    async with aiosqlite.connect(db_path) as conn:
        conn.row_factory = aiosqlite.Row
        await init_db(conn)
        yield conn


@pytest.mark.asyncio
async def test_init_db_creates_tables(db):
    async with db.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    ) as cursor:
        tables = {row[0] async for row in cursor}
    assert {"projects", "crew_runs", "agent_outputs", "human_reviews", "users"}.issubset(tables)


@pytest.mark.asyncio
async def test_insert_and_fetch_project(db):
    from api.database import insert_project, fetch_project
    await insert_project(db, slug="acme", llm_mode="standard", sector="rail", config_json='{}')
    project = await fetch_project(db, slug="acme")
    assert project["slug"] == "acme"
    assert project["llm_mode"] == "standard"
    assert project["status"] == "created"


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
