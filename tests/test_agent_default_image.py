"""The first portrait uploaded for a faceless agent becomes the deployment's default.

Patrick's instruction, 7 September: portraits stay per project, but *"if no default image
exists, then use the first uploaded image as the default for all future projects."*

**The rule has no subject among the real agents, and that shapes every test here.** The plan
was written while Laura Nelson had no portrait; she was given one on 7 September, so all
eighteen agents on the roll now carry a built-in asset and none of them is promotable. The rule
is still correct and still worth having - it fires for the next agent declared, in the window
before somebody draws them - so the subject is **synthetic**: `FACELESS` is registered into
`AGENT_IDENTITY` for the duration of a test with `image=None`. Nothing in `agents/identity.py`
is edited to manufacture one, which would be repairing the product to suit the test.

The consequence is that the two halves of the rule are asserted from opposite directions. The
*promotion* needs the synthetic agent. The *refusal* - an agent that already has a face is
never promoted over - is the case every real agent exercises, so it is driven against Avery,
whose `/agents/avery-singh.jpg` is shipped in the repository.

Three properties are asserted rather than assumed, and each is one a plausible wrong
implementation would satisfy:

- **Provenance, not merely a row.** A promotion that overwrote would leave a row too, so
  `promoted_from_slug` is what the second-upload test reads.
- **The served bytes, not merely the row.** A row that stayed while the file was replaced is
  exactly the half of the race the atomic claim exists to prevent.
- **A project override beats a promoted default.** Without it, a resolver that answered the
  promoted default unconditionally would pass every other level test in this file.
"""

import asyncio
import io

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from PIL import Image

from agents.identity import AGENT_IDENTITY, Identity
from api.config import get_settings
from api.database import fetch_agent_default_image, get_system_connection
from api.services.agent_config_service import agent_defaults, resolve_agent_config
from api.services.agent_default_images import (
    forget_agent_default_images,
    promoted_default_dir,
    promoted_default_file,
    promoted_default_url,
)

SLUG_A = "agent-default-image-alpha"
SLUG_B = "agent-default-image-beta"

# A synthetic agent with no portrait. See the module docstring: every real agent has one, so
# the promotion rule has no live subject and the subject has to be made rather than borrowed.
FACELESS = "faceless_test_agent"

# A real agent that already has a face, shipped in the repository. The refusal's subject.
AVERY = "stakeholder_interviewer"

PROMOTED_URL = f"/api/agents/{FACELESS}/image"


def _encode(image: Image.Image, image_format: str) -> bytes:
    buffer = io.BytesIO()
    image.save(buffer, image_format)
    return buffer.getvalue()


def _png(shade: str = "white") -> bytes:
    return _encode(Image.new("RGB", (120, 90), shade), "PNG")


def _jpeg(shade: str = "black") -> bytes:
    """Deliberately a *different format* from `_png`.

    The loser of the race would store `<agent>.jpg` beside the winner's `<agent>.png`, so two
    formats make "exactly one file" an assertion rather than a tautology - a second upload in
    the same format could only ever overwrite the first at the same path.
    """
    return _encode(Image.new("RGB", (120, 90), shade), "JPEG")


def _upload(data: bytes, content_type: str = "image/png"):
    extension = {"image/png": "png", "image/jpeg": "jpg"}[content_type]
    return {"file": (f"portrait.{extension}", data, content_type)}


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


def _anonymous() -> AsyncClient:
    """No Authorization header at all - the participant reading the interview page."""
    from api.main import app

    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def _row(agent_id: str) -> dict | None:
    async with get_system_connection() as conn:
        return await fetch_agent_default_image(conn, agent_id=agent_id)


def _promoted_files(agent_id: str) -> list[str]:
    directory = promoted_default_dir()
    if not directory.exists():
        return []
    return sorted(p.name for p in directory.iterdir() if p.name.startswith(agent_id))


@pytest_asyncio.fixture
async def deployment(tmp_path, monkeypatch, client):
    """Two projects, an anonymous caller, and a faceless agent on the roll.

    All three directories go to this test's own `tmp_path`. DATABASE_DIR and PROJECTS_DIR for
    the reason CLAUDE.md gives about the shared `/tmp/agentpool_test`; **DATA_DIR because this
    is the first thing that writes a deployment-level asset**, and a promoted portrait left in
    the repository's `data/` would be inherited by every later run of this file - which is
    precisely the poisoned-database shape, reached through a file instead of a row.
    """
    monkeypatch.setenv("DATABASE_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("PROJECTS_DIR", str(tmp_path / "projects"))
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "deployment"))
    get_settings.cache_clear()
    forget_agent_default_images()

    # The synthetic subject. `setitem` on the real dict is what every reader sees, because
    # they all hold a reference to this object rather than a copy of it - and monkeypatch
    # removes the key again at teardown, so the roll is eighteen agents outside this file.
    monkeypatch.setitem(AGENT_IDENTITY, FACELESS, Identity("Frankie Faceless", None))

    for slug in (SLUG_A, SLUG_B):
        response = await client.post("/projects", json=_project_body(slug))
        assert response.status_code in (200, 201), response.text

    async with _anonymous() as anonymous:
        yield {"admin": client, "anonymous": anonymous}

    forget_agent_default_images()
    get_settings.cache_clear()


# ── Step 3: first wins, and the second does not displace it ─────────────────────────────


@pytest.mark.asyncio
async def test_the_first_upload_for_a_faceless_agent_becomes_the_deployment_default(deployment):
    response = await deployment["admin"].post(
        f"/projects/{SLUG_A}/agents/{FACELESS}/image", files=_upload(_png())
    )
    assert response.status_code == 200, response.text
    assert response.json()["promoted_to_deployment_default"] is True

    row = await _row(FACELESS)
    assert row is not None, "no default was recorded for an agent that had no face"
    assert row["promoted_from_slug"] == SLUG_A
    assert row["extension"] == ".png"


@pytest.mark.asyncio
async def test_the_second_upload_does_not_displace_the_promoted_default(deployment):
    """**Assert the provenance, not merely that a row exists.**

    A promotion that overwrote would leave a row too, and a test asking only "is there a row"
    would pass against exactly the behaviour this forbids.
    """
    first = _png()
    await deployment["admin"].post(
        f"/projects/{SLUG_A}/agents/{FACELESS}/image", files=_upload(first)
    )
    second = await deployment["admin"].post(
        f"/projects/{SLUG_B}/agents/{FACELESS}/image",
        files=_upload(_jpeg(), "image/jpeg"),
    )
    assert second.status_code == 200, second.text
    assert second.json()["promoted_to_deployment_default"] is False

    row = await _row(FACELESS)
    assert row["promoted_from_slug"] == SLUG_A
    assert row["extension"] == ".png"

    # And the bytes, not only the row. A row that stayed while the file was replaced is the
    # half of the race the atomic claim exists to prevent, and it is invisible to the two
    # assertions above.
    served = await deployment["anonymous"].get(PROMOTED_URL)
    assert served.status_code == 200, served.text
    assert served.headers["content-type"].startswith("image/png")
    assert _promoted_files(FACELESS) == [f"{FACELESS}.png"]


@pytest.mark.asyncio
async def test_the_second_project_still_gets_its_own_override(deployment):
    """Losing the promotion is not losing the upload.

    The second engagement asked for a portrait on *its* project and must have one. A door that
    treated a lost claim as a failed upload would be a rule about the deployment silently
    refusing a project-scoped write.
    """
    await deployment["admin"].post(
        f"/projects/{SLUG_A}/agents/{FACELESS}/image", files=_upload(_png())
    )
    response = await deployment["admin"].post(
        f"/projects/{SLUG_B}/agents/{FACELESS}/image",
        files=_upload(_jpeg(), "image/jpeg"),
    )
    served = await deployment["anonymous"].get(response.json()["url"])
    assert served.status_code == 200, served.text
    assert served.headers["content-type"].startswith("image/jpeg")


# ── Step 5: an agent that already has a face is never promoted over ─────────────────────


@pytest.mark.asyncio
async def test_an_agent_that_already_has_a_face_is_never_promoted_over(deployment):
    """**No row at all**, not merely an unchanged one.

    Avery's `/agents/avery-singh.jpg` is shipped in the repository. A promotion keyed only on
    "is the table empty for this agent" would satisfy every other test in this file and would
    give him a new face on every future engagement, chosen by whichever consultant happened to
    upload a portrait for him first.
    """
    assert AGENT_IDENTITY[AVERY].image, "this test needs an agent that has a built-in portrait"

    response = await deployment["admin"].post(
        f"/projects/{SLUG_A}/agents/{AVERY}/image", files=_upload(_png())
    )
    assert response.status_code == 200, response.text
    assert response.json()["promoted_to_deployment_default"] is False

    assert await _row(AVERY) is None
    assert _promoted_files(AVERY) == []
    # And the deployment door has nothing to serve for him.
    served = await deployment["anonymous"].get(f"/api/agents/{AVERY}/image")
    assert served.status_code == 404


@pytest.mark.asyncio
async def test_no_agent_on_the_roll_is_promotable_today(deployment):
    """The premise the two tests above rest on, asserted rather than remembered.

    Every one of the eighteen declared agents has a portrait, so the promotion rule currently
    has no live subject - which is exactly why `FACELESS` exists. If this fails, an agent has
    been added without one and the rule has become live for them; that is the rule working, and
    this test is the notice.
    """
    faceless = [
        agent_id
        for agent_id, identity in AGENT_IDENTITY.items()
        if identity.image is None and agent_id != FACELESS
    ]
    assert faceless == [], (
        f"{faceless} now have no built-in portrait, so the first project to upload one for "
        f"them sets it for the whole deployment"
    )


# ── Step 7: the four levels, in order ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_level_four_an_agent_with_nothing_anywhere_resolves_to_no_image(deployment):
    """Nothing uploaded, nothing promoted, nothing shipped - `AgentAvatar` renders initials."""
    resolved = await resolve_agent_config(SLUG_A, FACELESS)
    assert resolved["image_url"] is None


@pytest.mark.asyncio
async def test_level_three_the_built_in_asset_is_what_an_unconfigured_agent_resolves_to(
    deployment,
):
    resolved = await resolve_agent_config(SLUG_A, AVERY)
    assert resolved["image_url"] == AGENT_IDENTITY[AVERY].image


@pytest.mark.asyncio
async def test_level_two_a_promoted_default_is_inherited_by_a_project_that_never_uploaded(
    deployment,
):
    """The point of the whole rule: uploaded on A, resolved on B, which did nothing."""
    await deployment["admin"].post(
        f"/projects/{SLUG_A}/agents/{FACELESS}/image", files=_upload(_png())
    )
    resolved = await resolve_agent_config(SLUG_B, FACELESS)
    assert resolved["image_url"] == PROMOTED_URL


@pytest.mark.asyncio
async def test_level_one_a_project_override_beats_the_promoted_default(deployment):
    """**The pair is the whole point.**

    A resolver that answered the promoted default unconditionally would pass all three tests
    above. This is the one that distinguishes it, and it is asserted on the project that did
    the uploading - which holds both a promoted default and an override of its own.
    """
    upload = await deployment["admin"].post(
        f"/projects/{SLUG_A}/agents/{FACELESS}/image", files=_upload(_png())
    )
    assert upload.json()["promoted_to_deployment_default"] is True

    own_url = upload.json()["url"]
    assert own_url != PROMOTED_URL, "the two levels must be distinguishable addresses"

    save = await deployment["admin"].put(
        f"/projects/{SLUG_A}/agents/{FACELESS}/config", json={"image_url": own_url}
    )
    assert save.status_code == 200, save.text

    resolved = await resolve_agent_config(SLUG_A, FACELESS)
    assert resolved["image_url"] == own_url
    # And the other project, which set no override, still inherits the promoted default -
    # so this asserts precedence rather than the promotion having been undone.
    assert (await resolve_agent_config(SLUG_B, FACELESS))["image_url"] == PROMOTED_URL


@pytest.mark.asyncio
async def test_a_promoted_default_outranks_a_built_in_asset_added_afterwards(deployment):
    """The read order the precedence table states, which no real agent can currently exercise.

    Promotion refuses an agent that already has a face, so levels 2 and 3 can only both exist
    for an agent given a shipped portrait *after* a default was promoted for them. The table
    says level 2 wins, and the reason is that a repository decision should not silently
    outrank an operator's. Reachable only by synthesising it, which is what this does.
    """
    await deployment["admin"].post(
        f"/projects/{SLUG_A}/agents/{FACELESS}/image", files=_upload(_png())
    )
    AGENT_IDENTITY[FACELESS] = Identity("Frankie Faceless", "/agents/frankie-faceless.jpg")

    assert agent_defaults(FACELESS)["image_url"] == PROMOTED_URL


# ── The doors say which default is a promoted one ───────────────────────────────────────
#
# The promotion reached the interview page from the moment it was written, because that page
# renders `resolve_agent_config`'s **resolved** value and level 2 is folded into it. The
# dashboard cannot do that: `defaults["image_url"]` is `/agents/avery-singh.jpg` for an agent
# with no promotion, and Vite serves `ui/public` under the `/dashboard` base, so a front end
# reading it unconditionally 404s all eighteen faces. It therefore walks the four levels itself
# and needs to be **told** which defaults are promoted - the alternative, sniffing for an
# `/api/` prefix, is this rule restated in TypeScript.


@pytest.mark.asyncio
async def test_the_config_door_names_the_promoted_default_for_an_agent_that_has_one(
    deployment,
):
    """Uploaded on A, named on B - the project that did nothing and inherits the face.

    `promoted_default_image_url` is the level itself rather than a flag about `defaults`, so
    what the dashboard has to draw is on the wire as an address it can draw.
    """
    await deployment["admin"].post(
        f"/projects/{SLUG_A}/agents/{FACELESS}/image", files=_upload(_png())
    )

    body = (
        await deployment["admin"].get(f"/projects/{SLUG_B}/agents/{FACELESS}/config")
    ).json()

    assert body["promoted_default_image_url"] == PROMOTED_URL
    # And the resolution still folds it in, unchanged. The new key reports a level; it does not
    # replace the fold, and a change that moved level 2 out of `agent_defaults` would fail here.
    assert body["defaults"]["image_url"] == PROMOTED_URL
    assert body["resolved"]["image_url"] == PROMOTED_URL


@pytest.mark.asyncio
async def test_an_agent_whose_default_is_a_built_in_asset_is_named_as_having_none(deployment):
    """The control, and the reason the field is worth anything.

    A key that simply echoed `defaults["image_url"]` would satisfy the test above and would tell
    the dashboard to render `/agents/avery-singh.jpg`, which is the 404 this whole field exists
    to prevent. Avery has a shipped portrait and no promotion, so the two answers must differ.
    """
    body = (
        await deployment["admin"].get(f"/projects/{SLUG_B}/agents/{AVERY}/config")
    ).json()

    assert body["promoted_default_image_url"] is None
    assert body["defaults"]["image_url"] == AGENT_IDENTITY[AVERY].image
    assert body["defaults"]["image_url"] is not None


@pytest.mark.asyncio
async def test_a_project_override_does_not_change_what_the_promoted_level_is(deployment):
    """Level 1 beating level 2 is the *front end's* decision, and it needs both to make it.

    The door reports the levels; it does not pre-empt them. A door that answered `None` here
    because an override existed would work today and break the moment anything wanted to say
    "this project has overridden the deployment's face".
    """
    upload = await deployment["admin"].post(
        f"/projects/{SLUG_A}/agents/{FACELESS}/image", files=_upload(_png())
    )
    own_url = upload.json()["url"]
    assert own_url != PROMOTED_URL

    save = await deployment["admin"].put(
        f"/projects/{SLUG_A}/agents/{FACELESS}/config", json={"image_url": own_url}
    )
    assert save.status_code == 200, save.text

    assert save.json()["overrides"]["image_url"] == own_url
    assert save.json()["promoted_default_image_url"] == PROMOTED_URL


@pytest.mark.asyncio
async def test_the_bulk_door_names_the_promoted_default_exactly_as_the_single_door_does(
    deployment,
):
    """Both doors, with a promotion in play - which is the state no other comparison reaches.

    `test_the_bulk_door_answers_what_the_single_door_answers` already holds whole responses
    equal for every agent on the roll, and it is the stronger test - but it runs on a deployment
    with nothing promoted, where every agent's answer to this question is `None`. A batch that
    hard-coded `None` would pass it. This one has a subject, and a control beside it in the same
    response.
    """
    await deployment["admin"].post(
        f"/projects/{SLUG_A}/agents/{FACELESS}/image", files=_upload(_png())
    )

    agents = (
        await deployment["admin"].get(f"/projects/{SLUG_B}/agents/config")
    ).json()["agents"]

    for agent_id in (FACELESS, AVERY):
        single = await deployment["admin"].get(
            f"/projects/{SLUG_B}/agents/{agent_id}/config"
        )
        assert agents[agent_id] == single.json(), agent_id

    assert agents[FACELESS]["promoted_default_image_url"] == PROMOTED_URL
    assert agents[AVERY]["promoted_default_image_url"] is None


# ── Step 4's power-check: two uploads racing produce one row and one file ───────────────


@pytest.mark.asyncio
async def test_a_claim_that_was_lost_writes_no_file(deployment, monkeypatch):
    """`rowcount` decides, and nothing else does.

    The deterministic half of Step 4, and the one worth having first: whatever the scheduling,
    a caller told it did not win the row must not put bytes in the deployment's store. An
    implementation that wrote the file before asking, or asked and ignored the answer, fails
    here without needing a race to be reproduced.
    """
    import api.services.agent_default_images as service

    async def lost(conn, **kwargs):
        return False

    monkeypatch.setattr(service, "claim_agent_default_image", lost)

    response = await deployment["admin"].post(
        f"/projects/{SLUG_A}/agents/{FACELESS}/image", files=_upload(_png())
    )
    assert response.status_code == 200, response.text
    assert response.json()["promoted_to_deployment_default"] is False
    assert _promoted_files(FACELESS) == []


@pytest.mark.asyncio
async def test_two_concurrent_uploads_promote_exactly_once(deployment, monkeypatch):
    """The window `INSERT OR IGNORE` closes, driven rather than argued.

    Check-then-write would have both callers read no row, both decide to promote, and the
    loser write its file **after** losing the row - so the table would name one engagement and
    the bytes would come from the other. The two payloads are different formats on purpose:
    the loser's file would land at `<agent>.jpg` beside the winner's `<agent>.png` rather than
    overwriting it, which is what makes "exactly one file" say something.

    **The barrier is what makes this a test rather than a hope.** Two `POST`s under
    `asyncio.gather` do *not* interleave here - the first upload's claim completes before the
    second one begins - so the window is never entered and a check-then-write implementation
    passes. It did: the version of this test without the barrier went green against exactly
    the defect it was written to forbid. Holding both callers at the moment of decision until
    both have arrived is what forces the schedule in which the two implementations differ, and
    it is the difference between asserting the property and asserting that the machine
    happened not to exercise it.
    """
    import api.services.agent_default_images as service

    real_claim = service.claim_agent_default_image
    barrier = asyncio.Barrier(2)

    async def claim_together(conn, **kwargs):
        await barrier.wait()
        return await real_claim(conn, **kwargs)

    monkeypatch.setattr(service, "claim_agent_default_image", claim_together)

    responses = await asyncio.gather(
        deployment["admin"].post(
            f"/projects/{SLUG_A}/agents/{FACELESS}/image", files=_upload(_png())
        ),
        deployment["admin"].post(
            f"/projects/{SLUG_B}/agents/{FACELESS}/image",
            files=_upload(_jpeg(), "image/jpeg"),
        ),
    )
    assert [r.status_code for r in responses] == [200, 200], [r.text for r in responses]

    promotions = [r.json()["promoted_to_deployment_default"] for r in responses]
    assert promotions.count(True) == 1, f"exactly one call must win the claim, got {promotions}"

    row = await _row(FACELESS)
    assert row is not None
    winner = SLUG_A if promotions[0] else SLUG_B
    assert row["promoted_from_slug"] == winner

    files = _promoted_files(FACELESS)
    assert files == [f"{FACELESS}{row['extension']}"], (
        f"the promoted store holds {files}, so a call that lost the row still wrote a file"
    )


# ── The deployment door ─────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_the_promoted_portrait_is_served_to_a_caller_with_no_login(deployment):
    """Unauthenticated, like the branding image, and for the same reason: the interview page.

    Fetched rather than spelled. `resolve_agent_config` answers an address, and an address is a
    promise that something answers - comparing it to the string that built it is a spell-check
    of the resolver against itself, which is how the per-project door came to return
    `/api/projects/...` and 404 in the browser for a fortnight.
    """
    original = _png()
    await deployment["admin"].post(
        f"/projects/{SLUG_A}/agents/{FACELESS}/image", files=_upload(original)
    )
    address = (await resolve_agent_config(SLUG_B, FACELESS))["image_url"]

    served = await deployment["anonymous"].get(address)
    assert served.status_code == 200, (
        f"the resolved address does not resolve: {address!r} answered {served.status_code}"
    )
    assert "://" not in address, "the address must not reach off-site"
    assert served.headers["x-content-type-options"] == "nosniff"
    # Downscaling is `prepare_portrait`'s and is asserted where it holds; what matters here is
    # that the promoted store holds the *prepared* bytes rather than the raw upload.
    assert served.content == (promoted_default_dir() / f"{FACELESS}.png").read_bytes()


@pytest.mark.asyncio
async def test_the_deployment_door_answers_404_for_an_agent_with_no_promoted_default(
    deployment,
):
    response = await deployment["anonymous"].get(f"/api/agents/{FACELESS}/image")
    assert response.status_code == 404
    assert response.json()["detail"] == "No default portrait for this agent."


@pytest.mark.asyncio
async def test_the_deployment_door_names_an_agent_outside_the_roll(deployment):
    """A different sentence, deliberately: the roll is a global constant already published by
    `GET /projects/{slug}/agents/config`, so naming it discloses nothing about any engagement,
    and the caller who reaches it is an operator with a typo."""
    response = await deployment["anonymous"].get("/api/agents/no_such_agent/image")
    assert response.status_code == 404
    assert response.json()["detail"] == "Unknown agent 'no_such_agent'"


@pytest.mark.asyncio
async def test_a_row_naming_an_unservable_extension_is_refused_rather_than_guessed_at(
    deployment,
):
    """The one guard on this branch whose reach was described and never established.

    `promoted_default_file` refuses a row whose extension maps to no accepted content type,
    because serving bytes under a guessed type from an unauthenticated door is worse than
    answering that there is nothing here. Only a hand-edited row reaches it - the map is
    inverted from `PORTRAIT_CONTENT_TYPES`, so a storable extension cannot become unservable
    by drift - so a hand-edited row is what this drives.

    **The file is written as well as the row, and that is the whole test.** Without it the
    door's own `path.exists()` check answers the same 404 for a different reason, and a
    version of the guard that guessed `application/octet-stream` would pass just as happily.
    With the bytes present, guessing serves them and refusing does not.
    """
    await deployment["admin"].post(
        f"/projects/{SLUG_A}/agents/{FACELESS}/image", files=_upload(_png())
    )
    async with get_system_connection() as conn:
        await conn.execute(
            "UPDATE agent_default_images SET extension = ? WHERE agent_id = ?",
            (".bmp", FACELESS),
        )
        await conn.commit()
    (promoted_default_dir() / f"{FACELESS}.bmp").write_bytes(_png())
    forget_agent_default_images()

    assert promoted_default_file(FACELESS) is None, (
        "an extension no accepted content type maps to was resolved to a file to serve"
    )
    response = await deployment["anonymous"].get(f"/api/agents/{FACELESS}/image")
    assert response.status_code == 404, (
        f"the door served {response.status_code} for a row naming an unservable extension"
    )
    assert response.json()["detail"] == "No default portrait for this agent."


@pytest.mark.asyncio
async def test_the_promoted_url_is_not_the_slug_it_came_from(deployment):
    """The address must not name the engagement that uploaded it.

    Two reasons, and only one of them is privacy: a project-scoped address would tie every
    other project's rendering to the continued existence of that engagement, and it would put
    one client's slug in another client's markup.
    """
    await deployment["admin"].post(
        f"/projects/{SLUG_A}/agents/{FACELESS}/image", files=_upload(_png())
    )
    address = promoted_default_url(FACELESS)
    assert SLUG_A not in address
    assert "/projects/" not in address
