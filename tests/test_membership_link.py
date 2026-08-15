"""One person, one login, a row per engagement.

project_memberships already meant "this user is on this project". Carrying stakeholder_id
makes it mean "and this is who they are here", which is what removes the email match: the
same login points at a different person record on each project.
"""
import pytest
from api.database import get_system_connection, insert_user, link_membership


@pytest.mark.asyncio
async def test_one_login_links_to_a_different_person_on_each_project(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_DIR", str(tmp_path))
    from api.config import get_settings
    get_settings.cache_clear()
    try:
        async with get_system_connection() as conn:
            await insert_user(conn, username="patrick@arup.com", email="patrick@arup.com",
                              role="reviewer", hashed_pw="x")
            cur = await conn.execute("SELECT id FROM users WHERE username=?",
                                     ("patrick@arup.com",))
            uid = (await cur.fetchone())[0]
            await link_membership(conn, user_id=uid, project_slug="alpha", stakeholder_id=7)
            await link_membership(conn, user_id=uid, project_slug="beta", stakeholder_id=41)
            cur = await conn.execute(
                "SELECT project_slug, stakeholder_id FROM project_memberships "
                "WHERE user_id=? ORDER BY project_slug", (uid,))
            rows = [tuple(r) for r in await cur.fetchall()]
        assert rows == [("alpha", 7), ("beta", 41)]
    finally:
        get_settings.cache_clear()


@pytest.mark.asyncio
async def test_relinking_the_same_project_replaces_rather_than_duplicates(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_DIR", str(tmp_path))
    from api.config import get_settings
    get_settings.cache_clear()
    try:
        async with get_system_connection() as conn:
            await insert_user(conn, username="d@example.com", email="d@example.com",
                              role="reviewer", hashed_pw="x")
            cur = await conn.execute("SELECT id FROM users WHERE username=?", ("d@example.com",))
            uid = (await cur.fetchone())[0]
            await link_membership(conn, user_id=uid, project_slug="alpha", stakeholder_id=7)
            await link_membership(conn, user_id=uid, project_slug="alpha", stakeholder_id=9)
            cur = await conn.execute(
                "SELECT stakeholder_id FROM project_memberships WHERE user_id=?", (uid,))
            rows = [r[0] for r in await cur.fetchall()]
        assert rows == [9], "UNIQUE(user_id, project_slug) means one row, updated not doubled"
    finally:
        get_settings.cache_clear()
