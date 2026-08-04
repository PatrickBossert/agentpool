# agents/tools/sqlite_state.py
import json
from pathlib import Path
from typing import Callable
from pydantic import BaseModel, Field
from crewai.tools import BaseTool
from api.config import get_settings
from agents.tools._db import insert_agent_output_sync, latest_output_path


# Keys whose content is checked before it is stored. The tool returns a string and CrewAI
# hands that back to the agent, so refusing a write and returning the problems lets the
# agent correct itself inside the same run - rather than the fault surfacing days later
# through a Save button that appears to do nothing.
#
# This does not replace save_model's validation: a person editing in the grid can also
# construct an invalid model, and that path must keep refusing. The two guard different
# writers.
def _validate_value_chain_model(parsed: dict, slug: str) -> list[str]:
    from api.services.value_chain_model import (
        validate_against_registry,
        validate_contributions_have_tasks,
        validate_has_entity,
        validate_model,
    )

    problems = validate_model(parsed)

    # Held to the agent, not to the editor. A person adding a party in the grid creates a
    # contribution before its tasks exist; refusing that save would refuse the action that
    # created it. A deliverable has no such excuse - a party whose part is described and
    # decomposed into nothing cannot be interviewed about, scheduled, or held to anything.
    problems.extend(validate_contributions_have_tasks(parsed))

    # Same reasoning as contributions-have-tasks: the editor may hold a model with no entity
    # while a person works on it, but a deliverable that A and C scripts cannot anchor to is
    # not finished.
    problems.extend(validate_has_entity(parsed))

    # The registry is the ID authority, and it lives on disk - which is why the comparison
    # itself is pure and the load happens here. Every stable ID shared by the migrated model
    # and the agent's rebuild had been reused for a different activity, 14 of 14, under an
    # instruction that forbade it.
    problems.extend(validate_against_registry(parsed, _current_registry(slug)))
    return problems


def _current_registry(slug: str) -> dict:
    """The registry in force, or an empty ledger when there is none yet."""
    settings = get_settings()
    path = latest_output_path(
        Path(settings.projects_dir) / slug / "outputs" / "value_chain_registry.json"
    )
    if path is None:
        return {}
    try:
        return json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        # A registry that cannot be read is not a reason to refuse a write - that would
        # block everything on a corrupt sidecar.
        return {}


def _validate_value_chain_registry(parsed: dict, slug: str) -> list[str]:
    """The ledger may grow and may retire, but may not redefine or forget.

    Without this the model check is only as good as a file the same agent can replace in
    the same run: fourteen IDs were reused in one run precisely by writing a fresh registry
    first, after which every model check passed against it.
    """
    from api.services.value_chain_model import validate_registry_succession

    return validate_registry_succession(_current_registry(slug), parsed)


def _current_script_registry(slug: str) -> dict:
    """The script ledger in force, or an empty one when there is none yet."""
    settings = get_settings()
    path = latest_output_path(
        Path(settings.projects_dir) / slug / "outputs" / "interview_script_registry.json"
    )
    if path is None:
        return {}
    try:
        return json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return {}


def _validate_interview_scripts(parsed: dict, slug: str) -> list[str]:
    from api.services.interview_script_model import (
        validate_scripts,
        validate_scripts_against_registry,
    )

    problems = validate_scripts(parsed)
    # The value chain registry, not the script one: this checks that each script's anchor
    # names a node that exists.
    problems.extend(validate_scripts_against_registry(parsed, _current_registry(slug)))
    return problems


def _validate_interview_script_registry(parsed: dict, slug: str) -> list[str]:
    from api.services.interview_script_model import validate_script_registry_succession

    return validate_script_registry_succession(_current_script_registry(slug), parsed)


_VALIDATORS: dict[str, Callable[[dict, str], list[str]]] = {
    "value_chain_model": _validate_value_chain_model,
    "value_chain_registry": _validate_value_chain_registry,
    "interview_scripts": _validate_interview_scripts,
    "interview_script_registry": _validate_interview_script_registry,
}


class SQLiteStateToolInput(BaseModel):
    operation: str = Field(description="'read' or 'write'")
    key: str = Field(description="Unique key for this state blob (used as filename)")
    agent_name: str = Field(description="Name of the agent writing/reading this state")
    value: str = Field(default="", description="JSON string to write (required for 'write')")


class SQLiteStateTool(BaseTool):
    name: str = "SQLiteStateTool"
    description: str = (
        "Read or write a JSON state blob scoped to this project. "
        "Use 'write' to save intermediate results; use 'read' to retrieve them. "
        "The key becomes the filename (e.g. key='themes' → outputs/themes.json)."
    )
    args_schema: type[BaseModel] = SQLiteStateToolInput
    slug: str

    def _run(
        self,
        operation: str,
        key: str,
        agent_name: str,
        value: str = "",
    ) -> str:
        settings = get_settings()
        outputs_dir = Path(settings.projects_dir) / self.slug / "outputs"
        outputs_dir.mkdir(parents=True, exist_ok=True)
        file_path = outputs_dir / f"{key}.json"

        if operation == "write":
            try:
                parsed = json.loads(value)
            except json.JSONDecodeError as e:
                return f"Error: value is not valid JSON — {e}"

            validator = _VALIDATORS.get(key)
            if validator is not None:
                if not isinstance(parsed, dict):
                    return (
                        f"Error: {key} was not written - it is structurally invalid. "
                        f"Fix these and write it again: value must be a JSON object, "
                        f"got {type(parsed).__name__}."
                    )
                problems = validator(parsed, self.slug)
                if problems:
                    return (
                        f"Error: {key} was not written - it is structurally invalid. "
                        f"Fix these and write it again: " + "; ".join(problems)
                    )
            try:
                file_path.write_text(value)
                insert_agent_output_sync(
                    slug=self.slug,
                    agent_name=agent_name,
                    output_type=key,
                    file_path=str(file_path),
                )
            except (OSError, ValueError) as e:
                return f"Error: write failed — {e}"
            return f"Written to {file_path}"

        if operation == "read":
            # Resolve through latest_output_path: the write above is renamed to
            # a _vN suffix by insert_agent_output_sync, so reading file_path
            # directly never finds anything the tool itself wrote.
            stored = latest_output_path(file_path)
            if stored is None:
                return f"Error: no state found for key '{key}'"
            return stored.read_text()

        return f"Error: unknown operation '{operation}' — use 'read' or 'write'"
