"""`GET` and `PUT /projects/{slug}/agents/{agent_id}/config`, over HTTP.

The table and its resolver landed in Task 1 and nothing could write them except a test, so
every project on the deployment ran on the defaults - the wrong-voice defect's first broken
link ("the choice is not persisted anywhere a server can see") was only half repaired. This
is the door the Setup section saves through, and these are the properties it has to hold.

**The assertions are one layer down wherever they can be.** CLAUDE.md records eight separate
occasions on this project where a test verified a property one layer away from where it
holds, and the shape here is exactly the one that invites it: it is cheap to assert the
response body echoed back what was sent, and the response body is not what conducts an
interview. So the voice test reads `resolve_agent_config` - the function the session stamp
actually calls - and the clearing test reads the column, not the JSON.
"""
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from agents.identity import AGENT_IDENTITY
from api.auth import create_access_token
from api.config import get_settings
from api.database import (
    fetch_agent_config,
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

SLUG_A = "agent-config-door-alpha"
SLUG_B = "agent-config-door-beta"

AVERY = "stakeholder_interviewer"

ACCESS_DENIED = "Access denied to this project"
ADMIN_REQUIRED = (
    "Project administration required - org admin or above, or project_admin on this project"
)

# Not a voice this repository has an opinion about - it is a string chosen to be visibly
# unlike any real ElevenLabs id, so an assertion on it cannot accidentally pass because a
# default happened to match. The branch's whole subject is voice facts declared in the wrong
# places; a test fixture that reads like a real one is how the sixth copy gets written.
CHOSEN_VOICE = "test-voice-not-a-real-id"


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


def _all_null() -> dict:
    return {
        "display_name": None, "image_url": None, "voice_id": None,
        "language": None, "country_code": None, "model_id": None,
    }


@pytest_asyncio.fixture
async def doors(tmp_path, monkeypatch, client):
    """Two projects under two organisations, and four callers of different authority.

    DATABASE_DIR and PROJECTS_DIR are redirected at this test's own tmp_path for the reason
    CLAUDE.md gives: the system database holding `users`, `project_memberships` and
    `project_registry` otherwise lives at the shared, persistent /tmp/agentpool_test, and a
    fixture inserting a fixed username passes once and fails on every run afterwards.
    """
    monkeypatch.setenv("DATABASE_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("PROJECTS_DIR", str(tmp_path / "projects"))
    get_settings.cache_clear()

    for slug in (SLUG_A, SLUG_B):
        r = await client.post("/projects", json=_project_body(slug))
        assert r.status_code in (200, 201), r.text

    async with get_system_connection() as sys_conn:
        org_a = await insert_organisation(sys_conn, slug="ac-org-alpha", name="Alpha")
        org_b = await insert_organisation(sys_conn, slug="ac-org-beta", name="Beta")
        await insert_project_registry(
            sys_conn, slug=SLUG_A, org_id=org_a, display_name=SLUG_A
        )
        await insert_project_registry(
            sys_conn, slug=SLUG_B, org_id=org_b, display_name=SLUG_B
        )
        await insert_user(
            sys_conn, username="ac-outsider", email="ac-outsider@example.com",
            role="reviewer", hashed_pw="x",
        )
        await sys_conn.commit()

    await _seed_member(SLUG_A, username="ac-member", is_participant=True)
    await _seed_member(SLUG_A, username="ac-padmin", is_project_admin=True)

    outsider = _client_for("ac-outsider", "reviewer")
    member = _client_for("ac-member", "reviewer")
    padmin = _client_for("ac-padmin", "reviewer")
    admin_a = _client_for("ac-admin-a", "org_admin", org_id=org_a)

    async with outsider, member, padmin, admin_a:
        yield {
            "outsider": outsider, "member": member,
            "padmin": padmin, "admin_a": admin_a,
        }

    get_settings.cache_clear()


# ── What an unconfigured project answers ────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_an_unconfigured_project_answers_the_agents_own_defaults(doors):
    """The control. Without it, a change that broke resolution entirely would pass every
    assertion below - each of which is about a value moving away from the default."""
    r = await doors["admin_a"].get(f"/projects/{SLUG_A}/agents/{AVERY}/config")
    assert r.status_code == 200, r.text
    body = r.json()

    identity = AGENT_IDENTITY[AVERY]
    assert body["configured"] is False
    assert body["overrides"] == _all_null()
    assert body["defaults"]["display_name"] == identity.display_name
    assert body["defaults"]["voice_id"] == identity.voice_id
    assert body["resolved"] == body["defaults"]


@pytest.mark.asyncio
async def test_defaults_and_overrides_are_answered_apart(doors):
    """A Setup tab has to say whether a value is a choice or an inheritance, and it cannot if
    the door resolves them together before answering. This is the property sp58's platform-URL
    panel established for the deployment address; the failure it prevents is an administrator
    leaving a copy of today's default in a box, pinning the agent to it for ever."""
    await doors["admin_a"].put(
        f"/projects/{SLUG_A}/agents/{AVERY}/config",
        json={**_all_null(), "display_name": "Ellie Marsh"},
    )
    body = (await doors["admin_a"].get(f"/projects/{SLUG_A}/agents/{AVERY}/config")).json()

    assert body["overrides"]["display_name"] == "Ellie Marsh"
    assert body["defaults"]["display_name"] == AGENT_IDENTITY[AVERY].display_name
    assert body["resolved"]["display_name"] == "Ellie Marsh"
    # The five untouched fields are still inheritances, not choices, and the door says so.
    assert body["overrides"]["voice_id"] is None
    assert body["resolved"]["voice_id"] == AGENT_IDENTITY[AVERY].voice_id


# ── What the save reaches ───────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_a_saved_voice_is_what_the_interview_would_resolve(doors):
    """One layer down, deliberately.

    Asserting the response body would prove the door echoes what it was sent, which is not the
    property anybody cares about: the property is that the *session stamp* picks it up.
    `resolve_agent_config` is the function `interview_service` calls to build the stamp, so it
    is what is asked here rather than the JSON the door just returned.
    """
    from api.services.agent_config_service import resolve_agent_config

    r = await doors["admin_a"].put(
        f"/projects/{SLUG_A}/agents/{AVERY}/config",
        json={**_all_null(), "voice_id": CHOSEN_VOICE},
    )
    assert r.status_code == 200, r.text

    resolved = await resolve_agent_config(SLUG_A, AVERY)
    assert resolved["voice_id"] == CHOSEN_VOICE
    # And nothing else moved: a project that chose a voice has not thereby named the agent.
    assert resolved["display_name"] == AGENT_IDENTITY[AVERY].display_name


@pytest.mark.asyncio
async def test_a_field_left_out_of_the_body_is_cleared_in_the_column(doors):
    """PUT replaces the row, and the column is what proves it.

    `upsert_agent_config` writes all six on every call, so an omitted field is a *clear*
    rather than a leave-alone. Asserted on the stored NULL and not on the resolved value,
    because a cleared override and a stored copy of the default resolve to the same string -
    and the difference between them is whether this agent still follows a rename in
    `agents/identity.py`.
    """
    admin = doors["admin_a"]
    await admin.put(
        f"/projects/{SLUG_A}/agents/{AVERY}/config",
        json={**_all_null(), "display_name": "Ellie Marsh", "voice_id": CHOSEN_VOICE},
    )
    # The second save mentions the voice and not the name, exactly as a form posting its whole
    # state would after the name box was emptied.
    await admin.put(
        f"/projects/{SLUG_A}/agents/{AVERY}/config",
        json={"voice_id": CHOSEN_VOICE},
    )

    async with get_connection(SLUG_A) as conn:
        project = await fetch_project(conn, slug=SLUG_A)
        row = await fetch_agent_config(conn, project_id=project["id"], agent_id=AVERY)
    assert row is not None
    assert row["display_name"] is None, "the omitted field was left alone rather than cleared"
    assert row["voice_id"] == CHOSEN_VOICE


@pytest.mark.asyncio
async def test_an_empty_string_is_an_override_and_not_a_clear(doors):
    """`''` and NULL are different states, and the wire must not collapse them.

    A project that has deliberately cleared a display name has said something; a project that
    never opened the settings has not. `_override` in the resolver tests for NULL rather than
    truthiness precisely so the two stay apart, and a door that normalised `''` to `None`
    would reinstate the default over a decision somebody made.
    """
    await doors["admin_a"].put(
        f"/projects/{SLUG_A}/agents/{AVERY}/config",
        json={**_all_null(), "display_name": ""},
    )
    body = (await doors["admin_a"].get(f"/projects/{SLUG_A}/agents/{AVERY}/config")).json()
    assert body["overrides"]["display_name"] == ""
    assert body["resolved"]["display_name"] == ""


@pytest.mark.asyncio
async def test_one_projects_configuration_does_not_reach_another(doors):
    """The table is keyed on `(project_id, agent_id)` and each project has its own database,
    so this is two guarantees at once rather than one."""
    await doors["admin_a"].put(
        f"/projects/{SLUG_A}/agents/{AVERY}/config",
        json={**_all_null(), "voice_id": CHOSEN_VOICE},
    )
    from api.services.agent_config_service import resolve_agent_config

    assert (await resolve_agent_config(SLUG_B, AVERY))["voice_id"] == AGENT_IDENTITY[AVERY].voice_id


# ── The roll is closed ──────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
@pytest.mark.parametrize("verb", ["get", "put"])
async def test_an_agent_id_outside_the_roll_is_refused_by_both_verbs(doors, verb):
    """`agent_id` is a permanent contract and an id outside `AGENT_IDENTITY` is a typo or a
    retired key, never an agent with no preferences. Answering a shrug would let a misspelled
    id be configured into a row that nothing ever reads - a setting that appears to save and
    reaches no interview, which is the failure this branch exists to end."""
    url = f"/projects/{SLUG_A}/agents/interveiwer/config"
    r = (
        await doors["admin_a"].get(url) if verb == "get"
        else await doors["admin_a"].put(url, json=_all_null())
    )
    assert r.status_code == 404, r.text
    assert "interveiwer" in r.json()["detail"]


# ── Authority ───────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_a_member_may_read_but_may_not_write(doors):
    """The read takes the membership floor and nothing else - a reviewer may see who is going
    to interview their stakeholders. The write takes the administration axis, because naming
    an agent and choosing its voice is configuring the engagement.

    Both halves in one test on purpose: a caller refused by two gates at once tells you
    nothing about either, and the read proves this caller genuinely clears the floor.
    """
    member = doors["member"]
    assert (await member.get(f"/projects/{SLUG_A}/agents/{AVERY}/config")).status_code == 200

    r = await member.put(f"/projects/{SLUG_A}/agents/{AVERY}/config", json=_all_null())
    assert r.status_code == 403
    assert r.json()["detail"] == ADMIN_REQUIRED


@pytest.mark.asyncio
async def test_a_project_admin_may_configure_their_own_engagements_agents(doors):
    """The widened half of the administration axis, and the reason it is not platform tier.

    A client's own project administrator names their interviewer and picks its voice; sp44
    moved fifteen configuration doors to exactly this authority and this is the sixteenth.
    Nothing here decides where the engagement's material is sent - `model_id` on this row is
    the **speech synthesis** model, not one of the six LLM model ids that are refused to this
    caller on `PATCH /{slug}/settings`.
    """
    r = await doors["padmin"].put(
        f"/projects/{SLUG_A}/agents/{AVERY}/config",
        json={**_all_null(), "voice_id": CHOSEN_VOICE},
    )
    assert r.status_code == 200, r.text
    assert r.json()["resolved"]["voice_id"] == CHOSEN_VOICE


@pytest.mark.asyncio
@pytest.mark.parametrize("verb", ["get", "put"])
async def test_a_non_member_is_refused_by_the_floor(doors, verb):
    url = f"/projects/{SLUG_A}/agents/{AVERY}/config"
    r = (
        await doors["outsider"].get(url) if verb == "get"
        else await doors["outsider"].put(url, json=_all_null())
    )
    assert r.status_code == 403
    assert r.json()["detail"] == ACCESS_DENIED


@pytest.mark.asyncio
@pytest.mark.parametrize("verb", ["get", "put"])
async def test_an_administrator_of_another_engagement_is_refused(doors, verb):
    """The caller an "anonymous is refused" test cannot see.

    `admin_a` is a real, fully-privileged org_admin whose organisation owns A and not B, so it
    clears the administration axis on its login role alone and the only thing that can refuse
    it on B is the floor. This is the shape of the hole sp38 found in `milestones.py`.
    """
    url = f"/projects/{SLUG_B}/agents/{AVERY}/config"
    r = (
        await doors["admin_a"].get(url) if verb == "get"
        else await doors["admin_a"].put(url, json=_all_null())
    )
    assert r.status_code == 403
    assert r.json()["detail"] == ACCESS_DENIED


@pytest.mark.asyncio
async def test_my_permissions_reports_the_authority_this_door_refuses_with(doors):
    """The section renders its controls by asking this, so the two must agree.

    A control that always 403s is worse than no control, and the failure runs the other way
    too: reporting `can_change_platform_tier_settings` here would withhold the section from a
    project_admin the door would have accepted. Both callers are driven, so the flag is proven
    to *discriminate* rather than merely to be present.
    """
    padmin = (await doors["padmin"].get(f"/projects/{SLUG_A}/my-permissions")).json()
    member = (await doors["member"].get(f"/projects/{SLUG_A}/my-permissions")).json()

    assert padmin["can_administer_project"] is True
    assert padmin["can_change_platform_tier_settings"] is False, (
        "the fixture's project_admin holds the platform tier too, so this test could not "
        "tell the two flags apart"
    )
    assert member["can_administer_project"] is False
