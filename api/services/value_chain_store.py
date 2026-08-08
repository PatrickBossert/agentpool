# api/services/value_chain_store.py
"""Reading and saving the value chain model.

An edit produces a new working version rather than an in-place write, and records who asked
for it. That is the discipline the approval loop already follows - the versioned artefact is
the source of truth, and a committed version is never modified.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from api.config import get_settings
from api.database import (
    fetch_agent_outputs,
    fetch_project,
    get_connection,
    insert_agent_output,
    insert_output_change,
    set_current_output,
)
from api.services.value_chain_model import validate_model

OUTPUT_TYPE = "value_chain_model"
AGENT_NAME = "value_chain_mapper"


def _outputs_dir(slug: str) -> Path:
    settings = get_settings()
    path = Path(settings.projects_dir) / slug / "outputs"
    path.mkdir(parents=True, exist_ok=True)
    return path


async def load_model(slug: str) -> dict | None:
    """The current model, or None if none has been saved."""
    async with get_connection(slug) as conn:
        project = await fetch_project(conn, slug=slug)
        if not project:
            return None
        outputs = [
            o for o in await fetch_agent_outputs(conn, project_id=project["id"])
            if o["output_type"] == OUTPUT_TYPE and o.get("is_current")
        ]
    if not outputs:
        return None
    path = Path(outputs[0]["file_path"])
    if not path.exists():
        return None
    return json.loads(path.read_text())


async def save_model(
    slug: str,
    model: dict,
    *,
    saved_by: str,
    summary: str = "",
    rationale: str = "",
    intent: str = "change_request",
) -> int:
    """Write the next version. Raises ValueError with the problems if the model is invalid.

    Validation runs before anything is written, so a rejected save leaves no file and no
    row - a half-saved model would be worse than a refused one.

    The save itself never waits on a rationale - demanding one before someone can save is
    how people stop editing. Without one the edit still lands, just as `unclassified`, so a
    later triage pass can find it rather than the next agent run silently reverting it.
    """
    problems = validate_model(model)
    if problems:
        raise ValueError("; ".join(problems))

    async with get_connection(slug) as conn:
        project = await fetch_project(conn, slug=slug)
        if not project:
            raise ValueError(f"project {slug!r} not found")

        existing = [
            o for o in await fetch_agent_outputs(conn, project_id=project["id"])
            if o["output_type"] == OUTPUT_TYPE
        ]
        version = max((o["version"] for o in existing), default=0) + 1

        path = _outputs_dir(slug) / f"value_chain_model_v{version}.json"
        path.write_text(json.dumps(model, indent=2))

        output_id = await insert_agent_output(
            conn,
            project_id=project["id"],
            agent_name=AGENT_NAME,
            output_type=OUTPUT_TYPE,
            file_path=str(path),
            version=version,
        )
        # insert_agent_output does not set is_current, so supersede the rest explicitly.
        await set_current_output(
            conn, project_id=project["id"], output_type=OUTPUT_TYPE, output_id=output_id,
        )

        await insert_output_change(
            conn,
            output_id=output_id,
            requested_by=saved_by,
            source="edit",
            # The reviewer's words when they gave them, otherwise the mechanical summary -
            # which is a record that an edit happened, not a reason it did.
            request=rationale.strip() or summary,
            summary=f"saved value chain model version {version}",
            kind=intent if rationale.strip() else "unclassified",
        )

    return output_id


async def migrate_project(slug: str, *, saved_by: str) -> dict:
    """Build the model from this project's registry and its latest Mermaid output.

    Refuses when a model already exists: re-running would discard whatever anybody has
    edited since, and migration is a one-off recovery rather than a repeatable import.
    """
    if await load_model(slug) is not None:
        raise FileExistsError("a value chain model already exists for this project")

    from agents.tools._db import current_output_path

    outputs = _outputs_dir(slug)
    registry_path = current_output_path(slug, "value_chain_registry")
    # Sort numerically on the version suffix - lexical order would put v9 after v12, and
    # the real sp-gs-am project already has a v12, so this matters immediately. A filename
    # that matches the glob but carries no numeric suffix (e.g. a hand-renamed backup)
    # cannot be placed in that ordering, so it is excluded from the candidates rather than
    # crashing the sort or being guessed at as "latest".
    candidates = []
    for path in outputs.glob("value_chain_v*.md"):
        match = re.search(r"_v(\d+)", path.name)
        if match:
            candidates.append((int(match.group(1)), path))
    mermaid_paths = [path for _, path in sorted(candidates)]
    if registry_path is None or not mermaid_paths:
        raise FileNotFoundError(
            "need value_chain_registry.json and a value_chain_v*.md to migrate"
        )

    from api.services.value_chain_migration import migrate

    registry = json.loads(registry_path.read_text())
    model = migrate(registry, mermaid_paths[-1].read_text())

    # An empty model is perfectly valid - validate_model has nothing to object to - so it
    # used to save as v1 and report success. The page then said no value chain had been
    # mapped, the Migrate button was gone because a model existed, and every retry was
    # refused 409: a one-way trapdoor. Refusing before anything is written leaves the
    # project able to migrate once its registry is corrected. A registry with no entries at
    # all is a different case and stays allowed - there is genuinely nothing to migrate.
    entries = registry.get("activities", [])
    if entries and not model["segments"]:
        levels = sorted({repr(e.get("level", "")) for e in entries})
        raise ValueError(
            "expected at least one L1 entry to become a segment, and found none: "
            f"{len(entries)} registry entries carry levels {', '.join(levels)}, "
            f"which produced {len(model['segments'])} segments, "
            f"{len(model['activities'])} activities and "
            f"{len(model['contributions'])} contributions. "
            "Correct the registry's level values to L1, L2 and L3, then migrate again."
        )

    # A diagram with no recoverable colour attribution leaves every activity with zero
    # contributions - the same problem validate_model now catches per activity, but naming
    # it once here beats reporting it once per activity (17 identical complaints for the
    # real sp-gs-am project's activity count, and none of them says why). The cascade in
    # migrate() already tried the dominant party at every level and found nothing, so there
    # is genuinely nothing left to recover - only a crew run supplies attribution from here.
    if entries and not model["contributions"]:
        raise ValueError(
            "no party attribution could be recovered from the diagram: "
            f"{len(entries)} registry entries produced {len(model['segments'])} segments "
            f"and {len(model['activities'])} activities, but 0 contributions, so no "
            "activity could be placed in a lane. Run the crew that builds the value chain "
            "model instead of migrating this project."
        )

    await save_model(
        slug, model, saved_by=saved_by, summary="migrated from the Mermaid diagram"
    )
    return {
        "created": True,
        "counts": {
            "parties": len(model["parties"]),
            "segments": len(model["segments"]),
            "activities": len(model["activities"]),
            "contributions": len(model["contributions"]),
            "tasks": len(model["tasks"]),
            "derived": sum(
                1 for c in model["contributions"] if c["attribution"] == "derived"
            ),
        },
    }
