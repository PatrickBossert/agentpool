# scripts/backfill_value_lever_ledger.py
"""Give the levers already on record a permanent id, once, and register them.

`value_levers` has never carried an id. It is a JSON array whose only identifying field is
`lever` - a full sentence - and Morgan rewords every one of them on every run: across the
five live versions on `sp-gs-am`, v3 -> v4 reordered the same ten titles and v4 -> v5
reworded all ten. So neither the title nor the position identifies a lever, and review state
cannot be hung on either. This is the one-off that assigns `LV-001`..`LV-0nn` to the levers
that already exist, so that everything after it can key on an id instead.

**The assignment happens once, and a re-run cannot renumber.** Three things make that true
rather than hoped for:

  1. An entry that already carries a `lever_id` is never given another one. Only entries
     with no id are assigned one at all.
  2. `--apply` writes the ids back into the artefact, as a new version through the same
     `insert_agent_output_sync` every agent write uses. After that first run every entry
     carries an id, so rule 1 leaves all of them alone for ever. Without this the ids would
     exist only in the ledger, where Morgan cannot see them, and her next write would name
     none of them.
  3. The next number is taken from the highest id already in the ledger or the artefact -
     never from the count, never from a position. A lever deleted, reordered or reworded
     therefore changes nothing about what the next new lever is called.

**A script, not a migration**, for the reason `backfill_value_chain_ledger.py` gives:
`get_connection(slug)` runs the migration block for any slug it is handed, so backfilling
through it would create and migrate databases for slugs that are not projects. Every
database here is read with plain `sqlite3`, read-only, except the two writes `--apply` makes
through the ordinary helpers.

**A project whose database has no `value_lever_ledger` table is skipped, not created.** The
table arrives through the migration block; a missing one means the API has not been
restarted on this branch yet.

Dry run by default. Pass `--apply` to write.

Do NOT point this at the repository's `data/` directory casually; that is live data. The
operator's command is in the branch report.
"""
from __future__ import annotations

import argparse
import contextlib
import json
import re
import sqlite3
import sys
from pathlib import Path

# `python scripts/backfill_value_lever_ledger.py` puts `scripts/` on `sys.path`, not the
# repository root, so `api` and `agents` are not importable without this.
_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))

from api.config import get_settings  # noqa: E402 - must follow the bootstrap above

BACKFILL_AUTHOR = "backfill"
LEVER_OWNER = "value_lever_analyst"
_LEVER_ID = re.compile(r"^LV-(\d+)$")


class BackfillRefused(Exception):
    """The run cannot proceed and nothing has been written."""


def _read_only(db_path: Path) -> sqlite3.Connection:
    return sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)


def _project_slug_in(conn: sqlite3.Connection) -> tuple[str | None, str]:
    """The slug this database claims to be, with the reason when it claims none."""
    try:
        row = conn.execute("SELECT slug FROM projects ORDER BY id LIMIT 1").fetchone()
    except sqlite3.Error:
        return None, "no projects table - not a project database"
    if row is None:
        return None, "projects table is empty - never became a project"
    return row[0], ""


def _has_ledger_table(conn: sqlite3.Connection) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='value_lever_ledger'"
    ).fetchone()
    return row is not None


def _current_levers_row(conn: sqlite3.Connection) -> tuple[Path | None, int, str]:
    """The levers file the ledger marks current, its version, and why not when there is none.

    The ledger, never the disk. `latest_output_path`'s glob returns the highest number on
    disk, which is a different answer after a revert - and a backfill that assigned ids
    against a version the project has deliberately reverted away from would be assigning
    them to levers nobody is looking at.
    """
    try:
        row = conn.execute(
            "SELECT version, file_path FROM agent_outputs"
            " WHERE output_type='value_levers' AND is_current=1"
            " ORDER BY version DESC LIMIT 1"
        ).fetchone()
    except sqlite3.Error as exc:
        return None, 0, f"agent_outputs is not readable ({exc})"
    if row is None:
        return None, 0, "no current value_levers - Morgan has not run on this project"
    version, file_path = row[0], Path(row[1])
    # Stored paths are relative to the repository root on this deployment.
    if not file_path.is_absolute():
        file_path = _ROOT / file_path
    if not file_path.exists():
        return None, version, f"current levers v{version} are not on disk at {file_path}"
    return file_path, version, ""


def _levers_in(path: Path) -> tuple[list, str]:
    try:
        loaded = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        return [], f"{path.name} could not be read ({exc})"
    if not isinstance(loaded, list):
        return [], f"{path.name} is not a JSON array of levers"
    return loaded, ""


def _next_number(existing: set[str]) -> int:
    """One above the highest LV- number anywhere, so a number is never handed out twice.

    Taken from the ids themselves rather than from how many levers there are. A count
    renumbers the moment a lever is dropped, which is the whole failure this file exists to
    make impossible.
    """
    numbers = [int(m.group(1)) for m in (_LEVER_ID.match(i) for i in existing) if m]
    return max(numbers, default=0) + 1


def assign_lever_ids(levers: list, held: set[str]) -> tuple[list, list[dict]]:
    """The levers with an id on every entry, and a record of the ones newly assigned.

    Pure, so it can be driven directly: the assignment rule is the load-bearing half of
    this file and deserves to be testable without a database, an artefact or a filesystem.
    An entry that already carries an id is returned untouched - that is what makes a second
    run a no-op rather than a renumbering.
    """
    from agents.tools._db import _usable_lever_id

    assigned: list[dict] = []
    taken = set(held)
    for lever in levers:
        if isinstance(lever, dict):
            existing = _usable_lever_id(lever)
            if existing:
                taken.add(existing)
    out: list = []
    for position, lever in enumerate(levers, start=1):
        if not isinstance(lever, dict) or _usable_lever_id(lever):
            out.append(lever)
            continue
        lever_id = f"LV-{_next_number(taken):03d}"
        taken.add(lever_id)
        assigned.append({
            "position": position,
            "lever_id": lever_id,
            "title": lever.get("lever"),
        })
        # lever_id first, so the id is the first thing a reader of the file sees.
        out.append({"lever_id": lever_id, **lever})
    return out, assigned


def _rewrite_artefact(slug: str, levers: list) -> int:
    """Write the id-carrying levers as a new version, and return that version.

    Through `insert_agent_output_sync`, the same helper every agent write uses, so
    `is_current` is maintained and the previous version stays on disk. Attributed to
    `value_lever_analyst` rather than to the backfill: `agent_outputs.agent_name` is the
    key's owner everywhere else in the system, and a stranger's name on it would make
    ownership and lineage views report a write by an agent that does not exist. The ledger
    records who actually did it, in `last_author`.
    """
    from agents.tools._db import _output_version_sync, insert_agent_output_sync

    outputs = Path(get_settings().projects_dir) / slug / "outputs"
    outputs.mkdir(parents=True, exist_ok=True)
    path = outputs / "value_levers.json"
    path.write_text(json.dumps(levers, indent=2))
    new_id = insert_agent_output_sync(
        slug=slug, agent_name=LEVER_OWNER, output_type="value_levers",
        file_path=str(path),
    )
    return _output_version_sync(slug, new_id)


def backfill_value_lever_ledger(*, apply: bool = False) -> dict:
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
                    "reason": "no value_lever_ledger table - open this project through the"
                              " API once so the migration block creates it, then run again",
                })
                continue
            levers_path, version, why_not = _current_levers_row(conn)
            if levers_path is None:
                report["skipped"].append({"file": db_path.name, "reason": why_not})
                continue
            levers, why_not = _levers_in(levers_path)
            if why_not:
                report["skipped"].append({"file": db_path.name, "reason": why_not})
                continue
            held = {r[0] for r in conn.execute("SELECT lever_id FROM value_lever_ledger")}

        identified, assigned = assign_lever_ids(levers, held)
        from agents.tools._db import _usable_lever_id

        missing = [
            lever for lever in identified
            if isinstance(lever, dict)
            and _usable_lever_id(lever)
            and _usable_lever_id(lever) not in held
        ]
        entry = {
            "slug": stem,
            "levers_file": levers_path.name,
            "levers_version": version,
            "levers": len(levers),
            "already_registered": len(held),
            "assigned": assigned,
            "to_register": [_usable_lever_id(lever) for lever in missing],
            "registered": 0,
            "rewrote_artefact": None,
        }
        if apply and (assigned or missing):
            from agents.tools._db import register_levers_sync

            # The artefact first, so the version the ledger records is the version that
            # actually names the ids. If this succeeds and the registration below does not,
            # a re-run finds every id in the artefact, assigns nothing new, and registers
            # what is missing - which is why this order is the recoverable one.
            if assigned:
                version = _rewrite_artefact(stem, identified)
                entry["rewrote_artefact"] = version
            entry["registered"] = register_levers_sync(
                stem, missing, version, BACKFILL_AUTHOR
            )
        report["projects"].append(entry)

    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="actually write the rows")
    args = parser.parse_args()
    try:
        result = backfill_value_lever_ledger(apply=args.apply)
    except BackfillRefused as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        raise SystemExit(2)
    print(json.dumps(result, indent=2))
    if not args.apply:
        print("\nDRY RUN - nothing changed. Pass --apply to assign and register them.")
