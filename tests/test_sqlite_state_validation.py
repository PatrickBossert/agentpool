# tests/test_sqlite_state_validation.py
"""An agent cannot store a structurally invalid model.

The tool returns a string and CrewAI hands that back to the agent, so a refusal that
names the problems is something the agent can act on inside the same run.
"""
import json
import sqlite3
from pathlib import Path

import pytest

from agents.tools.sqlite_state import SQLiteStateTool

SLUG = "sqlite-state-validation-test"


@pytest.fixture(autouse=True)
def clean(tmp_path, monkeypatch):
    """Point the tool at its own temporary projects and database directories, with the
    minimal schema insert_agent_output_sync needs for SLUG to already exist as a project.

    Both directories live under this test's own tmp_path so nothing touches real data and
    ordering against other test files cannot matter - in particular test_projects_api.py's
    autouse fixture rmtree's the shared /tmp/agentpool_test before each of its own tests,
    and runs alphabetically before this file, so relying on that shared directory would be
    order-dependent.
    """
    from api.config import get_settings

    get_settings.cache_clear()
    monkeypatch.setenv("PROJECTS_DIR", str(tmp_path))

    db_dir = tmp_path / "data"
    db_dir.mkdir()
    monkeypatch.setenv("DATABASE_DIR", str(db_dir))

    conn = sqlite3.connect(str(db_dir / f"{SLUG}.db"))
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
    conn.execute("INSERT INTO projects (id, slug) VALUES (1, ?)", (SLUG,))
    conn.commit()
    conn.close()

    yield
    get_settings.cache_clear()


def _valid_model() -> dict:
    return {
        "model_version": 1,
        "segments": [{"id": "1", "label": "Segment"}],
        "parties": [{"id": "sp", "label": "SP-GS"}],
        "activities": [{"id": "1.1", "segment_id": "1", "label": "A"}],
        "contributions": [
            {"activity_id": "1.1", "party_id": "sp", "column": 10, "attribution": "stated"}
        ],
        "tasks": [],
        "propositions": [],
        "links": [],
    }


def test_a_valid_model_is_written():
    tool = SQLiteStateTool(slug=SLUG)
    result = tool._run(
        operation="write", key="value_chain_model",
        agent_name="value_chain_mapper", value=json.dumps(_valid_model()),
    )
    assert "Written to" in result


def test_an_invalid_model_is_refused_and_the_problems_are_returned():
    """The returned string is what the agent reads and acts on - a bare refusal would
    tell it nothing it could use."""
    model = _valid_model()
    model["activities"].append({"id": "1.2", "segment_id": "1", "label": "B"})
    model["contributions"].append(
        {"activity_id": "1.2", "party_id": "sp", "column": 10, "attribution": "stated"}
    )

    tool = SQLiteStateTool(slug=SLUG)
    result = tool._run(
        operation="write", key="value_chain_model",
        agent_name="value_chain_mapper", value=json.dumps(model),
    )

    assert "Written to" not in result
    assert "column 10" in result
    assert "1.1" in result and "1.2" in result


def test_an_invalid_model_writes_no_file():
    """Refusing but writing anyway would be worse than not checking at all.

    A successful write is immediately renamed by insert_agent_output_sync to a
    versioned name (value_chain_model_v1.json), so the unsuffixed path is absent
    whether the write was refused or whether it succeeded and got renamed out from
    under it - asserting on that one path alone proves nothing. Assert on evidence a
    successful write actually leaves behind instead: no file under any name for this
    key, and no agent_outputs row recording it.
    """
    model = _valid_model()
    model["contributions"][0]["attribution"] = "guessed"

    tool = SQLiteStateTool(slug=SLUG)
    tool._run(
        operation="write", key="value_chain_model",
        agent_name="value_chain_mapper", value=json.dumps(model),
    )

    from api.config import get_settings
    outputs_dir = Path(get_settings().projects_dir) / SLUG / "outputs"
    assert list(outputs_dir.glob("value_chain_model*.json")) == []

    db_path = Path(get_settings().database_dir) / f"{SLUG}.db"
    conn = sqlite3.connect(str(db_path))
    try:
        row_count = conn.execute(
            "SELECT COUNT(*) FROM agent_outputs WHERE output_type=?",
            ("value_chain_model",),
        ).fetchone()[0]
    finally:
        conn.close()
    assert row_count == 0


def test_a_json_array_is_refused_not_thrown():
    """validate_model assumes a dict and calls .get unconditionally, so a JSON array
    parses cleanly but must not reach the validator raw - it should be refused with
    the same Error: shape as any other structurally invalid write, not crash the tool."""
    tool = SQLiteStateTool(slug=SLUG)
    result = tool._run(
        operation="write", key="value_chain_model",
        agent_name="value_chain_mapper", value="[]",
    )

    assert result.startswith("Error:")
    assert "Written to" not in result

    from api.config import get_settings
    outputs_dir = Path(get_settings().projects_dir) / SLUG / "outputs"
    assert list(outputs_dir.glob("value_chain_model*.json")) == []

    db_path = Path(get_settings().database_dir) / f"{SLUG}.db"
    conn = sqlite3.connect(str(db_path))
    try:
        row_count = conn.execute(
            "SELECT COUNT(*) FROM agent_outputs WHERE output_type=?",
            ("value_chain_model",),
        ).fetchone()[0]
    finally:
        conn.close()
    assert row_count == 0


def test_a_json_scalar_is_refused_not_thrown():
    """Same guard, a bare JSON string this time - null and numbers take the same path."""
    tool = SQLiteStateTool(slug=SLUG)
    result = tool._run(
        operation="write", key="value_chain_model",
        agent_name="value_chain_mapper", value="null",
    )

    assert result.startswith("Error:")
    assert "Written to" not in result

    from api.config import get_settings
    outputs_dir = Path(get_settings().projects_dir) / SLUG / "outputs"
    assert list(outputs_dir.glob("value_chain_model*.json")) == []

    db_path = Path(get_settings().database_dir) / f"{SLUG}.db"
    conn = sqlite3.connect(str(db_path))
    try:
        row_count = conn.execute(
            "SELECT COUNT(*) FROM agent_outputs WHERE output_type=?",
            ("value_chain_model",),
        ).fetchone()[0]
    finally:
        conn.close()
    assert row_count == 0


def test_a_key_with_no_validator_is_written_unchanged():
    """The tool stays general - only registered keys are checked."""
    tool = SQLiteStateTool(slug=SLUG)
    result = tool._run(
        operation="write", key="interview_scripts",
        agent_name="interaction_designer", value=json.dumps({"anything": True}),
    )
    assert "Written to" in result


def test_the_real_agent_written_model_would_have_been_refused():
    """The model that prompted this work. Had this check existed, Alex would have been
    told inside his own run rather than a person finding it days later."""
    path = Path("projects/sp-gs-am/outputs/value_chain_model_v2.json")
    if not path.exists():
        pytest.skip("sp-gs-am fixtures not present in this checkout")

    tool = SQLiteStateTool(slug=SLUG)
    result = tool._run(
        operation="write", key="value_chain_model",
        agent_name="value_chain_mapper", value=path.read_text(),
    )

    assert "Written to" not in result
    assert "5.1" in result


def _no_model_written() -> tuple[list, int]:
    """The evidence a refused write leaves: no file under any name, and no output row."""
    from api.config import get_settings

    outputs_dir = Path(get_settings().projects_dir) / SLUG / "outputs"
    files = list(outputs_dir.glob("value_chain_model*.json"))

    conn = sqlite3.connect(str(Path(get_settings().database_dir) / f"{SLUG}.db"))
    try:
        rows = conn.execute(
            "SELECT COUNT(*) FROM agent_outputs WHERE output_type=?",
            ("value_chain_model",),
        ).fetchone()[0]
    finally:
        conn.close()
    return files, rows


def _write_registry(tool: SQLiteStateTool, label: str) -> None:
    """Register 1.1 as meaning `label`, through the tool so the _vN rename happens."""
    tool._run(
        operation="write",
        key="value_chain_registry",
        agent_name="value_chain_mapper",
        value=json.dumps(
            {
                "schema_version": 2,
                "activities": [
                    {"id": "1", "label": "Segment", "level": "L1", "active": True},
                    {"id": "1.1", "label": label, "level": "L2", "active": True,
                     "parent_id": "1"},
                ],
            }
        ),
    )


def test_a_model_reusing_a_registered_id_is_refused_and_no_row_is_recorded():
    """The registry is the ID authority. 1.1 already means one thing; a model arriving
    with a different label for it is renaming a stable ID, which is what happened 14
    times in one run under an instruction that forbade it."""
    tool = SQLiteStateTool(slug=SLUG)
    _write_registry(tool, "Fleet Strategy & Policy Setting")

    result = tool._run(
        operation="write", key="value_chain_model",
        agent_name="value_chain_mapper", value=json.dumps(_valid_model()),
    )

    assert "Written to" not in result
    # Both labels: the agent's correction is to take a different id for the new thing,
    # and it cannot do that without being told what the id already means.
    assert "Fleet Strategy & Policy Setting" in result
    assert "1.1" in result
    files, rows = _no_model_written()
    assert files == [] and rows == 0


def test_a_model_agreeing_with_the_registry_is_written():
    tool = SQLiteStateTool(slug=SLUG)
    _write_registry(tool, "A")

    result = tool._run(
        operation="write", key="value_chain_model",
        agent_name="value_chain_mapper", value=json.dumps(_valid_model()),
    )

    assert "Written to" in result


def test_a_model_is_written_when_no_registry_exists_yet():
    """A first run has nothing to check against and must not be blocked by its absence."""
    tool = SQLiteStateTool(slug=SLUG)
    result = tool._run(
        operation="write", key="value_chain_model",
        agent_name="value_chain_mapper", value=json.dumps(_valid_model()),
    )

    assert "Written to" in result


def _registry_payload(*entries: tuple[str, str, str], active: bool = True) -> str:
    return json.dumps(
        {
            "schema_version": 2,
            "activities": [
                {"id": i, "label": l, "level": v, "active": active} for i, l, v in entries
            ],
        }
    )


def _write_registry_payload(tool: SQLiteStateTool, payload: str) -> str:
    return tool._run(
        operation="write", key="value_chain_registry",
        agent_name="value_chain_mapper", value=payload,
    )


def _no_registry_written_since(before: int) -> bool:
    from api.config import get_settings

    conn = sqlite3.connect(str(Path(get_settings().database_dir) / f"{SLUG}.db"))
    try:
        rows = conn.execute(
            "SELECT COUNT(*) FROM agent_outputs WHERE output_type=?",
            ("value_chain_registry",),
        ).fetchone()[0]
    finally:
        conn.close()
    return rows == before


def test_a_registry_redefining_a_registered_id_is_refused():
    """The ledger is the ID authority, and the agent that writes the model writes it too.

    Left unchecked, the model validator is only as good as a file the same run can replace
    - which is exactly how fourteen IDs were reused while every model check passed.
    """
    tool = SQLiteStateTool(slug=SLUG)
    _write_registry_payload(tool, _registry_payload(("2.1", "Fleet Strategy", "L2")))

    result = _write_registry_payload(
        tool, _registry_payload(("2.1", "Multi-Year Work Packaging", "L2"))
    )

    assert "Written to" not in result
    assert "Fleet Strategy" in result and "Multi-Year Work Packaging" in result
    assert _no_registry_written_since(1)


def test_a_registry_dropping_a_registered_id_is_refused():
    tool = SQLiteStateTool(slug=SLUG)
    _write_registry_payload(
        tool, _registry_payload(("1.1", "Strategy", "L2"), ("1.2", "Acquisition", "L2"))
    )

    result = _write_registry_payload(tool, _registry_payload(("1.1", "Strategy", "L2")))

    assert "Written to" not in result
    assert "1.2" in result
    assert _no_registry_written_since(1)


def test_a_registry_that_grows_and_retires_is_written():
    tool = SQLiteStateTool(slug=SLUG)
    _write_registry_payload(tool, _registry_payload(("1.1", "Strategy", "L2")))

    grown = json.dumps(
        {
            "schema_version": 2,
            "activities": [
                {"id": "1.1", "label": "Strategy", "level": "L2", "active": False},
                {"id": "1.2", "label": "Acquisition", "level": "L2", "active": True},
            ],
        }
    )
    assert "Written to" in _write_registry_payload(tool, grown)


def test_a_first_registry_is_written_because_there_is_nothing_to_succeed():
    tool = SQLiteStateTool(slug=SLUG)
    result = _write_registry_payload(tool, _registry_payload(("1", "Property", "L1")))
    assert "Written to" in result
