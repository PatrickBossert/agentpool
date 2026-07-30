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


async def save_model(slug: str, model: dict, *, saved_by: str, summary: str) -> int:
    """Write the next version. Raises ValueError with the problems if the model is invalid.

    Validation runs before anything is written, so a rejected save leaves no file and no
    row - a half-saved model would be worse than a refused one.
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
            request=summary,
            summary=f"saved value chain model version {version}",
        )

    return output_id


async def migrate_project(slug: str, *, saved_by: str) -> dict:
    """Build the model from this project's registry and its latest Mermaid output.

    Refuses when a model already exists: re-running would discard whatever anybody has
    edited since, and migration is a one-off recovery rather than a repeatable import.
    """
    if await load_model(slug) is not None:
        raise FileExistsError("a value chain model already exists for this project")

    outputs = _outputs_dir(slug)
    registry_path = outputs / "value_chain_registry.json"
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
    if not registry_path.exists() or not mermaid_paths:
        raise FileNotFoundError(
            "need value_chain_registry.json and a value_chain_v*.md to migrate"
        )

    from api.services.value_chain_migration import migrate

    model = migrate(
        json.loads(registry_path.read_text()),
        mermaid_paths[-1].read_text(),
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
