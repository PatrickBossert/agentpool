# tests/test_derive_registry.py
import json
import sqlite3
import pytest
from pathlib import Path
from unittest.mock import patch


def _read_registry(base, slug):
    """Read the registry the tool just wrote.

    insert_agent_output_sync renames each output to a _vN suffix, so nothing is
    left at the base filename. Resolve the same way production does.
    """
    from agents.tools.derive_registry import _latest_registry
    outputs = base / "projects" / slug / "outputs"
    path = _latest_registry(outputs)
    assert path is not None, "no registry file was written"
    return json.loads(path.read_text())


SAMPLE_TREE = [
    {
        "id": "1", "label": "Inbound", "level": "L1",
        "children": [
            {
                "id": "1.1", "label": "Materials Receipt", "level": "L2",
                "children": [
                    {"id": "1.1.1", "label": "Goods-in Inspection", "level": "L3"},
                ]
            },
            {"id": "1.2", "label": "Supplier Management", "level": "L2", "children": []},
        ]
    },
    {
        "id": "2", "label": "Operations", "level": "L1",
        "children": [
            {"id": "2.1", "label": "Manufacturing", "level": "L2"},
        ]
    }
]


@pytest.fixture
def project_dir(tmp_path):
    slug = "test-proj"
    p = tmp_path / "projects" / slug / "outputs"
    p.mkdir(parents=True)
    db_path = tmp_path / "data" / "test-proj.db"
    db_path.parent.mkdir(parents=True)
    conn = sqlite3.connect(str(db_path))
    conn.execute("CREATE TABLE projects (id INTEGER PRIMARY KEY, slug TEXT)")
    # Mirror the production schema in api/database.py, including the columns
    # added by later migrations (is_current, revision_notes) — _db.py writes to
    # is_current, so omitting it fails with "no such column".
    conn.execute(
        "CREATE TABLE agent_outputs ("
        " id INTEGER PRIMARY KEY, project_id INTEGER, agent_name TEXT,"
        " output_type TEXT, file_path TEXT, version INTEGER,"
        " review_status TEXT DEFAULT 'pending', revision_notes TEXT,"
        " is_current INTEGER NOT NULL DEFAULT 1,"
        " created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)"
    )
    conn.execute("INSERT INTO projects (id, slug) VALUES (1, 'test-proj')")
    conn.commit()
    conn.close()
    return tmp_path, slug


def _write_tree(project_dir, slug, tree):
    base, _ = project_dir
    path = base / "projects" / slug / "outputs" / "value_chain_tree.json"
    path.write_text(json.dumps(tree))
    return path


def _make_tool(project_dir, slug):
    base, _ = project_dir
    from agents.tools.derive_registry import DeriveRegistryTool
    with patch("agents.tools.derive_registry.get_settings") as m_settings, \
         patch("agents.tools._db.get_settings") as m_db_settings:
        m_settings.return_value.projects_dir = str(base / "projects")
        m_db_settings.return_value.database_dir = str(base / "data")
        return DeriveRegistryTool(slug=slug), m_settings, m_db_settings


def test_derive_registry_no_tree(project_dir, tmp_path):
    slug = "test-proj"
    base = tmp_path
    from agents.tools.derive_registry import DeriveRegistryTool
    with patch("agents.tools.derive_registry.get_settings") as m:
        m.return_value.projects_dir = str(base / "projects")
        tool = DeriveRegistryTool(slug=slug)
        result = tool._run()
    assert "not found" in result


def test_derive_registry_creates_flat_entries(project_dir):
    base, slug = project_dir
    path = (base / "projects" / slug / "outputs" / "value_chain_tree.json")
    path.write_text(json.dumps(SAMPLE_TREE))
    from agents.tools.derive_registry import DeriveRegistryTool
    with patch("agents.tools.derive_registry.get_settings") as m_s, \
         patch("agents.tools._db.get_settings") as m_db:
        m_s.return_value.projects_dir = str(base / "projects")
        m_db.return_value.database_dir = str(base / "data")
        tool = DeriveRegistryTool(slug=slug)
        result = tool._run()

    assert "6 active" in result
    data = _read_registry(base, slug)
    assert data["schema_version"] == 2
    acts = data["activities"]
    assert len(acts) == 6
    ids = [a["id"] for a in acts]
    assert set(ids) == {"1", "1.1", "1.1.1", "1.2", "2", "2.1"}


def test_derive_registry_all_active(project_dir):
    base, slug = project_dir
    (base / "projects" / slug / "outputs" / "value_chain_tree.json").write_text(json.dumps(SAMPLE_TREE))
    from agents.tools.derive_registry import DeriveRegistryTool
    with patch("agents.tools.derive_registry.get_settings") as m_s, \
         patch("agents.tools._db.get_settings") as m_db:
        m_s.return_value.projects_dir = str(base / "projects")
        m_db.return_value.database_dir = str(base / "data")
        DeriveRegistryTool(slug=slug)._run()
    data = _read_registry(base, slug)
    assert all(a["active"] for a in data["activities"])


def test_derive_registry_parent_id_set(project_dir):
    base, slug = project_dir
    (base / "projects" / slug / "outputs" / "value_chain_tree.json").write_text(json.dumps(SAMPLE_TREE))
    from agents.tools.derive_registry import DeriveRegistryTool
    with patch("agents.tools.derive_registry.get_settings") as m_s, \
         patch("agents.tools._db.get_settings") as m_db:
        m_s.return_value.projects_dir = str(base / "projects")
        m_db.return_value.database_dir = str(base / "data")
        DeriveRegistryTool(slug=slug)._run()
    data = _read_registry(base, slug)
    by_id = {a["id"]: a for a in data["activities"]}
    assert by_id["1.1"]["parent_id"] == "1"
    assert by_id["1.1.1"]["parent_id"] == "1.1"
    assert "parent_id" not in by_id["1"]


def test_derive_registry_marks_removed_as_inactive(project_dir):
    base, slug = project_dir
    old_registry = {
        "schema_version": 2,
        "activities": [
            {"id": "1", "label": "Old L1", "level": "L1", "active": True},
            {"id": "1.1", "label": "Old L2", "level": "L2", "parent_id": "1", "active": True},
            {"id": "OLD", "label": "Removed", "level": "L2", "parent_id": "1", "active": True},
        ]
    }
    (base / "projects" / slug / "outputs" / "value_chain_registry.json").write_text(json.dumps(old_registry))
    # New tree does NOT contain "OLD"
    new_tree = [{"id": "1", "label": "New L1", "level": "L1", "children": [
        {"id": "1.1", "label": "New L2", "level": "L2"}
    ]}]
    (base / "projects" / slug / "outputs" / "value_chain_tree.json").write_text(json.dumps(new_tree))
    from agents.tools.derive_registry import DeriveRegistryTool
    with patch("agents.tools.derive_registry.get_settings") as m_s, \
         patch("agents.tools._db.get_settings") as m_db:
        m_s.return_value.projects_dir = str(base / "projects")
        m_db.return_value.database_dir = str(base / "data")
        result = DeriveRegistryTool(slug=slug)._run()

    assert "inactive" in result
    data = _read_registry(base, slug)
    by_id = {a["id"]: a for a in data["activities"]}
    assert by_id["1"]["active"] is True
    assert by_id["1.1"]["active"] is True
    assert by_id["OLD"]["active"] is False


def test_derive_registry_invalid_tree(project_dir):
    base, slug = project_dir
    (base / "projects" / slug / "outputs" / "value_chain_tree.json").write_text("not-json")
    from agents.tools.derive_registry import DeriveRegistryTool
    with patch("agents.tools.derive_registry.get_settings") as m_s:
        m_s.return_value.projects_dir = str(base / "projects")
        tool = DeriveRegistryTool(slug=slug)
        result = tool._run()
    assert "not valid JSON" in result


def test_derive_registry_preserves_history_across_runs(project_dir):
    """Running twice must keep entries dropped from the tree, as active=false.

    Regression test: insert_agent_output_sync renames each written registry to a
    _vN path, so the tool's second run found nothing at the base filename and
    silently started fresh — losing every previously-recorded inactive activity.
    """
    base, slug = project_dir
    outputs = base / "projects" / slug / "outputs"
    from agents.tools.derive_registry import DeriveRegistryTool

    def _run_with(tree):
        (outputs / "value_chain_tree.json").write_text(json.dumps(tree))
        with patch("agents.tools.derive_registry.get_settings") as m_s, \
             patch("agents.tools._db.get_settings") as m_db:
            m_s.return_value.projects_dir = str(base / "projects")
            m_db.return_value.database_dir = str(base / "data")
            return DeriveRegistryTool(slug=slug)._run()

    # First run records both activities
    _run_with([{"id": "1", "label": "Kept", "level": "L1", "children": [
        {"id": "1.1", "label": "Dropped Later", "level": "L2"}
    ]}])
    first = _read_registry(base, slug)
    assert {a["id"] for a in first["activities"]} == {"1", "1.1"}

    # Second run drops 1.1 from the tree — it must survive as inactive
    result = _run_with([{"id": "1", "label": "Kept", "level": "L1", "children": []}])

    assert "inactive" in result
    by_id = {a["id"]: a for a in _read_registry(base, slug)["activities"]}
    assert by_id["1"]["active"] is True
    assert by_id["1.1"]["active"] is False, "history lost between runs"
