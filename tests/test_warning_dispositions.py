"""A reviewer's judgement, and the rule that stops one dismissal blinding a check forever.

A dismissal says "this is a false positive at this magnitude". Once the magnitude moves
materially it is a different claim, so the dismissal expires. Without that, one dismissal
silences the check permanently, which is how a warning system dies.
"""
import pytest
import pytest_asyncio
from api.config import get_settings
from api.database import (
    get_connection, fetch_validation_warnings, dispose_validation_warning,
)
from agents.tools._db import record_validation_warnings_sync

@pytest.fixture(autouse=True)
def _granted_authority():
    """This module is about the disposition rules - which values are legal, which need a
    reason, and when a dismissal expires - not about who may record one. The client fixture's
    sysadmin token names no real user, so caller_may_contribute correctly answers False.

    Not a weakening of the gate: tests/test_write_door_authority.py drives every one of
    these doors over HTTP as a real member with and without the flag, so deleting the gate
    fails there. Patched on the router module, where the name is looked up - the routers
    bind their own reference via `from ... import`, so patching authority_service itself
    would miss them (CLAUDE.md's four-crew-tests entry).
    """
    from unittest.mock import AsyncMock, patch

    with patch("api.routers.validations.caller_may_contribute", new=AsyncMock(return_value=True)):
        yield




@pytest_asyncio.fixture
async def disp_project(tmp_path, monkeypatch):
    """Isolated, because the re-raise rule needs a database no other test writes to."""
    monkeypatch.setenv("DATABASE_DIR", str(tmp_path))
    monkeypatch.setenv("PROJECTS_DIR", str(tmp_path / "projects"))
    get_settings.cache_clear()
    slug = "disp-test"
    async with get_connection(slug) as conn:
        await conn.execute(
            "INSERT INTO projects (slug, sector) VALUES (?,?)", (slug, "test"))
        await conn.commit()
        async with conn.execute("SELECT id FROM projects WHERE slug=?", (slug,)) as cur:
            project_id = (await cur.fetchone())[0]
    yield slug, project_id
    get_settings.cache_clear()


def _skew(measure):
    return [{"subject": None, "code": "l3_skew", "detail": f"{measure:.0%} at L3",
             "measure": measure}]


async def _dispose_only_row(slug, project_id, disposition, note):
    async with get_connection(slug) as conn:
        rows = await fetch_validation_warnings(conn, project_id=project_id)
        await dispose_validation_warning(
            conn, warning_id=rows[0]["id"], disposition=disposition,
            note=note, by="consultant")


async def _only_row(slug, project_id):
    async with get_connection(slug) as conn:
        return (await fetch_validation_warnings(conn, project_id=project_id))[0]


@pytest.mark.asyncio
async def test_a_dismissal_holds_when_the_measure_barely_moves(disp_project):
    slug, project_id = disp_project
    record_validation_warnings_sync(slug, 1, "theme_anchor", _skew(0.80))
    await _dispose_only_row(slug, project_id, "dismissed", "all tactical this time")

    record_validation_warnings_sync(slug, 2, "theme_anchor", _skew(0.85))
    row = await _only_row(slug, project_id)
    assert row["disposition"] == "dismissed", "5pp is not a material move"
    assert row["disposition_note"] == "all tactical this time"


@pytest.mark.asyncio
async def test_a_dismissal_expires_when_the_measure_moves_materially(disp_project):
    slug, project_id = disp_project
    record_validation_warnings_sync(slug, 1, "theme_anchor", _skew(0.72))
    await _dispose_only_row(slug, project_id, "dismissed", "borderline, fine")

    record_validation_warnings_sync(slug, 2, "theme_anchor", _skew(0.95))
    row = await _only_row(slug, project_id)
    assert row["disposition"] == "open", "23pp must re-raise"
    assert row["disposition_note"] is None, "the stale reason must not survive"


@pytest.mark.asyncio
async def test_an_acknowledgement_is_never_auto_reset(disp_project):
    """Acknowledged already says 'this is real' - no measure makes it more so."""
    slug, project_id = disp_project
    record_validation_warnings_sync(slug, 1, "theme_anchor", _skew(0.72))
    await _dispose_only_row(slug, project_id, "acknowledged", "real")

    record_validation_warnings_sync(slug, 2, "theme_anchor", _skew(0.99))
    row = await _only_row(slug, project_id)
    assert row["disposition"] == "acknowledged"
    assert row["disposition_note"] == "real"


@pytest.mark.asyncio
async def test_a_measureless_warning_cannot_expire_a_dismissal(disp_project):
    """missing_l0 has no measure. With nothing to compare, the dismissal stands."""
    slug, project_id = disp_project
    w = [{"subject": None, "code": "missing_l0", "detail": "no root", "measure": None}]
    record_validation_warnings_sync(slug, 1, "value_chain_tree", w)
    await _dispose_only_row(slug, project_id, "dismissed", "single-entity client")

    record_validation_warnings_sync(slug, 2, "value_chain_tree", w)
    assert (await _only_row(slug, project_id))["disposition"] == "dismissed"


# ── the endpoints ─────────────────────────────────────────────────────────────────

@pytest_asyncio.fixture
async def api_project():
    """A project on the DEFAULT settings, because the shared `client` fixture builds the
    app against them - a monkeypatched DATABASE_DIR would leave the client reading a
    different database from the one the test writes to. Every assertion below is scoped to
    the slug this fixture created, never to a global count or a hardcoded id."""
    slug = "disp-api-test"
    async with get_connection(slug) as conn:
        await conn.execute(
            "INSERT OR IGNORE INTO projects (slug, sector) VALUES (?,?)", (slug, "test"))
        await conn.execute("DELETE FROM validation_warnings")
        await conn.commit()
        async with conn.execute("SELECT id FROM projects WHERE slug=?", (slug,)) as cur:
            project_id = (await cur.fetchone())[0]
    yield slug, project_id


@pytest.mark.asyncio
async def test_the_endpoints_list_and_dispose(api_project, client):
    slug, project_id = api_project
    record_validation_warnings_sync(slug, 1, "theme_anchor", _skew(0.80))

    listed = await client.get(f"/projects/{slug}/validation-warnings")
    assert listed.status_code == 200
    body = [w for w in listed.json() if w["code"] == "l3_skew"]
    assert len(body) == 1

    patched = await client.patch(
        f"/projects/{slug}/validation-warnings/{body[0]['id']}",
        json={"disposition": "dismissed", "note": "all tactical"})
    assert patched.status_code == 200

    async with get_connection(slug) as conn:
        rows = await fetch_validation_warnings(conn, project_id=project_id)
    row = next(r for r in rows if r["code"] == "l3_skew")
    assert row["disposition"] == "dismissed"
    assert row["disposition_note"] == "all tactical"


@pytest.mark.asyncio
async def test_an_invalid_disposition_is_rejected(api_project, client):
    slug, project_id = api_project
    record_validation_warnings_sync(slug, 1, "theme_anchor", _skew(0.80))
    async with get_connection(slug) as conn:
        rows = await fetch_validation_warnings(conn, project_id=project_id)
    wid = next(r["id"] for r in rows if r["code"] == "l3_skew")

    r = await client.patch(
        f"/projects/{slug}/validation-warnings/{wid}",
        json={"disposition": "maybe", "note": ""})
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_a_dismissal_without_a_reason_is_rejected(api_project, client):
    """A dismissal with no reason is indistinguishable from nobody looking, which is the
    exact ambiguity the disposition exists to remove."""
    slug, project_id = api_project
    record_validation_warnings_sync(slug, 1, "theme_anchor", _skew(0.80))
    async with get_connection(slug) as conn:
        rows = await fetch_validation_warnings(conn, project_id=project_id)
    wid = next(r["id"] for r in rows if r["code"] == "l3_skew")

    r = await client.patch(
        f"/projects/{slug}/validation-warnings/{wid}",
        json={"disposition": "dismissed", "note": "   "})
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_an_acknowledgement_needs_no_reason(api_project, client):
    """Acknowledging says the warning is right; there is nothing extra to explain."""
    slug, project_id = api_project
    record_validation_warnings_sync(slug, 1, "theme_anchor", _skew(0.80))
    async with get_connection(slug) as conn:
        rows = await fetch_validation_warnings(conn, project_id=project_id)
    wid = next(r["id"] for r in rows if r["code"] == "l3_skew")

    r = await client.patch(
        f"/projects/{slug}/validation-warnings/{wid}",
        json={"disposition": "acknowledged", "note": ""})
    assert r.status_code == 200


@pytest.mark.asyncio
async def test_disposing_an_unknown_warning_is_a_404(api_project, client):
    slug, _ = api_project
    r = await client.patch(
        f"/projects/{slug}/validation-warnings/999999",
        json={"disposition": "acknowledged", "note": ""})
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_the_list_can_be_filtered_by_source(api_project, client):
    slug, _ = api_project
    record_validation_warnings_sync(slug, 1, "theme_anchor", _skew(0.80))
    record_validation_warnings_sync(slug, 1, "value_chain_tree", [
        {"subject": None, "code": "missing_l0", "detail": "no root", "measure": None}])

    r = await client.get(
        f"/projects/{slug}/validation-warnings", params={"source": "value_chain_tree"})
    assert [w["code"] for w in r.json()] == ["missing_l0"]
