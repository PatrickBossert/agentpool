# tests/test_repair_registry_current.py
"""Exactly one row may claim to be the current version of an output type."""
import pytest
import pytest_asyncio

from api.database import get_connection, insert_project
from scripts.repair_registry_current import repair_duplicate_current

SLUG = "repair-test"


@pytest_asyncio.fixture
async def project(tmp_path, monkeypatch):
    from api.config import get_settings

    get_settings.cache_clear()
    monkeypatch.setenv("DATABASE_DIR", str(tmp_path))
    monkeypatch.setenv("PROJECTS_DIR", str(tmp_path / "projects"))
    async with get_connection(SLUG) as conn:
        await insert_project(
            conn, slug=SLUG, llm_mode="standard", sector="utilities", config_json="{}"
        )
        for agent, version in (("value_chain_mapper", 5), ("interaction_designer", 1)):
            await conn.execute(
                "INSERT INTO agent_outputs (project_id, agent_name, output_type, file_path,"
                " version, is_current, review_status) VALUES (1,?,?,?,?,1,'pending')",
                (agent, "value_chain_registry", f"r_v{version}.json", version),
            )
        await conn.commit()
    yield
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_the_highest_version_stays_current(project):
    async with get_connection(SLUG) as conn:
        corrected = await repair_duplicate_current(conn, output_type="value_chain_registry")
        rows = await conn.execute_fetchall(
            "SELECT agent_name, version FROM agent_outputs"
            " WHERE output_type='value_chain_registry' AND is_current=1"
        )
    assert corrected == 1
    assert [tuple(r) for r in rows] == [("value_chain_mapper", 5)]


@pytest.mark.asyncio
async def test_running_it_twice_changes_nothing_further(project):
    async with get_connection(SLUG) as conn:
        await repair_duplicate_current(conn, output_type="value_chain_registry")
        second = await repair_duplicate_current(conn, output_type="value_chain_registry")
    assert second == 0
