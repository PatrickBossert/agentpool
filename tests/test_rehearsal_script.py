# tests/test_rehearsal_script_selection.py
"""Which script a rehearsal interview is conducted from.

`GET /api/interviews/test/script` read `projects/smoke-test/outputs/interview_scripts.json` - a
*crew output* on a *deletable project*, behind a *product feature*. `smoke-test` was archived on
the owner's instruction, so the door answered 404 with the message *run discovery_mapping on the
smoke-test project first*, naming a project that no longer existed, and the test-interview button
stopped working.

Restoring the file would have left the dependency, and the dependency is the defect. The fixture
is committed and owned by the product instead, and the tests below assert that it is reachable
with **no project at all, no `projects/` directory, and from any working directory**, because
those are the three ways the old arrangement could break - and only the first of them is the one
that actually happened.
"""
import ast
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from api.config import get_settings
from api.services.rehearsal_script import (
    RehearsalScriptUnavailable,
    default_rehearsal_script,
)

SCRIPT_DOOR = "/api/interviews/test/script"


def _code_strings_and_attributes(source: str) -> tuple[set[str], set[str]]:
    """Every string literal that is *code*, and every attribute name read, from a module.

    By AST and not by grep, because the prose in the module under test deliberately names
    `projects/smoke-test/outputs/interview_scripts.json` - it is the record of the defect, and
    the first version of this guard failed on its own subject's docstring. CLAUDE.md states the
    rule twice over: *a comment citing a rule is evidence about intent*, and *enumerate by
    behaviour, not by name* - and it records `get_agent_image`, a handler whose docstring
    contains `check_project_access` while explaining why it does not call it, so a text-keyed
    sweep counted it as gated. A docstring cannot be an `ast.Call`, and it cannot be a string
    this function returns either.
    """
    tree = ast.parse(source)
    docstrings = {
        id(node.body[0].value)
        for node in ast.walk(tree)
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
        and node.body
        and isinstance(node.body[0], ast.Expr)
        and isinstance(node.body[0].value, ast.Constant)
        and isinstance(node.body[0].value.value, str)
    }
    strings = {
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and id(node) not in docstrings
    }
    attributes = {node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)}
    return strings, attributes


def test_the_guard_below_can_tell_a_docstring_from_code():
    """Establish the walk, in both directions, rather than describing it.

    CLAUDE.md records four guards whose own account of their coverage was wrong, and the repair
    each time is the same: make the walk a pure function over given text and drive one of each
    kind through it *both* ways. A one-sided test passes against a walk that reports everything
    and against one that reports nothing - and this walk's first version reported its subject's
    prose, which is the failing direction.
    """
    strings, attributes = _code_strings_and_attributes(
        '"""A module docstring naming projects/smoke-test and projects_dir."""\n'
        "def f():\n"
        '    """A function docstring naming projects/smoke-test too."""\n'
        '    return "harmless"\n'
    )
    assert not [s for s in strings if "smoke-test" in s], "prose was read as code"
    assert "harmless" in strings, "a real string literal was missed"

    strings, attributes = _code_strings_and_attributes(
        'PATH = "projects/smoke-test/outputs/interview_scripts.json"\n'
        "def f(settings):\n"
        "    return settings.projects_dir\n"
    )
    assert [s for s in strings if "smoke-test" in s], "a literal path was not seen"
    assert "projects_dir" in attributes, "an attribute read was not seen"


def test_the_default_script_is_a_committed_fixture_and_not_a_project_output():
    """It is in the repository, under `api/`, and no project and no setting is consulted.

    Asserted on where the file is **resolved from** as well as on it existing, because "the
    script loads" was true of the broken arrangement too for as long as `smoke-test` existed. The
    defect was never that the file was absent; it was that the file belonged to somebody who
    could delete it - so the guard is that nothing in the code names a project directory, in
    either of the two ways it could: a literal path, or `get_settings().projects_dir`.
    """
    fixture = (
        Path(__file__).resolve().parents[1]
        / "api" / "fixtures" / "rehearsal_interview_script.json"
    )
    assert fixture.exists(), "the rehearsal script must be committed, not generated"

    module = Path(__file__).resolve().parents[1] / "api/services/rehearsal_script.py"
    strings, attributes = _code_strings_and_attributes(module.read_text())

    assert not [s for s in strings if "smoke-test" in s], \
        "the rehearsal default names a project again"
    assert "projects_dir" not in attributes, \
        "the committed fixture must not be resolved through projects_dir"
    assert "fixtures" in strings, "the fixture is expected to live under api/fixtures/"


def test_the_default_script_is_a_usable_interview():
    """The shape the dialog consumes, and enough of it to demonstrate the mechanism.

    The archived smoke-test script was read before this was written and was not restored: it
    baked the name *Patrick* and the consultancy's own name *FutureEdge* into its welcome and
    closing messages, so the rehearsal greeted whoever sat down as somebody else in front of a
    client. Those two names are asserted absent, so a future edit cannot reintroduce the defect
    that caused the rewrite - and no participant name is hardcoded at all.
    """
    script = default_rehearsal_script()

    for field in ("node_label", "welcome_message", "closing_message", "sections"):
        assert script.get(field), f"the rehearsal script needs a {field}"

    questions = [q for s in script["sections"] for q in s["questions"]]
    assert len(questions) >= 4, "a rehearsal a client watches must not be one or two questions"
    for q in questions:
        assert q["text"] and q["probing_instructions"] and q["evasion_signals"], \
            "every question must give the elaboration press something to press on"

    spoken = json.dumps(script)
    assert "Patrick" not in spoken, "the rehearsal must not greet everyone by one person's name"
    assert "FutureEdge" not in spoken, "the rehearsal must not name the consultancy to a client"


def test_the_default_script_loads_from_any_working_directory(tmp_path):
    """Driven in a subprocess with `cwd` elsewhere, which a same-process test cannot see.

    CLAUDE.md records four tests that read a bare relative `Path("projects/sp-gs-am/outputs/...")`
    and are dark whenever pytest is started from anywhere but the repository root. A fixture
    resolved from `__file__` cannot have that defect, and this is what establishes it rather than
    describing it - a relative `Path("api/fixtures/...")` passes every other test in this file.
    """
    repo = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        [sys.executable, "-c",
         "from api.services.rehearsal_script import default_rehearsal_script;"
         " print(default_rehearsal_script()['node_label'])"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        env={**os.environ, "PYTHONPATH": str(repo)},
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip(), "the fixture answered nothing from another directory"


@pytest.mark.asyncio
async def test_the_rehearsal_door_serves_the_committed_script(client):
    """The door, over HTTP, with nothing in `projects/` at all.

    Asserted on the **served body**, not on the status: a 200 carrying an empty object would
    satisfy a status-only assertion and would be a rehearsal that opens and asks nothing. This
    is the arm the old door failed, and it failed it by answering 404.
    """
    res = await client.get(SCRIPT_DOOR)
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["sections"], "the script reached the dialog with no questions in it"
    assert body["welcome_message"] == default_rehearsal_script()["welcome_message"]
    questions = [q for s in body["sections"] for q in s["questions"]]
    assert len(questions) >= 4


@pytest.mark.asyncio
async def test_the_door_does_not_depend_on_the_projects_directory(client, tmp_path, monkeypatch):
    """`PROJECTS_DIR` pointed somewhere empty, which is the state that broke it.

    The archival of `smoke-test` is exactly this: a `projects/` directory with nothing the door
    needs in it. Driven rather than argued, because the whole point of the repair is that this
    case is now indistinguishable from any other.
    """
    get_settings.cache_clear()
    monkeypatch.setenv("PROJECTS_DIR", str(tmp_path / "no-projects-here"))
    try:
        res = await client.get(SCRIPT_DOOR)
        assert res.status_code == 200, res.text
        assert res.json()["sections"]
    finally:
        get_settings.cache_clear()


@pytest.mark.asyncio
async def test_an_unreadable_fixture_is_a_five_hundred_and_not_a_four_oh_four(
    client, monkeypatch
):
    """The status carries the diagnosis, and 404 sent people to the wrong place for months.

    A missing committed fixture is a broken deployment. 404 reads as "this engagement has not
    produced a script yet", which is what sent whoever hit the old door to run `discovery_mapping`
    on an archived project.
    """
    monkeypatch.setattr(
        "api.routers.interviews.default_rehearsal_script",
        lambda: (_ for _ in ()).throw(RehearsalScriptUnavailable("gone")),
    )
    res = await client.get(SCRIPT_DOOR)
    assert res.status_code == 500, res.text
    assert res.status_code != 404
