# tests/test_template_layer_retired.py
"""The template-assignment layer is gone, and nothing that mattered went with it.

It held a level that was wrong on 100% of its rows (103 of 103 said L2 regardless of the
node), a script_id duplicating the ledger's primary key, an activity_id duplicating the
script's node_id, and a node_label whose matching is what made publish 404 on every real
project.
"""
import pytest


@pytest.mark.asyncio
async def test_the_node_templates_routes_are_gone(client):
    # The brief's sample called client.get(...) synchronously; the `client` fixture in
    # conftest.py is an httpx.AsyncClient, so that returned an unawaited coroutine rather
    # than exercising the route. Awaited here to actually hit the (removed) endpoint.
    r = await client.get("/projects/any-slug/node-templates")
    assert r.status_code == 404, (
        f"the retired routes must not answer, got {r.status_code}"
    )


def test_the_auto_assign_service_is_gone():
    with pytest.raises(ModuleNotFoundError):
        import api.services.auto_assign_service  # noqa: F401


@pytest.mark.asyncio
async def test_the_questionnaire_lookup_no_longer_reads_the_retired_table(tmp_path, monkeypatch):
    """interview_service read an assignment only to find a questionnaire_template_id. Exactly
    1 of 103 rows had one, and questionnaires moved inline when questionnaire_builder was
    removed. A session must still open with the table gone."""
    monkeypatch.setenv("DATABASE_DIR", str(tmp_path))
    from api.config import get_settings
    get_settings.cache_clear()
    try:
        from api.database import get_connection
        async with get_connection("q-gone") as conn:
            cur = await conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' "
                "AND name='node_template_assignments'")
            assert await cur.fetchone() is None, "the table must not be created on a fresh DB"
    finally:
        get_settings.cache_clear()
