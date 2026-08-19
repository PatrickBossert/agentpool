# scripts/restore_state_value_chain.py
"""Restore the `state` and `value_chain` output types after an over-broad prune.

`scripts/prune_fragmented_outputs.py` deleted 59 agent_outputs rows across 33 output
types from sp-gs-am. Two of those types were misclassified as legacy fragments and are
in fact live:

- `state` is written on every registry derivation by DeriveRegistryTool
  (agents/tools/derive_registry.py).
- `value_chain` is written by MermaidRenderTool (agents/tools/mermaid_render.py) and
  read by the API (api/routers/projects.py) and eight agent-chat personas
  (api/services/agent_chat_service.py).

With `state` at zero rows, insert_agent_output_sync (agents/tools/_db.py) would compute
the next version as 1 from an empty MAX(version) and rename the current
value_chain_registry.json onto value_chain_registry_v1.json - a POSIX rename that
silently overwrites the preserved v1 file already sitting there. Restoring `state` first
returns its version counter to 15 and disarms that.

Source of truth is the pre-prune backup, data/<slug>.pre-prune-2026-08-05.db. This
script:

1. Backs up the current (post-prune) database with SQLite's online backup API, not a
   file copy, so a mid-write post-prune db can't be copied inconsistently.
2. Re-inserts the 27 agent_outputs rows (state + value_chain) and then the 5
   human_reviews rows that reference them, both with their ORIGINAL ids - a handful of
   human_reviews rows point at agent_outputs.id directly, and the ids must match for
   that reference to still resolve. Rows first, then files: if this raises, nothing has
   moved and the run is repeatable.
3. Moves the 10 archived files these rows point at back into outputs/.

Nothing else is touched. The 29 interview_scripts_* fragment types and
value_chain_model_raw stay deleted.
"""
from __future__ import annotations

import asyncio
import shutil
import sqlite3
import sys
from pathlib import Path

# Running this by path puts `scripts/` on `sys.path`, not the repository root, so `api` is not
# importable. See the note in `backfill_project_registry.py`.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from api.config import get_settings  # noqa: E402 - must follow the bootstrap above
from api.database import get_connection, get_db_path  # noqa: E402

RESTORE_TYPES = ("state", "value_chain")

# The 10 files whose agent_outputs rows are being restored and which still exist under
# the archive - the other paths referenced by those rows are unversioned base names
# (value_chain.md, value_chain_summary.json, value_chain_tree.json,
# value_chain_registry.json) that insert_agent_output_sync had already renamed away
# from before the prune ever ran, so there is nothing to move for them.
FILES_TO_RESTORE = (
    "discovery_mapping_status.json",
    "value_chain_summary_v9.json",
    "value_chain_summary_v11.json",
    "value_chain_summary_v12.json",
    "value_chain_tree_v13.json",
    "value_chain_v8.md",
    "value_chain_v9.md",
    "value_chain_v10.md",
    "value_chain_v11.md",
    "value_chain_v12.md",
)


def backup_current_db(slug: str, backup_name: str) -> Path:
    """Snapshot the live (post-prune) db via SQLite's backup API before touching it."""
    src_path = get_db_path(slug)
    dest_path = Path(get_settings().database_dir) / backup_name
    src = sqlite3.connect(src_path)
    dest = sqlite3.connect(dest_path)
    try:
        src.backup(dest)
    finally:
        dest.close()
        src.close()
    return dest_path


async def restore_rows(slug: str, pre_prune_path: Path) -> tuple[int, int]:
    pre = sqlite3.connect(f"file:{pre_prune_path}?mode=ro", uri=True)
    pre.row_factory = sqlite3.Row
    try:
        output_rows = pre.execute(
            """
            SELECT id, project_id, agent_name, output_type, file_path, version,
                   review_status, revision_notes, created_at, is_current
            FROM agent_outputs
            WHERE output_type IN (?, ?)
            ORDER BY id
            """,
            RESTORE_TYPES,
        ).fetchall()
        output_ids = [r["id"] for r in output_rows]
        placeholders = ",".join("?" * len(output_ids))
        review_rows = pre.execute(
            f"""
            SELECT id, output_id, crew_run_id, reviewer, decision, prompt, notes, reviewed_at
            FROM human_reviews
            WHERE output_id IN ({placeholders})
            ORDER BY id
            """,
            output_ids,
        ).fetchall()
    finally:
        pre.close()

    async with get_connection(slug) as conn:
        # agent_outputs first - human_reviews.output_id references it and
        # get_connection enables foreign_keys, so the parent rows must land first.
        await conn.executemany(
            """
            INSERT INTO agent_outputs
                (id, project_id, agent_name, output_type, file_path, version,
                 review_status, revision_notes, created_at, is_current)
            VALUES (?,?,?,?,?,?,?,?,?,?)
            """,
            [
                (
                    r["id"], r["project_id"], r["agent_name"], r["output_type"],
                    r["file_path"], r["version"], r["review_status"],
                    r["revision_notes"], r["created_at"], r["is_current"],
                )
                for r in output_rows
            ],
        )
        await conn.commit()

        await conn.executemany(
            """
            INSERT INTO human_reviews
                (id, output_id, crew_run_id, reviewer, decision, prompt, notes, reviewed_at)
            VALUES (?,?,?,?,?,?,?,?)
            """,
            [
                (
                    r["id"], r["output_id"], r["crew_run_id"], r["reviewer"],
                    r["decision"], r["prompt"], r["notes"], r["reviewed_at"],
                )
                for r in review_rows
            ],
        )
        await conn.commit()

    return len(output_rows), len(review_rows)


def restore_files(slug: str, archive_name: str) -> tuple[list[str], list[str]]:
    archive = Path(get_settings().projects_dir) / slug / archive_name
    outputs = Path(get_settings().projects_dir) / slug / "outputs"
    moved: list[str] = []
    missing: list[str] = []
    for name in FILES_TO_RESTORE:
        source = archive / name
        dest = outputs / name
        if not source.exists():
            missing.append(name)
            continue
        shutil.move(str(source), str(dest))
        moved.append(name)
    return moved, missing


async def main(slug: str, pre_prune_name: str, archive_name: str, backup_name: str) -> None:
    backup_path = backup_current_db(slug, backup_name)
    print(f"post-prune backup written: {backup_path}")

    pre_prune_path = Path(get_settings().database_dir) / pre_prune_name
    n_outputs, n_reviews = await restore_rows(slug, pre_prune_path)
    print(f"restored agent_outputs rows: {n_outputs}")
    print(f"restored human_reviews rows: {n_reviews}")

    moved, missing = restore_files(slug, archive_name)
    print(f"moved files: {len(moved)} of {len(FILES_TO_RESTORE)}")
    for name in moved:
        print(f"  {name}")
    if missing:
        print(f"MISSING from archive (not moved): {len(missing)}")
        for name in missing:
            print(f"  {name}")


if __name__ == "__main__":
    if len(sys.argv) != 5:
        raise SystemExit(
            "usage: restore_state_value_chain.py <slug> <pre-prune-db-name>"
            " <archive-dir-name> <post-prune-backup-db-name>"
        )
    asyncio.run(main(sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4]))
