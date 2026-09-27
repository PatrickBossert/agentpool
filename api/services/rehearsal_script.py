"""The script a rehearsal interview is conducted from: a committed fixture, or a project's own.

**The default is owned by the product, not by a project.** It used to be
`projects/smoke-test/outputs/interview_scripts.json` - the output of a crew run on a real,
deletable project - so the rehearsal button was a product feature depending on an operator not
tidying up. When `smoke-test` was archived on the owner's instruction the door began answering
404 with a message telling whoever read it to *run discovery_mapping on the smoke-test project
first*, which is advice about a project that no longer exists. CLAUDE.md prescribes the shape
for exactly this, in its entry about four tests that skip silently on a missing
`projects/sp-gs-am/outputs/...`: a committed fixture rather than a bare relative path into
`projects/`.

So the fixture is resolved from **`__file__`**, never from `get_settings().projects_dir` and
never from a relative path. That is two separate defects closed rather than one: nothing an
operator deletes can break it, and nothing about the process's working directory can either -
the four dark tests CLAUDE.md names are dark on this workstation too whenever `pytest` is
started from anywhere but the repository root, because a bare relative `Path(...)` reads the
cwd. A path anchored to the module cannot.

The archived copy was read before this was written, and it was not worth restoring. It baked
the name *Patrick* into its welcome and closing messages and the consultancy's own name,
*FutureEdge*, into the welcome - so the rehearsal greeted whoever sat down as somebody else, in
front of a client - and it carried four questions on one operational topic, no `script_id` and
no `framing_block`. A smoke test is meant to be thin; a rehearsal a client watches is not.

The second half of this module is the other direction the same problem is solved in: a
consultant may rehearse one of the *project's* scripts instead. That is what makes the
committed default a floor rather than the only option.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

from api.config import get_settings
from api.database import fetch_project, get_connection

_log = logging.getLogger(__name__)

# Anchored to this module, so neither an operator tidying `projects/` nor the process's working
# directory can move it. See the module docstring.
_FIXTURE = Path(__file__).resolve().parent.parent / "fixtures" / "rehearsal_interview_script.json"


class RehearsalScriptUnavailable(Exception):
    """The committed fixture is missing or is not readable JSON.

    A deployment defect rather than a request defect - the file is committed - so the door
    answers 500 rather than 404. A 404 here would read as "this engagement has not got there
    yet", which is precisely the diagnosis that let this door stay broken.
    """


class ScriptNotOffered(Exception):
    """The caller named a script this project does not offer for rehearsal.

    Either there is no ledger row for the id, or the row is retired (`active = 0`). The two are
    deliberately one exception: both mean "not yours to rehearse", and telling them apart would
    disclose that an id exists while refusing to serve it.
    """


def default_rehearsal_script() -> dict:
    """The committed rehearsal script.

    Raises `RehearsalScriptUnavailable` rather than returning a stub, because a stub is how a
    missing fixture becomes a rehearsal that runs and demonstrates nothing.
    """
    try:
        return json.loads(_FIXTURE.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        _log.error("the committed rehearsal script could not be read: %s", exc)
        raise RehearsalScriptUnavailable(
            f"the committed rehearsal script at {_FIXTURE.name} could not be read: {exc}"
        ) from exc


async def rehearsal_script_options(slug: str) -> list[dict]:
    """Every script this project offers for rehearsal, in id order.

    `active = 1` only. Retirement exists in `interview_script_ledger` and a retired script is
    not an instrument anybody should be rehearsing - so the filter is **here**, on the server,
    and never in the dropdown. CLAUDE.md states that rule for the knowledge-tier picker in the
    words "never restate the rule in TypeScript"; a list the client filters is a list a second
    client will forget to filter.

    Each entry carries the `review_status` as well as the id and the label, because the offer is
    deliberately **not** approved-only. Measured on the live engagement before deciding: exactly
    one of 86 scripts is `approved`, and it is a van technician's interview - while the ones that
    suit a strategy audience are all `pending`. A rehearsal is not a client deliverable, so
    restricting the list to `approved` would have been over-cautious to the point of being
    useless. Showing the state is what makes the choice informed rather than blind.

    Intersected with the current `interview_scripts` artefact, so nothing is offered that the
    serve door would then 404 on. The ledger says what may be rehearsed and the artefact says
    what *can* be; an option that fails when clicked is worse than an option that is absent.

    Answers `[]` for every way this can come up empty - a fresh engagement with no scripts, a
    database predating the ledger migration, an artefact that cannot be read. **Never raises**:
    the committed default must stay rehearsable when a project has nothing of its own, which is
    the state every engagement is in until Maya has run.
    """
    rows = await _active_ledger_rows(slug)
    if not rows:
        return []
    available = _script_ids_in_current_artefact(slug)
    if available is None:
        # The artefact is unreadable. Offering the ledger's ids unintersected would hand the
        # consultant a list where every choice 404s; offering none leaves the default, which
        # works. Fewer options, never a broken one.
        return []
    return [row for row in rows if row["script_id"] in available]


async def project_rehearsal_script(slug: str, script_id: str) -> dict:
    """One of this project's own scripts, by id, for a rehearsal.

    The ledger is asked **first** and is the authority on whether the id may be rehearsed at
    all, before the artefact is opened. A retired script is refused here and not merely absent
    from the dropdown: CLAUDE.md's recurring failure mode is a property verified one layer away
    from where it holds, and "a retired script is not offered" enforced only in the list is a
    rule any hand-built URL walks straight past.
    """
    offered = {row["script_id"] for row in await _active_ledger_rows(slug)}
    if script_id not in offered:
        raise ScriptNotOffered(
            f"'{script_id}' is not a script this project offers for rehearsal"
        )
    scripts = _current_artefact(slug)
    script = (scripts or {}).get(script_id)
    if not isinstance(script, dict):
        raise ScriptNotOffered(
            f"'{script_id}' is registered but is not in this project's current interview scripts"
        )
    return script


def _database_exists(slug: str) -> bool:
    """Whether this slug has a database, asked without creating one.

    **Neither of the two readers below may materialise a database for a slug that has none.**
    `get_connection` creates the file and runs every migration on it; `current_output_path`
    resolves its row through `get_project_id`, a bare `sqlite3.connect`, which creates it too. So
    a caller naming slugs would otherwise leave one empty database per guess - which CLAUDE.md
    forbids outright, and which `caller_roles`, `_stakeholder_matches_invite` and
    `keyterms_for_project` all carry this same guard for.

    Driven rather than reasoned about: without it, asking these two functions about two
    non-existent slugs left `also-not-a-project.db` and `definitely-not-a-project.db` on disk.

    Both doors call `check_project_access` first, so an org_admin naming a slug outside their
    organisation is refused before reaching here - but a `sysadmin` passes that floor
    unconditionally, so the probe is reachable rather than theoretical. And a standing rule is
    not kept by the reachability of its exceptions, which is the sentence
    `keyterms_for_project`'s own guard is written under.
    """
    return (Path(get_settings().database_dir) / f"{slug}.db").exists()


async def _active_ledger_rows(slug: str) -> list[dict]:
    """The active ledger rows, or `[]` for any reason there are none to read."""
    if not _database_exists(slug):
        return []
    try:
        async with get_connection(slug) as conn:
            project = await fetch_project(conn, slug=slug)
            if not project:
                return []
            cur = await conn.execute(
                "SELECT script_id, node_id, node_label, review_status"
                "  FROM interview_script_ledger"
                " WHERE project_id = ? AND active = 1"
                " ORDER BY script_id",
                (project["id"],),
            )
            return [
                {
                    "script_id": row["script_id"],
                    # The value chain node this script interviews about. Carried because a
                    # consultant choosing a rehearsal recognises the engagement by its chain
                    # rather than by a script's sequence number: `1.F` says frontline, `0.A`
                    # says audit, and `SC-006` says only that it was the sixth written.
                    #
                    # It also brings this list into line with the rest of the product.
                    # CLAUDE.md: *"A script is shown by its value chain node id. `script_id`
                    # remains the identity - stakeholder assignments and stored answers cite
                    # it"* - which is how `ScriptReviewRow` labels the approver's view. This
                    # dropdown showed the identity and not the address, which is the one place
                    # in the product that did. Both are shown here rather than swapping one for
                    # the other, because the id is what a consultant types when asking for a
                    # specific script and what every report cites.
                    "node_id": row["node_id"] or "",
                    "node_label": row["node_label"] or "",
                    "review_status": row["review_status"] or "pending",
                }
                for row in await cur.fetchall()
            ]
    except Exception:
        _log.warning("rehearsal: no interview script ledger for %s", slug, exc_info=True)
        return []


def _current_artefact(slug: str) -> dict | None:
    """This project's current `interview_scripts`, resolved through the ledger.

    `current_output_path`, never `latest_output_path` - the rule CLAUDE.md states under
    *Resolving an output*. A glob over `interview_scripts_v*` returns the highest number on
    disk, which is not the current version after a revert, and would rehearse an instrument a
    human had already rejected.
    """
    from agents.tools._db import current_output_path

    # The same guard `_active_ledger_rows` carries, for the reason `_database_exists` states:
    # `current_output_path` reaches `get_project_id`, a bare `sqlite3.connect`, which creates the
    # file. Both callers already return early on an empty ledger, so this is unreachable today -
    # and it is here because a standing rule must not depend on that staying true.
    if not _database_exists(slug):
        return None

    try:
        path = current_output_path(slug, "interview_scripts")
        if path is None:
            return None
        data = json.loads(path.read_text())
    except Exception:
        _log.warning("rehearsal: could not read interview scripts for %s", slug, exc_info=True)
        return None
    return data if isinstance(data, dict) else None


def _script_ids_in_current_artefact(slug: str) -> set[str] | None:
    """The ids the current artefact holds, or None when it cannot be read at all.

    None and `set()` mean different things to the caller - "unknown" against "known to be
    empty" - so they are not collapsed.
    """
    data = _current_artefact(slug)
    if data is None:
        return None
    return {key for key, value in data.items() if isinstance(value, dict)}
