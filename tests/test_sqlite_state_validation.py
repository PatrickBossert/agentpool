# tests/test_sqlite_state_validation.py
"""An agent cannot store a structurally invalid model.

The tool returns a string and CrewAI hands that back to the agent, so a refusal that
names the problems is something the agent can act on inside the same run.
"""
import json
from pathlib import Path

import pytest

from agents.tools.sqlite_state import SQLiteStateTool

SLUG = "sqlite-state-validation-test"


@pytest.fixture(autouse=True)
def clean(tmp_path, monkeypatch):
    """Point the tool at a temporary projects directory so nothing touches real data."""
    from api.config import get_settings

    get_settings.cache_clear()
    monkeypatch.setenv("PROJECTS_DIR", str(tmp_path))
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
    """Refusing but writing anyway would be worse than not checking at all."""
    model = _valid_model()
    model["contributions"][0]["attribution"] = "guessed"

    tool = SQLiteStateTool(slug=SLUG)
    tool._run(
        operation="write", key="value_chain_model",
        agent_name="value_chain_mapper", value=json.dumps(model),
    )

    from api.config import get_settings
    path = Path(get_settings().projects_dir) / SLUG / "outputs" / "value_chain_model.json"
    assert not path.exists()


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
