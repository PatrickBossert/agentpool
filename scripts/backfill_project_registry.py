# scripts/backfill_project_registry.py
"""Register every project already on disk against the home organisation.

`check_project_access` resolves a non-sysadmin org_admin by comparing the JWT's `org_id` to
the `project_registry` row for the slug, and falls through to 403 when there is no row. Project
creation now writes that row whatever the creator's role, but every project created before that
change has none - on the live deployment, all of them. This is the one-off that closes the gap
behind them.

**A script, not a migration.** `get_connection(slug)` runs the migration block for any slug it
is handed, including one materialised by a probe, so backfilling from there would write registry
rows for slugs that are not projects at all. Every database this touches is opened with plain
`sqlite3` - project databases read-only - so nothing here creates, migrates, or upgrades
anything.

**It never invents an organisation.** The organisation is resolved by slug and a miss is a
refusal, not an insert: a typo in `--org` must not quietly create a second organisation that new
projects would then not be registered to. On a deployment running this branch the home
organisation already exists, because `init_system_db` seeds it on every system connection - so
a refusal here means the API has not been restarted yet, or `--org` names something else.

**A file is a project only if it says so.** A candidate is registered only when its own
`projects` table holds a row whose slug matches the filename stem. That is what keeps the
dated backup copies the other scripts in here leave behind - `sp-gs-am.pre-interview-reset-
2026-08-04.db` - from being registered as projects in their own right, and it is the same
distinction the "do not backfill in a migration" rule is protecting: a materialised shell with
no `projects` row is not an engagement.

Dry run by default, as `prune_fragmented_outputs.py` and `reset_interview_artefacts.py` are.
Pass `--apply` to write. Safe to run twice - registration is `INSERT OR IGNORE` on a unique
slug, and a second run reports every project under `already_registered` and writes nothing.

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

from api.config import get_settings


class BackfillRefused(Exception):
    """The run cannot proceed and nothing has been written."""


def _project_slug_in(db_path: Path) -> str | None:
    """The slug this database claims to be, or None if it is not a project database.

    Read-only, so a probe cannot be turned into a project by being looked at.
    """
    try:
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    except sqlite3.Error:
        return None
    with contextlib.closing(conn):
        try:
            cur = conn.execute("SELECT slug FROM projects ORDER BY id LIMIT 1")
            row = cur.fetchone()
        except sqlite3.Error:
            return None
    return row[0] if row else None


def backfill_project_registry(
    *, org_slug: str | None = None, apply: bool = False
) -> dict:
    settings = get_settings()
    database_dir = Path(settings.database_dir)
    org_slug = org_slug or settings.home_org_slug

    system_db = database_dir / "system.db"
    if not system_db.exists():
        raise BackfillRefused(
            f"No system database at {system_db} - nothing to register into."
        )

    with contextlib.closing(sqlite3.connect(system_db)) as sys_conn:
        sys_conn.row_factory = sqlite3.Row
        try:
            cur = sys_conn.execute(
                "SELECT id, slug, name FROM organisations WHERE slug=?", (org_slug,)
            )
            org = cur.fetchone()
            known = [r["slug"] for r in sys_conn.execute(
                "SELECT slug FROM organisations ORDER BY slug"
            )]
        except sqlite3.OperationalError as exc:
            raise BackfillRefused(
                f"{system_db} has no organisations table ({exc}). Start the API once so"
                " init_system_db can create and seed it, then run this again."
            ) from exc

        if org is None:
            raise BackfillRefused(
                f"No organisation with slug '{org_slug}'. This script does not create one."
                f" Organisations present: {known or 'none'}."
                " Start the API once to seed the home organisation, or create it through"
                " POST /auth/orgs, then run this again."
            )

        registered_slugs = {
            r["slug"] for r in sys_conn.execute("SELECT slug FROM project_registry")
        }

        report: dict = {
            "database_dir": str(database_dir),
            "organisation": {"id": org["id"], "slug": org["slug"], "name": org["name"]},
            "registered": [],
            "already_registered": [],
            "skipped": [],
            "applied": apply,
        }

        for db_path in sorted(database_dir.glob("*.db")):
            if db_path.name == "system.db":
                continue
            stem = db_path.stem
            claimed = _project_slug_in(db_path)
            if claimed is None:
                report["skipped"].append(
                    {"file": db_path.name, "reason": "no projects row - not a project database"}
                )
                continue
            if claimed != stem:
                report["skipped"].append({
                    "file": db_path.name,
                    "reason": f"projects row says '{claimed}', filename says '{stem}'"
                              " - a copy or backup, not the live database for that slug",
                })
                continue
            if stem in registered_slugs:
                report["already_registered"].append(stem)
                continue
            report["registered"].append(stem)
            if apply:
                sys_conn.execute(
                    "INSERT OR IGNORE INTO project_registry (slug, org_id, display_name)"
                    " VALUES (?,?,?)",
                    (stem, org["id"], stem),
                )
        if apply:
            sys_conn.commit()

    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--org",
        default=None,
        help="slug of the organisation to register against (default: home_org_slug)",
    )
    parser.add_argument("--apply", action="store_true", help="actually write the rows")
    args = parser.parse_args()
    try:
        result = backfill_project_registry(org_slug=args.org, apply=args.apply)
    except BackfillRefused as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        raise SystemExit(2)
    print(json.dumps(result, indent=2))
    if not args.apply:
        print("\nDRY RUN - nothing changed. Pass --apply to register them.")
