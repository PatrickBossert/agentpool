# tests/test_assignment_api.py
import pytest
from pathlib import Path
from api.config import get_settings
from api.database import (
    get_connection,
    insert_project,
    fetch_project,
    insert_orchestration_run,
    insert_stakeholder,
    fetch_stakeholder_assignments,
    replace_stakeholder_assignments,
)

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


@pytest.mark.asyncio
async def test_replace_and_fetch_stakeholder_assignments():
    """replace saves rows; fetch returns them in id order."""
    async with get_connection(SLUG) as conn:
        await insert_project(conn, slug=SLUG, llm_mode="standard", sector="rail", config_json="{}")
        project = await fetch_project(conn, slug=SLUG)
        run_id = await insert_orchestration_run(conn, project_id=project["id"])
        sh_id = await insert_stakeholder(
            conn,
            project_id=project["id"],
            name="Jane",
            job_title="CFO",
            organisation="Acme",
            email="",
            slack_handle="",
            stakeholder_groups=[],
            project_role="recipient",
            value_streams=[],
            value_chain_stage="",
            activity="",
            disposition="neutral",
            location="",
            country_code="",
            timezone="",
            preferred_language="",
            currency="",
        )
        count = await replace_stakeholder_assignments(
            conn,
            orchestration_run_id=run_id,
            assignments=[{"stakeholder_id": sh_id, "level": "L2", "node_label": "Billing"}],
        )
    assert count == 1
    async with get_connection(SLUG) as conn:
        rows = await fetch_stakeholder_assignments(conn, orchestration_run_id=run_id)
    assert len(rows) == 1
    assert rows[0]["level"] == "L2"
    assert rows[0]["node_label"] == "Billing"
    assert rows[0]["stakeholder_id"] == sh_id


@pytest.mark.asyncio
async def test_replace_stakeholder_assignments_replaces_not_appends():
    """Calling replace twice keeps only the second set."""
    async with get_connection(SLUG) as conn:
        await insert_project(conn, slug=SLUG, llm_mode="standard", sector="rail", config_json="{}")
        project = await fetch_project(conn, slug=SLUG)
        run_id = await insert_orchestration_run(conn, project_id=project["id"])
        sh_id = await insert_stakeholder(
            conn,
            project_id=project["id"],
            name="Bob",
            job_title="PM",
            organisation="Acme",
            email="",
            slack_handle="",
            stakeholder_groups=[],
            project_role="recipient",
            value_streams=[],
            value_chain_stage="",
            activity="",
            disposition="neutral",
            location="",
            country_code="",
            timezone="",
            preferred_language="",
            currency="",
        )
        await replace_stakeholder_assignments(
            conn,
            orchestration_run_id=run_id,
            assignments=[{"stakeholder_id": sh_id, "level": "L1", "node_label": "Operations"}],
        )
        count = await replace_stakeholder_assignments(
            conn,
            orchestration_run_id=run_id,
            assignments=[{"stakeholder_id": sh_id, "level": "L2", "node_label": "Billing"}],
        )
    assert count == 1
    async with get_connection(SLUG) as conn:
        rows = await fetch_stakeholder_assignments(conn, orchestration_run_id=run_id)
    assert len(rows) == 1
    assert rows[0]["node_label"] == "Billing"


@pytest.mark.asyncio
async def test_fetch_stakeholder_assignments_empty_for_unknown_run():
    """Returns [] when no assignments exist for a run."""
    async with get_connection(SLUG) as conn:
        await insert_project(conn, slug=SLUG, llm_mode="standard", sector="rail", config_json="{}")
        project = await fetch_project(conn, slug=SLUG)
        run_id = await insert_orchestration_run(conn, project_id=project["id"])
        rows = await fetch_stakeholder_assignments(conn, orchestration_run_id=run_id)
    assert rows == []
