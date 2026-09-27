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

The second half of this file is the choice: the default, or one of this project's own active
scripts. Its two properties are asserted where they hold rather than one layer away - the
retirement filter on the **serve** door as well as on the list, since a rule enforced only in the
dropdown is a rule a hand-built URL walks past.

And the serve door gained a slug, which CLAUDE.md says means it gained a floor in the same change
- invisible to the route sweep, which is keyed on `{slug}` in the *path* and this one takes it as
a query parameter. The floor is driven over HTTP with a real administrator of a *different*
engagement, which is the caller an "anonymous is refused" test would have passed before the fix.
"""
import ast
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from api.auth import create_access_token
from api.config import get_settings
from api.database import (
    get_connection,
    get_system_connection,
    insert_organisation,
    insert_project,
    insert_project_registry,
)
from api.services.rehearsal_script import (
    RehearsalScriptUnavailable,
    ScriptNotOffered,
    default_rehearsal_script,
    project_rehearsal_script,
    rehearsal_script_options,
)

SCRIPT_DOOR = "/api/interviews/test/script"
OPTIONS_DOOR = "/api/interviews/test/script-options"

# Labels chosen to be visibly unlike anything in the committed fixture or in any project's real
# data, so an assertion on one cannot pass because a default happened to match. CLAUDE.md records
# the inverse - a sentinel drawn from the system's own defaults cannot fail - found on this very
# door's neighbour, where the end-to-end test asserted on a string that *was*
# `agent_defaults("stakeholder_interviewer")["image_url"]`.
CHOSEN_LABEL = "Zephyr Chosen Interview - Market Development"
RETIRED_LABEL = "Quondam Retired Interview - Do Not Offer"


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
    res = await client.get(SCRIPT_DOOR, params={"slug": "rehearsal-any"})
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
        res = await client.get(SCRIPT_DOOR, params={"slug": "rehearsal-any"})
        assert res.status_code == 200, res.text
        assert res.json()["sections"]
    finally:
        get_settings.cache_clear()


@pytest.mark.asyncio
async def test_an_unreadable_fixture_is_a_five_hundred_and_not_a_four_oh_four(
    client, monkeypatch
):
    """The status carries the diagnosis, and 404 sent people to the wrong place.

    A missing committed fixture is a broken deployment. 404 reads as "this engagement has not
    produced a script yet", which is what sent whoever hit the old door to run `discovery_mapping`
    on an archived project.
    """
    monkeypatch.setattr(
        "api.routers.interviews.default_rehearsal_script",
        lambda: (_ for _ in ()).throw(RehearsalScriptUnavailable("gone")),
    )
    res = await client.get(SCRIPT_DOOR, params={"slug": "rehearsal-any"})
    assert res.status_code == 500, res.text
    assert res.status_code != 404


# --- Seeding a project's own scripts --------------------------------------------------------


async def _make_project(slug: str) -> int:
    async with get_connection(slug) as conn:
        await insert_project(
            conn, slug=slug, llm_mode="standard", sector="test", config_json="{}"
        )
        async with conn.execute("SELECT id FROM projects WHERE slug=?", (slug,)) as cur:
            return (await cur.fetchone())["id"]


def _script(script_id: str, label: str, question: str) -> dict:
    return {
        "script_id": script_id,
        "node_id": "1.1",
        "node_label": label,
        "study_objectives": [],
        "welcome_message": f"Welcome to {label}.",
        "closing_message": f"Thank you, that was {label}.",
        "sections": [
            {
                "title": "Only Section",
                "questions": [
                    {
                        "id": "Q1",
                        "text": question,
                        "follow_up_count": 0,
                        "probing_instructions": "Probe.",
                        "follow_up_branches": [],
                        "evasion_signals": [],
                    }
                ],
            }
        ],
    }


async def _seed_scripts(slug: str, project_id: int, scripts: dict, *, active: dict[str, int]):
    """Write an `interview_scripts` artefact and its ledger rows, through the real resolution.

    The artefact is registered in `agent_outputs` with the ledger's own columns rather than
    dropped on disk under a guessed filename, because `current_output_path` - which the code
    under test uses, and must - asks the ledger and not the disk. A fixture that wrote the file
    alone would pass against a reader that globbed, which is the reader this codebase has four
    recorded incidents from.
    """
    outputs = Path(get_settings().projects_dir) / slug / "outputs"
    outputs.mkdir(parents=True, exist_ok=True)
    path = outputs / "interview_scripts_v1.json"
    path.write_text(json.dumps(scripts))

    async with get_connection(slug) as conn:
        await conn.execute(
            "INSERT INTO agent_outputs (project_id, agent_name, output_type, file_path,"
            " version, review_status) VALUES (?,?,?,?,?,?)",
            (project_id, "interaction_designer", "interview_scripts", str(path), 1, "pending"),
        )
        for script_id, body in scripts.items():
            await conn.execute(
                "INSERT INTO interview_script_ledger"
                " (script_id, project_id, node_id, node_label, active, review_status,"
                "  last_version) VALUES (?,?,?,?,?,?,?)",
                (
                    script_id,
                    project_id,
                    body.get("node_id", "1"),
                    body.get("node_label", ""),
                    active.get(script_id, 1),
                    "pending",
                    1,
                ),
            )
        await conn.commit()


@pytest.fixture
def isolated(tmp_path, monkeypatch):
    """A private DATABASE_DIR and PROJECTS_DIR, per CLAUDE.md's poisoned-database rule.

    Both, not only the first: the service reads the ledger out of `DATABASE_DIR` and the artefact
    out of `PROJECTS_DIR`, and CLAUDE.md records five tests catalogued for weeks as product
    defects which turned out to be three test files hardcoding one of these while the code under
    test read the other.
    """
    get_settings.cache_clear()
    monkeypatch.setenv("DATABASE_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("PROJECTS_DIR", str(tmp_path / "projects"))
    (tmp_path / "data").mkdir(parents=True, exist_ok=True)
    (tmp_path / "projects").mkdir(parents=True, exist_ok=True)
    yield tmp_path
    get_settings.cache_clear()


@pytest_asyncio.fixture
async def project_with_scripts(isolated):
    """One active script and one retired one, both in the current artefact and both in the ledger.

    Both halves in one fixture on purpose: CLAUDE.md's rule is that either half of "a retired
    script is not offered, and an active one is" passes alone - the first against a list that
    shows nothing, the second against a list that shows everything.
    """
    slug = "rehearsal-chooser"
    project_id = await _make_project(slug)
    scripts = {
        "SC-001": _script("SC-001", CHOSEN_LABEL, "Where does growth come from?"),
        "SC-002": _script("SC-002", RETIRED_LABEL, "This question must never be asked."),
    }
    await _seed_scripts(slug, project_id, scripts, active={"SC-001": 1, "SC-002": 0})
    return slug


# --- The choice ----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_the_default_is_offered_to_a_project_with_no_scripts_at_all(isolated, client):
    """A fresh engagement has no scripts, and the rehearsal must not require Maya to have run.

    Both doors, because they fail differently: the list would 404 on a missing ledger and the
    serve door would 500 on a missing artefact, and either would take the rehearsal down on every
    engagement that has not reached the mapping stage - which is all of them at the point where
    somebody most wants to hear what an interview sounds like.
    """
    slug = "rehearsal-fresh"
    await _make_project(slug)

    options = await client.get(OPTIONS_DOOR, params={"slug": slug})
    assert options.status_code == 200, options.text
    assert options.json() == {"scripts": []}, "a project with no scripts offers none"

    res = await client.get(SCRIPT_DOOR, params={"slug": slug})
    assert res.status_code == 200, res.text
    assert res.json()["welcome_message"] == default_rehearsal_script()["welcome_message"]


@pytest.mark.asyncio
async def test_a_retired_script_is_not_offered_and_an_active_one_is(project_with_scripts, client):
    """The filter, both ways, on the list door.

    The control is the point. A `rehearsal_script_options` that answered `[]` for everything would
    pass the retirement half perfectly, and one that answered every row would pass the
    availability half.
    """
    res = await client.get(OPTIONS_DOOR, params={"slug": project_with_scripts})
    assert res.status_code == 200, res.text
    offered = res.json()["scripts"]

    assert [s["script_id"] for s in offered] == ["SC-001"]
    assert offered[0]["node_label"] == CHOSEN_LABEL
    assert offered[0]["review_status"] == "pending", \
        "the state is shown so the choice is informed - the list is not approved-only"
    assert RETIRED_LABEL not in json.dumps(offered)


@pytest.mark.asyncio
async def test_the_serve_door_refuses_a_retired_script_too(project_with_scripts, client):
    """Not only absent from the dropdown - refused when named.

    CLAUDE.md's recurring failure mode is a property verified one layer away from where it holds.
    A retirement rule enforced in the list alone is enforced in the one place a hand-built URL
    does not go through, and the active control beside it is what stops this passing against a
    door that refuses every id.
    """
    res = await client.get(
        SCRIPT_DOOR, params={"slug": project_with_scripts, "script_id": "SC-002"}
    )
    assert res.status_code == 404, res.text
    assert RETIRED_LABEL not in res.text, "the refusal disclosed the retired script's label"

    ok = await client.get(
        SCRIPT_DOOR, params={"slug": project_with_scripts, "script_id": "SC-001"}
    )
    assert ok.status_code == 200, ok.text


@pytest.mark.asyncio
async def test_the_chosen_script_is_the_one_served(project_with_scripts, client):
    """The chosen id decides the body, and the default is not silently substituted.

    Asserted on the question text - what the rehearsal would actually ask - rather than on an id
    echoed back, which a handler ignoring `script_id` entirely would still return correctly if it
    echoed the parameter it was given.
    """
    res = await client.get(
        SCRIPT_DOOR, params={"slug": project_with_scripts, "script_id": "SC-001"}
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["node_label"] == CHOSEN_LABEL
    questions = [q["text"] for s in body["sections"] for q in s["questions"]]
    assert questions == ["Where does growth come from?"]
    assert body["welcome_message"] != default_rehearsal_script()["welcome_message"], \
        "the chosen script was ignored and the committed default served instead"


@pytest.mark.asyncio
async def test_an_unknown_script_id_is_refused_rather_than_falling_back(
    project_with_scripts, client
):
    """404, never the default.

    Falling back would make a typo in a script id indistinguishable from a deliberate choice of
    the sample: the consultant would rehearse the wrong instrument and be told nothing.
    """
    res = await client.get(
        SCRIPT_DOOR, params={"slug": project_with_scripts, "script_id": "SC-999"}
    )
    assert res.status_code == 404, res.text


@pytest.mark.asyncio
async def test_a_registered_script_missing_from_the_artefact_is_not_offered(isolated, client):
    """The ledger says what may be rehearsed; the artefact says what can be.

    An option that 404s when clicked is worse than an option that is absent, and the two tables
    are free to disagree - a ledger row is permanent by design while the artefact is rewritten on
    every run and repointed by a revert.
    """
    slug = "rehearsal-gap"
    project_id = await _make_project(slug)
    scripts = {"SC-001": _script("SC-001", CHOSEN_LABEL, "Where does growth come from?")}
    await _seed_scripts(slug, project_id, scripts, active={"SC-001": 1})
    async with get_connection(slug) as conn:
        await conn.execute(
            "INSERT INTO interview_script_ledger"
            " (script_id, project_id, node_id, node_label, active) VALUES (?,?,?,?,1)",
            ("SC-777", project_id, "9.9", "Phantom Interview"),
        )
        await conn.commit()

    offered = (await client.get(OPTIONS_DOOR, params={"slug": slug})).json()["scripts"]
    assert [s["script_id"] for s in offered] == ["SC-001"]

    res = await client.get(SCRIPT_DOOR, params={"slug": slug, "script_id": "SC-777"})
    assert res.status_code == 404, res.text


# --- The floor the slug brought with it -----------------------------------------------------


@pytest_asyncio.fixture
async def two_engagements(isolated, client):
    """Two projects owned by two organisations, and a real org_admin of each.

    The stranger is a legitimate administrator of a *different* engagement, which is the caller
    that matters: a test driving an anonymous request passes against a door with no floor at all,
    because `require_any_auth` refuses it either way. CLAUDE.md names this exact substitution in
    its account of `tests/test_milestone_door_authority.py`.
    """
    owned, foreign = "rehearsal-owned", "rehearsal-foreign"
    owned_id = await _make_project(owned)
    await _make_project(foreign)

    scripts = {"SC-001": _script("SC-001", CHOSEN_LABEL, "Where does growth come from?")}
    await _seed_scripts(owned, owned_id, scripts, active={"SC-001": 1})

    async with get_system_connection() as sys_conn:
        org_a = await insert_organisation(sys_conn, slug="rehearsal-org-a", name="A")
        org_b = await insert_organisation(sys_conn, slug="rehearsal-org-b", name="B")
        await insert_project_registry(
            sys_conn, slug=owned, org_id=org_a, display_name=owned
        )
        await insert_project_registry(
            sys_conn, slug=foreign, org_id=org_b, display_name=foreign
        )
        await sys_conn.commit()

    def _client_for(username: str, org_id: int) -> AsyncClient:
        from api.main import app

        token = create_access_token(username, "org_admin", "test-secret", org_id=org_id)
        return AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
            headers={"Authorization": f"Bearer {token}"},
        )

    owner = _client_for("rehearsal-admin-a", org_a)
    stranger = _client_for("rehearsal-admin-b", org_b)
    async with owner, stranger:
        yield {"slug": owned, "owner": owner, "stranger": stranger}


@pytest.mark.asyncio
async def test_a_foreign_org_admin_is_refused_both_rehearsal_doors(two_engagements):
    """The floor, on both doors and on both arms of the serve door.

    The **default arm is driven as well as the chosen one**, and it is the one that matters: the
    slug decides nothing about which script that arm serves, so it is the arm somebody would
    reasonably leave unscoped - and leaving it unscoped is a door that answers a stranger 200 and
    confirms the slug exists.

    The refusals are asserted **on the wire** and not only on the status. CLAUDE.md records the
    sibling `speak` door for exactly this: a check moved to after the work still answers 403, so a
    status-only test passes a door that assembles the private thing and then refuses.
    """
    slug = two_engagements["slug"]
    stranger, owner = two_engagements["stranger"], two_engagements["owner"]

    for params in ({"slug": slug}, {"slug": slug, "script_id": "SC-001"}):
        refused = await stranger.get(SCRIPT_DOOR, params=params)
        assert refused.status_code == 403, f"{params} -> {refused.status_code} {refused.text}"
        assert CHOSEN_LABEL not in refused.text

    refused = await stranger.get(OPTIONS_DOOR, params={"slug": slug})
    assert refused.status_code == 403, refused.text
    assert CHOSEN_LABEL not in refused.text, \
        "the list was assembled and then refused - the label crossed the wire"

    # The control: the same three requests from the engagement's own administrator succeed, so the
    # refusals above are about authority rather than a door that refuses everybody.
    assert (await owner.get(SCRIPT_DOOR, params={"slug": slug})).status_code == 200
    served = await owner.get(SCRIPT_DOOR, params={"slug": slug, "script_id": "SC-001"})
    assert served.status_code == 200, served.text
    assert served.json()["node_label"] == CHOSEN_LABEL
    offered = await owner.get(OPTIONS_DOOR, params={"slug": slug})
    assert offered.status_code == 200 and offered.json()["scripts"]


@pytest.mark.asyncio
async def test_both_doors_refuse_a_request_with_no_slug(isolated, client):
    """422, matching the two sibling test doors rather than inventing a third convention.

    An optional slug is a slug a caller omits, and on this door the slug *is* the floor.
    """
    for door in (SCRIPT_DOOR, OPTIONS_DOOR):
        assert (await client.get(door)).status_code == 422, door
        assert (await client.get(door, params={"slug": ""})).status_code == 422, door


# --- The service, driven directly ----------------------------------------------------------


@pytest.mark.asyncio
async def test_the_options_never_raise_for_a_project_that_does_not_exist(isolated):
    """`[]`, not an exception. The committed default must stay rehearsable regardless.

    Driven at the service rather than the door because the door refuses an unknown slug first:
    the property is about the reader being defensive, which is what keeps a missing ledger table
    from costing somebody their rehearsal.
    """
    assert await rehearsal_script_options("no-such-engagement") == []


@pytest.mark.asyncio
async def test_choosing_a_script_on_a_project_that_has_none_is_refused(isolated):
    """The narrow direction. `ScriptNotOffered`, never the default and never a KeyError."""
    slug = "rehearsal-empty"
    await _make_project(slug)
    with pytest.raises(ScriptNotOffered):
        await project_rehearsal_script(slug, "SC-001")
