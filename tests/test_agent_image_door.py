"""`POST` and `GET /projects/{slug}/agents/{agent_id}/image`, over HTTP.

`tests/test_agent_image_upload.py` drives `prepare_portrait` directly, because the downscale
and the EXIF strip are properties of the bytes that function returns. This file is about the
**door**: who may open it, what it stores, where, under what name, and what the unauthenticated
`GET` beside it will hand to a participant's browser.

The split matters. CLAUDE.md records eight occasions on this project where a property was
verified one layer away from where it holds, and the shape available here is exactly that one:
it is cheap to assert `prepare_portrait` strips EXIF and cheap to assert this door answers 200,
and neither says the served file is clean. So `test_a_phone_photograph_is_served_without_the_
location_it_was_taken_at` reads the bytes back out of the `GET`, which is the layer a
participant actually receives.
"""

import io

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from PIL import Image

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
from api.services.image_intake import MAX_PORTRAIT_BYTES, MAX_PORTRAIT_EDGE

SLUG_A = "agent-image-door-alpha"
SLUG_B = "agent-image-door-beta"

AVERY = "stakeholder_interviewer"

ACCESS_DENIED = "Access denied to this project"
ADMIN_REQUIRED = (
    "Project administration required - org admin or above, or project_admin on this project"
)

# The same rule `test_agent_config_door.py` states for its own sentinels: a value the system
# cannot produce on its own, so "the override survived" and "there is no row and the default
# came back" cannot satisfy the same assertion.
SENTINEL_NAME = "Ellie Marsh-Not-A-Default"


def _encode(image: Image.Image, image_format: str, **options) -> bytes:
    buffer = io.BytesIO()
    image.save(buffer, image_format, **options)
    return buffer.getvalue()


def _png(size: tuple[int, int] = (900, 600)) -> bytes:
    """Larger than `MAX_PORTRAIT_EDGE` on purpose, so every use of it exercises the downscale."""
    return _encode(Image.new("RGB", size, "white"), "PNG")


def _jpeg(size: tuple[int, int] = (900, 600)) -> bytes:
    return _encode(Image.new("RGB", size, "white"), "JPEG")


def _phone_photograph() -> bytes:
    """A JPEG carrying the photographer's location, as a phone writes it."""
    exif = Image.Exif()
    exif[0x8825] = {1: "N", 2: (51.0, 30.0, 0.0), 3: "W", 4: (0.0, 7.0, 0.0)}
    return _encode(Image.new("RGB", (900, 600), "white"), "JPEG", exif=exif)


def _project_body(slug: str) -> dict:
    return {
        "client_slug": slug,
        "llm_mode": "standard",
        "sector": "transport",
        "stakeholder_groups": [],
        "value_stream_labels": [],
        "review_gates": True,
        "slack_channel": "",
        "approver_name": "Approver Fixture", "approver_email": "approver@fixture.test",}


def _client_for(username: str, role: str, org_id: int | None = None) -> AsyncClient:
    from api.main import app

    token = create_access_token(username, role, "test-secret", org_id=org_id)
    return AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        headers={"Authorization": f"Bearer {token}"},
    )


def _anonymous() -> AsyncClient:
    """No Authorization header at all - the participant reading the interview page."""
    from api.main import app

    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


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


def _upload(data: bytes, content_type: str = "image/png", filename: str = "portrait.png"):
    return {"file": (filename, data, content_type)}


@pytest_asyncio.fixture
async def doors(tmp_path, monkeypatch, client):
    """Two projects under two organisations, and callers of four different authorities.

    DATABASE_DIR and PROJECTS_DIR are redirected at this test's own tmp_path for the reason
    CLAUDE.md gives - the shared, persistent /tmp/agentpool_test makes a fixture that inserts a
    fixed username pass once and fail on every run afterwards. PROJECTS_DIR matters twice as
    much here as it does for the configuration door: this one writes files under it.
    """
    monkeypatch.setenv("DATABASE_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("PROJECTS_DIR", str(tmp_path / "projects"))
    get_settings.cache_clear()

    for slug in (SLUG_A, SLUG_B):
        r = await client.post("/projects", json=_project_body(slug))
        assert r.status_code in (200, 201), r.text

    async with get_system_connection() as sys_conn:
        org_a = await insert_organisation(sys_conn, slug="ai-org-alpha", name="Alpha")
        org_b = await insert_organisation(sys_conn, slug="ai-org-beta", name="Beta")
        await insert_project_registry(
            sys_conn, slug=SLUG_A, org_id=org_a, display_name=SLUG_A
        )
        await insert_project_registry(
            sys_conn, slug=SLUG_B, org_id=org_b, display_name=SLUG_B
        )
        await insert_user(
            sys_conn, username="ai-outsider", email="ai-outsider@example.com",
            role="reviewer", hashed_pw="x",
        )
        await sys_conn.commit()

    await _seed_member(SLUG_A, username="ai-member", is_participant=True)
    await _seed_member(SLUG_A, username="ai-padmin", is_project_admin=True)

    outsider = _client_for("ai-outsider", "reviewer")
    member = _client_for("ai-member", "reviewer")
    padmin = _client_for("ai-padmin", "reviewer")
    admin_a = _client_for("ai-admin-a", "org_admin", org_id=org_a)
    anonymous = _anonymous()

    async with outsider, member, padmin, admin_a, anonymous:
        yield {
            "outsider": outsider, "member": member, "padmin": padmin,
            "admin_a": admin_a, "anonymous": anonymous,
        }

    get_settings.cache_clear()


# ── What the upload stores, and where ───────────────────────────────────────────────────


def stored_bytes_of(tmp_path, slug, agent_id, extension):
    """The bytes actually on disk, so a served response can be compared against them.

    Named rather than inlined because the assertion it feeds - "the URL resolves AND returns
    what was stored" - is worth reading as one line at the call site.
    """
    return (tmp_path / "projects" / slug / "assets" / "agents" / f"{agent_id}{extension}").read_bytes()


@pytest.mark.asyncio
async def test_an_uploaded_portrait_is_stored_downscaled_under_a_same_origin_url(doors, tmp_path):
    """The three properties of a successful upload, and the middle one is the point of Task 4.

    The URL is **same-origin**, which is what an uploaded portrait buys over the free-text
    field: an off-site `image_url` makes every participant's browser reach a third party from
    the unauthenticated interview page, disclosing their IP, their user agent and the timing of
    an interview in progress - on an engagement whose documents and inference may deliberately
    be on the premises.

    The stored bytes are asserted to be **smaller and shorter than the original**, not merely
    present. A door that wrote `data` straight through would satisfy "a file exists" exactly as
    well, and the file on disk is what the `GET` below serves.
    """
    original = _png((3000, 2000))
    r = await doors["admin_a"].post(
        f"/projects/{SLUG_A}/agents/{AVERY}/image", files=_upload(original)
    )
    assert r.status_code == 200, r.text
    body = r.json()

    # **Fetched, not spelled.** This asserted `body["url"] == f"/api/projects/..."` - the same
    # literal the handler produced, so it could not fail however wrong the address was. It was
    # wrong: nothing serves `/api/projects/...` (only `/api/templates` and `/api/interviews`
    # carry that prefix), so the portrait uploaded correctly, was served correctly at its real
    # path, and rendered as a broken image in the browser. Found by uploading through the
    # running server on 7 September, which is the one thing the test as written could not do.
    #
    # A URL is a promise that something answers. Asking whether it answers is the assertion;
    # comparing it to the string that built it is a spell-check of the handler against itself.
    assert "://" not in body["url"], "the stored address must not reach off-site"
    served = await doors["admin_a"].get(body["url"])
    assert served.status_code == 200, (
        f"the URL the door returned does not resolve: {body['url']!r} answered "
        f"{served.status_code}"
    )
    assert served.content == stored_bytes_of(tmp_path, SLUG_A, AVERY, ".png")
    assert body["original_bytes"] == len(original)
    assert body["bytes"] < body["original_bytes"]

    stored = tmp_path / "projects" / SLUG_A / "assets" / "agents" / f"{AVERY}.png"
    assert stored.exists(), f"nothing was written at {stored}"
    assert len(stored.read_bytes()) == body["bytes"]
    assert max(Image.open(io.BytesIO(stored.read_bytes())).size) == MAX_PORTRAIT_EDGE


@pytest.mark.asyncio
async def test_the_upload_leaves_the_rest_of_the_configuration_alone(doors):
    """The upload answers a URL; it does not write the row.

    `upsert_agent_config` **replaces** the row - a field absent from the call is cleared, which
    is the property `test_agent_config_door.py` asserts on the column. So an upload that wrote
    `image_url` on its own would silently clear this agent's name, voice, language, country and
    synthesis model, and the administrator would discover it on the interview page.

    Asserted against a sentinel display name saved first, so "the name survived" cannot be
    confused with "there is no row at all".
    """
    admin = doors["admin_a"]
    await admin.put(
        f"/projects/{SLUG_A}/agents/{AVERY}/config",
        json={"display_name": SENTINEL_NAME},
    )
    r = await admin.post(f"/projects/{SLUG_A}/agents/{AVERY}/image", files=_upload(_png()))
    assert r.status_code == 200, r.text

    async with get_connection(SLUG_A) as conn:
        project = await fetch_project(conn, slug=SLUG_A)
        row = await fetch_agent_config(conn, project_id=project["id"], agent_id=AVERY)
    assert row is not None, "the sentinel save did not land, so this test asserts nothing"
    assert row["display_name"] == SENTINEL_NAME
    # And the door did not quietly write the URL either - the caller sends it back through
    # `PUT .../config` with the rest of the row, which is the order the Setup section uses.
    assert row["image_url"] is None


@pytest.mark.asyncio
async def test_replacing_a_portrait_with_another_format_removes_the_old_file(doors, tmp_path):
    """A correctness requirement, not tidiness.

    The `GET` serves the first extension it finds, so a JPEG left beside a newly uploaded PNG
    goes on being served for ever: the administrator is told the upload succeeded and the old
    face stays on the interview page. Both halves are asserted - the old file is gone **and**
    the served bytes are the new ones - because a door that deleted nothing would still pass an
    assertion that the new file exists.
    """
    admin = doors["admin_a"]
    await admin.post(
        f"/projects/{SLUG_A}/agents/{AVERY}/image",
        files=_upload(_jpeg(), "image/jpeg", "portrait.jpg"),
    )
    directory = tmp_path / "projects" / SLUG_A / "assets" / "agents"
    assert (directory / f"{AVERY}.jpg").exists(), "the first upload did not land"

    await admin.post(f"/projects/{SLUG_A}/agents/{AVERY}/image", files=_upload(_png()))

    assert not (directory / f"{AVERY}.jpg").exists(), (
        "the previous portrait survived under its own extension, so the GET below may serve it"
    )
    served = await doors["anonymous"].get(f"/projects/{SLUG_A}/agents/{AVERY}/image")
    assert served.status_code == 200
    assert served.headers["content-type"] == "image/png"


# ── What the unauthenticated GET hands to a participant ─────────────────────────────────

@pytest.mark.asyncio
async def test_the_portrait_is_served_to_a_caller_with_no_login_at_all(doors):
    """No floor, deliberately, and this is the test that says so.

    The interview page renders this for a participant holding a session token and no account,
    which is why `GET /{slug}/branding/image` has no floor either - CLAUDE.md names those two
    as the deliberate exceptions on the whole surface. Driven with a client carrying **no
    Authorization header**, so it cannot pass on a token that happened to be lying around.
    """
    await doors["admin_a"].post(
        f"/projects/{SLUG_A}/agents/{AVERY}/image", files=_upload(_png())
    )

    r = await doors["anonymous"].get(f"/projects/{SLUG_A}/agents/{AVERY}/image")
    assert r.status_code == 200, r.text
    assert r.headers["content-type"] == "image/png"
    assert r.headers["x-content-type-options"] == "nosniff"
    assert Image.open(io.BytesIO(r.content)).format == "PNG"


@pytest.mark.asyncio
async def test_a_phone_photograph_is_served_without_the_location_it_was_taken_at(doors):
    """The privacy property at the layer a participant receives it, not at the function.

    `tests/test_agent_image_upload.py` proves `prepare_portrait` returns bytes with no EXIF.
    That is one layer away from the guarantee, which is that the **served** file carries no GPS
    coordinates - and this door writes a file, chooses what to write, and serves it back with no
    authentication whatever. So the bytes are read out of the response.

    The fixture asserts itself first. Without that, a `_phone_photograph` that silently stopped
    writing the GPS block would leave this test passing against nothing.
    """
    original = _phone_photograph()
    assert Image.open(io.BytesIO(original)).getexif().get_ifd(0x8825), (
        "the fixture must actually carry GPS, or this test asserts nothing"
    )

    r = await doors["admin_a"].post(
        f"/projects/{SLUG_A}/agents/{AVERY}/image",
        files=_upload(original, "image/jpeg", "portrait.jpg"),
    )
    assert r.status_code == 200, r.text

    served = await doors["anonymous"].get(f"/projects/{SLUG_A}/agents/{AVERY}/image")
    assert served.status_code == 200
    assert not Image.open(io.BytesIO(served.content)).getexif()


@pytest.mark.asyncio
async def test_a_project_that_has_uploaded_nothing_answers_404(doors):
    """The control. Every assertion above is about a portrait being served, and without this a
    door that served some other project's file - or the same file for every agent - would pass
    all of them."""
    r = await doors["anonymous"].get(f"/projects/{SLUG_A}/agents/{AVERY}/image")
    assert r.status_code == 404, r.text


@pytest.mark.asyncio
async def test_one_projects_portrait_is_not_served_by_another(doors):
    """Portraits are per project, so B must answer 404 while A answers 200."""
    await doors["admin_a"].post(
        f"/projects/{SLUG_A}/agents/{AVERY}/image", files=_upload(_png())
    )
    anonymous = doors["anonymous"]
    assert (await anonymous.get(f"/projects/{SLUG_A}/agents/{AVERY}/image")).status_code == 200
    assert (await anonymous.get(f"/projects/{SLUG_B}/agents/{AVERY}/image")).status_code == 404


@pytest.mark.asyncio
async def test_one_agents_portrait_is_not_served_for_another(doors):
    """The filename is the `agent_id`, so this is what stops Avery's face standing in for
    Laura's - the exact substitution the spec's initials fallback exists to avoid."""
    await doors["admin_a"].post(
        f"/projects/{SLUG_A}/agents/{AVERY}/image", files=_upload(_png())
    )
    r = await doors["anonymous"].get(f"/projects/{SLUG_A}/agents/second_interviewer/image")
    assert r.status_code == 404, r.text


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "filename,content_type,expected,forbidden",
    [
        # The extension the caller supplied disagrees with the type they declared. `.jpeg` is
        # the ordinary shape of this - a camera writes it and a person uploads it unchanged.
        ("portrait.jpeg", "image/jpeg", ".jpg", ".jpeg"),
        # No extension at all, which a filename from a paste or a scanner carries.
        ("portrait", "image/png", ".png", ""),
        # And the hostile shape. `file.filename` is the caller's string; if it ever reached the
        # stored name, this is what would be reaching it.
        ("../../../evil.php", "image/png", ".png", ".php"),
    ],
)
async def test_the_stored_extension_comes_from_the_declared_type_never_from_the_filename(
    doors, tmp_path, filename, content_type, expected, forbidden
):
    """The one input on this door that reaches the filesystem, and it is not the caller's.

    `extension` is `prepare_portrait`'s, taken from `PORTRAIT_CONTENT_TYPES` after the
    allowlist, after the magic-byte prefix and after Pillow agreed the decoded format matched.
    The property was **true and asserted by nothing** until this test: a review mutation taking
    the extension from `file.filename` instead passed all twenty-two tests in this file, because
    every one of them uploads a file whose name already agrees with its type.

    The consequence of that mutation is functional rather than exploitable, and it is worse for
    being quiet: `portrait.jpeg` stores as `.jpeg`, the `GET` looks for `.jpg` and answers 404
    for ever, and the replacement loop - which iterates the same three extensions - never cleans
    it up. So the assertion is two-sided, on the name that must exist **and** the name that must
    not, since "the right file is there" passes just as well when a second, wrong one is beside
    it.
    """
    data = _jpeg() if content_type == "image/jpeg" else _png()
    r = await doors["admin_a"].post(
        f"/projects/{SLUG_A}/agents/{AVERY}/image",
        files=_upload(data, content_type, filename),
    )
    assert r.status_code == 200, r.text

    root = tmp_path / "projects"
    directory = root / SLUG_A / "assets" / "agents"
    assert (directory / f"{AVERY}{expected}").exists()
    if forbidden:
        assert not (directory / f"{AVERY}{forbidden}").exists()
    # The assets tree holds that one file and nothing else, and nothing anywhere under the root
    # carries the caller's name - which is where the traversal in the third parameter would
    # show up rather than beside the portrait. (The root also holds `config.yaml`, written by
    # project creation, so it is scoped rather than compared whole.)
    written = {p.name for p in (root / SLUG_A / "assets").rglob("*") if p.is_file()}
    assert written == {f"{AVERY}{expected}"}, f"unexpected files in the assets tree: {written}"
    assert not list(root.rglob("*evil*")), "the caller's filename reached the filesystem"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "slug,shape",
    [
        ("%00", "a slug that is nothing but a NUL byte"),
        ("rev%00alpha", "a NUL byte in the middle of a real-looking slug"),
        ("x" * 400, "a slug longer than any filesystem will accept"),
    ],
)
async def test_a_slug_the_filesystem_will_not_accept_answers_404_and_not_500(doors, slug, shape):
    """Driven **anonymously**, because this door has no floor to stop anybody reaching it.

    All three answered 500 on delivery, from two different places: a NUL byte raises
    `ValueError` out of `_portrait_dir`'s `.resolve()`, and an over-long name resolves perfectly
    well and then raises `OSError(ENAMETOOLONG)` at the `exists()` in the serving loop. So the
    two halves have to be guarded separately - a fix at the first place alone leaves the third
    parameter failing, which is exactly why it is parametrised rather than asserted once.

    `is_contained_slug` has carried this guard since it was written; `_portrait_dir` reasoned
    correctly about not reusing that function for the *root* and dropped the half that was not
    about the root at all.

    Not merely tidiness: it is unauthenticated, reachable by anyone who can reach the port, and
    it writes a stack trace to the log on every request. It also made the door's own docstring
    untrue, which is the shape CLAUDE.md names - a guard described rather than established.
    """
    r = await doors["anonymous"].get(f"/projects/{slug}/agents/{AVERY}/image")
    assert r.status_code == 404, f"{shape} answered {r.status_code}: {r.text[:200]}"
    assert r.json()["detail"] == "No portrait found for this agent.", (
        "a hostile slug must be indistinguishable from a project that uploaded nothing"
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("slug", ["%00", "x" * 400])
async def test_the_same_slugs_answer_404_on_the_upload_door_too(doors, client, slug):
    """The `POST` side of the same defect, refused at `_assert_project_exists`.

    Lower stakes - it is behind the administration gate, so only somebody who could already
    upload can reach it - but it is the identical `Path.exists()` on a caller-chosen name, one
    function above, and a known 500 left beside a fixed one is what lends false confidence to
    the entry next to it.

    Driven as a **sysadmin**, because that is the only caller `check_project_access` lets
    through to the existence check on a slug that does not exist.
    """
    r = await client.post(
        f"/projects/{slug}/agents/{AVERY}/image", files=_upload(_png())
    )
    assert r.status_code == 404, r.text


def test_the_portrait_directory_cannot_escape_the_projects_root(monkeypatch, tmp_path):
    """Driven as a pure function over given slugs, both the shapes it must refuse and the shape
    it must not.

    CLAUDE.md: a guard's reach must be **established, not described** - and this is the one
    input on this door that an anonymous caller chooses freely, since the `GET` has no floor to
    stop them before the string is joined onto a filesystem path. A one-sided test would pass
    against a function that refused everything as well as against one that refused nothing, so
    the legitimate slug is asserted to resolve *inside* the root.
    """
    from api.routers.agent_config import _portrait_dir

    monkeypatch.setenv("PROJECTS_DIR", str(tmp_path / "projects"))
    get_settings.cache_clear()
    root = (tmp_path / "projects").resolve()

    inside = _portrait_dir("acme-rail")
    assert inside is not None and str(inside).startswith(str(root) + "/")

    for escape in ("../elsewhere", "../../etc", "/etc", "a/../../b"):
        assert _portrait_dir(escape) is None, f"{escape!r} resolved to a path outside the root"

    # And the names the filesystem refuses outright, which are a different failure from a name
    # that points somewhere else: `.resolve()` raises on these rather than answering a path, so
    # a containment check written without a `try` never runs at all.
    for unusable in ("\x00", "rev\x00alpha"):
        assert _portrait_dir(unusable) is None, f"{unusable!r} raised instead of being refused"

    get_settings.cache_clear()


# ── What the upload refuses ─────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_a_payload_that_is_not_the_type_it_declares_is_refused(doors, tmp_path):
    """The magic-byte prefix check, kept in front of the decoder.

    `prepare_portrait` performs a strictly stronger version of this - it decodes and compares
    the reported format - but only after handing the whole payload to Pillow. The cheap refusal
    stays, exactly as `upload_branding_image` has it. Asserted with the branding door's own
    sentence so the two doors are visibly the same check rather than two spellings of one.

    The absence of a stored file is asserted too: a refusal raised after the write is not a
    refusal, which is the rule the knowledge-tier doors follow for a purge.
    """
    r = await doors["admin_a"].post(
        f"/projects/{SLUG_A}/agents/{AVERY}/image",
        files=_upload(_jpeg(), "image/png", "lying.png"),
    )
    assert r.status_code == 422, r.text
    assert r.json()["detail"] == "File content does not match declared content type"
    assert not (tmp_path / "projects" / SLUG_A / "assets" / "agents").exists()


@pytest.mark.asyncio
async def test_a_type_outside_the_allowlist_is_refused_and_named(doors):
    """`describeError` puts this sentence in front of the administrator, so it names the type
    they sent and the ones they may send. "The image could not be uploaded" would send them
    back to try the same file again."""
    r = await doors["admin_a"].post(
        f"/projects/{SLUG_A}/agents/{AVERY}/image",
        files=_upload(b"GIF89a" + b"\0" * 32, "image/gif", "portrait.gif"),
    )
    assert r.status_code == 422, r.text
    detail = r.json()["detail"]
    assert "image/gif" in detail
    assert "image/png" in detail and "image/jpeg" in detail and "image/webp" in detail


@pytest.mark.asyncio
async def test_a_payload_above_the_ceiling_is_refused_and_the_message_names_the_limit(doors):
    """The ceiling belongs to `prepare_portrait`, and the door returns its sentence verbatim.

    Deliberately **not** restated in the router: a second copy of the number is a second thing
    to change. The payload carries a real PNG prefix so it clears the magic-byte check first,
    which is what makes this a test of the ceiling rather than of the check in front of it.
    """
    oversize = b"\x89PNG\r\n\x1a\n" + b"\0" * MAX_PORTRAIT_BYTES
    r = await doors["admin_a"].post(
        f"/projects/{SLUG_A}/agents/{AVERY}/image", files=_upload(oversize)
    )
    assert r.status_code == 422, r.text
    assert str(MAX_PORTRAIT_BYTES // (1024 * 1024)) in r.json()["detail"]


@pytest.mark.asyncio
async def test_a_payload_that_is_no_image_at_all_is_a_refusal_and_not_a_500(doors):
    """`PortraitRejected` is the only exception `prepare_portrait` raises for any input, and it
    is the caller's fault rather than the server's. A PNG prefix on random bytes clears the
    magic-byte check and dies in the decoder, which is the path this asserts."""
    r = await doors["admin_a"].post(
        f"/projects/{SLUG_A}/agents/{AVERY}/image",
        files=_upload(b"\x89PNG\r\n\x1a\n" + b"not an image at all"),
    )
    assert r.status_code == 422, r.text


def test_every_accepted_content_type_has_a_magic_prefix():
    """The prefix table and the allowlist are held equal, because the failure is silent.

    `data[:4].startswith(b"")` is `True` for every payload, so a fourth type added to
    `PORTRAIT_CONTENT_TYPES` with no entry here would get a **vacuous** check and nothing on
    screen would say the door had stopped verifying it. That is the shape of defect this
    project keeps finding: a guard that reads as working while covering nothing.
    """
    from api.routers.agent_config import _MAGIC_PREFIXES
    from api.services.image_intake import PORTRAIT_CONTENT_TYPES

    assert set(_MAGIC_PREFIXES) == set(PORTRAIT_CONTENT_TYPES)
    assert all(prefix for prefix in _MAGIC_PREFIXES.values()), (
        "an empty prefix is a prefix of everything, which is no check at all"
    )


# ── Authority ───────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_a_member_may_not_upload_a_portrait(doors):
    """The administration axis, over the membership floor. Giving an agent a face is
    configuring the engagement, exactly as naming it and choosing its voice are - so a reviewer
    who clears the floor is still refused, and the refusal names the authority they lack.

    The floor is proven cleared in the same test by reading the configuration, because a caller
    refused by two gates at once says nothing about either.
    """
    member = doors["member"]
    assert (await member.get(f"/projects/{SLUG_A}/agents/{AVERY}/config")).status_code == 200

    r = await member.post(f"/projects/{SLUG_A}/agents/{AVERY}/image", files=_upload(_png()))
    assert r.status_code == 403, r.text
    assert r.json()["detail"] == ADMIN_REQUIRED


@pytest.mark.asyncio
async def test_a_project_admin_may_upload_a_portrait_on_their_own_engagement(doors):
    """The widened half of the administration axis - a client's own project administrator
    gives their interviewer a face, the same authority that lets them name it."""
    r = await doors["padmin"].post(
        f"/projects/{SLUG_A}/agents/{AVERY}/image", files=_upload(_png())
    )
    assert r.status_code == 200, r.text


@pytest.mark.asyncio
async def test_a_non_member_is_refused_by_the_floor(doors):
    r = await doors["outsider"].post(
        f"/projects/{SLUG_A}/agents/{AVERY}/image", files=_upload(_png())
    )
    assert r.status_code == 403, r.text
    assert r.json()["detail"] == ACCESS_DENIED


@pytest.mark.asyncio
async def test_an_administrator_of_another_engagement_is_refused(doors):
    """The caller an "anonymous is refused" test cannot see.

    `admin_a` is a real, fully-privileged org_admin whose organisation owns A and not B, so it
    clears the administration axis on its login role alone and only the floor can refuse it
    here. This is the shape of the hole sp38 found in `milestones.py`, and the floor is
    asserted to come **first**: the refusal is the floor's sentence, not the gate's.
    """
    r = await doors["admin_a"].post(
        f"/projects/{SLUG_B}/agents/{AVERY}/image", files=_upload(_png())
    )
    assert r.status_code == 403, r.text
    assert r.json()["detail"] == ACCESS_DENIED


@pytest.mark.asyncio
async def test_an_outsider_is_refused_before_being_told_whether_the_slug_exists(doors):
    """The order the branding door's docstring gives, asserted rather than described.

    A caller from outside the engagement must not be able to use this door to learn which slugs
    exist, so the floor runs before the existence check - and a real slug and an invented one
    must therefore be indistinguishable to them. Both are driven, because a door that answered
    403 to everything would pass a test that only sent the real one.
    """
    outsider = doors["outsider"]
    real = await outsider.post(
        f"/projects/{SLUG_A}/agents/{AVERY}/image", files=_upload(_png())
    )
    invented = await outsider.post(
        f"/projects/no-such-engagement-at-all/agents/{AVERY}/image", files=_upload(_png())
    )
    assert real.status_code == invented.status_code == 403
    assert real.json()["detail"] == invented.json()["detail"] == ACCESS_DENIED


@pytest.mark.asyncio
@pytest.mark.parametrize("verb", ["post", "get"])
async def test_an_agent_id_outside_the_roll_is_refused_by_both_verbs(doors, verb):
    """`agent_id` becomes the stored **filename**, so an id outside `AGENT_IDENTITY` is both a
    typo and the one string on this path that a caller could otherwise steer at the
    filesystem. Refused on the roll, which answers both concerns at once."""
    url = f"/projects/{SLUG_A}/agents/interveiwer/image"
    r = (
        await doors["admin_a"].post(url, files=_upload(_png())) if verb == "post"
        else await doors["anonymous"].get(url)
    )
    assert r.status_code == 404, r.text
    if verb == "post":
        assert "interveiwer" in r.json()["detail"]


@pytest.mark.asyncio
async def test_probing_an_unknown_slug_materialises_no_database(doors, client):
    """A slug with no database is a 404, and asking must not create one.

    Driven as a **sysadmin**, because nobody else reaches the check - every other role is
    refused by `check_project_access` first. So this is the file-per-guess hazard CLAUDE.md
    names twice rather than an escalation, and a sysadmin is exactly the caller for whom this
    door would otherwise be the file-creating one.
    """
    from api.database import get_db_path

    unknown = "no-such-project-agent-image"
    assert not get_db_path(unknown).exists(), "the fixture slug already exists"

    r = await client.post(
        f"/projects/{unknown}/agents/{AVERY}/image", files=_upload(_png())
    )
    assert r.status_code == 404, r.text
    assert not get_db_path(unknown).exists(), (
        "asking about an unknown slug created its database - one file per guess"
    )
