# tests/test_output_changes.py
"""A change asked of an output, recorded with who asked.

In this project the only door is a reviewer's note. Chat and inline editing arrive
later and write the same rows with a different source.
"""
import pytest
from pathlib import Path

from api.config import get_settings

SLUG = "changes-test"
PROJECT = {
    "client_slug": SLUG,
    "llm_mode": "standard",
    "sector": "transport",
    "stakeholder_groups": ["Operations"],
    "value_stream_labels": ["Asset Mgmt"],
    "crews_enabled": ["discovery"],
    "review_gates": True,
    "slack_channel": "",
}


@pytest.fixture(autouse=True)
def clean():
    settings = get_settings()
    db_path = Path(settings.database_dir) / f"{SLUG}.db"
    db_path.unlink(missing_ok=True)
    yield
    get_settings.cache_clear()
    db_path.unlink(missing_ok=True)


async def _make_output(slug: str, agent_name: str) -> int:
    from api.database import get_connection, fetch_project, insert_agent_output
    async with get_connection(slug) as conn:
        project = await fetch_project(conn, slug=slug)
        return await insert_agent_output(
            conn,
            project_id=project["id"],
            agent_name=agent_name,
            output_type="value_chain",
            file_path="/tmp/vc.json",
            version=1,
        )


@pytest.mark.asyncio
async def test_a_note_is_recorded_against_the_caller(client):
    await client.post("/projects", json=PROJECT)
    output_id = await _make_output(SLUG, "value_chain_mapper")

    resp = await client.post(
        f"/projects/{SLUG}/changes",
        json={"output_id": output_id, "request": "Add an L3 for asset tagging"},
    )
    assert resp.status_code == 201
    assert resp.json()["requested_by"] == "admin"
    assert resp.json()["source"] == "note"


@pytest.mark.asyncio
async def test_changes_are_listed_for_the_crew_that_owns_the_output(client):
    await client.post("/projects", json=PROJECT)
    mine = await _make_output(SLUG, "value_chain_mapper")     # discovery_mapping
    theirs = await _make_output(SLUG, "interaction_designer")  # assessment_design

    for output_id, text in ((mine, "mine"), (theirs, "theirs")):
        await client.post(
            f"/projects/{SLUG}/changes",
            json={"output_id": output_id, "request": text},
        )

    listed = (
        await client.get(f"/projects/{SLUG}/changes?crew_name=discovery_mapping")
    ).json()
    assert [c["request"] for c in listed] == ["mine"]


@pytest.mark.asyncio
async def test_a_note_leaves_committed_versions_untouched(client):
    """The invariant later projects' differential depends on."""
    await client.post("/projects", json=PROJECT)
    output_id = await _make_output(SLUG, "value_chain_mapper")

    await client.post(
        f"/projects/{SLUG}/commits",
        json={"crew_name": "discovery_mapping", "notes": ""},
    )
    await client.post(
        f"/projects/{SLUG}/changes",
        json={"output_id": output_id, "request": "later thought"},
    )

    from api.database import get_connection
    async with get_connection(SLUG) as conn:
        async with conn.execute(
            "SELECT output_id FROM approval_commit_outputs"
        ) as cur:
            frozen = [r["output_id"] for r in await cur.fetchall()]
    assert frozen == [output_id]


@pytest.mark.asyncio
async def test_a_change_against_an_unknown_output_is_rejected(client):
    await client.post("/projects", json=PROJECT)
    resp = await client.post(
        f"/projects/{SLUG}/changes",
        json={"output_id": 999999, "request": "nothing to change"},
    )
    assert resp.status_code == 422
