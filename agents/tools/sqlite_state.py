# agents/tools/sqlite_state.py
import json
from pathlib import Path
from typing import Callable
from pydantic import BaseModel, Field
from crewai.tools import BaseTool
from api.config import get_settings
from agents.tools._db import (
    insert_agent_output_sync,
    latest_output_path,
    link_output_sync,
    output_id_for_path_sync,
    record_blocked_write_sync,
    record_run_input_sync,
)
from agents.tools.ownership import OUTPUT_OWNERS, check_write


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


def _project_disciplines(slug: str) -> tuple[str, ...]:
    """The project's own vertical axis, or the default list.

    A missing or unreadable config is not a reason to refuse a write - that would block every
    script on a sidecar file.
    """
    from api.config import load_project_config
    from api.services.interview_script_model import DEFAULT_DISCIPLINES

    settings = get_settings()
    try:
        config = load_project_config(Path(settings.projects_dir) / slug)
        return tuple(config.get("disciplines") or DEFAULT_DISCIPLINES)
    except Exception:
        return DEFAULT_DISCIPLINES


def _current_levers(slug: str) -> list[dict]:
    """Morgan's levers, or none when she has not run.

    Absence is not a failure: Maya may legitimately design before the levers exist, and
    refusing her write then would block the pipeline on an upstream artefact.
    """
    settings = get_settings()
    path = latest_output_path(
        Path(settings.projects_dir) / slug / "outputs" / "value_levers.json"
    )
    if path is None:
        return []
    try:
        loaded = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return []
    return loaded if isinstance(loaded, list) else []


def _validate_interview_scripts(parsed: dict, slug: str) -> list[str]:
    from api.services.interview_script_model import (
        validate_elicitation_order,
        validate_levers_unnamed_in_unaided_sections,
        validate_scripts,
        validate_scripts_against_registry,
    )

    problems = validate_scripts(parsed, disciplines=_project_disciplines(slug))
    # The value chain registry, not the script one: this checks that each script's anchor
    # names a node that exists.
    problems.extend(validate_scripts_against_registry(parsed, _current_registry(slug)))
    # The ordering rule is checkable, so it is checked rather than left to an instruction
    # Maya may or may not follow.
    problems.extend(validate_elicitation_order(parsed))
    problems.extend(validate_levers_unnamed_in_unaided_sections(parsed, _current_levers(slug)))
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
    agent_name: str = ""
    run_id: int = 0

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
            # The identity the tool was built with, not the one the caller supplied. An
            # identity an agent asserts about itself is not an identity.
            identity = self.agent_name or agent_name
            if self.agent_name and agent_name and agent_name != self.agent_name:
                return (
                    f"Refused: this tool belongs to {self.agent_name}, and the write claims "
                    f"to be from {agent_name}."
                )
            refusal = check_write(key, identity)
            if refusal:
                try:
                    record_blocked_write_sync(
                        self.slug, self.run_id, identity, key,
                        OUTPUT_OWNERS.get(key), refusal,
                    )
                except Exception:
                    pass  # never let bookkeeping turn a refusal into a permitted write
                return refusal
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
                new_output_id = insert_agent_output_sync(
                    slug=self.slug,
                    agent_name=agent_name,
                    output_type=key,
                    file_path=str(file_path),
                )
            except (OSError, ValueError) as e:
                return f"Error: write failed — {e}"
            try:
                link_output_sync(self.slug, self.run_id, new_output_id)
            except Exception:
                # The write already landed - both the file and its agent_outputs row are
                # durable by this point. Letting this raise would tell the agent the write
                # failed when it didn't, and it would write again, versioning a duplicate.
                # A missing lineage edge is a smaller loss than that.
                pass
            return f"Written to {file_path}"

        if operation == "read":
            # Resolve through latest_output_path: the write above is renamed to
            # a _vN suffix by insert_agent_output_sync, so reading file_path
            # directly never finds anything the tool itself wrote.
            stored = latest_output_path(file_path)
            if stored is None:
                return f"Error: no state found for key '{key}'"
            try:
                record_run_input_sync(
                    self.slug, self.run_id, output_id_for_path_sync(self.slug, str(stored))
                )
            except Exception:
                # A read must never fail because its bookkeeping did - the agent needs
                # the content, and a missing edge degrades the graph rather than the run.
                pass
            return stored.read_text()

        return f"Error: unknown operation '{operation}' — use 'read' or 'write'"
