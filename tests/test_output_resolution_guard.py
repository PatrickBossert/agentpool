# tests/test_output_resolution_guard.py
"""No code may resolve a declared output by filename.

Writes are versioned to a _vN suffix and the current version is recorded in agent_outputs, so a
bare `<type>.json` names a file that does not exist. It fails silently: the reader gets None, an
empty list, or a 404, and nothing reports why. This has now been found in six places across three
separate tasks, which is why it gets a guard rather than a sixth individual fix.

CLAUDE.md's "Resolving an output: ask the ledger, never the disk" records four incidents from the
same root - a demoted clean baseline, a value_chain_tree_v13 shadow, a version-counter reset, and
an agent reading a three-week-old summary.

A second guard, below, covers the sibling defect: a project database opened with a raw
aiosqlite.connect instead of through the shared helper that applies WAL and a busy timeout.
"""
import re
from pathlib import Path

import pytest

from agents.tools.ownership import OUTPUT_OWNERS

# The one legitimate bare read: a hand-written fixture for the built-in test interview that
# really does live at that path and is not produced by any agent.
_ALLOWED = {("api/routers/interviews.py", "interview_scripts")}


def test_no_declared_output_is_resolved_by_filename():
    root = Path(__file__).resolve().parents[1]
    offenders = []
    for directory in ("api", "agents"):
        for path in (root / directory).rglob("*.py"):
            rel = str(path.relative_to(root))
            for number, line in enumerate(path.read_text().splitlines(), 1):
                for output_type in OUTPUT_OWNERS:
                    if f'"{output_type}.json"' in line and (rel, output_type) not in _ALLOWED:
                        offenders.append(f"{rel}:{number} builds a path to {output_type}.json")
    assert not offenders, (
        "resolve these through current_output_path(slug, output_type):\n  "
        + "\n  ".join(offenders)
    )


def test_no_project_database_is_opened_outside_the_shared_helper():
    """Project databases carry WAL and a busy timeout, applied in one place.

    A raw aiosqlite.connect gets journal_mode=delete and Python's 5s default instead - measured
    on the live database. Task 15 fixed four such sites and its review found three more in a file
    nobody had checked, which is why this is a guard rather than an eighth fix.

    system.db is a different database with different needs and is not covered here. The brief
    for this guard proposed excluding lines that mention a variable named `sys_db_path` or
    `sys_path`, but five real, legitimate call sites outside api/database.py and api/main.py
    open system.db through exactly those two spellings (api/routers/projects.py,
    api/services/run_service.py, api/services/auto_assign_service.py twice, and
    api/services/interview_service.py) - a name-only match would have exempted every one of
    them, which is correct today but only by convention. Matching how the path was *derived*
    instead - the variable traces back to a `get_system_db_path()` call somewhere earlier in
    the same file - holds even if a future system.db open picks a differently-spelled variable,
    and still flags a project-db open that happens to reuse one of these names but was not
    actually built from get_system_db_path().
    """
    root = Path(__file__).resolve().parents[1]
    # Legitimate raw opens: the helpers themselves, and one startup admin scan that runs
    # before the app serves any request.
    allowed = {"api/database.py", "api/main.py"}
    connect_re = re.compile(r"aiosqlite\.connect\(\s*(?:str\()?(\w+)\)?\s*\)")
    offenders = []
    for directory in ("api", "agents"):
        for path in (root / directory).rglob("*.py"):
            rel = str(path.relative_to(root))
            if rel in allowed:
                continue
            lines = path.read_text().splitlines()
            for number, line in enumerate(lines, 1):
                if "aiosqlite.connect(" not in line:
                    continue
                match = connect_re.search(line)
                variable = match.group(1) if match else None
                # A variable assigned from get_system_db_path() anywhere earlier in the file
                # is system.db, whatever it happens to be called - the derivation is what
                # matters, not the spelling.
                derived_from_system_db = variable is not None and any(
                    re.match(rf"\s*{re.escape(variable)}\s*=\s*get_system_db_path\(\)", earlier)
                    for earlier in lines[:number]
                )
                if not derived_from_system_db:
                    offenders.append(f"{rel}:{number}")
    assert not offenders, (
        "open project databases through api.database.interview_db_connection or "
        f"get_connection, not raw:\n  " + "\n  ".join(offenders)
    )
