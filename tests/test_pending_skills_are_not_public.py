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
# Approved - a human ruled on it - and still one engagement's material, which is the pair
# sp65's I2 is about. Its own sentence names the client, so it discloses on sight.
_NARROW_RULE = (
    "Iberdrola's steering group reads the summary before the board pack, so lead with it."
)
_NARROW_NAME = "sp65-public-check approved narrow rule"
# Its own slug, not `_ORIGIN_SLUG`. The global control row legitimately carries the origin it
# was proposed on and is legitimately readable, so asserting the shared slug is absent from the
# body would fail against correct behaviour - and, worse, would have passed for the wrong
# reason had the two rows been filtered together.
_NARROW_ORIGIN = "sp65-narrow-client-engagement"
_AGENT = "Interaction Designer"


def _token(role: str) -> str:
    claims = {"org_id": 1} if role == "org_admin" else {}
    return create_access_token("someone", role, get_settings().jwt_secret, **claims)


def _auth(role: str) -> dict:
    return {"Authorization": f"Bearer {_token(role)}"}


async def _insert(
    name: str, description: str, *, status: str, scope: str = "project",
    source_project: str = _ORIGIN_SLUG,
) -> int:
    from api.database import get_system_connection, insert_skill

    async with get_system_connection() as conn:
        return await insert_skill(
            conn,
            name=name,
            description=description,
            source="revision",
            source_project=source_project,
            source_ref="SC-014",
            proposed_by_agent="interaction_designer",
            status=status,
            scope=scope,
            agents=[_AGENT],
        )


@pytest_asyncio.fixture(autouse=True)
async def _rows():
    """Three rows - the proposal, a published rule, and the one in between - removed afterwards
    whatever happened.

    The third is what sp65's review (I2) found. It is `approved`, so the status test lets it
    through, and it is scoped to one engagement, so it reaches only that engagement's prompt -
    a human has signed off a sentence about one client, which is not the same thing as
    publishing it. Two rows could not tell the two questions apart.

    `@pytest_asyncio.fixture`, never a plain `@pytest.fixture`: `asyncio_mode = strict` hands
    a plain async fixture over as an un-awaited generator, so setup and teardown both silently
    do not run and `system.db` - which is shared across the whole suite - keeps the rows.
    """
    await _insert(_PROPOSAL_NAME, _RULE, status="pending")
    await _insert(_APPROVED_NAME, "Always state the units on a figure you carry forward.",
                  status="approved", scope="global")
    await _insert(_NARROW_NAME, _NARROW_RULE, status="approved", scope="project",
                  source_project=_NARROW_ORIGIN)
    yield
    from api.database import get_system_connection, delete_skill

    async with get_system_connection() as conn:
        async with conn.execute(
            "SELECT id FROM skills WHERE name IN (?, ?, ?)",
            (_PROPOSAL_NAME, _APPROVED_NAME, _NARROW_NAME),
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

    A **global** skill is already in that agent's prompt on every engagement; there is nothing
    to protect and a good deal to explain by showing it. The row this reads is explicitly
    `scope="global"` since sp65 - it was merely `approved` before, and that was the whole of
    finding I2: the status was standing in for the scope.
    """
    res = await client.get("/admin/skills?status=approved", headers=_auth(role))

    assert res.status_code == 200
    assert any(s["name"] == _APPROVED_NAME for s in res.json())


@pytest.mark.parametrize("role", ["reviewer", "org_admin"])
@pytest.mark.asyncio
async def test_an_approved_rule_scoped_to_one_engagement_is_not_in_the_library(client, role):
    """I2. Approval is not publication, and until sp65 this door treated it as though it were.

    The row is `approved`, so the status test lets it through; it is scoped to one engagement,
    so `_skill_applies_here` puts it in front of that engagement's agents and nobody else's.
    Handing it - with the `source_project` naming the client - to a `reviewer` on an unrelated
    project disclosed the sentence, the client, and the engagement's slug.

    Asserted against the whole response body as well as the parsed names, because the rule, the
    name and the slug each leak independently and a check on one of the three is a check on
    none of the others.
    """
    res = await client.get("/admin/skills?status=approved", headers=_auth(role))

    assert res.status_code == 200
    names = [s["name"] for s in res.json()]
    assert _NARROW_NAME not in names
    assert _NARROW_RULE not in res.text
    assert _NARROW_ORIGIN not in res.text
    # The control, in the same request: the global library still came back, so this is not a
    # door that started answering an empty list.
    assert _APPROVED_NAME in names


@pytest.mark.asyncio
async def test_a_sysadmin_still_reads_an_approved_rule_scoped_to_one_engagement(client):
    """The control on the test above, and the one that keeps demotion possible.

    A reviewer who finds a rule that was really about a single engagement has to be able to see
    it in order to change it - `LibrarySkillCard` reads this door - so the narrowing is about
    who asks, not about the row disappearing from the product.
    """
    res = await client.get("/admin/skills?status=approved")

    assert res.status_code == 200
    row = next(s for s in res.json() if s["name"] == _NARROW_NAME)
    assert row["scope"] == "project"
    assert row["source_project"] == _NARROW_ORIGIN


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
    # And the scope narrowing applies to the defaulted read as well as the explicit one. They
    # are two branches of one `if` today; a later refactor that moves the filter into the
    # explicit arm alone would be invisible without this line.
    assert _NARROW_NAME not in names
    assert _NARROW_RULE not in res.text


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


# ── the same finding, one table over, and the table has gone ───────────────────────────────
#
# Three tests stood here against `GET`/`POST /agent-skill-notes`, which had the same shape of
# hole as the queue above and was closed the same way. The whole mechanism retired in sp65 -
# it was never intended, and `intent='skill'` on the review door files a proposal onto the
# queue this file is about instead - so the door they drove no longer exists. The finding they
# recorded is not lost: it is the same one the tests above make, on the table that survived.

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
