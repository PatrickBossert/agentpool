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
def _validate_value_chain_model(parsed: dict) -> list[str]:
    from api.services.value_chain_model import validate_model
    return validate_model(parsed)


_VALIDATORS: dict[str, Callable[[dict], list[str]]] = {
    "value_chain_model": _validate_value_chain_model,
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
        "The key becomes the filename (e.g. key='requirements' → outputs/requirements.json)."
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
                problems = validator(parsed)
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
