# tests/test_bulk_script_sendback.py
"""The bulk script send-back door: what reaches Maya, what it refuses, and what it counts.

Maya's prompt was corrected in 8be5f373 after a real interview on 17 September found two
defects in the instrument - a pre-written synthesis spoken as if it had been derived from the
conversation, and a closing that promised the interviewee's words would reach the board
"unfiltered" with no confidentiality statement anywhere. SC-013 was sent back singly and run
38 regenerated it; eighty-five scripts still carry the old closing, and the only route to
correcting them was eighty-five calls to the singular door, each firing its own notification.

**The assertion this file exists for is the first one.** A send-back that is recorded,
visible on the ledger endpoint, and notified can still never reach the agent:
`scripts_awaiting_regeneration` compares `last_version <= reviewed_at_version`, and
`last_version` is NULL on every row `script_ledger_backfill.py` wrote, because the JSON
registry it loaded predates per-batch versioning. `NULL <= 0` is NULL rather than true, so
those rows failed the WHERE clause silently. The live `sp-gs-am` ledger is 83 such rows out
of 86 - so the fixtures here are written in the backfilled shape deliberately, and every
assertion about "the note reached Maya" is made on what the *run* reads, never on the door's
own 200.

The authority test is driven over HTTP with real callers, per
tests/test_milestone_door_authority.py: a login with no membership, a member with no content
role, and a reviewer, so each refusal is attributable to one gate.
"""
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from api.auth import create_access_token
from api.config import get_settings
from api.database import (
    fetch_project,
    fetch_user,
    get_connection,
    get_system_connection,
    insert_stakeholder,
    insert_user,
    link_membership,
)
from api.services.script_review_service import scripts_awaiting_regeneration

SLUG = "bulk-sendback-test"
BULK = f"/projects/{SLUG}/script-ledger/review-batch"

# Refusal sentences, asserted rather than merely intended: a caller refused by two gates at
# once tells you nothing about either.
NOT_PERMITTED = "Not permitted to review scripts on this project"
ACCESS_DENIED = "Access denied to this project"


async def _seed(slug: str, script_ids, *, versioned=()):
    """A project, a reviewer, and one ledger row per id in the backfilled shape.

    `last_version` is deliberately omitted - the column has no default, so the row lands with
    NULL exactly as script_ledger_backfill.py leaves it. Ids named in `versioned` get a real
    version instead, so a test can tell the two shapes apart when it needs to.
    """
    async with get_connection(slug) as conn:
        await conn.execute("INSERT INTO projects (slug) VALUES (?)", (slug,))
        await conn.commit()
        cur = await conn.execute("SELECT id FROM projects WHERE slug=?", (slug,))
        project_id = (await cur.fetchone())["id"]
        await conn.execute(
            "INSERT INTO stakeholders (project_id, name, email, is_reviewer)"
            " VALUES (?, 'Priya Raman', 'priya.raman@example.test', 1)",
            (project_id,),
        )
        for n, script_id in enumerate(script_ids):
            if script_id in versioned:
                await conn.execute(
                    "INSERT INTO interview_script_ledger"
                    " (script_id, project_id, node_id, node_label, last_version, last_author)"
                    " VALUES (?,?,?,?,?, 'maya')",
                    (script_id, project_id, f"1.{n}", f"Activity {n}", 7),
                )
            else:
                await conn.execute(
                    "INSERT INTO interview_script_ledger"
                    " (script_id, project_id, node_id, node_label, last_author)"
                    " VALUES (?,?,?,?, 'maya')",
                    (script_id, project_id, f"1.{n}", f"Activity {n}"),
                )
        await conn.commit()
        return project_id


@pytest_asyncio.fixture
async def ledger(tmp_path, monkeypatch):
    """Three backfilled scripts on their own database, isolated from the shared /tmp path.

    DATABASE_DIR is redirected at this test's own tmp_path rather than relying on unlinking
    the file: conftest points it at a persistent directory, and these fixtures insert by a
    fixed script_id, which passes once and fails on every run afterwards.
    """
    monkeypatch.setenv("DATABASE_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("PROJECTS_DIR", str(tmp_path / "projects"))
    (tmp_path / "data").mkdir(parents=True, exist_ok=True)
    (tmp_path / "projects").mkdir(parents=True, exist_ok=True)
    get_settings.cache_clear()

    project_id = await _seed(SLUG, ["SC-001", "SC-002", "SC-003"])
    yield SLUG, project_id

    get_settings.cache_clear()


def _reviewer():
    """Grant the content role without wiring a login - the walk is tested separately below.

    Patched where the name is looked up, `api.routers.script_reviews`, because the router
    binds its own reference with `from ... import`. The gate is `caller_may_contribute` and
    not `caller_roles`: this door asks the rule by its name rather than restating
    `{reviewer, approver}`, so that is the seam a stub has to land on.
    """
    return patch(
        "api.routers.script_reviews.caller_may_contribute", new=AsyncMock(return_value=True)
    )


def _no_mail():
    """Stub the notifier where the router looks it up, so nothing composes a real email.

    Patched on the service module because the router imports it inside the handler body, so
    the lookup happens at call time against `api.services.commit_notify_service`.
    """
    return patch(
        "api.services.commit_notify_service.notify_scripts_sent_back", new=AsyncMock()
    )


async def _pending(slug, project_id):
    async with get_connection(slug) as conn:
        return await scripts_awaiting_regeneration(conn, project_id=project_id)


# ---------------------------------------------------------------------------
# The assertion this door exists for.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_bulk_send_back_reaches_maya_on_backfilled_rows(client, ledger):
    """The note reaches the agent, asserted on what the run reads and not on the door's 200.

    Every row here has `last_version` NULL, which is the shape 83 of the live ledger's 86 rows
    are in. Before the COALESCE repair this call would have answered 200, written three review
    events, updated three ledger rows, and put nothing whatever in Maya's prompt. Asserting on
    the response would not have distinguished the two.
    """
    slug, project_id = ledger
    with _reviewer(), _no_mail():
        r = await client.post(BULK, json={
            "script_ids": ["SC-001", "SC-002", "SC-003"],
            "decision": "changes_requested",
            "return_to": "agent",
            "notes": "the closing promises the board hears them unfiltered - remove it",
        })
    assert r.status_code == 200, r.text

    pending = await _pending(slug, project_id)
    assert {p["script_id"] for p in pending} == {"SC-001", "SC-002", "SC-003"}
    assert all("unfiltered" in p["notes"] for p in pending)


@pytest.mark.asyncio
async def test_the_note_reaches_the_prompt_the_crew_is_actually_given(client, ledger):
    """One layer further out: not the query, but the block run_service injects into Maya.

    `scripts_awaiting_regeneration` having the rows and the prompt naming them are two
    different claims, and this project has repeatedly asserted the first while shipping a
    defect in the second. `_fetch_regeneration_requests` is what calls it.
    """
    slug, _ = ledger
    from api.services.run_service import _fetch_regeneration_requests

    with _reviewer(), _no_mail():
        r = await client.post(BULK, json={
            "script_ids": ["SC-001", "SC-002"],
            "decision": "changes_requested",
            "return_to": "agent",
            "notes": "add a confidentiality statement to the closing",
        })
    assert r.status_code == 200, r.text

    block = await _fetch_regeneration_requests(slug, "assessment_design")
    assert "SC-001" in block and "SC-002" in block
    assert "confidentiality" in block
    # SC-003 was not in the batch and must not be swept in.
    assert "SC-003" not in block


@pytest.mark.asyncio
async def test_a_send_back_to_reviewers_does_not_reach_the_agent(client, ledger):
    """return_to='reviewer' is a human-to-human loop. The door accepts it; Maya never sees it.

    Without this, a door that ignored `return_to` and always wrote 'agent' would pass every
    other test in this file.
    """
    slug, project_id = ledger
    with _reviewer(), _no_mail():
        r = await client.post(BULK, json={
            "script_ids": ["SC-001", "SC-002"],
            "decision": "changes_requested",
            "return_to": "reviewer",
            "notes": "please re-read these",
        })
    assert r.status_code == 200, r.text
    assert r.json()["sent_back"] == 2
    assert await _pending(slug, project_id) == []


# ---------------------------------------------------------------------------
# What the door refuses, and the control that proves it does not refuse everything.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("decision", ["approved", "reviewed", "edited"])
async def test_only_changes_requested_may_be_recorded_in_bulk(client, ledger, decision):
    """Approval is the deliberate act the gate exists to protect, and the other two are worse
    than they look: `review_count` excludes only 'approved', so a bulk 'reviewed' would
    satisfy the not-yet-reviewed gate on every script at once - the same click-through,
    arriving through a door that never mentions approval.
    """
    slug, project_id = ledger
    with _reviewer(), _no_mail():
        r = await client.post(BULK, json={
            "script_ids": ["SC-001"], "decision": decision, "return_to": "agent",
        })
    assert r.status_code == 422, r.text
    assert decision in r.json()["detail"]

    # Nothing was written - a refusal that still recorded the review would be worse than none.
    async with get_connection(slug) as conn:
        cur = await conn.execute(
            "SELECT COUNT(*) FROM script_reviews WHERE project_id=?", (project_id,))
        assert (await cur.fetchone())[0] == 0


@pytest.mark.asyncio
async def test_changes_requested_still_works(client, ledger):
    """The control. Without it a door that refused every decision would pass the test above."""
    slug, project_id = ledger
    with _reviewer(), _no_mail():
        r = await client.post(BULK, json={
            "script_ids": ["SC-001"], "decision": "changes_requested", "return_to": "agent",
            "notes": "n",
        })
    assert r.status_code == 200, r.text
    assert r.json()["sent_back"] == 1
    assert [p["script_id"] for p in await _pending(slug, project_id)] == ["SC-001"]


@pytest.mark.asyncio
@pytest.mark.parametrize("return_to", [None, "", "maya", "agents"])
async def test_a_send_back_must_name_its_target(client, ledger, return_to):
    """Both defaults are wrong - to the agent it rewrites an instrument a reviewer is about to
    re-read, to the reviewer it silently drops a request for regeneration. Refused at the door
    rather than per item, so the whole request fails once instead of eighty-five times.
    """
    with _reviewer(), _no_mail():
        r = await client.post(BULK, json={
            "script_ids": ["SC-001"], "decision": "changes_requested", "return_to": return_to,
        })
    assert r.status_code == 422, r.text


@pytest.mark.asyncio
async def test_an_empty_batch_is_refused(client, ledger):
    """An explicit list is the whole safety property of this door - the blast radius must be
    visible in the request. An empty one is a caller that has not said what it means."""
    with _reviewer(), _no_mail():
        r = await client.post(BULK, json={
            "script_ids": [], "decision": "changes_requested", "return_to": "agent",
        })
    assert r.status_code == 422, r.text


# ---------------------------------------------------------------------------
# Per-item outcomes.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_mixed_batch_lands_the_good_ids_and_reports_the_rest(client, ledger):
    """All-or-nothing means one stale id blocks a correction of eighty-five; silent partial
    success is worse than either.

    The valid id landing is asserted through the run's own query, not through the response -
    a loop that aborted on the first bad id would report the rest as untouched and look
    entirely correct from its status code.
    """
    slug, project_id = ledger
    with _reviewer(), _no_mail():
        r = await client.post(BULK, json={
            # The unknown id sits *first*, so a loop that aborts on the first failure loses
            # everything after it.
            "script_ids": ["SC-404", "SC-001", "SC-001", "SC-003"],
            "decision": "changes_requested", "return_to": "agent", "notes": "fix the closing",
        })
    assert r.status_code == 200, r.text
    body = r.json()

    # One outcome per entry in the request, in the order asked - so the response can be
    # checked against the request without having to reconstruct which ids were collapsed.
    assert [x["script_id"] for x in body["results"]] == \
        ["SC-404", "SC-001", "SC-001", "SC-003"]
    assert [x["status"] for x in body["results"]] == \
        ["not_found", "sent_back", "duplicate", "sent_back"]
    assert body["sent_back"] == 2

    assert {p["script_id"] for p in await _pending(slug, project_id)} == {"SC-001", "SC-003"}

    # The duplicate recorded one review event, not two.
    async with get_connection(slug) as conn:
        cur = await conn.execute(
            "SELECT COUNT(*) FROM script_reviews WHERE project_id=? AND script_id='SC-001'",
            (project_id,))
        assert (await cur.fetchone())[0] == 1


@pytest.mark.asyncio
async def test_a_failure_part_way_through_does_not_lose_the_rest(client, ledger):
    """The loop's resilience, driven rather than reasoned about.

    `record_script_review` raises nothing reachable for `changes_requested` -
    AlreadyApprovedError and NotYetReviewedError both fire only on `approved`, which this door
    refuses - so the classification branch is defence against that function's refusals
    widening, and cannot be reached by a request. It is driven here by making the shared
    service raise for one id, which is the property that actually matters: a mid-batch failure
    is reported and the ids after it still land.
    """
    slug, project_id = ledger
    from api.services import script_review_service

    real = script_review_service.record_script_review

    async def flaky(conn, *, script_id, **kw):
        if script_id == "SC-002":
            raise ValueError("no ledger row for script_id 'SC-002'")
        return await real(conn, script_id=script_id, **kw)

    with _reviewer(), _no_mail(), patch(
        "api.routers.script_reviews.record_script_review", new=flaky
    ):
        r = await client.post(BULK, json={
            "script_ids": ["SC-001", "SC-002", "SC-003"],
            "decision": "changes_requested", "return_to": "agent", "notes": "fix the closing",
        })
    assert r.status_code == 200, r.text
    assert [x["status"] for x in r.json()["results"]] == ["sent_back", "refused", "sent_back"]
    assert {p["script_id"] for p in await _pending(slug, project_id)} == {"SC-001", "SC-003"}


# ---------------------------------------------------------------------------
# The backlog, which is the number that decides whether the next run finishes.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_the_answer_reports_the_whole_backlog_and_not_just_this_call(client, ledger):
    """Run 32 wrote 41 scripts, hit CrewAI's default max_iter before its ledger write, and
    reported `completed` - so a run asked to regenerate more than it finishes is a known
    failure of this system, not a hypothetical one.

    The number that decides whether the next run finishes is the *total* awaiting
    regeneration, including send-backs from earlier calls nobody has regenerated. Two calls of
    two would each look modest while producing one run of four, which is why this is asserted
    across two calls rather than on one.
    """
    slug, _ = ledger
    with _reviewer(), _no_mail():
        first = await client.post(BULK, json={
            "script_ids": ["SC-001"], "decision": "changes_requested",
            "return_to": "agent", "notes": "fix the closing",
        })
        second = await client.post(BULK, json={
            "script_ids": ["SC-002", "SC-003"], "decision": "changes_requested",
            "return_to": "agent", "notes": "fix the closing",
        })
    assert first.json()["sent_back"] == 1
    assert first.json()["awaiting_regeneration"] == 1
    # The second call added two and must report three, not two.
    assert second.json()["sent_back"] == 2
    assert second.json()["awaiting_regeneration"] == 3


@pytest.mark.asyncio
async def test_the_backlog_reported_is_the_backlog_the_run_will_be_given(client, ledger):
    """The count is read from the same function the run reads, so it cannot drift from it.

    A separately-computed count - a `len(sent_back)` plus a stored total, say - would be a
    second declaration of one number, free to fall behind. Asserted as equality with what
    `_fetch_regeneration_requests` actually names, since that is the claim being made to the
    operator: this is how many scripts the next run is being asked to rewrite.
    """
    slug, _ = ledger
    from api.services.run_service import _fetch_regeneration_requests

    with _reviewer(), _no_mail():
        r = await client.post(BULK, json={
            "script_ids": ["SC-001", "SC-002", "SC-003"],
            "decision": "changes_requested", "return_to": "agent", "notes": "fix the closing",
        })
    reported = r.json()["awaiting_regeneration"]
    block = await _fetch_regeneration_requests(slug, "assessment_design")
    named = [ln for ln in block.splitlines() if ln.startswith("- ")]
    assert reported == len(named) == 3


@pytest.mark.asyncio
async def test_a_send_back_to_reviewers_is_not_counted_as_backlog(client, ledger):
    """The backlog is what Maya is owed, so a human-to-human return must not inflate it -
    otherwise the one number an operator uses to judge the risk of a run counts work no run
    will do."""
    with _reviewer(), _no_mail():
        r = await client.post(BULK, json={
            "script_ids": ["SC-001", "SC-002"], "decision": "changes_requested",
            "return_to": "reviewer", "notes": "please re-read",
        })
    assert r.json()["sent_back"] == 2
    assert r.json()["awaiting_regeneration"] == 0


# ---------------------------------------------------------------------------
# One notification for the batch.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_one_notification_for_the_whole_batch(client, ledger):
    """Counted, not merely observed to have happened. Eighty-five notifications is the defect
    this door exists to remove, and a notifier called inside the loop would reintroduce it
    while passing any assertion of the form "a notification was sent"."""
    with _reviewer(), patch(
        "api.services.commit_notify_service.notify_scripts_sent_back", new=AsyncMock()
    ) as notify:
        r = await client.post(BULK, json={
            "script_ids": ["SC-001", "SC-002", "SC-003"],
            "decision": "changes_requested", "return_to": "agent", "notes": "fix the closing",
        })
    assert r.status_code == 200, r.text
    assert notify.await_count == 1
    assert notify.await_args.args[1] == ["SC-001", "SC-002", "SC-003"]


@pytest.mark.asyncio
async def test_nothing_is_announced_when_nothing_landed(client, ledger):
    """A batch of entirely unknown ids notifies nobody. A notification whose body names no
    script sends a reviewer to a ledger to look for a change that was never made."""
    with _reviewer(), patch(
        "api.services.commit_notify_service.notify_scripts_sent_back", new=AsyncMock()
    ) as notify:
        r = await client.post(BULK, json={
            "script_ids": ["SC-404", "SC-405"], "decision": "changes_requested",
            "return_to": "agent", "notes": "fix the closing",
        })
    assert r.status_code == 200, r.text
    assert notify.await_count == 0


@pytest.mark.asyncio
async def test_a_failed_notification_does_not_undo_a_recorded_send_back(client, ledger):
    """The notification is outside the transaction with its own guard, as the singular door's
    is: a failed notification must not turn eighty-five recorded send-backs into a 500 and an
    operator who does not know whether to retry."""
    slug, project_id = ledger
    with _reviewer(), patch(
        "api.services.commit_notify_service.notify_scripts_sent_back",
        new=AsyncMock(side_effect=RuntimeError("resend is down")),
    ):
        r = await client.post(BULK, json={
            "script_ids": ["SC-001"], "decision": "changes_requested",
            "return_to": "agent", "notes": "fix the closing",
        })
    assert r.status_code == 200, r.text
    assert [p["script_id"] for p in await _pending(slug, project_id)] == ["SC-001"]


@pytest.mark.asyncio
async def test_the_notification_body_names_the_batch_and_links_to_a_real_crew(client, ledger):
    """The notifier driven for real, with only the mail seam stubbed.

    Every existing test of `notify_script_sent_back` patched it out, which is why the line
    building the link had never run and shipped `?crew=SC-014` - a crew that does not exist.
    Its bulk sibling would have taken the same route, so it is driven here instead of mocked.
    """
    from urllib.parse import parse_qs, urlparse

    from api.services.commit_notify_service import LEDGER_CREW

    with _reviewer(), patch(
        "api.services.commit_notify_service.send_project_mail", new=AsyncMock()
    ) as send:
        r = await client.post(BULK, json={
            "script_ids": ["SC-001", "SC-002"], "decision": "changes_requested",
            "return_to": "agent", "notes": "remove the unfiltered promise",
        })
    assert r.status_code == 200, r.text
    send.assert_awaited_once()

    kwargs = send.await_args.kwargs
    assert "2" in kwargs["subject"]
    assert "SC-001" in kwargs["body"] and "SC-002" in kwargs["body"]
    assert "remove the unfiltered promise" in kwargs["body"]

    link = [ln for ln in kwargs["body"].splitlines() if "http" in ln][0]
    crew = parse_qs(urlparse(link.split()[-1]).query)["crew"][0]
    assert crew == LEDGER_CREW["script"]


# ---------------------------------------------------------------------------
# The gate, over HTTP, with real callers.
# ---------------------------------------------------------------------------


def _client_for(username: str, role: str) -> AsyncClient:
    from api.main import app

    token = create_access_token(username, role, "test-secret")
    return AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test",
        headers={"Authorization": f"Bearer {token}"},
    )


async def _seed_login(slug: str, username: str, **flags) -> None:
    """A login wired the whole way - users row, membership, stakeholder on this project."""
    async with get_connection(slug) as conn:
        project = await fetch_project(conn, slug=slug)
        stakeholder_id = await insert_stakeholder(
            conn, project_id=project["id"], name=username,
            email=f"{username}@example.test", **flags,
        )
    async with get_system_connection() as sys_conn:
        await insert_user(sys_conn, username=username, email=f"{username}@example.test",
                          role="reviewer", hashed_pw="x")
        user = await fetch_user(sys_conn, username=username)
        await link_membership(sys_conn, user_id=user["id"], project_slug=slug,
                              stakeholder_id=stakeholder_id)


@pytest_asyncio.fixture
async def real_callers(ledger):
    """Three real logins: an outsider, a member with no content role, and a reviewer.

    The middle one is the caller that matters. An "anonymous is refused" test passes against a
    door with no content gate at all, because the membership floor refuses anonymous anyway.
    """
    slug, project_id = ledger
    await _seed_login(slug, "bulk-member", is_participant=1)
    await _seed_login(slug, "bulk-reviewer", is_reviewer=1)
    return slug, project_id


@pytest.mark.asyncio
async def test_a_login_with_no_membership_is_refused_by_the_floor(real_callers):
    """check_project_access, and it is asserted on the sentence: a caller refused by two gates
    says nothing about either."""
    slug, _ = real_callers
    async with _client_for("bulk-outsider", "reviewer") as c:
        r = await c.post(BULK, json={
            "script_ids": ["SC-001"], "decision": "changes_requested", "return_to": "agent",
        })
    assert r.status_code == 403, r.text
    assert r.json()["detail"] == ACCESS_DENIED


@pytest.mark.asyncio
async def test_a_member_without_a_content_role_is_refused_by_the_gate(real_callers):
    """Clears the floor, refused by the content gate - so this is the one caller whose refusal
    is attributable to the gate alone, and the one an anonymous-only test would have missed.
    """
    slug, project_id = real_callers
    async with _client_for("bulk-member", "reviewer") as c:
        r = await c.post(BULK, json={
            "script_ids": ["SC-001"], "decision": "changes_requested", "return_to": "agent",
        })
    assert r.status_code == 403, r.text
    assert r.json()["detail"] == NOT_PERMITTED
    assert await _pending(slug, project_id) == []


@pytest.mark.asyncio
async def test_a_reviewer_on_the_project_may_send_a_batch_back(real_callers):
    """The control. Without it, a door refusing everybody would pass both tests above."""
    slug, project_id = real_callers
    with _no_mail():
        async with _client_for("bulk-reviewer", "reviewer") as c:
            r = await c.post(BULK, json={
                "script_ids": ["SC-001", "SC-002"], "decision": "changes_requested",
                "return_to": "agent", "notes": "fix the closing",
            })
    assert r.status_code == 200, r.text
    assert {p["script_id"] for p in await _pending(slug, project_id)} == {"SC-001", "SC-002"}


@pytest.mark.asyncio
async def test_the_bulk_door_calls_the_membership_floor(real_callers):
    """CLAUDE.md's floor: 105 of 108 `{slug}` handlers call `check_project_access`, and the
    three that do not are deliberate unauthenticated reads. Asserted as a call rather than by
    grepping the source, because a docstring naming the function is an `ast.Constant` and a
    guard is an `ast.Call` - the distinction that made an earlier sweep find two exceptions
    where there were three.
    """
    import ast
    import inspect

    from api.routers import script_reviews

    fn = script_reviews.review_scripts_in_bulk
    tree = ast.parse(inspect.getsource(fn).lstrip())
    called = {
        n.func.id for n in ast.walk(tree)
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
    }
    assert "check_project_access" in called
    # The content gate asked by name. `caller_roles` spelled out inline would pass a test
    # looking merely for "some authority call", which is why the assertion names the rule.
    assert "caller_may_contribute" in called
