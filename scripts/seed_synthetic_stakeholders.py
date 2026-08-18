# scripts/seed_synthetic_stakeholders.py
"""Seed a scratch project with a plausible roster of synthetic stakeholders, and take it
out again.

WHY. `sp-gs-am` is a test run ahead of a similar live engagement. It holds two real
stakeholders and 86 active value chain activities, so every surface that reasons about
"who speaks for what" - the assignment page, the coverage report, the Stakeholder Manager -
has been exercised against two rows and 86 nodes. That is not a test of anything. This
seeds ~60 people with job titles, entities and levels spread across the chain, and files
them against nodes at the altitude their insight actually lives at, so those surfaces meet
something the shape of a real roster before a real roster exists.

IDENTIFYING A SEEDED ROW - and this is the whole design. `stakeholders.is_synthetic`, a
column. Not a naming convention, not a marker inside a free-text field, not "the ones with
the odd email":

  - `insert_stakeholder` does not accept it, so nothing created through the API is ever
    marked;
  - `_STAKEHOLDER_UPDATABLE_FIELDS` does not contain it, so `update_stakeholder` raises
    ValueError on it - no PUT, PATCH or CSV import can set it on a real person or clear it
    on a seeded one, whatever anybody edits while testing.

The predicate `WHERE is_synthetic = 1` is therefore exactly the set this script wrote, at
any later date, no matter what has been edited in between - which is the property `--remove`
needs and which no convention can offer.

The addresses are a second, weaker signal, and they are there for the human rather than the
machine: `forename.surname@synthetic.invalid`. `.invalid` is reserved by RFC 2606 and can
never have an MX record, so a seeded row is unmistakable at a glance in the roster AND
cannot be delivered to. That matters more than it looks: `dev_mode` holds outbound mail to
one address on the PAM report and commit-notification paths ONLY. The interview reminder
sender (`campaign_service.send_reminder_emails_svc`) and the transcript sender
(`routers/interviews.py`) both post the stakeholder's own address straight to Resend with no
dev_mode check at all. Sixty rows carrying plausible-looking real addresses would be sixty
live sends waiting for the FROM domain to be verified. `.invalid` closes that by
construction.

NO INVITES. Every seeded row is `is_participant` and nothing else. A role beyond participant
is what makes `stakeholders.py` mint an invite, and an invite is a redeemable credential.
This script also writes through the database rather than the API, so even a mistake in the
roster could not reach `_issue_invite_if_newly_privileged`.

Dry run by default, as `prune_fragmented_outputs.py`, `reset_interview_artefacts.py` and
`backfill_project_registry.py` are. `--apply` is required to write, and the first `--apply`
copies the database aside first.

Safe to run twice: identity is `(project_id, email)`, inserts skip an address already
present, and assignments are `INSERT ... ON CONFLICT DO NOTHING` against the table's own
UNIQUE(project_id, stakeholder_id, node_id). A second run reports zero of everything.

The roster below cites `sp-gs-am`'s node ids directly, and every one of them is checked
against the project's own `value_chain_registry` before anything is written. An id that is
unknown or retired there is a refusal, not a warning - a seeded assignment pointing at a
node that does not exist would be worse than no seed at all.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import shutil
import sqlite3
from datetime import date
from pathlib import Path

from api.config import get_settings

# Reserved by RFC 2606: no MX record can ever exist under it, so nothing addressed here can
# be delivered even if every other guard were removed.
SYNTHETIC_EMAIL_DOMAIN = "synthetic.invalid"


class SeedRefused(Exception):
    """The run cannot proceed and nothing has been written."""


# ── The roster ────────────────────────────────────────────────────────────────
#
# (name, job_title, entity, organisation, level, [node_id, ...])
#
# `entity` is the party this person acts as within the chain - the same sense the two real
# rows use it in, where Patrick Bossert is entity "Advisor" at organisation "ARUP".
# `level` is the altitude the person's insight sits at, which is the altitude their nodes
# sit at: governance and assurance at L0, functional at L1, decision and effectiveness at
# L2, tactical and efficiency at L3. Anchoring everybody at L3 is the exact bias CLAUDE.md
# warns skews value proposition generation, and a seed that did it would build that skew
# into every downstream synthesis this project has yet to run.
#
# Coverage is deliberately incomplete and deliberately uneven: 76 of the 86 active nodes
# carry somebody, several nodes carry two or three, and ten carry nobody. 100% coverage
# never happens on a real engagement, and a coverage report handed a perfect roster reports
# nothing and proves nothing.
#
# `value_chain_stage` and `activity` are left empty on purpose. They are free-text copies of
# node labels, and Alex re-emits every label on every run - one run produced 59 label
# changes. The assignment rows below cite node *ids*, which are a permanent contract. Ask
# the ledger, never the copy.
ROSTER: list[tuple[str, str, str, str, str, list[str]]] = [
    # ── L0: the organisation, its audit function, its corporate services frontline ──
    ("Alistair Groves", "Managing Director, Group Services", "GS UK",
     "Scottish Power Group Services UK", "L0", ["0"]),
    ("Fiona Craigie", "Head of Internal Audit", "GS UK",
     "Scottish Power Group Services UK", "L0", ["0.A"]),
    ("Rhona Baillie", "Audit Manager, Asset Assurance", "GS UK",
     "Scottish Power Group Services UK", "L0", ["0.A"]),
    ("Duncan Aitchison", "Head of Corporate Services", "GS UK",
     "Scottish Power Group Services UK", "L0", ["0.S"]),
    ("Morag Kinnaird", "Corporate Services Coordinator", "GS UK",
     "Scottish Power Group Services UK", "L0", ["0.S"]),

    # ── L1: the three chains, plus their customer and frontline role nodes ──
    ("Callum Strachan", "Property Director", "GS UK",
     "Scottish Power Group Services UK", "L1", ["1"]),
    ("Elspeth Rennie", "Head of Property Operations", "GS UK",
     "Scottish Power Group Services UK", "L1", ["1", "1.F"]),
    ("Gordon Meiklejohn", "Regional Facilities Manager", "ISS",
     "ISS Facility Services", "L1", ["1.F"]),
    ("Iona Selkirk", "Business Unit Liaison, Networks", "Customer",
     "ScottishPower Energy Networks", "L1", ["1.C"]),
    ("Nairn Fotheringham", "Fleet Director", "GS UK",
     "Scottish Power Group Services UK", "L1", ["2"]),
    ("Struan Dalgleish", "Head of Fleet Operations", "GS UK",
     "Scottish Power Group Services UK", "L1", ["2", "2.F"]),
    ("Kirsty Lamont", "Depot Supervisor", "GS UK",
     "Scottish Power Group Services UK", "L1", ["2.F"]),
    ("Ewan Tarbet", "Field Team Lead, Generation", "Customer",
     "ScottishPower Renewables", "L1", ["2.C"]),
    ("Marjory Inglis", "Head of Support Services", "GS UK",
     "Scottish Power Group Services UK", "L1", ["3"]),

    # ── L2: decision and effectiveness. 2.6 and 3.4 are left uncovered on purpose. ──
    ("Hamish Kerrigan", "Asset Strategy Manager", "GS UK",
     "Scottish Power Group Services UK", "L2", ["1.1"]),
    ("Sorcha Bannerman", "Portfolio Investment Manager", "GS UK",
     "Scottish Power Group Services UK", "L2", ["1.2"]),
    ("Lachlan Purdie", "Works Programme Manager", "GS UK",
     "Scottish Power Group Services UK", "L2", ["1.3"]),
    ("Bridget Corrigall", "Scheduling and Logistics Manager", "ISS",
     "ISS Facility Services", "L2", ["1.4"]),
    ("Angus Wemyss", "Maintenance Delivery Manager", "ISS",
     "ISS Facility Services", "L2", ["1.5"]),
    ("Catriona Muirhead", "Performance and Improvement Manager", "GS UK",
     "Scottish Power Group Services UK", "L2", ["1.6"]),
    ("Robbie Dunsmuir", "Fleet Policy and Compliance Manager", "GS UK",
     "Scottish Power Group Services UK", "L2", ["2.1"]),
    ("Shona Lithgow", "Fleet Portfolio Analyst", "GS UK",
     "Scottish Power Group Services UK", "L2", ["2.2"]),
    ("Findlay Ogilvie", "EV Transition Programme Manager", "Fleet Alliance",
     "Fleet Alliance", "L2", ["2.3"]),
    ("Isla Rutherglen", "Fleet Deployment Manager", "GS UK",
     "Scottish Power Group Services UK", "L2", ["2.4"]),
    ("Douglas Prentice", "Workshop Manager", "ISS",
     "ISS Facility Services", "L2", ["2.5"]),
    ("Priya Ramanathan", "Digital Systems Manager", "GS UK",
     "Scottish Power Group Services UK", "L2", ["3.1"]),
    ("Malcolm Hendry", "Governance and Risk Manager", "GS UK",
     "Scottish Power Group Services UK", "L2", ["3.2"]),
    ("Alison Weatherstone", "Commercial Contracts Manager", "GS UK",
     "Scottish Power Group Services UK", "L2", ["3.3"]),
    ("Niall Sillars", "Asset Data Manager", "GS UK",
     "Scottish Power Group Services UK", "L2", ["3.5"]),

    # ── L3, Property: tactical and efficiency. 1.6.3 and 1.6.4 left uncovered. ──
    ("Ross Cargill", "Asset Information Analyst", "GS UK",
     "Scottish Power Group Services UK", "L3", ["1.1.1"]),
    ("Jean Threipland", "Compliance Records Officer", "GS UK",
     "Scottish Power Group Services UK", "L3", ["1.1.2", "3.2.3"]),
    ("Kenneth Lyall", "Lifecycle Modelling Analyst", "Advisor",
     "ARUP", "L3", ["1.2.1", "1.2.2"]),
    ("Innes Tullis", "Work Packaging Planner", "GS UK",
     "Scottish Power Group Services UK", "L3", ["1.3.1", "1.3.2"]),
    ("Kirsteen Mackie", "Procurement Category Lead", "GS UK",
     "Scottish Power Group Services UK", "L3", ["1.4.1"]),
    ("Barry Nisbet", "Dispatch Controller", "ISS",
     "ISS Facility Services", "L3", ["1.4.2", "1.4.3"]),
    ("Craig Whitelaw", "Helpdesk Team Leader", "ISS",
     "ISS Facility Services", "L3", ["1.5.1"]),
    ("Sheena Dalrymple", "Statutory Inspection Supervisor", "ISS",
     "ISS Facility Services", "L3", ["1.5.2"]),
    ("Jamie Ferrier", "Maintenance Technician", "ISS",
     "ISS Facility Services", "L3", ["1.5.3", "1.5.4"]),
    ("Wendy Guthrie", "Maintenance Technician", "ISS",
     "ISS Facility Services", "L3", ["1.5.3"]),
    ("Rhoda Sinclair", "Capital Projects Manager", "GS UK",
     "Scottish Power Group Services UK", "L3", ["1.5.5", "1.5.6"]),
    ("Ryan Pollock", "Performance Reporting Analyst", "GS UK",
     "Scottish Power Group Services UK", "L3", ["1.6.1", "1.6.2"]),

    # ── L3, Fleet. 2.5.1 and 2.6.4 left uncovered. ──
    ("Moira Cadell", "Fleet Register Administrator", "GS UK",
     "Scottish Power Group Services UK", "L3", ["2.1.1"]),
    ("Gregor Wishart", "DVSA Compliance Officer", "GS UK",
     "Scottish Power Group Services UK", "L3", ["2.1.2", "2.6.2"]),
    ("Alice Frew", "Net-Zero Policy Lead", "Customer",
     "ScottishPower Group Sustainability", "L3", ["2.1.3", "2.6.3"]),
    ("Neil Ballantyne", "Fleet Lifecycle Analyst", "GS UK",
     "Scottish Power Group Services UK", "L3", ["2.2.1", "2.2.3"]),
    ("Susan Kilpatrick", "EV Transition Analyst", "Fleet Alliance",
     "Fleet Alliance", "L3", ["2.2.2", "2.3.2"]),
    ("Graeme Ochiltree", "Fleet Procurement Lead", "GS UK",
     "Scottish Power Group Services UK", "L3", ["2.3.1", "2.3.3"]),
    ("Fraser Bogle", "Vehicle Allocation Coordinator", "GS UK",
     "Scottish Power Group Services UK", "L3", ["2.4.1", "2.4.3"]),
    ("Nicola Braid", "Fleet Maintenance Scheduler", "ISS",
     "ISS Facility Services", "L3", ["2.4.2"]),
    ("Owen Redpath", "Vehicle Technician", "ISS",
     "ISS Facility Services", "L3", ["2.5.2", "2.5.4"]),
    ("Sandy Kilbride", "EV Battery Specialist", "ISS",
     "ISS Facility Services", "L3", ["2.5.3"]),
    ("Yvonne Traquair", "Fleet Cost and Emissions Analyst", "GS UK",
     "Scottish Power Group Services UK", "L3", ["2.6.1"]),

    # ── L3, Support Services. 3.1.6, 3.2.4, 3.4.3 and 3.5.3 left uncovered. ──
    ("Iain Marnoch", "Tririga Systems Lead", "GS UK",
     "Scottish Power Group Services UK", "L3", ["3.1.1"]),
    ("Rosemary Auchinleck", "SAP Finance Systems Analyst", "GS UK",
     "Scottish Power Group Services UK", "L3", ["3.1.2", "3.1.3"]),
    ("Anita Chakrabarti", "AI Delivery Lead", "GS UK",
     "Scottish Power Group Services UK", "L3", ["3.1.4", "3.1.5"]),
    ("Bruce Elphinstone", "Safety and Security Manager", "GS UK",
     "Scottish Power Group Services UK", "L3", ["3.2.1", "3.2.2"]),
    ("Colin Drysdale", "ISS Contract Manager", "ISS",
     "ISS Facility Services", "L3", ["3.3.1", "3.3.4"]),
    ("Sean Riddoch", "Financial Controller", "GS UK",
     "Scottish Power Group Services UK", "L3", ["3.3.2", "3.3.3"]),
    ("Martin Gillespie", "Change Programme Manager", "GS UK",
     "Scottish Power Group Services UK", "L3", ["3.4.1", "3.4.2"]),
    ("Zoe Handyside", "Asset Register Data Steward", "GS UK",
     "Scottish Power Group Services UK", "L3", ["3.5.1", "3.5.2"]),
]

# The L1 chain a node id belongs to, used only to fill `value_streams` - the column
# `campaign_service` filters on when it picks who to remind. A seeded row with an empty
# value_streams is invisible to every campaign, which would make the roster useless for the
# one thing it is being seeded for.
_CHAIN_LABELS = {"1": "Property", "2": "Fleet", "3": "Support Services"}


def synthetic_email(name: str) -> str:
    """forename.surname@synthetic.invalid - stable, unique, and undeliverable by RFC."""
    local = ".".join(part for part in name.lower().split() if part)
    return f"{local}@{SYNTHETIC_EMAIL_DOMAIN}"


def _value_streams(node_ids: list[str]) -> list[str]:
    """The chains this person's nodes sit in, deduplicated and ordered.

    "Organisation" for the L0 nodes, which belong to no chain: they are the organisation
    itself, its audit function, and its corporate services frontline.
    """
    streams: list[str] = []
    for node_id in node_ids:
        label = _CHAIN_LABELS.get(node_id.split(".")[0], "Organisation")
        if label not in streams:
            streams.append(label)
    return streams


def _assert_roster_is_well_formed() -> None:
    """Two mistakes a hand-written roster invites, caught before anything is opened.

    A duplicated address would silently make one person two rows on a second run - the
    identity `(project_id, email)` would match the first insert and skip the second
    forever. A duplicated node on one person is harmless (the UNIQUE swallows it) but is
    always a copy-paste slip worth being told about.
    """
    emails = [synthetic_email(row[0]) for row in ROSTER]
    duplicates = sorted({e for e in emails if emails.count(e) > 1})
    if duplicates:
        raise SeedRefused(f"roster has duplicate addresses: {', '.join(duplicates)}")
    for name, _title, _entity, _org, _level, node_ids in ROSTER:
        if len(set(node_ids)) != len(node_ids):
            raise SeedRefused(f"roster repeats a node id for {name}: {node_ids}")


# ── Preconditions ─────────────────────────────────────────────────────────────

def _assert_is_this_project(db_path: Path, slug: str) -> None:
    """Read-only, and before anything else opens the file.

    `get_connection` runs the migration block for any slug it is handed, including one that
    does not exist yet - it would happily materialise `data/typo.db`, migrate it to the
    current schema and leave it there looking like a project. So the file must already
    exist and must already hold a `projects` row claiming this slug before this script
    opens it in a way that can write.
    """
    if not db_path.exists():
        raise SeedRefused(f"no database at {db_path} - '{slug}' is not a project here")
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        row = conn.execute(
            "SELECT 1 FROM projects WHERE slug=?", (slug,)
        ).fetchone()
    except sqlite3.DatabaseError as exc:
        raise SeedRefused(f"{db_path} is not a readable project database: {exc}") from exc
    finally:
        conn.close()
    if row is None:
        raise SeedRefused(
            f"{db_path} holds no projects row for '{slug}' - it is a backup copy or a "
            "probe, not an engagement"
        )


def _assert_nodes_exist(slug: str) -> None:
    """Every node id the roster cites must be registered AND active on this project.

    A refusal rather than a warning. An assignment against an id no registry holds is a row
    the assignment page cannot render and the coverage report cannot classify, and it would
    be indistinguishable from a real mis-keyed assignment for as long as it sat there.
    """
    from api.services.project_service import get_value_chain_node_index

    index = get_value_chain_node_index(slug)
    if not index:
        raise SeedRefused(
            f"'{slug}' has no value_chain_registry - there is nothing to assign against"
        )
    cited = {node_id for row in ROSTER for node_id in row[5]}
    unknown = sorted(node_id for node_id in cited if node_id not in index)
    retired = sorted(
        node_id for node_id in cited
        if node_id in index and not index[node_id]["active"]
    )
    problems = []
    if unknown:
        problems.append(f"not in the registry: {', '.join(unknown)}")
    if retired:
        problems.append(f"retired in the registry: {', '.join(retired)}")
    if problems:
        raise SeedRefused(f"roster cites node ids {'; '.join(problems)}")


def _backup_path(db_path: Path, on: date, *, remove: bool = False) -> Path:
    """The copy taken before a run, named for what the copy actually holds.

    `--remove` used to take its backup under `pre-synthetic-<today>`, which on any day but
    the seeding day names a *post*-synthetic snapshot as a pre-synthetic one. Nothing was
    lost - the file is a faithful copy of the state before the removal - but a reader
    reaching for the pre-seed state would have opened a file holding sixty seeded rows.
    Seeding keeps its name, so `data/sp-gs-am.pre-synthetic-2026-08-18.db` still means what
    the ledger says it means.
    """
    stem = "pre-removal" if remove else "pre-synthetic"
    return db_path.with_name(f"{db_path.stem}.{stem}-{on.isoformat()}.db")


# ── The work ──────────────────────────────────────────────────────────────────

async def _seed(conn, project_id: int) -> dict:
    existing = {
        row["email"]: row["id"]
        for row in await conn.execute_fetchall(
            "SELECT id, email FROM stakeholders WHERE project_id=? AND is_synthetic=1",
            (project_id,),
        )
    }
    inserted_people = 0
    ids_by_email: dict[str, int] = dict(existing)

    for name, job_title, entity, organisation, level, _nodes in ROSTER:
        email = synthetic_email(name)
        if email in ids_by_email:
            continue
        cur = await conn.execute(
            "INSERT INTO stakeholders"
            " (project_id, name, job_title, organisation, email, value_streams,"
            "  disposition, country_code, timezone, preferred_language, currency,"
            "  level, entity, comms_channel, project_role,"
            "  is_participant, is_synthetic)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,1,1)",
            (
                project_id, name, job_title, organisation, email,
                json.dumps(_value_streams(_nodes)),
                "neutral", "GB", "Europe/London", "English", "GBP",
                level, entity, "email", "recipient",
            ),
        )
        ids_by_email[email] = cur.lastrowid
        inserted_people += 1

    inserted_assignments = 0
    for name, _title, _entity, _org, _level, node_ids in ROSTER:
        stakeholder_id = ids_by_email[synthetic_email(name)]
        for node_id in node_ids:
            cur = await conn.execute(
                "INSERT INTO stakeholder_assignments (project_id, stakeholder_id, node_id)"
                " VALUES (?,?,?)"
                " ON CONFLICT(project_id, stakeholder_id, node_id) DO NOTHING",
                (project_id, stakeholder_id, node_id),
            )
            inserted_assignments += cur.rowcount
    await conn.commit()
    return {
        "stakeholders_inserted": inserted_people,
        "assignments_inserted": inserted_assignments,
        "stakeholders_total": len(ids_by_email),
    }


# Tables that point at a stakeholder and hold something a person did, rather than something
# this script wrote. `--remove` refuses rather than cascading through them: a transcript is
# a thing somebody said once, and no rerun brings it back.
_INTERVIEW_DEPENDANTS = (
    ("interview_sessions", "stakeholder_id"),
    ("interview_responses", "stakeholder_id"),
    ("interview_answers", "stakeholder_id"),
    ("reminder_emails", "stakeholder_id"),
)


async def _remove(conn, project_id: int) -> dict:
    rows = await conn.execute_fetchall(
        "SELECT id FROM stakeholders WHERE project_id=? AND is_synthetic=1", (project_id,)
    )
    ids = [row["id"] for row in rows]
    if not ids:
        return {"stakeholders_deleted": 0, "assignments_deleted": 0}

    placeholders = ",".join("?" * len(ids))
    blocking: dict[str, int] = {}
    for table, column in _INTERVIEW_DEPENDANTS:
        exists = await conn.execute_fetchall(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
        )
        if not exists:
            continue
        found = await conn.execute_fetchall(
            f"SELECT COUNT(*) AS n FROM {table} WHERE {column} IN ({placeholders})", ids
        )
        if found[0]["n"]:
            blocking[table] = found[0]["n"]
    if blocking:
        detail = ", ".join(f"{n} in {t}" for t, n in sorted(blocking.items()))
        raise SeedRefused(
            "synthetic stakeholders are cited by interview data and were not removed - "
            f"{detail}. That data is a record of something a person did; delete it "
            "deliberately first (see scripts/reset_interview_artefacts.py) if it really "
            "is disposable."
        )

    cur = await conn.execute(
        f"DELETE FROM stakeholder_assignments WHERE project_id=?"
        f" AND stakeholder_id IN ({placeholders})",
        [project_id, *ids],
    )
    assignments_deleted = cur.rowcount
    # The second assignment table used to be swept here too. It is gone - dropped by
    # _migrate_drop_stakeholder_node_assignments, which `get_connection` above has already
    # run against this file - so there is one table left for a seeded row to leave rows in.
    cur = await conn.execute(
        f"DELETE FROM stakeholders WHERE id IN ({placeholders})", ids
    )
    deleted = cur.rowcount
    await conn.commit()
    return {"stakeholders_deleted": deleted, "assignments_deleted": assignments_deleted}


async def _run(slug: str, *, apply: bool, remove: bool, today: date) -> dict:
    from api.database import get_connection

    settings = get_settings()
    db_path = Path(settings.database_dir) / f"{slug}.db"

    _assert_roster_is_well_formed()
    _assert_is_this_project(db_path, slug)
    if not remove:
        _assert_nodes_exist(slug)

    backup = _backup_path(db_path, today, remove=remove)
    if apply and not backup.exists():
        shutil.copy2(db_path, backup)

    if not apply:
        # Dry run opens nothing writable. `get_connection` would migrate the file, which is
        # a write, and a dry run that upgrades the schema is not a dry run.
        return {
            "slug": slug,
            "applied": False,
            "mode": "remove" if remove else "seed",
            "roster_size": len(ROSTER),
            "assignments_in_roster": sum(len(row[5]) for row in ROSTER),
            "backup_would_be": str(backup),
        }

    async with get_connection(slug) as conn:
        rows = await conn.execute_fetchall(
            "SELECT id FROM projects WHERE slug=?", (slug,)
        )
        project_id = rows[0]["id"]
        result = await (_remove(conn, project_id) if remove else _seed(conn, project_id))

    result.update({"slug": slug, "applied": True,
                   "mode": "remove" if remove else "seed",
                   "backup": str(backup)})
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--slug", required=True, help="project slug, e.g. sp-gs-am")
    parser.add_argument("--apply", action="store_true", help="write (default is a dry run)")
    parser.add_argument(
        "--remove", action="store_true",
        help="delete every is_synthetic row and its assignments instead of seeding",
    )
    args = parser.parse_args()
    try:
        result = asyncio.run(
            _run(args.slug, apply=args.apply, remove=args.remove, today=date.today())
        )
    except SeedRefused as exc:
        print(f"refused: {exc}")
        return 1
    for key, value in result.items():
        print(f"{key}: {value}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
