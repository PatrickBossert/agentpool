# scripts/backfill_value_chain_ledger.py
"""Register every value chain node already assigned into `value_chain_ledger`.

The ledger is maintained by the write path from now on - both doors onto
`value_chain_registry` call `register_nodes_sync` - but every id assigned before that
change has no row. On the live deployment that is all 89 of them, and an id outside the
ledger is an id a later write could re-anchor unrefused. This is the one-off that closes
the gap behind them.

**A script, not a migration.** `get_connection(slug)` runs the migration block for any slug
it is handed, including one materialised by a probe, so backfilling from there would create
and migrate databases for slugs that are not projects at all. Every database this reads is
opened read-only with plain `sqlite3`; the only write is `register_nodes_sync`, which opens
the project database directly and runs no migrations either.

**A file is a project only if it says so**, and only if the slug it claims matches its own
filename. That is what keeps the dated backup copies the other scripts in here leave behind
- `sp-gs-am.pre-interview-reset-2026-08-04.db` - from being backfilled as projects in their
own right, exactly as `backfill_project_registry.py` does it.

**It registers only ids the ledger does not already hold.** `register_nodes_sync` is
idempotent on the anchor by construction, but it also stamps `last_version` and
`last_author` on every id it is handed - which is a staleness signal Tasks 3 and 4 read, and
a backfill has no business moving it on a row the live write path has already maintained.
Filtering here rather than there keeps that rule in the script that needs it and leaves the
write path's own behaviour alone. It is what makes a second run a no-op rather than merely
harmless.

**A project whose database has no `value_chain_ledger` table is skipped, not created.** The
table arrives through the migration block; a missing one means the API has not been
restarted on this branch yet, and materialising it here would put schema creation in a
script, which is the thing this file is careful not to be.

Dry run by default, as `backfill_project_registry.py` and `prune_fragmented_outputs.py` are.
Pass `--apply` to write.

Do NOT point this at the repository's `data/` directory casually; that is live data. The
operator's command is in the branch report.
"""
from __future__ import annotations

import argparse
import contextlib
import json
import sqlite3
import sys
from pathlib import Path

# `python scripts/backfill_value_chain_ledger.py` puts `scripts/` on `sys.path`, not the
# repository root, so `api` and `agents` are not importable and the script dies on its first
# import. Every script in here is a one-off an operator runs by path, from the root, on a
# live deployment - and one that fails on invocation is one an operator works around rather
# than runs.
_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))

from api.config import get_settings  # noqa: E402 - must follow the bootstrap above

BACKFILL_AUTHOR = "backfill"


class BackfillRefused(Exception):
    """The run cannot proceed and nothing has been written."""


def _read_only(db_path: Path) -> sqlite3.Connection:
    return sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)


def _project_slug_in(conn: sqlite3.Connection) -> tuple[str | None, str]:
    """The slug this database claims to be, with the reason when it claims none.

    The three "no" cases are reported apart because they are three different things an
    operator might act on: unreadable is worth a look, no `projects` table is a
    probe-materialised shell or another system database's backup, and an empty `projects`
    table is a database that never became a project (`vc-sort-check` on the live
    deployment).
    """
    try:
        row = conn.execute("SELECT slug FROM projects ORDER BY id LIMIT 1").fetchone()
    except sqlite3.Error:
        return None, "no projects table - not a project database"
    if row is None:
        return None, "projects table is empty - never became a project"
    return row[0], ""


def _has_ledger_table(conn: sqlite3.Connection) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='value_chain_ledger'"
    ).fetchone()
    return row is not None


def _current_registry_row(conn: sqlite3.Connection) -> tuple[Path | None, int, str]:
    """The registry file the ledger marks current, its version, and why not when there is none.

    The ledger, never the disk. `latest_output_path`'s glob returns the highest number on
    disk, which is a different answer after a revert and was wrong four separate times on
    this project - and a backfill reading the wrong version would register ids the project
    has deliberately reverted away from.
    """
    try:
        row = conn.execute(
            "SELECT version, file_path FROM agent_outputs"
            " WHERE output_type='value_chain_registry' AND is_current=1"
            " ORDER BY version DESC LIMIT 1"
        ).fetchone()
    except sqlite3.Error as exc:
        return None, 0, f"agent_outputs is not readable ({exc})"
    if row is None:
        return None, 0, "no current value_chain_registry - nothing has been derived yet"
    version, file_path = row[0], Path(row[1])
    # Stored paths are relative to the repository root on this deployment.
    if not file_path.is_absolute():
        file_path = _ROOT / file_path
    if not file_path.exists():
        return None, version, f"current registry v{version} is not on disk at {file_path}"
    return file_path, version, ""


def _activities_in(path: Path) -> tuple[list, str]:
    try:
        loaded = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        return [], f"{path.name} could not be read ({exc})"
    activities = loaded.get("activities") if isinstance(loaded, dict) else None
    if not isinstance(activities, list):
        return [], f"{path.name} holds no activities list"
    return activities, ""


def backfill_value_chain_ledger(*, apply: bool = False) -> dict:
    settings = get_settings()
    database_dir = Path(settings.database_dir)
    if not database_dir.is_dir():
        raise BackfillRefused(f"No database directory at {database_dir}.")

    report: dict = {
        "database_dir": str(database_dir),
        "projects": [],
        "skipped": [],
        "applied": apply,
    }

    for db_path in sorted(database_dir.glob("*.db")):
        if db_path.name == "system.db":
            continue
        stem = db_path.stem
        try:
            conn = _read_only(db_path)
        except sqlite3.Error as exc:
            report["skipped"].append(
                {"file": db_path.name, "reason": f"cannot be opened read-only ({exc})"}
            )
            continue
        with contextlib.closing(conn):
            claimed, why_not = _project_slug_in(conn)
            if claimed is None:
                report["skipped"].append({"file": db_path.name, "reason": why_not})
                continue
            if claimed != stem:
                report["skipped"].append({
                    "file": db_path.name,
                    "reason": f"projects row says '{claimed}', filename says '{stem}'"
                              " - a copy or backup, not the live database for that slug",
                })
                continue
            if not _has_ledger_table(conn):
                report["skipped"].append({
                    "file": db_path.name,
                    "reason": "no value_chain_ledger table - open this project through the"
                              " API once so the migration block creates it, then run again",
                })
                continue
            registry_path, version, why_not = _current_registry_row(conn)
            if registry_path is None:
                report["skipped"].append({"file": db_path.name, "reason": why_not})
                continue
            activities, why_not = _activities_in(registry_path)
            if why_not:
                report["skipped"].append({"file": db_path.name, "reason": why_not})
                continue
            held = {
                r[0] for r in conn.execute("SELECT node_id FROM value_chain_ledger")
            }

        missing = [
            a for a in activities
            if isinstance(a, dict)
            and isinstance(a.get("id"), str)
            and a["id"]
            and a["id"] not in held
        ]
        entry = {
            "slug": stem,
            "registry": registry_path.name,
            "registry_version": version,
            "activities_in_registry": len(activities),
            "already_registered": len(held),
            "to_register": [a["id"] for a in missing],
            "registered": 0,
        }
        if apply and missing:
            from agents.tools._db import register_nodes_sync

            entry["registered"] = register_nodes_sync(
                stem, missing, version, BACKFILL_AUTHOR
            )
        report["projects"].append(entry)

    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="actually write the rows")
    args = parser.parse_args()
    try:
        result = backfill_value_chain_ledger(apply=args.apply)
    except BackfillRefused as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        raise SystemExit(2)
    print(json.dumps(result, indent=2))
    if not args.apply:
        print("\nDRY RUN - nothing changed. Pass --apply to register them.")
