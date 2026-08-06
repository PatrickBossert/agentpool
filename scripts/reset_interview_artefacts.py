# scripts/reset_interview_artefacts.py
"""Clear every interview artefact so Maya rebuilds from scratch.

Dry run by default. --apply is required to act, for the same reason
prune_fragmented_outputs.py requires it: the previous bulk operation on outputs demoted two
live artefacts because a filename family was split across output types, and nobody noticed
until a reader returned the wrong version.

Interview SESSIONS and ANSWERS are deliberately untouched. A script is reproducible - Maya
writes it again in an hour. A transcript is a thing a person said once, and no rerun brings
it back.
"""
from __future__ import annotations
import argparse
import contextlib
import json
import shutil
import sqlite3
from datetime import date
from pathlib import Path

from api.config import get_settings

INTERVIEW_OUTPUT_TYPES = (
    "interview_scripts",
    "interview_script_registry",
    "l0_interview_summaries",
    "l1_interview_summaries",
    "l2_interview_summaries",
    "customer_interview_summaries",
    "audit_interview_summaries",
    "frontline_interview_summaries",
    "corp_services_interview_summaries",
)

# Rows that point at an agent_output. The lineage work added foreign keys, so a delete that
# leaves any of these dangling is refused rather than cascaded.
_DEPENDANTS = (
    ("output_citations", "output_id"),
    ("output_lineage", "output_id"),
    ("output_changes", "output_id"),
    ("approval_commit_outputs", "output_id"),
    ("human_reviews", "output_id"),
    ("run_inputs", "output_id"),
)


def reset_interview_artefacts(slug: str, *, apply: bool = False) -> dict:
    settings = get_settings()
    db_path = Path(settings.database_dir) / f"{slug}.db"
    outputs = Path(settings.projects_dir) / slug / "outputs"

    placeholders = ",".join("?" * len(INTERVIEW_OUTPUT_TYPES))
    with contextlib.closing(sqlite3.connect(db_path)) as conn:
        rows = conn.execute(
            f"SELECT id, output_type, version, file_path FROM agent_outputs"
            f" WHERE output_type IN ({placeholders})",
            INTERVIEW_OUTPUT_TYPES,
        ).fetchall()

    # Every file whose stem belongs to one of these types, not only the paths the database
    # names - a version written and then renamed can leave a file no row points at, which
    # is exactly how six different L0 interviews came to be merged into one view.
    files: list[Path] = []
    if outputs.is_dir():
        for output_type in INTERVIEW_OUTPUT_TYPES:
            files.extend(sorted(outputs.glob(f"{output_type}_v*.json")))
            exact = outputs / f"{output_type}.json"
            if exact.exists():
                files.append(exact)

    report = {
        "rows": len(rows),
        "files": len(files),
        "backup_db": None,
        "archive": None,
        "types": sorted({r[1] for r in rows}),
    }
    if not apply:
        print(json.dumps(report, indent=2))
        print("\nDRY RUN - nothing changed. Pass --apply to act.")
        return report

    backup = db_path.with_suffix(f".pre-interview-reset-{date.today().isoformat()}.db")
    shutil.copy2(db_path, backup)
    report["backup_db"] = str(backup)

    archive = outputs.parent / f"_interview_reset_{date.today().isoformat()}"
    archive.mkdir(parents=True, exist_ok=True)
    report["archive"] = str(archive)
    for f in files:
        shutil.move(str(f), str(archive / f.name))

    with contextlib.closing(sqlite3.connect(db_path)) as conn:
        conn.execute("PRAGMA foreign_keys = ON")
        ids = [r[0] for r in rows]
        if ids:
            marks = ",".join("?" * len(ids))
            for table, column in _DEPENDANTS:      # dependants first, then the rows
                with contextlib.suppress(sqlite3.OperationalError):
                    conn.execute(f"DELETE FROM {table} WHERE {column} IN ({marks})", ids)
            conn.execute(f"DELETE FROM agent_outputs WHERE id IN ({marks})", ids)
        conn.commit()

    print(json.dumps(report, indent=2))
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("slug")
    parser.add_argument("--apply", action="store_true", help="actually clear them")
    args = parser.parse_args()
    reset_interview_artefacts(args.slug, apply=args.apply)
