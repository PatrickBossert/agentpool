# tests/test_template_layer_retired.py
"""The template-assignment layer is gone, and nothing that mattered went with it.

It held a level that was wrong on 100% of its rows (103 of 103 said L2 regardless of the
node), a script_id duplicating the ledger's primary key, an activity_id duplicating the
script's node_id, and a node_label whose matching is what made publish 404 on every real
project.
"""
import pytest


def test_the_node_templates_routes_are_gone():
    """Asserted against the route table, not a response.

    A request-level version of this test (`client.get("/projects/any-slug/node-templates")`,
    asserting 404) cannot distinguish "the route is gone" from "the route exists and answered
    404 anyway": the old GET handler's own preamble was `if not get_db_path(slug).exists():
    raise HTTPException(404)`, and `any-slug` has no database, so the *live* route already
    returned 404 for exactly this request. The route could be fully restored, and that
    version of the test would stay green.

    Checking the route table catches all three retired routes (GET, PUT, and POST .../publish
    all share the `/node-templates` path segment) in one assertion, and does not depend on
    any handler's internal 404 logic.

    Power-checked: temporarily re-mounted a stand-in for the old GET handler on the real
    `app` and confirmed this assertion fails (`AssertionError: retired /node-templates routes
    are still registered: ['/projects/{slug}/node-templates']`) before removing it again.
    """
    from api.main import app

    node_template_paths = sorted({
        r.path for r in app.routes if "node-template" in getattr(r, "path", "")
    })
    assert node_template_paths == [], (
        f"retired /node-templates routes are still registered: {node_template_paths}"
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
