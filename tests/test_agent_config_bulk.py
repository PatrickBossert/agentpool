"""`GET /projects/{slug}/agents/config` - the whole roll, in one request.

Nine sites on the dashboard draw an agent's name and face, and until this branch all nine read
a static map in `ui/src/components/agentStatus.ts`. Patrick uploaded a portrait for Jordan on
`sp-gs-am`: the file was downscaled and stored, the row recorded the URL, the URL served 200,
**and every face on the dashboard was unchanged.** The configuration was correct at the layer
it was built and invisible at the layer it is looked at.

This door is what the front end reads instead. It exists as a batch and not as nine × eighteen
calls to the per-agent door, and the risk a batch carries is the one this file is mostly about:
**a second implementation of "override where present, default otherwise".** Two code paths for
that rule are two places to get it wrong, and they diverge silently because nothing compares
them. So the first test compares them - whole response against whole response, for every agent
on the roll, with the project configured so the two arms are actually distinguishable.

The comparison is deliberately made against the door and not against `resolve_agent_config`.
Both doors calling the same resolver is the *implementation* this wants; asserting it at the
resolver would pass against a batch that resolved correctly and then dropped a key on the way
out, which is a shape the front end would see and the resolver would not.
"""
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from agents.identity import AGENT_IDENTITY
from api.auth import create_access_token
from api.config import get_settings
from api.database import (
    fetch_project,
    fetch_user,
    get_connection,
    get_system_connection,
    insert_organisation,
    insert_project_registry,
    insert_stakeholder,
    insert_user,
    link_membership,
)

SLUG = "agent-config-bulk-alpha"
OTHER = "agent-config-bulk-beta"

JORDAN = "stakeholder_manager"
AVERY = "stakeholder_interviewer"

ACCESS_DENIED = "Access denied to this project"

# The address the upload door answers, which is the value Patrick's row actually held. Written
# out rather than assembled, so this test cannot agree with a defect in the code that builds it.
JORDANS_PORTRAIT = f"/projects/{SLUG}/agents/{JORDAN}/image"


def _project_body(slug: str) -> dict:
    return {
        "client_slug": slug,
        "llm_mode": "standard",
        "sector": "transport",
        "stakeholder_groups": [],
        "value_stream_labels": [],
        "review_gates": True,
        "slack_channel": "",
    }


def _client_for(username: str, role: str, org_id: int | None = None) -> AsyncClient:
    from api.main import app

    token = create_access_token(username, role, "test-secret", org_id=org_id)
    return AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        headers={"Authorization": f"Bearer {token}"},
    )


async def _seed_member(slug: str, *, username: str, **flags) -> None:
    async with get_connection(slug) as conn:
        project = await fetch_project(conn, slug=slug)
        stakeholder_id = await insert_stakeholder(
            conn, project_id=project["id"], name=username,
            email=f"{username}@example.com", **flags,
        )
    async with get_system_connection() as sys_conn:
        await insert_user(
            sys_conn, username=username, email=f"{username}@example.com",
            role="reviewer", hashed_pw="x",
        )
        user = await fetch_user(sys_conn, username=username)
        await link_membership(
            sys_conn, user_id=user["id"], project_slug=slug, stakeholder_id=stakeholder_id
        )


@pytest_asyncio.fixture
async def doors(tmp_path, monkeypatch, client):
    """One configured project, one unconfigured, and three callers.

    DATABASE_DIR and PROJECTS_DIR are redirected at this test's own tmp_path for the reason
    CLAUDE.md gives: the system database holding `users`, `project_memberships` and
    `project_registry` otherwise lives at the shared, persistent /tmp/agentpool_test, and a
    fixture inserting a fixed username passes once and fails on every run afterwards.

    **The project is configured before anything is read**, and configured on two agents rather
    than one. An unconfigured project answers the defaults through either door, so a comparison
    made on one would pass against a batch that ignored `project_agent_config` entirely - which
    is precisely the defect this task exists to repair, one layer over.
    """
    monkeypatch.setenv("DATABASE_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("PROJECTS_DIR", str(tmp_path / "projects"))
    get_settings.cache_clear()

    for slug in (SLUG, OTHER):
        r = await client.post("/projects", json=_project_body(slug))
        assert r.status_code in (200, 201), r.text

    async with get_system_connection() as sys_conn:
        org = await insert_organisation(sys_conn, slug="acb-org", name="Bulk")
        for slug in (SLUG, OTHER):
            await insert_project_registry(
                sys_conn, slug=slug, org_id=org, display_name=slug
            )
        await insert_user(
            sys_conn, username="acb-outsider", email="acb-outsider@example.com",
            role="reviewer", hashed_pw="x",
        )
        await sys_conn.commit()

    await _seed_member(SLUG, username="acb-member", is_participant=True)

    admin = _client_for("acb-admin", "org_admin", org_id=org)
    member = _client_for("acb-member", "reviewer")
    outsider = _client_for("acb-outsider", "reviewer")

    async with admin, member, outsider:
        # Through the real write door, so the row under test is the one a consultant produces.
        # Jordan is the reported defect: a portrait and nothing else. Avery is a name and a
        # cleared portrait, which is the *other* thing the resolver draws a distinction about -
        # `''` is the project saying "nothing", not the project saying nothing.
        r = await admin.put(
            f"/projects/{SLUG}/agents/{JORDAN}/config",
            json={
                "display_name": None, "image_url": JORDANS_PORTRAIT, "voice_id": None,
                "language": None, "country_code": None, "model_id": None,
            },
        )
        assert r.status_code == 200, r.text
        r = await admin.put(
            f"/projects/{SLUG}/agents/{AVERY}/config",
            json={
                "display_name": "Ava Sinclair", "image_url": "", "voice_id": None,
                "language": None, "country_code": None, "model_id": None,
            },
        )
        assert r.status_code == 200, r.text

        yield {"admin": admin, "member": member, "outsider": outsider}

    get_settings.cache_clear()


# ── The load-bearing comparison ──────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_the_bulk_door_answers_what_the_single_door_answers(doors):
    """The same resolution, not a second implementation of it.

    Every agent on the roll, whole response against whole response - `defaults`, `overrides`,
    `resolved`, `configured` and `is_interviewer` together. Comparing `resolved` alone would
    leave four keys the batch could get wrong in silence, and `overrides` is the one the front
    end actually reads.

    The roll is walked from `AGENT_IDENTITY` rather than from the bulk response, so a batch that
    simply omitted an agent fails here rather than agreeing vacuously about the ones it kept.
    """
    bulk = await doors["admin"].get(f"/projects/{SLUG}/agents/config")
    assert bulk.status_code == 200, bulk.text
    agents = bulk.json()["agents"]

    for agent_id in AGENT_IDENTITY:
        single = await doors["admin"].get(f"/projects/{SLUG}/agents/{agent_id}/config")
        assert single.status_code == 200, single.text
        assert agent_id in agents, f"the batch omitted {agent_id}"
        assert agents[agent_id] == single.json(), agent_id


@pytest.mark.asyncio
async def test_the_two_arms_of_the_comparison_are_actually_distinguishable(doors):
    """The control for the test above, and the reason the fixture configures anything.

    An unconfigured project answers its defaults through either door, so a comparison made on
    one would be satisfied by a batch that never read `project_agent_config` at all. This asserts
    the fixture put the two arms into the response: an override that differs from its default,
    and an agent left entirely alone.
    """
    agents = (await doors["admin"].get(f"/projects/{SLUG}/agents/config")).json()["agents"]

    jordan = agents[JORDAN]
    assert jordan["overrides"]["image_url"] == JORDANS_PORTRAIT
    assert jordan["resolved"]["image_url"] == JORDANS_PORTRAIT
    assert jordan["defaults"]["image_url"] != JORDANS_PORTRAIT
    assert jordan["configured"] is True

    untouched = agents["value_chain_mapper"]
    assert untouched["configured"] is False
    assert untouched["resolved"] == untouched["defaults"]


@pytest.mark.asyncio
async def test_a_cleared_field_stays_cleared_through_the_batch(doors):
    """`''` is the project saying "nothing"; NULL is the project saying nothing at all.

    `agent_config_service._override` draws that line and the whole module is built on it, so a
    batch that normalised the empty string on its way out - or read it with a truthiness test -
    would quietly reinstate a default over a decision somebody made. Asserted here because the
    front end's fallback is keyed on exactly this distinction.
    """
    agents = (await doors["admin"].get(f"/projects/{SLUG}/agents/config")).json()["agents"]

    assert agents[AVERY]["overrides"]["image_url"] == ""
    assert agents[AVERY]["resolved"]["image_url"] == ""
    assert agents[AVERY]["overrides"]["voice_id"] is None
    assert agents[AVERY]["resolved"]["voice_id"] == agents[AVERY]["defaults"]["voice_id"]


@pytest.mark.asyncio
async def test_the_batch_covers_the_whole_roll_and_nothing_else(doors):
    """Keys equal to `AGENT_IDENTITY`, set against set.

    Equality rather than containment: a missing agent is a face the dashboard cannot configure,
    and an *extra* key is an id nothing on the roll answers to - which is the direction a
    hand-written list drifts, and the reason this door enumerates the map instead.
    """
    agents = (await doors["admin"].get(f"/projects/{SLUG}/agents/config")).json()["agents"]
    assert set(agents) == set(AGENT_IDENTITY)


# ── Authority: the membership floor, and nothing above it ────────────────────────────────

@pytest.mark.asyncio
async def test_a_member_may_read_the_batch(doors):
    """A read, so the floor and nothing else - the authority of the door it batches.

    A participant is deliberately the caller: `check_project_access` treats membership as read
    access, and this answers what nine renders of the per-agent door would already answer them.
    """
    r = await doors["member"].get(f"/projects/{SLUG}/agents/config")
    assert r.status_code == 200, r.text
    assert set(r.json()["agents"]) == set(AGENT_IDENTITY)


@pytest.mark.asyncio
async def test_a_caller_outside_the_engagement_is_refused(doors):
    """The floor is asked, and it is asked *first*.

    Batching eighteen reads into one is exactly the shape that acquires an unguarded door -
    CLAUDE.md's sweep found two of them - so the refusal is driven rather than assumed.
    """
    r = await doors["outsider"].get(f"/projects/{SLUG}/agents/config")
    assert r.status_code == 403, r.text
    assert ACCESS_DENIED in r.json()["detail"]


@pytest.mark.asyncio
async def test_an_unknown_slug_is_a_404_and_materialises_no_database(doors, tmp_path):
    """404 before `get_connection`, so probing slugs cannot create a file per guess.

    `_assert_project_exists` carries this for the per-agent door and the batch takes it unasked;
    the assertion is on the directory rather than on the status, because a 404 raised *after*
    the connection was opened looks identical from the outside.

    The caller is a **sysadmin** deliberately. Everybody else is refused by
    `check_project_access` first - the org_admin above answers 403 here, because an unregistered
    slug belongs to no organisation - so a test driven by them would never reach the guard it
    claims to be about, and would pass against a door that had none.
    """
    async with _client_for("acb-sys", "sysadmin") as sysadmin:
        r = await sysadmin.get("/projects/acb-no-such-project/agents/config")
    assert r.status_code == 404, r.text
    assert not (tmp_path / "data" / "acb-no-such-project.db").exists()


@pytest.mark.asyncio
async def test_the_batch_reads_this_project_and_not_another(doors):
    """Jordan's portrait belongs to the engagement that uploaded it.

    Two projects under the same organisation, so the same caller reaches both and the only thing
    separating the answers is the slug the door resolved against.
    """
    other = (await doors["admin"].get(f"/projects/{OTHER}/agents/config")).json()["agents"]
    assert other[JORDAN]["configured"] is False
    assert other[JORDAN]["resolved"]["image_url"] == other[JORDAN]["defaults"]["image_url"]
    assert other[JORDAN]["resolved"]["image_url"] != JORDANS_PORTRAIT
