# tests/test_output_versioning.py
"""Two agents writing one output type must not collide on disk.

Maya's first value_chain_registry was numbered v1 because versions were scoped per agent,
and v1 was a filename Alex had already used. The rename destroyed his file, and both rows
went on claiming to be current.
"""
import sqlite3

import pytest

from agents.tools._db import insert_agent_output_sync

SLUG = "versioning-test"


@pytest.fixture
def project(tmp_path, monkeypatch):
    from api.config import get_settings

    get_settings.cache_clear()
    monkeypatch.setenv("PROJECTS_DIR", str(tmp_path))
    monkeypatch.setenv("DATABASE_DIR", str(tmp_path / "data"))
    (tmp_path / "data").mkdir()

    con = sqlite3.connect(str(tmp_path / "data" / f"{SLUG}.db"))
    con.execute("CREATE TABLE projects (id INTEGER PRIMARY KEY, slug TEXT)")
    con.execute(
        "CREATE TABLE agent_outputs (id INTEGER PRIMARY KEY, project_id INTEGER,"
        " agent_name TEXT, output_type TEXT, file_path TEXT, version INTEGER,"
        " review_status TEXT DEFAULT 'pending', revision_notes TEXT,"
        " is_current INTEGER NOT NULL DEFAULT 1,"
        " created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)"
    )
    con.execute("INSERT INTO projects (id, slug) VALUES (1, ?)", (SLUG,))
    con.commit()
    con.close()

    outputs = tmp_path / SLUG / "outputs"
    outputs.mkdir(parents=True)
    yield outputs
    get_settings.cache_clear()


def _write(outputs, agent, content):
    path = outputs / "shared_type.json"
    path.write_text(content)
    insert_agent_output_sync(SLUG, agent, "shared_type", str(path))


def test_a_second_agent_does_not_overwrite_the_first(project):
    _write(project, "value_chain_mapper", '{"from": "alex"}')
    _write(project, "interaction_designer", '{"from": "maya"}')

    files = sorted(p.name for p in project.glob("shared_type_v*.json"))
    assert files == ["shared_type_v1.json", "shared_type_v2.json"]
    assert (project / "shared_type_v1.json").read_text() == '{"from": "alex"}'


def test_only_one_row_is_current(project):
    _write(project, "value_chain_mapper", '{"from": "alex"}')
    _write(project, "interaction_designer", '{"from": "maya"}')

    con = sqlite3.connect(str(project.parent.parent / "data" / f"{SLUG}.db"))
    current = con.execute(
        "SELECT agent_name FROM agent_outputs WHERE output_type='shared_type' AND is_current=1"
    ).fetchall()
    con.close()
    assert len(current) == 1
    assert current[0][0] == "interaction_designer"


def test_one_agent_writing_twice_still_versions_normally(project):
    """The ordinary case, asserted so the fix does not break it."""
    _write(project, "value_chain_mapper", '{"v": 1}')
    _write(project, "value_chain_mapper", '{"v": 2}')

    files = sorted(p.name for p in project.glob("shared_type_v*.json"))
    assert files == ["shared_type_v1.json", "shared_type_v2.json"]
