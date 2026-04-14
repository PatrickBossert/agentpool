"""Integration tests for each tool. Requires ChromaDB running and ANTHROPIC_API_KEY set."""
import json
import pytest
from pathlib import Path
from api.config import get_settings


@pytest.mark.integration
def test_sqlite_state_tool_round_trip(test_slug, project_id):
    from agents.tools.sqlite_state import SQLiteStateTool
    settings = get_settings()

    tool = SQLiteStateTool(slug=test_slug)

    # Write a value
    write_result = tool._run(
        operation="write",
        key="test_state",
        agent_name="test_agent",
        value=json.dumps({"hello": "world"}),
    )
    assert "test_state" in write_result

    # Read it back
    read_result = tool._run(
        operation="read",
        key="test_state",
        agent_name="test_agent",
    )
    data = json.loads(read_result)
    assert data == {"hello": "world"}

    # Verify file was written
    file_path = Path(settings.projects_dir) / test_slug / "outputs" / "test_state.json"
    assert file_path.exists()
