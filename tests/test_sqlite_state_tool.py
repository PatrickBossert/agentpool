# tests/test_sqlite_state_tool.py
"""Unit tests for SQLiteStateTool.

Regression cover for a bug where the tool could never read back its own writes:
_run(operation="write") saved to outputs/<key>.json, insert_agent_output_sync
then renamed that file to <key>_v1.json, and _run(operation="read") looked only
at the un-suffixed path — so every read returned "no state found", silently
breaking state sharing between agents.
"""
import json
import sqlite3

import pytest
from unittest.mock import patch


@pytest.fixture
def state_project(tmp_path):
    """A project directory plus the minimal DB schema the tool writes to."""
    slug = "state-test"
    (tmp_path / "projects" / slug / "outputs").mkdir(parents=True)
    (tmp_path / "data").mkdir(parents=True)

    conn = sqlite3.connect(str(tmp_path / "data" / f"{slug}.db"))
    conn.execute("CREATE TABLE projects (id INTEGER PRIMARY KEY, slug TEXT)")
    # Mirrors api/database.py including migration-added columns
    conn.execute(
        "CREATE TABLE agent_outputs ("
        " id INTEGER PRIMARY KEY, project_id INTEGER, agent_name TEXT,"
        " output_type TEXT, file_path TEXT, version INTEGER,"
        " review_status TEXT DEFAULT 'pending', revision_notes TEXT,"
        " is_current INTEGER NOT NULL DEFAULT 1,"
        " created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)"
    )
    conn.execute("INSERT INTO projects (id, slug) VALUES (1, ?)", (slug,))
    conn.commit()
    conn.close()
    return tmp_path, slug


def _run(base, slug, **kwargs):
    from agents.tools.sqlite_state import SQLiteStateTool
    with patch("agents.tools.sqlite_state.get_settings") as m_s, \
         patch("agents.tools._db.get_settings") as m_db:
        m_s.return_value.projects_dir = str(base / "projects")
        m_db.return_value.database_dir = str(base / "data")
        return SQLiteStateTool(slug=slug)._run(**kwargs)


def test_write_then_read_round_trip(state_project):
    """The core regression: a value written must be readable back.

    Uses an owned, unvalidated key (`value_chain_summary` / `value_chain_mapper`) rather
    than a placeholder key - ownership now guards every write, and a key nobody owns would
    be refused before the round trip this test exists to check.
    """
    base, slug = state_project
    payload = {"hello": "world"}

    write_result = _run(base, slug, operation="write", key="value_chain_summary",
                        agent_name="value_chain_mapper", value=json.dumps(payload))
    assert "value_chain_summary" in write_result

    read_result = _run(base, slug, operation="read", key="value_chain_summary",
                       agent_name="value_chain_mapper")
    assert json.loads(read_result) == payload


def test_read_returns_latest_version_after_overwrite(state_project):
    """A second write must win — reads resolve the highest version, not the first."""
    base, slug = state_project
    for value in ({"v": 1}, {"v": 2}, {"v": 3}):
        _run(base, slug, operation="write", key="value_chain_summary",
             agent_name="value_chain_mapper", value=json.dumps(value))

    read_result = _run(base, slug, operation="read", key="value_chain_summary",
                       agent_name="value_chain_mapper")
    assert json.loads(read_result) == {"v": 3}


def test_read_missing_key_reports_not_found(state_project):
    base, slug = state_project
    result = _run(base, slug, operation="read", key="never_written",
                  agent_name="test_agent")
    assert "no state found" in result


def test_write_rejects_invalid_json(state_project):
    base, slug = state_project
    result = _run(base, slug, operation="write", key="value_chain_summary",
                  agent_name="value_chain_mapper", value="not-json")
    assert "not valid JSON" in result


def test_unknown_operation_reports_error(state_project):
    base, slug = state_project
    result = _run(base, slug, operation="delete", key="k", agent_name="test_agent")
    assert "unknown operation" in result
