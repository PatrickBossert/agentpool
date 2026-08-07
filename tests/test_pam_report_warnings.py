"""Pamela cannot report accurately on a crew whose output is structurally suspect.

Run 25 reported completed with result_json {} while DeriveRegistryTool had silently refused
to write the registry. Nothing in the report said so, because nothing in the report looked.
"""
import pytest
import pytest_asyncio
from api.config import get_settings
from api.database import (
    get_connection, fetch_validation_warnings, dispose_validation_warning,
)
from agents.tools._db import record_validation_warnings_sync
from api.services.pam_report_service import build_pam_report


@pytest_asyncio.fixture
async def pam_project(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_DIR", str(tmp_path))
    monkeypatch.setenv("PROJECTS_DIR", str(tmp_path / "projects"))
    get_settings.cache_clear()
    slug = "pam-warn"
    (tmp_path / "projects" / slug / "outputs").mkdir(parents=True, exist_ok=True)
    async with get_connection(slug) as conn:
        await conn.execute(
            "INSERT INTO projects (slug, sector) VALUES (?,?)", (slug, "test"))
        await conn.commit()
        async with conn.execute("SELECT id FROM projects WHERE slug=?", (slug,)) as cur:
            project_id = (await cur.fetchone())[0]
    yield slug, project_id
    get_settings.cache_clear()


async def _dispose(slug, project_id, code, disposition, note):
    async with get_connection(slug) as conn:
        rows = await fetch_validation_warnings(conn, project_id=project_id)
        target = next(r for r in rows if r["code"] == code)
        await dispose_validation_warning(
            conn, warning_id=target["id"], disposition=disposition,
            note=note, by="consultant")


@pytest.mark.asyncio
async def test_the_report_counts_warnings_by_crew(pam_project):
    slug, _ = pam_project
    record_validation_warnings_sync(slug, 1, "value_chain_tree", [
        {"subject": None, "code": "missing_l0", "detail": "no root", "measure": None}])
    record_validation_warnings_sync(slug, 1, "theme_anchor", [
        {"subject": None, "code": "l3_skew", "detail": "8 of 10", "measure": 0.8}])

    vw = (await build_pam_report(slug))["validation_warnings"]
    assert vw["open"] == 2
    assert vw["acknowledged"] == 0
    assert vw["by_crew"]["discovery_mapping"] == 1
    assert vw["by_crew"]["discovery_interviews"] == 1


@pytest.mark.asyncio
async def test_an_acknowledged_warning_still_counts(pam_project):
    """Acknowledged means the output needs fixing. That is exactly a health signal."""
    slug, project_id = pam_project
    record_validation_warnings_sync(slug, 1, "value_chain_tree", [
        {"subject": None, "code": "missing_l0", "detail": "no root", "measure": None}])
    await _dispose(slug, project_id, "missing_l0", "acknowledged", "real gap")

    vw = (await build_pam_report(slug))["validation_warnings"]
    assert vw["open"] == 0
    assert vw["acknowledged"] == 1
    assert vw["by_crew"]["discovery_mapping"] == 1


@pytest.mark.asyncio
async def test_a_dismissed_warning_is_not_counted(pam_project):
    """Somebody looked and recorded why. That is not a health problem."""
    slug, project_id = pam_project
    record_validation_warnings_sync(slug, 1, "value_chain_tree", [
        {"subject": None, "code": "missing_l0", "detail": "no root", "measure": None}])
    await _dispose(slug, project_id, "missing_l0", "dismissed", "single entity")

    vw = (await build_pam_report(slug))["validation_warnings"]
    assert vw["open"] == 0
    assert vw["acknowledged"] == 0
    assert vw["by_crew"] == {}


@pytest.mark.asyncio
async def test_the_key_is_present_when_there_are_no_warnings(pam_project):
    """A missing key and a zero count read the same to a consumer using .get(), and
    different to one using []. Always present."""
    slug, _ = pam_project
    assert (await build_pam_report(slug))["validation_warnings"] == {
        "open": 0, "acknowledged": 0, "by_crew": {},
    }


@pytest.mark.asyncio
async def test_a_warning_from_an_unmapped_source_is_counted_but_not_attributed(pam_project):
    """output_resolution warnings belong to no crew - they are raised by the resolver, not
    by an agent. They must still show in the totals rather than vanishing."""
    slug, _ = pam_project
    record_validation_warnings_sync(slug, 0, "output_resolution", [
        {"subject": "value_chain_model", "code": "current_file_missing",
         "detail": "v9 is not on disk", "measure": None}])

    vw = (await build_pam_report(slug))["validation_warnings"]
    assert vw["open"] == 1
    assert vw["by_crew"] == {}, "no crew owns a resolver finding"
