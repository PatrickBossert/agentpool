# scripts/prune_fragmented_outputs.py
"""Remove the fragmented and superseded output types from a project.

The list is literal rather than pattern-matched. A rule like "everything starting
interview_scripts_" would silently widen as new keys appeared, and this deletes data.

Rows go first, then files. If the delete raises, nothing has moved and the run can simply
be repeated. Files are moved into a timestamped archive rather than unlinked - the point
is a clean baseline, not destroyed evidence.
"""
from __future__ import annotations

import asyncio
import shutil
import sys
from pathlib import Path

from api.config import get_settings
from api.database import fetch_project, get_connection, prune_output_types

PRUNE_TYPES = [
    "interview_scripts_a",
    "interview_scripts_batch1",
    "interview_scripts_batch2",
    "interview_scripts_batch3",
    "interview_scripts_batch4",
    "interview_scripts_batch5",
    "interview_scripts_batch6",
    "interview_scripts_batch7",
    "interview_scripts_batch8",
    "interview_scripts_batch9",
    "interview_scripts_c",
    "interview_scripts_caf",
    "interview_scripts_customer_audit_frontline_corpservices",
    "interview_scripts_f",
    "interview_scripts_frontline",
    "interview_scripts_l0",
    "interview_scripts_l1",
    "interview_scripts_l1_fleet",
    "interview_scripts_l1_property",
    "interview_scripts_l2",
    "interview_scripts_l2_1",
    "interview_scripts_l2_2",
    "interview_scripts_l3",
    "interview_scripts_l3_1",
    "interview_scripts_part2",
    "interview_scripts_part3",
    "interview_scripts_part4",
    "interview_scripts_part5",
    "interview_scripts_part6",
    "interview_scripts_s",
    "state",
    "value_chain",
    "value_chain_model_raw",
]


async def main(slug: str, archive_name: str) -> None:
    async with get_connection(slug) as conn:
        project = await fetch_project(conn, slug=slug)
        if not project:
            raise SystemExit(f"no such project: {slug}")
        result = await prune_output_types(
            conn, project_id=project["id"], output_types=PRUNE_TYPES
        )

    print(f"deleted rows: {result['deleted']}")

    root = Path(get_settings().projects_dir).parent
    archive = Path(get_settings().projects_dir) / slug / archive_name
    archive.mkdir(parents=True, exist_ok=True)

    moved = 0
    for rel in result["file_paths"]:
        source = root / rel
        if source.exists():
            shutil.move(str(source), str(archive / source.name))
            moved += 1
    print(f"archived files: {moved} of {len(result['file_paths'])} into {archive}")
    print("(a path with no file is normal - several rows shared one filename)")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        raise SystemExit("usage: prune_fragmented_outputs.py <slug> <archive-dir-name>")
    asyncio.run(main(sys.argv[1], sys.argv[2]))
