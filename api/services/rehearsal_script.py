"""The script a rehearsal interview is conducted from: a committed fixture the product owns.

**The default is owned by the product, not by a project.** It used to be
`projects/smoke-test/outputs/interview_scripts.json` - the output of a crew run on a real,
deletable project, behind a product feature. When `smoke-test` was archived on the owner's
instruction the rehearsal door began answering 404 with the message *run discovery_mapping on
the smoke-test project first*, naming a project that no longer existed, and the test-interview
button stopped doing anything useful.

Restoring the file would have left the dependency in place, and the dependency is the defect: a
product feature must not read a deletable project's output, and an operator tidying up must not
be able to break it. CLAUDE.md prescribes the shape for exactly this, in its entry about four
tests that skip silently on a missing `projects/sp-gs-am/outputs/...` - a committed fixture
rather than a bare relative path into `projects/`.

So the fixture is resolved from **`__file__`**, never from `get_settings().projects_dir` and
never from a relative path. That is two separate defects closed rather than one: nothing an
operator deletes can break it, and nothing about the process's working directory can either -
the four tests CLAUDE.md names are dark on this workstation too whenever `pytest` is started
from anywhere but the repository root, because a bare relative `Path(...)` reads the cwd. A path
anchored to the module cannot.

The archived copy was read before this was written, and it was not worth restoring. It baked the
name *Patrick* into its welcome and closing messages and the consultancy's own name,
*FutureEdge*, into the welcome - so the rehearsal greeted whoever sat down as somebody else, in
front of a client - and it carried four questions on one operational topic, no `script_id` and no
`framing_block`. A smoke test is meant to be thin; a rehearsal a client watches is not.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

_log = logging.getLogger(__name__)

# Anchored to this module, so neither an operator tidying `projects/` nor the process's working
# directory can move it. See the module docstring.
_FIXTURE = Path(__file__).resolve().parent.parent / "fixtures" / "rehearsal_interview_script.json"


class RehearsalScriptUnavailable(Exception):
    """The committed fixture is missing or is not readable JSON.

    A deployment defect rather than a request defect - the file is committed - so the door
    answers 500 rather than 404. A 404 here would read as "this project has not got there yet",
    which is precisely the diagnosis that let this door stay broken.
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
