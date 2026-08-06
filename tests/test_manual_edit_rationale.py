# tests/test_manual_edit_rationale.py
"""A manual edit may explain itself. It must save either way.

Blocking a save to demand a rationale is how people stop editing, and an unexplained edit
recorded as unclassified is still better than an edit silently reverted on the next run.
"""
import pytest
import pytest_asyncio

from api.database import get_connection, insert_project

SLUG = "manual-edit-test"


@pytest_asyncio.fixture
async def project(tmp_path, monkeypatch):
    from api.config import get_settings

    get_settings.cache_clear()
    monkeypatch.setenv("DATABASE_DIR", str(tmp_path))
    monkeypatch.setenv("PROJECTS_DIR", str(tmp_path / "projects"))
    (tmp_path / "projects" / SLUG / "outputs").mkdir(parents=True)
    async with get_connection(SLUG) as conn:
        await insert_project(
            conn, slug=SLUG, llm_mode="standard", sector="utilities", config_json="{}"
        )
    yield
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_an_edit_with_a_rationale_records_the_intent(project):
    from api.services.value_chain_store import save_model

    await save_model(
        SLUG, {"segments": []}, saved_by="alice",
        rationale="ISS only maintains property", intent="correction",
    )

    async with get_connection(SLUG) as conn:
        rows = await conn.execute_fetchall(
            "SELECT kind, request FROM output_changes ORDER BY id DESC"
        )
    assert tuple(rows[0]) == ("correction", "ISS only maintains property")


@pytest.mark.asyncio
async def test_an_edit_without_a_rationale_still_saves(project):
    """The load-bearing case. An unexplained edit lands unclassified for later triage."""
    from api.services.value_chain_store import save_model

    output_id = await save_model(SLUG, {"segments": []}, saved_by="alice")

    async with get_connection(SLUG) as conn:
        rows = await conn.execute_fetchall(
            "SELECT kind FROM output_changes ORDER BY id DESC"
        )
    assert output_id is not None
    assert rows[0][0] == "unclassified"
