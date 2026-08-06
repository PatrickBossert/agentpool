"""A structural finding is recorded without refusing the write that produced it.

Deliberately not blocked_writes. That table means "an agent reached for something it does
not own"; this one means "what an agent wrote is structurally suspect". Overloading one
with the other would blur a distinction the ownership work paid to establish.
"""
import pytest
import pytest_asyncio
from api.config import get_settings
from api.database import (
    get_connection, fetch_validation_warnings, dispose_validation_warning,
)


@pytest_asyncio.fixture
async def warn_project(tmp_path, monkeypatch):
    """An isolated project database, so no test can see another's warnings."""
    monkeypatch.setenv("DATABASE_DIR", str(tmp_path))
    monkeypatch.setenv("PROJECTS_DIR", str(tmp_path / "projects"))
    get_settings.cache_clear()
    slug = "warn-test"
    async with get_connection(slug) as conn:
        await conn.execute(
            "INSERT INTO projects (slug, sector) VALUES (?,?)", (slug, "test"))
        await conn.commit()
        async with conn.execute("SELECT id FROM projects WHERE slug=?", (slug,)) as cur:
            project_id = (await cur.fetchone())[0]
    yield slug, project_id
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_recording_the_same_warning_twice_keeps_one_row(warn_project):
    slug, project_id = warn_project
    from agents.tools._db import record_validation_warnings_sync

    w = [{"subject": "0", "code": "missing_l0", "detail": "no root node", "measure": None}]
    record_validation_warnings_sync(slug, 1, "value_chain_tree", w)
    record_validation_warnings_sync(slug, 2, "value_chain_tree", w)

    async with get_connection(slug) as conn:
        rows = await fetch_validation_warnings(conn, project_id=project_id)
    assert len(rows) == 1, "re-running must not duplicate a warning"
    assert rows[0]["run_id"] == 2, "the row tracks the most recent occurrence"
    assert rows[0]["disposition"] == "open"


@pytest.mark.asyncio
async def test_disposition_survives_a_re_occurrence(warn_project):
    slug, project_id = warn_project
    from agents.tools._db import record_validation_warnings_sync

    w = [{"subject": "0", "code": "missing_l0", "detail": "no root", "measure": None}]
    record_validation_warnings_sync(slug, 1, "value_chain_tree", w)
    async with get_connection(slug) as conn:
        rows = await fetch_validation_warnings(conn, project_id=project_id)
        assert await dispose_validation_warning(
            conn, warning_id=rows[0]["id"], disposition="acknowledged",
            note="real gap", by="consultant",
        )
    record_validation_warnings_sync(slug, 2, "value_chain_tree", w)
    async with get_connection(slug) as conn:
        rows = await fetch_validation_warnings(conn, project_id=project_id)
    assert rows[0]["disposition"] == "acknowledged", \
        "a re-occurrence must not reset a reviewer's judgement"
    assert rows[0]["disposition_note"] == "real gap"


@pytest.mark.asyncio
async def test_fetch_filters_by_source_and_disposition(warn_project):
    slug, project_id = warn_project
    from agents.tools._db import record_validation_warnings_sync

    record_validation_warnings_sync(
        slug, 1, "value_chain_tree",
        [{"subject": "0", "code": "missing_l0", "detail": "d", "measure": None}])
    record_validation_warnings_sync(
        slug, 1, "theme_anchor",
        [{"subject": "TH-01", "code": "anchor_level_mismatch", "detail": "d",
          "measure": None}])

    async with get_connection(slug) as conn:
        tree = await fetch_validation_warnings(
            conn, project_id=project_id, sources=["value_chain_tree"])
        open_only = await fetch_validation_warnings(
            conn, project_id=project_id, dispositions=["open"])
    assert [r["code"] for r in tree] == ["missing_l0"]
    assert len(open_only) == 2


@pytest.mark.asyncio
async def test_two_warnings_differing_only_by_subject_are_separate_rows(warn_project):
    slug, project_id = warn_project
    from agents.tools._db import record_validation_warnings_sync

    record_validation_warnings_sync(slug, 1, "value_chain_tree", [
        {"subject": "1.F", "code": "missing_role_node", "detail": "d", "measure": None},
        {"subject": "2.F", "code": "missing_role_node", "detail": "d", "measure": None},
    ])
    async with get_connection(slug) as conn:
        rows = await fetch_validation_warnings(conn, project_id=project_id)
    assert sorted(r["subject"] for r in rows) == ["1.F", "2.F"]


@pytest.mark.asyncio
async def test_disposing_an_unknown_warning_reports_it(warn_project):
    slug, _ = warn_project
    async with get_connection(slug) as conn:
        assert not await dispose_validation_warning(
            conn, warning_id=9999, disposition="dismissed", note="x", by="y")
