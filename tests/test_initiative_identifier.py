"""Tests for the updated initiative_identifier task schema."""
from unittest.mock import MagicMock, patch


def test_task_description_includes_capability_uplifts():
    from agents.architecture.initiative_identifier import create_initiative_identifier_task
    agent = MagicMock()
    with patch("agents.architecture.initiative_identifier.Task") as MockTask:
        MockTask.return_value = MagicMock()
        create_initiative_identifier_task(agent=agent, context_tasks=[])
    _, kwargs = MockTask.call_args
    assert "capability_uplifts" in kwargs["description"]


def test_task_description_lists_all_seven_dimensions():
    from agents.architecture.initiative_identifier import create_initiative_identifier_task
    agent = MagicMock()
    with patch("agents.architecture.initiative_identifier.Task") as MockTask:
        MockTask.return_value = MagicMock()
        create_initiative_identifier_task(agent=agent, context_tasks=[])
    _, kwargs = MockTask.call_args
    for dim in ("people", "data", "systems", "organisation", "partnership", "architectural", "operating_model"):
        assert dim in kwargs["description"], f"Dimension '{dim}' missing from task description"


def test_task_description_includes_initiative_type():
    from agents.architecture.initiative_identifier import create_initiative_identifier_task
    agent = MagicMock()
    with patch("agents.architecture.initiative_identifier.Task") as MockTask:
        MockTask.return_value = MagicMock()
        create_initiative_identifier_task(agent=agent, context_tasks=[])
    _, kwargs = MockTask.call_args
    assert "initiative_type" in kwargs["description"]
    assert "enabler" in kwargs["description"]
    assert "change_activity" in kwargs["description"]


def test_task_description_includes_dependency_fields():
    from agents.architecture.initiative_identifier import create_initiative_identifier_task
    agent = MagicMock()
    with patch("agents.architecture.initiative_identifier.Task") as MockTask:
        MockTask.return_value = MagicMock()
        create_initiative_identifier_task(agent=agent, context_tasks=[])
    _, kwargs = MockTask.call_args
    assert "enabler_dependencies" in kwargs["description"]
    assert "change_dependencies" in kwargs["description"]


def test_task_description_includes_cost_estimate():
    from agents.architecture.initiative_identifier import create_initiative_identifier_task
    agent = MagicMock()
    with patch("agents.architecture.initiative_identifier.Task") as MockTask:
        MockTask.return_value = MagicMock()
        create_initiative_identifier_task(agent=agent, context_tasks=[])
    _, kwargs = MockTask.call_args
    assert "cost_estimate" in kwargs["description"]


def test_task_description_does_not_use_old_schema():
    """Old fields 'capability_gaps' and 'category' must not appear in the new schema."""
    from agents.architecture.initiative_identifier import create_initiative_identifier_task
    agent = MagicMock()
    with patch("agents.architecture.initiative_identifier.Task") as MockTask:
        MockTask.return_value = MagicMock()
        create_initiative_identifier_task(agent=agent, context_tasks=[])
    _, kwargs = MockTask.call_args
    assert "capability_gaps" not in kwargs["description"]
    # 'category' may appear in prose but not as a schema field key
    assert '"category"' not in kwargs["description"]
