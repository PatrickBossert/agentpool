"""The ledger keeps its labels through BOTH doors that write it.

DeriveRegistryTool preserves a registered label so a regenerated tree cannot rewrite the
ledger. SQLiteStateTool is the other door - value_chain_registry is Alex's own key - and
when validate_registry_succession stopped refusing label changes, that door lost its guard
and gained no replacement. Run 29 wrote 'Capital and Revenue Financial Control (350M)' over
'Capital & Revenue Financial Control (£350M)' straight into the ledger.

ownership.py says it plainly: ownership stops another agent reaching for a key; succession
stops its owner corrupting it.
"""
import json
import pytest
import pytest_asyncio
from pathlib import Path
from api.config import get_settings
from api.database import get_connection
from agents.tools._db import current_output_path

REGISTERED = "Capital & Revenue Financial Control (£350M)"


@pytest_asyncio.fixture
async def ledger_project(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_DIR", str(tmp_path))
    monkeypatch.setenv("PROJECTS_DIR", str(tmp_path / "projects"))
    get_settings.cache_clear()
    slug = "ledger-label-test"
    outputs = tmp_path / "projects" / slug / "outputs"
    outputs.mkdir(parents=True, exist_ok=True)
    async with get_connection(slug) as conn:
        await conn.execute(
            "INSERT INTO projects (slug, sector) VALUES (?,?)", (slug, "test"))
        await conn.commit()
        async with conn.execute("SELECT id FROM projects WHERE slug=?", (slug,)) as cur:
            pid = (await cur.fetchone())[0]
        p = outputs / "value_chain_registry_v1.json"
        p.write_text(json.dumps({"schema_version": 2, "activities": [
            {"id": "3.3.3", "label": REGISTERED, "level": "L3", "active": True},
            {"id": "1", "label": "Property", "level": "L1", "active": True},
        ]}))
        await conn.execute(
            "INSERT INTO agent_outputs (project_id, agent_name, output_type, file_path,"
            " version, is_current) VALUES (?,?,?,?,1,1)",
            (pid, "value_chain_mapper", "value_chain_registry", str(p)))
        await conn.commit()
    yield slug, outputs
    get_settings.cache_clear()


def _write_registry(slug, activities):
    from agents.tools.sqlite_state import SQLiteStateTool
    return SQLiteStateTool(slug=slug, agent_name="value_chain_mapper")._run(
        operation="write", key="value_chain_registry",
        agent_name="value_chain_mapper",
        value=json.dumps({"schema_version": 2, "activities": activities}))


def _stored(slug):
    return {a["id"]: a for a in json.loads(
        Path(current_output_path(slug, "value_chain_registry")).read_text())["activities"]}


@pytest.mark.asyncio
async def test_a_direct_write_cannot_rewrite_a_registered_label(ledger_project):
    slug, _ = ledger_project
    result = _write_registry(slug, [
        {"id": "3.3.3", "label": "Capital and Revenue Financial Control (350M)",
         "level": "L3", "active": True},
        {"id": "1", "label": "Property", "level": "L1", "active": True},
    ])
    assert not result.startswith("Error"), result
    assert _stored(slug)["3.3.3"]["label"] == REGISTERED, \
        "the ledger took the agent's wording"


@pytest.mark.asyncio
async def test_a_new_id_takes_the_label_it_is_given(ledger_project):
    slug, _ = ledger_project
    _write_registry(slug, [
        {"id": "3.3.3", "label": REGISTERED, "level": "L3", "active": True},
        {"id": "1", "label": "Property", "level": "L1", "active": True},
        {"id": "4", "label": "A Brand New Chain", "level": "L1", "active": True},
    ])
    assert _stored(slug)["4"]["label"] == "A Brand New Chain"


@pytest.mark.asyncio
async def test_retiring_an_id_still_works(ledger_project):
    """Preservation must not block the one edit this door legitimately makes."""
    slug, _ = ledger_project
    _write_registry(slug, [
        {"id": "3.3.3", "label": REGISTERED, "level": "L3", "active": False},
        {"id": "1", "label": "Property", "level": "L1", "active": True},
    ])
    stored = _stored(slug)
    assert stored["3.3.3"]["active"] is False
    assert stored["3.3.3"]["label"] == REGISTERED


@pytest.mark.asyncio
async def test_the_first_registry_is_taken_as_written(ledger_project, tmp_path,
                                                      monkeypatch):
    """With no ledger yet there is nothing to preserve."""
    monkeypatch.setenv("DATABASE_DIR", str(tmp_path / "fresh"))
    monkeypatch.setenv("PROJECTS_DIR", str(tmp_path / "fresh" / "projects"))
    get_settings.cache_clear()
    slug = "fresh-ledger"
    (tmp_path / "fresh" / "projects" / slug / "outputs").mkdir(parents=True)
    async with get_connection(slug) as conn:
        await conn.execute(
            "INSERT INTO projects (slug, sector) VALUES (?,?)", (slug, "test"))
        await conn.commit()

    _write_registry(slug, [{"id": "1", "label": "First Ever", "level": "L1",
                            "active": True}])
    assert _stored(slug)["1"]["label"] == "First Ever"
