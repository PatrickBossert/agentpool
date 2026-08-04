# tests/test_value_chain_store.py
"""The model is a versioned output, so an edit is a new version with an attributed change.

That is the discipline already recorded for the approval loop: the versioned artefact is
the source of truth, an edit never touches a committed version, and every change says who
asked for it.
"""
import shutil
from pathlib import Path

import pytest

from api.config import get_settings

SLUG = "vc-store-test"
PROJECT = {
    "client_slug": SLUG,
    "llm_mode": "standard",
    "sector": "transport",
    "stakeholder_groups": ["Operations"],
    "value_stream_labels": ["Asset Mgmt"],
    "crews_enabled": ["requirements"],
    "review_gates": True,
    "slack_channel": "",
}

MODEL = {
    "model_version": 1,
    "parties": [{"id": "sp", "label": "SP-GS", "colour": "#1a5276"}],
    "segments": [{"id": "1", "label": "PROPERTY", "description": ""}],
    "activities": [{"id": "1.1", "segment_id": "1", "label": "Reactive",
                    "description": "", "active": True}],
    "contributions": [{"activity_id": "1.1", "party_id": "sp", "column": 10,
                       "description": "", "attribution": "stated"}],
    "tasks": [], "propositions": [], "links": [],
}


@pytest.fixture(autouse=True)
def clean():
    def wipe():
        settings = get_settings()
        Path(settings.database_dir, f"{SLUG}.db").unlink(missing_ok=True)
        proj = Path(settings.projects_dir, SLUG)
        if proj.exists():
            shutil.rmtree(proj)
    wipe()
    yield
    get_settings.cache_clear()
    wipe()


@pytest.mark.asyncio
async def test_loading_before_anything_is_saved_returns_none(client):
    await client.post("/projects", json=PROJECT)
    from api.services.value_chain_store import load_model
    assert await load_model(SLUG) is None


@pytest.mark.asyncio
async def test_saving_then_loading_round_trips(client):
    await client.post("/projects", json=PROJECT)
    from api.services.value_chain_store import load_model, save_model
    await save_model(SLUG, MODEL, saved_by="alice", summary="first")
    assert await load_model(SLUG) == MODEL


@pytest.mark.asyncio
async def test_a_second_save_creates_a_new_version_and_supersedes_the_first(client):
    await client.post("/projects", json=PROJECT)
    from api.database import fetch_agent_outputs, fetch_project, get_connection
    from api.services.value_chain_store import OUTPUT_TYPE, save_model

    await save_model(SLUG, MODEL, saved_by="alice", summary="first")
    edited = {**MODEL, "segments": [{"id": "1", "label": "PROPERTY", "description": "edited"}]}
    await save_model(SLUG, edited, saved_by="bob", summary="second")

    async with get_connection(SLUG) as conn:
        project = await fetch_project(conn, slug=SLUG)
        outputs = [
            o for o in await fetch_agent_outputs(conn, project_id=project["id"])
            if o["output_type"] == OUTPUT_TYPE
        ]
    assert len(outputs) == 2
    assert sum(1 for o in outputs if o["is_current"]) == 1
    assert max(o["version"] for o in outputs) == 2


@pytest.mark.asyncio
async def test_a_save_records_an_attributed_change(client):
    await client.post("/projects", json=PROJECT)
    from api.database import get_connection
    from api.services.value_chain_store import save_model

    await save_model(SLUG, MODEL, saved_by="alice", summary="tidied the labels")

    async with get_connection(SLUG) as conn:
        async with conn.execute(
            "SELECT requested_by, source, request FROM output_changes"
        ) as cur:
            rows = [dict(r) for r in await cur.fetchall()]
    assert len(rows) == 1
    assert rows[0]["requested_by"] == "alice"
    assert rows[0]["source"] == "edit"
    assert "tidied the labels" in rows[0]["request"]


@pytest.mark.asyncio
async def test_an_invalid_model_is_refused_and_saves_nothing(client):
    await client.post("/projects", json=PROJECT)
    from api.database import fetch_agent_outputs, fetch_project, get_connection
    from api.services.value_chain_store import save_model

    broken = {**MODEL, "contributions": [
        {"activity_id": "9.9", "party_id": "sp", "column": 10,
         "description": "", "attribution": "stated"}
    ]}
    with pytest.raises(ValueError):
        await save_model(SLUG, broken, saved_by="alice", summary="broken")

    async with get_connection(SLUG) as conn:
        project = await fetch_project(conn, slug=SLUG)
        outputs = await fetch_agent_outputs(conn, project_id=project["id"])
    assert outputs == [] or all(o["output_type"] != "value_chain_model" for o in outputs)


@pytest.mark.asyncio
async def test_the_endpoint_returns_the_model_and_accepts_a_save(client):
    await client.post("/projects", json=PROJECT)
    assert (await client.get(f"/projects/{SLUG}/value-chain-model")).status_code == 404

    put = await client.put(
        f"/projects/{SLUG}/value-chain-model",
        json={"model": MODEL, "summary": "first"},
    )
    assert put.status_code == 200

    got = await client.get(f"/projects/{SLUG}/value-chain-model")
    assert got.status_code == 200
    assert got.json()["model"] == MODEL


@pytest.mark.asyncio
async def test_the_endpoint_reports_validation_problems_rather_than_saving(client):
    await client.post("/projects", json=PROJECT)
    broken = {**MODEL, "activities": [
        {"id": "1.1", "segment_id": "7", "label": "Reactive",
         "description": "", "active": True}
    ]}
    resp = await client.put(
        f"/projects/{SLUG}/value-chain-model",
        json={"model": broken, "summary": "broken"},
    )
    assert resp.status_code == 422
    assert any("7" in p for p in resp.json()["detail"]["problems"])
