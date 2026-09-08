# tests/test_pending_skills_are_not_public.py
"""A proposal an agent made about one engagement is not readable from another.

**Two statuses, two different kinds of thing.** An approved skill is an agent's published
instruction - `_fetch_skill_notes` injects it into that agent's prompt on every engagement,
and being global is exactly what makes it nobody's client material. A `pending` row is a
proposal, and since sp61 a proposal is the agent's own sentence about the engagement it was
corrected on, filed with that engagement's slug beside it.

`GET /admin/skills` is `require_any_auth` and used to permit `status=pending` to any login,
which was safe for precisely as long as a pending row was something an administrator had
typed into the review queue. `propose_skill` changed what is behind the door without changing
the door - CLAUDE.md's own rule arriving from the other side: *when a path starts carrying
something written about one client, re-read the exemption it is sitting under*.

**Both halves are asserted, because a fix that hid everything would pass either alone.** The
refusal is driven as the reviewer drove it - a `reviewer` and an `org_admin`, over HTTP, in
one process holding a proposal from a different engagement - and the control asserts the
approved library is still readable by the same callers, since that is the half a blunt
`require_sysadmin` on the whole endpoint would have broken.

The name is asserted as well as the description. `_derive_skill_name` makes an unnamed
proposal's name the first five words of the rule, so hiding the description alone discloses
the same sentence one clause shorter.
"""
import pytest
import pytest_asyncio

from api.auth import create_access_token
from api.config import get_settings
from api.services.skills_service import _derive_skill_name

# The shape the review drove: a rule that names a client, its system, and an incident.
_RULE = (
    "When interviewing Iberdrola's SAP migration staff, never name the Q3 outage in the welcome."
)
_ORIGIN_SLUG = "confidential-client-engagement"
_PROPOSAL_NAME = _derive_skill_name(_RULE)
_APPROVED_NAME = "sp61-public-check approved library rule"
_AGENT = "Interaction Designer"


def _token(role: str) -> str:
    claims = {"org_id": 1} if role == "org_admin" else {}
    return create_access_token("someone", role, get_settings().jwt_secret, **claims)


def _auth(role: str) -> dict:
    return {"Authorization": f"Bearer {_token(role)}"}


async def _insert(name: str, description: str, *, status: str) -> int:
    from api.database import get_system_connection, insert_skill

    async with get_system_connection() as conn:
        return await insert_skill(
            conn,
            name=name,
            description=description,
            source="revision",
            source_project=_ORIGIN_SLUG,
            source_ref="SC-014",
            proposed_by_agent="interaction_designer",
            status=status,
            agents=[_AGENT],
        )


@pytest_asyncio.fixture(autouse=True)
async def _rows():
    """The proposal and an approved sibling, removed afterwards whatever happened.

    `@pytest_asyncio.fixture`, never a plain `@pytest.fixture`: `asyncio_mode = strict` hands
    a plain async fixture over as an un-awaited generator, so setup and teardown both silently
    do not run and `system.db` - which is shared across the whole suite - keeps the rows.
    """
    await _insert(_PROPOSAL_NAME, _RULE, status="pending")
    await _insert(_APPROVED_NAME, "Always state the units on a figure you carry forward.",
                  status="approved")
    yield
    from api.database import get_system_connection, delete_skill

    async with get_system_connection() as conn:
        async with conn.execute(
            "SELECT id FROM skills WHERE name IN (?, ?)", (_PROPOSAL_NAME, _APPROVED_NAME),
        ) as cur:
            ids = [r["id"] for r in await cur.fetchall()]
    for skill_id in ids:
        async with get_system_connection() as conn:
            await delete_skill(conn, skill_id=skill_id)


@pytest.mark.parametrize("role", ["reviewer", "org_admin"])
@pytest.mark.asyncio
async def test_a_non_sysadmin_may_not_list_the_pending_queue(client, role):
    """The refusal, driven exactly as the review drove the disclosure."""
    res = await client.get("/admin/skills?status=pending", headers=_auth(role))

    assert res.status_code == 403
    body = res.text
    assert _RULE not in body
    assert _ORIGIN_SLUG not in body
    # The name is the first five words of the rule, so it leaks on its own.
    assert _PROPOSAL_NAME not in body


@pytest.mark.parametrize("role", ["reviewer", "org_admin"])
@pytest.mark.asyncio
async def test_the_approved_library_is_still_readable_by_the_same_callers(client, role):
    """The control. Without it, a fix that refused the whole endpoint would pass above.

    An approved skill is already in that agent's prompt on every engagement; there is nothing
    to protect and a good deal to explain by showing it.
    """
    res = await client.get("/admin/skills?status=approved", headers=_auth(role))

    assert res.status_code == 200
    assert any(s["name"] == _APPROVED_NAME for s in res.json())


@pytest.mark.parametrize("role", ["reviewer", "org_admin"])
@pytest.mark.asyncio
async def test_asking_for_no_status_at_all_answers_the_approved_library_only(client, role):
    """A caller expressing no preference is not a caller who was refused.

    It defaults to `approved` rather than 403 - but it must not be the unfiltered read it was,
    which returned every status including the proposal.
    """
    res = await client.get("/admin/skills", headers=_auth(role))

    assert res.status_code == 200
    names = [s["name"] for s in res.json()]
    assert _APPROVED_NAME in names
    assert _PROPOSAL_NAME not in names
    assert _RULE not in res.text


@pytest.mark.parametrize("role", ["reviewer", "org_admin"])
@pytest.mark.asyncio
async def test_the_rejected_queue_is_refused_too(client, role):
    """`rejected` holds the same proposals, refused. It was already narrowed to `approved`
    silently; it is now refused for the reason `pending` is, and by the same branch."""
    res = await client.get("/admin/skills?status=rejected", headers=_auth(role))

    assert res.status_code == 403


@pytest.mark.asyncio
async def test_a_sysadmin_still_reads_the_queue(client):
    """The second control: the queue has to work for whoever acts on it.

    The `client` fixture's token is a sysadmin's.
    """
    res = await client.get("/admin/skills?status=pending")

    assert res.status_code == 200
    rows = res.json()
    proposal = next(s for s in rows if s["name"] == _PROPOSAL_NAME)
    assert proposal["description"] == _RULE
    assert proposal["source_project"] == _ORIGIN_SLUG


# ── the same finding, one table over ───────────────────────────────────────────────────────

_FEEDBACK = (
    "Maya named the Q3 outage at Iberdrola in the welcome for SC-014 - never do that again."
)
_NOTE = "Do not name incidents in a welcome."


async def _store_skill_note() -> int:
    from api.database import get_system_connection, insert_skill_note

    async with get_system_connection() as conn:
        return await insert_skill_note(
            conn, agent_name=_AGENT, note=_NOTE, raw_input=_FEEDBACK,
        )


@pytest_asyncio.fixture
async def _a_skill_note():
    note_id = await _store_skill_note()
    yield note_id
    from api.database import get_system_connection

    async with get_system_connection() as conn:
        await conn.execute("DELETE FROM agent_skill_notes WHERE id = ?", (note_id,))
        await conn.commit()


@pytest.mark.parametrize("role", ["reviewer", "org_admin"])
@pytest.mark.asyncio
async def test_a_non_sysadmin_may_not_read_the_skill_notes(client, _a_skill_note, role):
    """`agent_skill_notes` is `skills` one table over, and had the same shape of hole.

    `fetch_skill_notes` is a `SELECT *`, so the door returned `raw_input` - the reviewer's own
    sentence about one engagement, written from `ReviewDialog` - to any login. `note` is the
    distilled imperative and is genuinely global, being injected into every engagement's
    prompts; `raw_input` is not, and both came back together.
    """
    res = await client.get("/agent-skill-notes", headers=_auth(role))

    assert res.status_code == 403
    assert _FEEDBACK not in res.text


@pytest.mark.asyncio
async def test_a_sysadmin_still_reads_the_skill_notes(client, _a_skill_note):
    """The control. A fix that refused everybody would pass the test above."""
    res = await client.get("/agent-skill-notes")

    assert res.status_code == 200
    stored = next(n for n in res.json() if n["id"] == _a_skill_note)
    assert stored["raw_input"] == _FEEDBACK
    assert stored["note"] == _NOTE


@pytest.mark.asyncio
async def test_a_reviewer_may_still_leave_feedback(client):
    """Writing your own sentence is not reading somebody else's, so `POST` is unchanged.

    Narrowing it would take the review loop's own door with it - `ReviewDialog` posts here as
    a reviewer - so this asserts the write is still reachable rather than leaving the
    asymmetry to be inferred from the absence of a test. It is refused at the validation step
    rather than the auth one, which is the distinction being made: 422, never 403.
    """
    res = await client.post(
        "/agent-skill-notes",
        json={"agent_name": _AGENT, "raw_input": "   "},
        headers=_auth("reviewer"),
    )

    assert res.status_code == 422


@pytest.mark.asyncio
async def test_the_derived_name_really_does_carry_the_rule(client):
    """Guards the assertions above rather than the product.

    They only mean something if `_derive_skill_name` produces a name made of the rule's own
    words. If it ever became a generic label, "the name did not appear" would pass while
    saying nothing, and the description assertions would be carrying the whole file.
    """
    assert _PROPOSAL_NAME
    assert _PROPOSAL_NAME in _RULE
    assert "Iberdrola" in _PROPOSAL_NAME
