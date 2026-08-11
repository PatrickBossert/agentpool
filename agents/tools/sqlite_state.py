# agents/tools/sqlite_state.py
import json
from pathlib import Path
from typing import Callable
from pydantic import BaseModel, Field
from crewai.tools import BaseTool
from api.config import get_settings
from agents.tools._db import (
    insert_agent_output_sync,
    current_output_path,
    link_output_sync,
    output_id_for_path_sync,
    record_blocked_write_sync,
    record_run_input_sync,
    record_validation_warnings_sync,
    register_scripts_sync,
    _output_version_sync,
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
    path = current_output_path(slug, "value_chain_registry")
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
    """The script ledger in force, or an empty one when there is none yet.

    Reads the interview_script_ledger table. It used to read the
    interview_script_registry artefact, which an agent wrote as the last step of a long
    run - so the guard was checking a record that could be up to a whole run out of date.
    """
    from agents.tools._db import current_script_ledger_sync
    try:
        return current_script_ledger_sync(slug)
    except Exception:
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
    path = current_output_path(slug, "value_levers")
    if path is None:
        return []
    try:
        loaded = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return []
    return loaded if isinstance(loaded, list) else []


def _validate_interview_scripts(parsed: dict, slug: str) -> list[str]:
    from api.services.interview_script_model import (
        validate_anchor_levels,
        validate_elicitation_order,
        validate_levers_unnamed_in_unaided_sections,
        validate_scripts,
        validate_scripts_against_registry,
        validate_scripts_against_script_registry,
    )

    problems = validate_scripts(parsed, disciplines=_project_disciplines(slug))
    # The value chain registry, not the script one: this checks that each script's anchor
    # names a node that exists.
    problems.extend(validate_scripts_against_registry(parsed, _current_registry(slug)))
    # And that it is the right kind of node. Existence alone let run 26 file an L0 board
    # interview against an L1 entity, because the L0 it wanted was not in the registry.
    problems.extend(validate_anchor_levels(parsed, _current_registry(slug)))
    # The ordering rule is checkable, so it is checked rather than left to an instruction
    # Maya may or may not follow.
    problems.extend(validate_elicitation_order(parsed))
    problems.extend(validate_levers_unnamed_in_unaided_sections(parsed, _current_levers(slug)))
    # The script registry is the ledger for script ids, and succession already holds writes to
    # it to that contract. This is the same rule on the door the scripts actually come through:
    # the merge keys on script_id, so an id that moves replaces rather than adds.
    problems.extend(
        validate_scripts_against_script_registry(parsed, _current_script_registry(slug))
    )
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


def _warn_themes(parsed: object, slug: str) -> list[dict]:
    from api.services.anchor_validation import validate_theme_anchors

    if not isinstance(parsed, list):
        return []   # shape is the schema's problem, not the anchor validator's
    # An empty registry accepts anything: Casey may legitimately run on a project whose
    # value chain is not built yet, and there is nothing to judge an anchor against.
    return validate_theme_anchors(parsed, _current_registry(slug))


def _warn_value_chain_tree(parsed: object, slug: str) -> list[dict]:
    from api.services.tree_validation import validate_tree_structure

    previous = _current_registry(slug)
    # None, not {}, on a first run: the validator skips the role-node and id-succession
    # checks when it has no baseline, and says so rather than passing silently.
    return validate_tree_structure(parsed, previous or None)


def _warn_interview_coverage(parsed: object, slug: str) -> list[dict]:
    from api.services.coverage_validation import validate_node_coverage

    if not isinstance(parsed, dict):
        return []
    return validate_node_coverage(parsed, _current_registry(slug))


# Warners differ from validators in two ways that matter, and both are why they are a
# separate map rather than another _VALIDATORS entry:
#
#   1. A validator REFUSES - the write never lands. A warner records and lets the write
#      through, because blocking the run would lose the work the run just did. That is not
#      hypothetical: DeriveRegistryTool refused a label change and the registry stuck at v5
#      for two days while the tree moved to v12, and the run still reported completed.
#   2. _VALIDATORS rejects any payload that is not a dict. value_chain_tree is a JSON
#      *list*, so registering it there would refuse every tree write ever made.
#
# They run after the write succeeds, so a recorded warning always refers to an output that
# actually exists.
_WARNERS: dict[str, Callable[[object, str], list[dict]]] = {
    "value_chain_tree": _warn_value_chain_tree,
    "themes": _warn_themes,
    "interview_scripts": _warn_interview_coverage,
}

# The `source` recorded against each warning, so a reviewer can tell a tree finding from a
# theme one without parsing the code.
_WARNER_SOURCE: dict[str, str] = {
    "value_chain_tree": "value_chain_tree",
    "themes": "theme_anchor",
    "interview_scripts": "interview_coverage",
}


# Keys whose write merges into the current version instead of replacing it.
#
# Maya's script set is roughly 400KB of JSON and max_tokens is 16384, so it cannot be
# written in one call. Before this, every batch clobbered the last: run 26 produced seven
# versions in fifty minutes and the one marked current held one script of eighteen. Every
# one of those writes succeeded - nothing was being refused, so nothing was going to
# self-correct. The version history recorded seven revisions where there had only been
# chunking.
#
# Merging is additive on purpose. A script absent from a batch means "not in this batch",
# never "delete this" - an agent that omits a key under context pressure would otherwise
# silently destroy work it had already banked. Retirement is expressed in
# interview_script_registry's active: false, where it is explicit and reversible.
def _preserve_registered_labels(parsed: dict, slug: str) -> dict:
    """A registered id keeps the label the ledger already holds.

    DeriveRegistryTool does this too, and it has to be done here as well because
    value_chain_registry has two doors: the derive tool, and SQLiteStateTool, where the key
    is Alex's own. validate_registry_succession used to refuse any label change and so
    guarded both; when that refusal was relaxed - because it contradicted Alex's brief and
    blocked derivation over an en dash - the derive tool gained preservation and this door
    gained nothing. Run 29 wrote 'Capital and Revenue Financial Control (350M)' over
    '(£350M)' straight into the ledger.

    ownership.py puts it exactly: ownership stops another agent reaching for a key,
    succession stops its owner corrupting it. This is the succession half, restored.

    Only the label is carried through. active, level and the entries themselves are the
    agent's to set - retiring an id is a legitimate edit through this door.
    """
    current = _current_registry(slug)
    registered = {
        str(a.get("id")): a.get("label")
        for a in (current.get("activities") or [])
        if isinstance(a, dict) and a.get("label")
    }
    if not registered:
        return parsed
    out = dict(parsed)
    out["activities"] = [
        {**a, "label": registered.get(str(a.get("id"))) or a.get("label", "")}
        if isinstance(a, dict) else a
        for a in (parsed.get("activities") or [])
    ]
    return out


_MERGE_ON_WRITE: frozenset[str] = frozenset({"interview_scripts"})


def _merge_with_current(key: str, parsed: dict, slug: str) -> dict:
    """The current artefact with this batch applied over it, newest wins per id."""
    current_path = current_output_path(slug, key)
    if current_path is None:
        return parsed
    try:
        current = json.loads(current_path.read_text())
    except (OSError, json.JSONDecodeError):
        return parsed          # an unreadable current version is no base, not a blocker
    if not isinstance(current, dict) or not isinstance(parsed, dict):
        return parsed
    merged = dict(current)
    merged.update(parsed)
    return merged


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

            # Merge before validating, so the validator judges the artefact that will
            # actually be stored rather than the fragment that arrived. A batch that would
            # corrupt the accumulated set is refused whole and the previous version stays
            # current - the refusal costs the batch, never the work already banked.
            if key in _MERGE_ON_WRITE and isinstance(parsed, dict):
                parsed = _merge_with_current(key, parsed, self.slug)
                if key == "interview_scripts":
                    # Scripts written before the level/perspective split filed a role
                    # node's letter in `level` with no `perspective` at all. Normalising
                    # here, before validation, means a batch that never touches those old
                    # entries still merges cleanly - without this, every future write would
                    # be refused outright the moment the old entries it is merged with fail
                    # the new level/perspective schema.
                    from api.services.interview_script_model import normalise_scripts
                    parsed = normalise_scripts(parsed)
                value = json.dumps(parsed, indent=2)

            # The ledger's labels are not the writer's to restate. Applied before the
            # validator, so succession judges what will actually be stored.
            if key == "value_chain_registry" and isinstance(parsed, dict):
                parsed = _preserve_registered_labels(parsed, self.slug)
                value = json.dumps(parsed, indent=2)

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

            if key == "interview_scripts" and isinstance(parsed, dict):
                # Registration is a side effect of the write, exactly as
                # insert_agent_output_sync maintains is_current, and for the same reason:
                # a correctness record whose maintenance is an agent's last instruction is
                # a record that goes missing when a run stops early. Run 32 wrote 41
                # scripts, hit the iteration ceiling before its ledger write, and reported
                # completed.
                try:
                    version = _output_version_sync(self.slug, new_output_id)
                    register_scripts_sync(self.slug, parsed, version, agent_name)
                except Exception:
                    # Never fail a durable write over the ledger. The next write re-derives
                    # it, and the validator refuses anything that would corrupt it meanwhile.
                    pass
            elif key == "interview_script_registry" and isinstance(parsed, dict):
                # The other door onto the same ledger - Maya's instructions still have her
                # write this as a cumulative summary after a batch of scripts, and until
                # that instruction is retired this write still happens and still needs to
                # leave the table agreeing with it. Without this hook the table only ever
                # learns ids from agents.tools.sqlite_state's interview_scripts branch above,
                # so a plain interview_script_registry write - including one that drops a
                # registered id - would pass validation against a table it never populated,
                # silently reopening the exact hole append-only registration exists to close.
                # Same append-only call, adapted for this key's {"scripts": [{"id",
                # "node_id", "node_label"}, ...]} shape rather than interview_scripts' dict
                # of full script bodies.
                try:
                    version = _output_version_sync(self.slug, new_output_id)
                    by_id = {
                        entry.get("id"): {
                            "node_id": entry.get("node_id"),
                            "node_label": entry.get("node_label", ""),
                        }
                        for entry in parsed.get("scripts", [])
                        if isinstance(entry, dict) and entry.get("id") and entry.get("node_id")
                    }
                    register_scripts_sync(self.slug, by_id, version, agent_name)
                except Exception:
                    pass

            warner = _WARNERS.get(key)
            if warner is not None:
                try:
                    found = warner(parsed, self.slug)
                    # complete=True: a warner re-derives every finding from the artefact it
                    # just judged, so anything absent is fixed and is cleared. Called even
                    # when nothing was found, because that is precisely when clearing
                    # matters - run 29 raised missing_l0 on tree v17 and fixed it on v18,
                    # and without this the warning outlived the problem.
                    record_validation_warnings_sync(
                        self.slug, self.run_id, _WARNER_SOURCE[key], found, complete=True
                    )
                except Exception:
                    # A warning is never worth failing a completed write over. The write and
                    # its row are durable by this point; telling the agent it failed would
                    # make it write again and version a duplicate.
                    pass

            try:
                link_output_sync(self.slug, self.run_id, self.agent_name, new_output_id)
            except Exception:
                # The write already landed - both the file and its agent_outputs row are
                # durable by this point. Letting this raise would tell the agent the write
                # failed when it didn't, and it would write again, versioning a duplicate.
                # A missing lineage edge is a smaller loss than that.
                pass
            return f"Written to {file_path}"

        if operation == "read":
            # Resolve through the ledger: the write above is renamed to a _vN suffix by
            # insert_agent_output_sync, so reading file_path directly never finds anything
            # the tool itself wrote - and the highest number on disk is not necessarily the
            # current version, which is how a 15 July file was read for three weeks.
            stored = current_output_path(self.slug, key, run_id=self.run_id)
            if stored is None:
                return f"Error: no state found for key '{key}'"
            try:
                record_run_input_sync(
                    self.slug, self.run_id, self.agent_name,
                    output_id_for_path_sync(self.slug, str(stored)),
                )
            except Exception:
                # A read must never fail because its bookkeeping did - the agent needs
                # the content, and a missing edge degrades the graph rather than the run.
                pass
            return stored.read_text()

        return f"Error: unknown operation '{operation}' — use 'read' or 'write'"
