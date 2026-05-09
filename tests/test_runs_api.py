import pytest
from pathlib import Path
from api.config import get_settings
from api.database import (
    get_connection,
    fetch_project,
    insert_crew_run,
)

SLUG = "runs-test"
PROJECT = {"client_slug": SLUG, "llm_mode": "standard", "sector": "rail"}


@pytest.fixture(autouse=True)
def clean():
    settings = get_settings()
    db_path = Path(settings.database_dir) / f"{SLUG}.db"
    db_path.unlink(missing_ok=True)
    yield
    get_settings.cache_clear()
    db_path.unlink(missing_ok=True)


async def _insert_orchestration_run(status: str = "completed") -> int:
    """Insert an orchestration_run row directly and return its id."""
    async with get_connection(SLUG) as conn:
        project = await fetch_project(conn, slug=SLUG)
        assert project is not None
        cur = await conn.execute(
            "INSERT INTO orchestration_runs (project_id, status) VALUES (?, ?)",
            (project["id"], status),
        )
        await conn.commit()
        return cur.lastrowid


@pytest.mark.asyncio
async def test_list_runs_empty(client):
    await client.post("/projects", json=PROJECT)
    resp = await client.get(f"/projects/{SLUG}/runs")
    assert resp.status_code == 200
    assert resp.json() == []


@pytest.mark.asyncio
async def test_list_runs_returns_history(client):
    await client.post("/projects", json=PROJECT)
    orch_id = await _insert_orchestration_run()
    async with get_connection(SLUG) as conn:
        project = await fetch_project(conn, slug=SLUG)
        assert project is not None
        await insert_crew_run(
            conn,
            project_id=project["id"],
            crew_name="discovery",
            status="completed",
            orchestration_run_id=orch_id,
        )
        await insert_crew_run(
            conn,
            project_id=project["id"],
            crew_name="value_design",
            status="completed",
            orchestration_run_id=orch_id,
        )

    resp = await client.get(f"/projects/{SLUG}/runs")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["id"] == orch_id
    assert data[0]["status"] == "completed"
    crew_names = [cr["crew_name"] for cr in data[0]["crew_runs"]]
    assert "discovery" in crew_names
    assert "value_design" in crew_names


@pytest.mark.asyncio
async def test_list_runs_excludes_unlinked_crew_runs(client):
    await client.post("/projects", json=PROJECT)
    orch_id = await _insert_orchestration_run()
    async with get_connection(SLUG) as conn:
        project = await fetch_project(conn, slug=SLUG)
        assert project is not None
        # crew run with NULL orchestration_run_id — should not appear in crew_runs list
        await insert_crew_run(
            conn,
            project_id=project["id"],
            crew_name="orphan",
            status="completed",
        )

    resp = await client.get(f"/projects/{SLUG}/runs")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["crew_runs"] == []


@pytest.mark.asyncio
async def test_list_runs_unknown_project_404(client):
    resp = await client.get("/projects/no-such-slug/runs")
    assert resp.status_code == 404
