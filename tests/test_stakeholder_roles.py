"""A person's rights live on the record that holds their name.

The five flags are one set, not two systems: is_participant already existed alongside
is_reviewer and is_approver, and project_admin and governor join them rather than living
somewhere else. Boolean columns rather than a JSON list because resolve_recipients already
filters on exactly these columns, and the role set is fixed and small.
"""
import pytest
from api.database import get_connection, insert_stakeholder, fetch_stakeholders


@pytest.mark.asyncio
async def test_all_five_roles_round_trip_as_booleans(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_DIR", str(tmp_path))
    from api.config import get_settings
    get_settings.cache_clear()
    try:
        async with get_connection("roles-test") as conn:
            await conn.execute("INSERT INTO projects (slug) VALUES ('roles-test')")
            await conn.commit()
            await insert_stakeholder(
                conn, project_id=1, name="Dougie McCrone", email="dougie@example.com",
                is_participant=True, is_reviewer=True, is_approver=True,
                is_project_admin=True, is_governor=True,
            )
            rows = await fetch_stakeholders(conn, project_id=1)
        assert len(rows) == 1
        r = rows[0]
        for flag in ("is_participant", "is_reviewer", "is_approver",
                     "is_project_admin", "is_governor"):
            assert r[flag] is True, f"{flag} did not round-trip as a bool"
    finally:
        get_settings.cache_clear()


@pytest.mark.asyncio
async def test_the_new_flags_default_to_false(tmp_path, monkeypatch):
    """A person added with no roles is nobody yet - adding a stakeholder must not
    accidentally confer administration."""
    monkeypatch.setenv("DATABASE_DIR", str(tmp_path))
    from api.config import get_settings
    get_settings.cache_clear()
    try:
        async with get_connection("roles-default") as conn:
            await conn.execute("INSERT INTO projects (slug) VALUES ('roles-default')")
            await conn.commit()
            await insert_stakeholder(conn, project_id=1, name="Nobody", email="n@example.com")
            rows = await fetch_stakeholders(conn, project_id=1)
        assert rows[0]["is_project_admin"] is False
        assert rows[0]["is_governor"] is False
    finally:
        get_settings.cache_clear()
