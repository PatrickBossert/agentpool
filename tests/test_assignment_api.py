# tests/test_assignment_api.py
import pytest
from pathlib import Path
from api.config import get_settings
from api.database import get_connection, insert_project, fetch_project, insert_orchestration_run

SLUG = "assignment-test"
PROJECT = {"client_slug": SLUG, "llm_mode": "standard", "sector": "rail"}


@pytest.fixture(autouse=True)
def clean():
    settings = get_settings()
    db_path = Path(settings.database_dir) / f"{SLUG}.db"
    db_path.unlink(missing_ok=True)
    yield
    get_settings.cache_clear()
    db_path.unlink(missing_ok=True)


@pytest.mark.asyncio
async def test_migration_creates_stakeholder_assignments_table(client):
    await client.post("/projects", json=PROJECT)
    async with get_connection(SLUG) as conn:
        async with conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='stakeholder_assignments'"
        ) as cur:
            row = await cur.fetchone()
    assert row is not None
