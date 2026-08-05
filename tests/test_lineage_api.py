# tests/test_lineage_api.py
"""One call carrying everything the Lineage tab renders."""
import pytest

SLUG = "lineage-api-test"
PROJECT = {
    "client_slug": SLUG, "llm_mode": "standard", "sector": "utilities",
    "stakeholder_groups": [], "value_stream_labels": [], "crews_enabled": ["requirements"],
    "review_gates": True, "slack_channel": "",
}


@pytest.mark.asyncio
async def test_lineage_returns_outputs_with_state(client):
    await client.post("/projects", json=PROJECT)
    resp = await client.get(f"/projects/{SLUG}/lineage")
    assert resp.status_code == 200
    body = resp.json()
    assert "outputs" in body and "documents" in body and "blocked_writes" in body


@pytest.mark.asyncio
async def test_documents_are_returned_by_name_not_by_stored_filename(client):
    """The stored name is a hash. Returning it would make every citation unreadable, which is
    the defect this whole thread started from."""
    await client.post("/projects", json=PROJECT)
    from api.database import get_connection

    async with get_connection(SLUG) as conn:
        await conn.execute(
            "INSERT INTO client_documents (id, project_id, filename, original_name,"
            " file_path, content_type, size_bytes) VALUES (3,1,'d89a.pdf','Annual.pdf','x','p',1)"
        )
        await conn.commit()

    body = (await client.get(f"/projects/{SLUG}/lineage")).json()
    assert body["documents"]["3"] == "Annual.pdf"


@pytest.mark.asyncio
async def test_an_unknown_project_is_404(client):
    resp = await client.get("/projects/no-such-project/lineage")
    assert resp.status_code == 404
