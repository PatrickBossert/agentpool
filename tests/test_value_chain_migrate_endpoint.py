# tests/test_value_chain_migrate_endpoint.py
"""Migration is a one-off recovery, not a repeatable import."""
import json
import shutil
from pathlib import Path

import pytest

from api.config import get_settings
from tests.test_value_chain_migration import MERMAID, REGISTRY

SLUG = "vc-migrate-test"
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


async def _write_fixtures(slug: str) -> None:
    """Put a registry and a Mermaid output where the migration looks for them."""
    outputs = Path(get_settings().projects_dir) / slug / "outputs"
    outputs.mkdir(parents=True, exist_ok=True)
    (outputs / "value_chain_registry.json").write_text(json.dumps(REGISTRY))
    (outputs / "value_chain_v1.md").write_text(MERMAID)


@pytest.mark.asyncio
async def test_migration_builds_a_model_from_the_registry_and_diagram(client):
    await client.post("/projects", json=PROJECT)
    await _write_fixtures(SLUG)   # writes registry json and the mermaid markdown

    resp = await client.post(f"/projects/{SLUG}/value-chain-model/migrate")
    assert resp.status_code == 200
    assert resp.json()["created"] is True

    got = await client.get(f"/projects/{SLUG}/value-chain-model")
    model = got.json()["model"]
    # migrate() (Task 2) treats every class referenced by a Mermaid node as a party, not
    # only classes that end up matched to a registry task. MERMAID's node C ("Inspect
    # asset") uses classDef partnerDXI even though no registry L3 label matches it, so
    # partnerDXI is a legitimate third party here - see
    # test_the_real_project_migrates_cleanly in test_value_chain_migration.py, which
    # asserts the same three-party outcome for the real sp-gs-am fixtures.
    assert {p["id"] for p in model["parties"]} == {"sp", "partnerISS", "partnerDXI"}


@pytest.mark.asyncio
async def test_migration_refuses_to_overwrite_an_existing_model(client):
    """Re-running must not silently discard edits somebody has made since."""
    await client.post("/projects", json=PROJECT)
    await _write_fixtures(SLUG)
    first = await client.post(f"/projects/{SLUG}/value-chain-model/migrate")
    assert first.status_code == 200  # must actually have created a model, or the 409
    # below would be vacuous - proving nothing about the refusal it claims to test.

    again = await client.post(f"/projects/{SLUG}/value-chain-model/migrate")
    assert again.status_code == 409


@pytest.mark.asyncio
async def test_migration_without_source_files_reports_that_clearly(client):
    await client.post("/projects", json=PROJECT)
    resp = await client.post(f"/projects/{SLUG}/value-chain-model/migrate")
    assert resp.status_code == 404


def _mermaid_for(party: str, colour: str) -> str:
    """A minimal single-node diagram, attributing 'Raise works order' to `party` - so the
    migrated task's party_id reveals which version file the migration actually opened."""
    return (
        '```mermaid\n'
        'flowchart LR\n'
        f'  A["Raise works order"]:::{party}\n'
        f'  classDef {party} fill:{colour},color:#fff,stroke:{colour}\n'
        '```'
    )


@pytest.mark.asyncio
async def test_migration_picks_the_highest_numbered_version_not_the_lexically_last(client):
    """'value_chain_v9.md' sorts after 'value_chain_v12.md' lexically ('9' > '1'), but v12
    is the real latest version - the trap the real sp-gs-am project hits today. A
    value_chain_vFinal.md with no numeric suffix is also present, to prove it is excluded
    from the candidates rather than crashing the sort or being treated as "latest".

    Each version's diagram attributes the same task to a distinct party, so the assertion
    is on the migrated output (which party the task landed with) rather than on which file
    happened to be opened.
    """
    await client.post("/projects", json=PROJECT)
    outputs = Path(get_settings().projects_dir) / SLUG / "outputs"
    outputs.mkdir(parents=True, exist_ok=True)
    (outputs / "value_chain_registry.json").write_text(json.dumps(REGISTRY))
    (outputs / "value_chain_v1.md").write_text(_mermaid_for("partyV1", "#111111"))
    (outputs / "value_chain_v9.md").write_text(_mermaid_for("partyV9", "#222222"))
    (outputs / "value_chain_v12.md").write_text(_mermaid_for("partyV12", "#333333"))
    (outputs / "value_chain_vFinal.md").write_text(_mermaid_for("partyVFinal", "#444444"))

    resp = await client.post(f"/projects/{SLUG}/value-chain-model/migrate")
    assert resp.status_code == 200

    got = await client.get(f"/projects/{SLUG}/value-chain-model")
    model = got.json()["model"]
    task = next(t for t in model["tasks"] if t["id"] == "1.1.1")
    assert task["party_id"] == "partyV12"
