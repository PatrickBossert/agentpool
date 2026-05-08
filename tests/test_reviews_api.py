import pytest
from pathlib import Path
from api.config import get_settings
from api.database import get_connection, fetch_project, insert_crew_run

SLUG = "rev-test"
PROJECT = {"client_slug": SLUG, "llm_mode": "standard", "sector": "rail"}


@pytest.fixture(autouse=True)
def clean():
    settings = get_settings()
    db_path = Path(settings.database_dir) / f"{SLUG}.db"
    db_path.unlink(missing_ok=True)
    yield
    get_settings.cache_clear()
    db_path.unlink(missing_ok=True)


async def _insert_pending_review(prompt: str, decision: str = "pending") -> None:
    async with get_connection(SLUG) as conn:
        project = await fetch_project(conn, slug=SLUG)
        run_id = await insert_crew_run(
            conn, project_id=project["id"], crew_name="TestCrew", status="running"
        )
        await conn.execute(
            "INSERT INTO human_reviews (crew_run_id, decision, prompt) VALUES (?,?,?)",
            (run_id, decision, prompt),
        )
        await conn.commit()


@pytest.mark.asyncio
async def test_list_reviews_returns_pending(client):
    await client.post("/projects", json=PROJECT)
    await _insert_pending_review("Please review the value chain diagram.")
    resp = await client.get(f"/projects/{SLUG}/reviews")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["prompt"] == "Please review the value chain diagram."
    assert data[0]["decision"] == "pending"
    assert "crew_run_id" in data[0]
    assert "id" in data[0]


@pytest.mark.asyncio
async def test_list_reviews_excludes_resolved(client):
    await client.post("/projects", json=PROJECT)
    await _insert_pending_review("Check architecture.", decision="approved")
    resp = await client.get(f"/projects/{SLUG}/reviews")
    assert resp.status_code == 200
    assert resp.json() == []


@pytest.mark.asyncio
async def test_list_reviews_unknown_project_404(client):
    resp = await client.get("/projects/no-such-project/reviews")
    assert resp.status_code == 404
