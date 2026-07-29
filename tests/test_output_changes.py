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


async def _snapshot(conn, output_id: int) -> tuple[dict, list[dict]]:
    """The identifying content a note must leave untouched: the output's own
    row (version, file_path) and every commit/output link that names it."""
    async with conn.execute(
        "SELECT id, version, file_path FROM agent_outputs WHERE id=?", (output_id,)
    ) as cur:
        output_row = dict(await cur.fetchone())
    async with conn.execute(
        "SELECT commit_id, output_id FROM approval_commit_outputs ORDER BY commit_id, output_id"
    ) as cur:
        links = [dict(r) for r in await cur.fetchall()]
    return output_row, links


@pytest.mark.asyncio
async def test_a_note_leaves_committed_versions_untouched(client):
    """The invariant later projects' differential depends on."""
    await client.post("/projects", json=PROJECT)
    output_id = await _make_output(SLUG, "value_chain_mapper")

    await client.post(
        f"/projects/{SLUG}/commits",
        json={"crew_name": "discovery_mapping", "notes": ""},
    )

    from api.database import get_connection
    async with get_connection(SLUG) as conn:
        before_output, before_links = await _snapshot(conn, output_id)

    assert before_links == [{"commit_id": before_links[0]["commit_id"], "output_id": output_id}]

    await client.post(
        f"/projects/{SLUG}/changes",
        json={"output_id": output_id, "request": "later thought"},
    )

    async with get_connection(SLUG) as conn:
        after_output, after_links = await _snapshot(conn, output_id)

    assert after_output == before_output
    assert after_links == before_links


@pytest.mark.asyncio
async def test_with_no_commit_all_changes_are_returned(client):
    """Never committed means the whole history so far - there is no later point to
    measure a "since" from."""
    await client.post("/projects", json=PROJECT)
    output_id = await _make_output(SLUG, "value_chain_mapper")

    for text in ("first", "second"):
        await client.post(
            f"/projects/{SLUG}/changes", json={"output_id": output_id, "request": text}
        )

    listed = (
        await client.get(f"/projects/{SLUG}/changes?crew_name=discovery_mapping")
    ).json()
    assert [c["request"] for c in listed] == ["second", "first"]


@pytest.mark.asyncio
async def test_a_change_recorded_before_the_commit_is_excluded(client):
    """Explicit timestamps, not wall-clock order - the DB writes are on the same
    machine within the same test and could otherwise land in the same second."""
    await client.post("/projects", json=PROJECT)
    output_id = await _make_output(SLUG, "value_chain_mapper")

    from api.database import get_connection
    async with get_connection(SLUG) as conn:
        await conn.execute(
            "INSERT INTO output_changes (output_id, requested_by, source, request, created_at) "
            "VALUES (?,?,?,?,?)",
            (output_id, "patrick", "note", "before the commit", "2026-01-01 00:00:00"),
        )
        await conn.commit()

    resp = await client.post(
        f"/projects/{SLUG}/commits",
        json={"crew_name": "discovery_mapping", "notes": ""},
    )
    assert resp.status_code == 201

    async with get_connection(SLUG) as conn:
        # Pin the commit itself to an explicit point after the change above.
        await conn.execute(
            "UPDATE approval_commits SET committed_at=? WHERE crew_name=?",
            ("2026-01-02 00:00:00", "discovery_mapping"),
        )
        await conn.commit()

    listed = (
        await client.get(f"/projects/{SLUG}/changes?crew_name=discovery_mapping")
    ).json()
    assert listed == []


@pytest.mark.asyncio
async def test_only_changes_recorded_after_the_commit_are_counted(client):
    """Both a before- and an after-commit change exist, so this fails under the old
    "every change ever" behaviour as well as proving the new scoping works."""
    await client.post("/projects", json=PROJECT)
    output_id = await _make_output(SLUG, "value_chain_mapper")

    from api.database import get_connection
    async with get_connection(SLUG) as conn:
        await conn.execute(
            "INSERT INTO output_changes (output_id, requested_by, source, request, created_at) "
            "VALUES (?,?,?,?,?)",
            (output_id, "patrick", "note", "before the commit", "2026-01-01 00:00:00"),
        )
        await conn.commit()

    resp = await client.post(
        f"/projects/{SLUG}/commits",
        json={"crew_name": "discovery_mapping", "notes": ""},
    )
    assert resp.status_code == 201

    async with get_connection(SLUG) as conn:
        await conn.execute(
            "UPDATE approval_commits SET committed_at=? WHERE crew_name=?",
            ("2026-01-02 00:00:00", "discovery_mapping"),
        )
        await conn.execute(
            "INSERT INTO output_changes (output_id, requested_by, source, request, created_at) "
            "VALUES (?,?,?,?,?)",
            (output_id, "patrick", "note", "after the commit", "2026-01-03 00:00:00"),
        )
        await conn.commit()

    listed = (
        await client.get(f"/projects/{SLUG}/changes?crew_name=discovery_mapping")
    ).json()
    assert [c["request"] for c in listed] == ["after the commit"]


@pytest.mark.asyncio
async def test_a_change_against_an_unknown_output_is_rejected(client):
    await client.post("/projects", json=PROJECT)
    resp = await client.post(
        f"/projects/{SLUG}/changes",
        json={"output_id": 999999, "request": "nothing to change"},
    )
    assert resp.status_code == 422
