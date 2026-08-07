"""A warning that has been fixed stops nagging.

Run 29 left `missing_l0` saying "the tree is a dict" - true of tree v17, fixed by v18 and
v19 in the same run. Nothing cleared it, so a reviewer saw a solved problem and the agent
would have been re-injected a warning it had already acted on.

A warner returns the COMPLETE set of findings for its source, so anything absent from that
set is no longer true. Only that contract permits clearing, which is why it is opt-in: the
resolver reports one output at a time and must not clear another's finding.
"""
import pytest
import pytest_asyncio
from api.config import get_settings
from api.database import (
    get_connection, fetch_validation_warnings, dispose_validation_warning,
)
from agents.tools._db import record_validation_warnings_sync


@pytest_asyncio.fixture
async def warn_project(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_DIR", str(tmp_path))
    monkeypatch.setenv("PROJECTS_DIR", str(tmp_path / "projects"))
    get_settings.cache_clear()
    slug = "clear-test"
    async with get_connection(slug) as conn:
        await conn.execute(
            "INSERT INTO projects (slug, sector) VALUES (?,?)", (slug, "test"))
        await conn.commit()
        async with conn.execute("SELECT id FROM projects WHERE slug=?", (slug,)) as cur:
            project_id = (await cur.fetchone())[0]
    yield slug, project_id
    get_settings.cache_clear()


def _w(code, subject=None, measure=None):
    return {"subject": subject, "code": code, "detail": f"{code} detail",
            "measure": measure}


async def _codes(slug, project_id):
    async with get_connection(slug) as conn:
        rows = await fetch_validation_warnings(conn, project_id=project_id)
    return sorted(r["code"] for r in rows)


@pytest.mark.asyncio
async def test_a_fixed_warning_is_cleared(warn_project):
    """The run 29 case: raised on one write, gone by the next."""
    slug, project_id = warn_project
    record_validation_warnings_sync(
        slug, 1, "value_chain_tree", [_w("missing_l0")], complete=True)
    assert await _codes(slug, project_id) == ["missing_l0"]

    record_validation_warnings_sync(slug, 1, "value_chain_tree", [], complete=True)
    assert await _codes(slug, project_id) == []


@pytest.mark.asyncio
async def test_only_the_fixed_finding_is_cleared(warn_project):
    slug, project_id = warn_project
    record_validation_warnings_sync(slug, 1, "value_chain_tree",
                                    [_w("missing_l0"), _w("id_redefined", "3.3.3")],
                                    complete=True)
    record_validation_warnings_sync(slug, 2, "value_chain_tree",
                                    [_w("id_redefined", "3.3.3")], complete=True)
    assert await _codes(slug, project_id) == ["id_redefined"]


@pytest.mark.asyncio
async def test_an_acknowledged_warning_that_is_fixed_is_cleared(warn_project):
    """Raised, acknowledged, fixed - that is the loop completing, not a record to keep."""
    slug, project_id = warn_project
    record_validation_warnings_sync(
        slug, 1, "value_chain_tree", [_w("missing_l0")], complete=True)
    async with get_connection(slug) as conn:
        rows = await fetch_validation_warnings(conn, project_id=project_id)
        await dispose_validation_warning(
            conn, warning_id=rows[0]["id"], disposition="acknowledged",
            note="real", by="consultant")

    record_validation_warnings_sync(slug, 2, "value_chain_tree", [], complete=True)
    assert await _codes(slug, project_id) == []


@pytest.mark.asyncio
async def test_a_dismissal_survives_the_condition_going_away(warn_project):
    """A dismissal is a standing judgement that this finding is a false positive. If the
    condition returns, that judgement should still apply - and it cannot if the row it
    lives on was deleted the moment the finding stopped appearing."""
    slug, project_id = warn_project
    record_validation_warnings_sync(
        slug, 1, "theme_anchor", [_w("l3_skew", None, 0.8)], complete=True)
    async with get_connection(slug) as conn:
        rows = await fetch_validation_warnings(conn, project_id=project_id)
        await dispose_validation_warning(
            conn, warning_id=rows[0]["id"], disposition="dismissed",
            note="all tactical", by="consultant")

    record_validation_warnings_sync(slug, 2, "theme_anchor", [], complete=True)
    async with get_connection(slug) as conn:
        rows = await fetch_validation_warnings(conn, project_id=project_id)
    assert [r["disposition"] for r in rows] == ["dismissed"]
    assert rows[0]["disposition_note"] == "all tactical"


@pytest.mark.asyncio
async def test_clearing_never_crosses_sources(warn_project):
    slug, project_id = warn_project
    record_validation_warnings_sync(
        slug, 1, "value_chain_tree", [_w("missing_l0")], complete=True)
    record_validation_warnings_sync(
        slug, 1, "theme_anchor", [_w("l3_skew", None, 0.9)], complete=True)

    record_validation_warnings_sync(slug, 2, "theme_anchor", [], complete=True)
    assert await _codes(slug, project_id) == ["missing_l0"]


@pytest.mark.asyncio
async def test_an_incomplete_report_clears_nothing(warn_project):
    """The resolver reports one output at a time. current_output_path finding
    value_chain_model present must not clear a warning about value_levers."""
    slug, project_id = warn_project
    record_validation_warnings_sync(slug, 1, "output_resolution",
                                    [_w("current_file_missing", "value_levers")])
    record_validation_warnings_sync(slug, 2, "output_resolution", [])
    assert await _codes(slug, project_id) == ["current_file_missing"]
