# tests/test_voice_catalogue.py
"""The voices door: both listings, the accent that reaches the wire, and the table that is gone.

**Every assertion here is on the request**, through an `httpx.MockTransport`, never on the
status code alone. This branch has already paid for that lesson twice: a security gate moved to
*after* synthesis still answered 403, and the only thing that caught it was reading what went
out. **No real ElevenLabs call is made by anything in this file.**

The two properties that are impossible to see any other way:

- **Preview costs nothing.** `preview_url` is a sample the API already hosts, so a picker plays
  it and makes no synthesis call. An implementation that spoke a line through `synthesise`
  instead would sound *identical* to a listener and cost characters on every preview, so the
  only thing that can distinguish them is an assertion that nothing reached
  `/v1/text-to-speech`.
- **Both listings are asked.** The rate exists only on `shared-voices` and Irish exists only
  there; accents and the account's own voices come from `/v1/voices`. A door built on one of
  them returns a plausible list that is missing either the cost or half the accents, and no
  assertion about the *response body* alone can tell that apart from a quiet account.
"""
from __future__ import annotations

import ast
import json
import re
from pathlib import Path

import httpx
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
    insert_organisation,
    insert_project,
    insert_project_registry,
    insert_stakeholder,
    insert_user,
    link_membership,
)
from api.services.voice_settings import (
    DEFAULT_INTERVIEW_ACCENT,
    project_interview_accent,
)

REPO = Path(__file__).resolve().parent.parent

SLUG_A = "voices-alpha"
SLUG_B = "voices-beta"

# The eight ids the two retired tables held between them - `VOICE_LOCALE_TABLE` in Taylor's
# prompt and its dead TypeScript twin `ui/src/utils/voiceLocale.ts`, which disagreed on four of
# them. Named here so the guards below can say "none of these" without reading them back out of
# the source they are checking, which would make the assertion unfalsifiable.
RETIRED_VOICE_IDS = {
    "21m00Tcm4TlvDq8ikWAM",  # Rachel  - en/GB and en/US in the prompt table
    "AZnzlk1XvdvUeBnXmlld",  # Domi    - en/AU
    "MF3mGyEYCl7XYWbV9V6O",  # Elli    - en/NZ
    "TxGEqnHWrfWFTfGW9XjX",  # Josh    - en/CA
    "pNInz6obpgDQGcFmaJgB",  # Adam    - fr/FR in the prompt, de/DE in the twin
    "yoZ06aMxZJJ28mfd3POQ",  # Sam     - de/DE in the prompt, es/ES in the twin
    "ErXwobaYiN019PkySvjV",  # Antoni  - es/ES in the prompt only
    "EXAVITQu4vr4xnSDxMaL",  # Bella   - en/US in the twin only
    "VR6AewLTigWG4xSOukaG",  # Arnold  - fr/FR in the twin only
}

# Two account voices, in the shape `GET /v1/voices` answers: accent and gender under `labels`,
# `available_for_tiers` present and empty, and no rate anywhere.
ACCOUNT_BODY = {
    "voices": [
        {
            "voice_id": "acct-daniel",
            "name": "Daniel",
            "labels": {"accent": "british", "gender": "male", "age": "middle-aged"},
            "preview_url": "https://storage.example/daniel.mp3",
            "available_for_tiers": [],
            "verified_languages": [{"language": "en", "model_id": "eleven_multilingual_v2"}],
        },
        {
            "voice_id": "acct-alba",
            "name": "Alba Mac - Animated Scottish",
            "labels": {"accent": "scottish", "gender": "female"},
            "preview_url": "https://storage.example/alba.mp3",
            "available_for_tiers": [],
        },
    ]
}

# Two library voices, in the shape `GET /v1/shared-voices` answers: accent and gender at the
# top level, and the rate that exists nowhere else. One of them is already in the account.
LIBRARY_BODY = {
    "voices": [
        {
            "public_owner_id": "owner-1",
            "voice_id": "lib-seamus",
            "name": "Seamus",
            "accent": "irish",
            "gender": "male",
            "preview_url": "https://storage.example/seamus.mp3",
            "rate": 0.6,
            "fiat_rate": 0.12,
            "free_users_allowed": True,
            "language": "en",
        },
        {
            "public_owner_id": "owner-2",
            "voice_id": "acct-daniel",
            "name": "Daniel",
            "accent": "british",
            "gender": "male",
            "preview_url": "https://storage.example/daniel.mp3",
            "rate": 0.0,
            "free_users_allowed": False,
            "language": "en",
        },
    ]
}


def _catalogue_wire(
    monkeypatch,
    *,
    account: dict | int = ACCOUNT_BODY,
    library: dict | int = LIBRARY_BODY,
    library_probe: dict | int | None = None,
    added: dict | int | None = None,
) -> list[httpx.Request]:
    """Point **the shared ElevenLabs client** at a `MockTransport` and record every request.

    Each argument takes either a body to answer with or a status code to fail with, which is
    what lets one fixture drive "the library is unreachable" without a second handler. **The
    handler answers 404 for any other path**, deliberately: a request this file has not
    anticipated must show up as a failure rather than as a cheerful empty list.

    **It is installed on `http_clients._tts_client`, not on a module's imported name**, and
    that is the difference between a recorder one module wide and one that sees every route
    through this provider. `get_tts_client` is imported *by value* into both
    `voice_catalogue` and `interview_service`, so rebinding either module's copy leaves the
    other's untouched - but every copy is the same function object, and every copy returns
    this module global. Setting the global therefore catches a synthesis call whatever module
    it arrives from and however its import happens to be written, which is the property
    `_import_handles` holds one layer down for imports.

    It replaced a `setattr("api.services.voice_catalogue.get_tts_client", ...)` that was one
    module wide, and the old form did not merely fail to *record* an out-of-module synthesis
    call - it **armed** one. This fixture writes a non-empty `elevenlabs_api_key` onto the
    shared settings object, which is exactly the guard (`raise ValueError("ELEVENLABS_API_KEY
    not configured")`) that otherwise stops `synthesise` before any socket. Driven: `await
    speak(...)` added to `list_voices` did not leave the wire assertion green - it failed
    noisily, and for the wrong reason: a **real HTTPS request to api.elevenlabs.io**, refused
    400, rather than the assertion that names the URL. A test fixture that both blinds the
    recorder and unlocks the provider is worse than no fixture.

    **`/v1/text-to-speech` is answered 200 rather than 404**, and that is deliberate against
    the 404-for-anything-else rule above. It is the one path this file asserts the *absence*
    of, so it must be able to succeed: answered 404, an injected synthesis call raises, the
    door 500s, and the test fails on its status assertion instead of on the assertion that
    names the URL - a right answer for a wrong reason, and one that says nothing about
    synthesis to whoever reads the failure.

    **What it still cannot see:** a caller that builds its own `httpx.AsyncClient` rather than
    asking `get_tts_client()`. `api/services/voice_metadata.py` deliberately does exactly that,
    for event-loop reasons of its own. It does not synthesise; if anything on this path ever
    reaches for its own client, this recorder is blind to it and
    `test_the_voices_path_imports_nothing_that_can_synthesise` is the guard that is not.

    **A second gap installing on the global rather than a name opens up:** `close_http_clients()`
    called while this recorder is installed sets `_tts_client` back to `None`, and the next
    `get_tts_client()` silently rebuilds a **real** `httpx.AsyncClient` - un-mocking every route
    this fixture armed, from that call onward. The old one-module `setattr` could not do this,
    since it replaced the function itself rather than a value the function reads. Not reached by
    anything in this file today - nothing that uses this fixture calls `close_http_clients()`.

    **The library half honours `accent` and `gender`, as the real endpoint does.** A stub that
    ignored them would return every library voice to every query, and the one property that
    matters most here - that an Irish voice is *absent* from a british-filtered result and
    still reachable through `accent_options` - would be unobservable, because the Irish voice
    would be sitting in the result set either way.

    **`library_probe` answers the *unfiltered* `shared-voices` call only**, so a test can fail
    the accent probe while the narrowed result set succeeds. That pair is not reachable with
    one `library` argument, and it is the pair that distinguishes two independent calls from
    two calls sharing a `try`. The two are told apart by whether the request carries a
    narrowing parameter, so a test using it must apply a **non-empty** accent: `?accent=`
    clears the filter and the result set then goes out unfiltered too, which is genuinely
    indistinguishable on the wire rather than a shortcoming of the stub.
    """
    seen: list[httpx.Request] = []

    def _answer(spec, request: httpx.Request) -> httpx.Response:
        if isinstance(spec, int):
            return httpx.Response(spec, json={"detail": "no"})
        return httpx.Response(200, json=spec)

    def _narrow(spec, request: httpx.Request) -> httpx.Response:
        if isinstance(spec, int):
            return httpx.Response(spec, json={"detail": "no"})
        kept = [
            v
            for v in spec["voices"]
            if all(
                request.url.params.get(field) in (None, v.get(field))
                for field in ("accent", "gender", "language")
            )
        ]
        return httpx.Response(200, json={**spec, "voices": kept})

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        path = request.url.path
        if path == "/v1/voices":
            return _answer(account, request)
        if path == "/v1/shared-voices":
            narrowing = {"accent", "gender", "language", "search"} & set(request.url.params)
            if library_probe is not None and not narrowing:
                return _narrow(library_probe, request)
            return _narrow(library, request)
        if path.startswith("/v1/voices/add/"):
            return _answer(added if added is not None else {"voice_id": "acct-new"}, request)
        if path.startswith("/v1/text-to-speech"):
            # Answered, not refused - see the docstring. The assertion is that nothing came
            # here, and an assertion about absence needs the path to have been available.
            return httpx.Response(200, content=b"audio-that-should-never-be-asked-for")
        return httpx.Response(404, json={"detail": f"unexpected path {path}"})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    monkeypatch.setattr("api.services.http_clients._tts_client", client)

    settings = get_settings()
    monkeypatch.setattr(settings, "elevenlabs_api_key", "test-key", raising=False)
    monkeypatch.setattr("api.services.voice_catalogue.get_settings", lambda: settings)
    return seen


def _client_for(username: str, role: str, org_id: int | None = None) -> AsyncClient:
    from api.main import app

    token = create_access_token(username, role, "test-secret", org_id=org_id)
    return AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        headers={"Authorization": f"Bearer {token}"},
    )


@pytest_asyncio.fixture
async def engagements(tmp_path, monkeypatch, client):
    """Two projects owned by two organisations, and four callers with four different standings.

    DATABASE_DIR and PROJECTS_DIR are redirected at this test's own tmp_path, following
    `tests/test_milestone_door_authority.py`: `users`, `project_memberships` and
    `project_registry` live in the shared, persistent system database, so a fixture inserting
    rows by fixed name passes once and fails on every run afterwards.

    The `project_admin` caller is the one that matters for the add door. An anonymous request
    is refused by the dependency and says nothing; a real, fully-privileged administrator *of
    this engagement* is the caller that isolates "the platform tier, not project
    administration".
    """
    monkeypatch.setenv("DATABASE_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("PROJECTS_DIR", str(tmp_path / "projects"))
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "tts"))
    get_settings.cache_clear()

    for slug in (SLUG_A, SLUG_B):
        res = await client.post(
            "/projects",
            json={
                "client_slug": slug,
                "llm_mode": "standard",
                "sector": "transport",
                "stakeholder_groups": [],
                "value_stream_labels": [],
                "review_gates": True,
                "slack_channel": "",
            },
        )
        assert res.status_code in (200, 201), res.text

    async with get_system_connection() as sys_conn:
        org_a = await insert_organisation(sys_conn, slug="voices-org-alpha", name="Alpha")
        org_b = await insert_organisation(sys_conn, slug="voices-org-beta", name="Beta")
        await insert_project_registry(
            sys_conn, slug=SLUG_A, org_id=org_a, display_name=SLUG_A
        )
        await insert_project_registry(
            sys_conn, slug=SLUG_B, org_id=org_b, display_name=SLUG_B
        )
        await sys_conn.commit()

    async with get_connection(SLUG_A) as conn:
        project = await fetch_project(conn, slug=SLUG_A)
        stakeholder_id = await insert_stakeholder(
            conn,
            project_id=project["id"],
            name="voices-padmin",
            email="voices-padmin@example.com",
            is_project_admin=True,
        )
    async with get_system_connection() as sys_conn:
        await insert_user(
            sys_conn,
            username="voices-padmin",
            email="voices-padmin@example.com",
            role="reviewer",
            hashed_pw="x",
        )
        user = await fetch_user(sys_conn, username="voices-padmin")
        await link_membership(
            sys_conn, user_id=user["id"], project_slug=SLUG_A, stakeholder_id=stakeholder_id
        )
        await sys_conn.commit()

    owner = _client_for("voices-admin-a", "org_admin", org_a)
    stranger = _client_for("voices-admin-b", "org_admin", org_b)
    padmin = _client_for("voices-padmin", "reviewer")
    async with owner, stranger, padmin:
        yield {"owner": owner, "stranger": stranger, "project_admin": padmin}

    get_settings.cache_clear()


def _urls(seen: list[httpx.Request]) -> list[str]:
    return [str(r.url) for r in seen]


def _library_calls(seen: list[httpx.Request]) -> list[httpx.Request]:
    """Every request to `shared-voices`, of which there are now **two** per listing.

    One is the unfiltered accent probe and one is the narrowed result set, and they ask
    different questions - so the assertions below select by what a request *carries* rather
    than by its index. Indexing would be quietly wrong the moment the probe's process cache is
    warm, which happens whenever one test calls the door twice.
    """
    return [r for r in seen if r.url.path == "/v1/shared-voices"]


# --- The two properties only the wire can show ----------------------------------------------


@pytest.mark.asyncio
async def test_the_door_asks_both_listings_and_neither_alone(engagements, monkeypatch):
    """One door, two listings, asserted on the wire.

    The rate lives only on `shared-voices` and Irish exists only there; the account's own
    voices and its accents come only from `/v1/voices`. A door that asked one of them would
    still answer 200 with a plausible list, so the response body cannot distinguish a
    one-endpoint picker from an account that happens to be small.
    """
    seen = _catalogue_wire(monkeypatch)

    res = await engagements["owner"].get(f"/projects/{SLUG_A}/voices")
    assert res.status_code == 200, res.text

    paths = [r.url.path for r in seen]
    assert "/v1/voices" in paths
    assert "/v1/shared-voices" in paths


@pytest.mark.asyncio
async def test_previewing_a_voice_reaches_no_text_to_speech_call(engagements, monkeypatch):
    """The whole reason preview is `preview_url`.

    Every voice in both listings carries a sample the API already hosts. Speaking one through
    `synthesise` would cost characters, be slower, and produce audio a listener could not tell
    from the free one - so the *only* thing that can distinguish the cheap implementation from
    the expensive one is this assertion. It is on the wire and not on the code, because a
    future caller reaching for `speak` would leave the source of this module untouched.

    **Its reach, stated as what it is and established by the test below rather than claimed
    here:** every route that asks `get_tts_client()`, from any module and under any spelling of
    the import, because the recorder is installed on the shared client itself. Not "whatever
    route a synthesis call arrives by" - which is what this docstring and its sibling's used to
    say, while the recorder was one module wide and the injection they existed to catch went
    to the real provider. A caller that builds its own `httpx.AsyncClient` is still outside it,
    and `test_the_voices_path_imports_nothing_that_can_synthesise` is what covers that.
    """
    seen = _catalogue_wire(monkeypatch)

    res = await engagements["owner"].get(f"/projects/{SLUG_A}/voices")
    assert res.status_code == 200, res.text

    assert seen, "no request went out at all - this assertion would pass vacuously"
    assert not [u for u in _urls(seen) if "text-to-speech" in u], _urls(seen)

    body = res.json()
    every = body["account"] + body["library"]
    assert every, "nothing was returned, so 'every entry carries a preview' is vacuous"
    assert all(v["preview_url"] for v in every), every


@pytest.mark.asyncio
async def test_the_wire_recorder_sees_a_synthesis_call_from_another_module(
    engagements, monkeypatch
):
    """The reach of the test above, established rather than described.

    This project has now had four guards whose own account of their coverage was wrong, and the
    repair each time is the same: drive one of the thing the guard claims to see. The claim here
    is "any route to text-to-speech, not just this module's" - so the call is made through
    `interview_service`'s **own** binding of `get_tts_client`, which is a different object from
    `voice_catalogue`'s and is the exact route the previous installation could not see. If the
    recorder is ever narrowed back to one module's imported name, this fails and the sentence
    above stops being true at the same moment.

    It is also the containment half. Under the previous fixture this same call left the machine
    for api.elevenlabs.io, because the fixture's own `elevenlabs_api_key` patch disarms the
    "not configured" guard that would otherwise have stopped it. A green suite is not evidence
    that no request went out; only a recorder in front of the socket is.
    """
    seen = _catalogue_wire(monkeypatch)

    from api.services.interview_service import speak

    await speak("sample", "acct-daniel", "eleven_turbo_v2")

    spoken = [u for u in _urls(seen) if "text-to-speech" in u]
    assert spoken, (
        "a synthesis call made through another module's binding was invisible to the "
        f"recorder, so the wire assertion above is one module wide: {_urls(seen)}"
    )


# --- Where the accent comes from, and where it goes ------------------------------------------


@pytest.mark.asyncio
async def test_the_projects_accent_reaches_the_library_query(engagements, monkeypatch):
    """The default filter is the project's setting, and it goes on the wire unmodified.

    Nothing translates it: the word stored in `interview_accent` is the word ElevenLabs is
    asked for. A translation would be a table, and a table of voice facts is what this branch
    exists to end.
    """
    seen = _catalogue_wire(monkeypatch)

    res = await engagements["owner"].get(f"/projects/{SLUG_A}/voices")
    assert res.status_code == 200, res.text
    assert res.json()["accent"] == DEFAULT_INTERVIEW_ACCENT == "british"
    assert res.json()["accent_source"] == "project"

    assert any(r.url.params.get("accent") == "british" for r in _library_calls(seen))


@pytest.mark.asyncio
async def test_a_saved_accent_becomes_the_default_filter(engagements, monkeypatch):
    """A Scottish engagement's picker opens on Scottish, and it says so on the wire.

    This is the decision the task had to make - where a project's locale comes from - asserted
    end to end: `PATCH /settings` stores it, and the very next listing asks ElevenLabs for it.
    """
    saved = await engagements["owner"].get(f"/projects/{SLUG_A}/settings")
    assert saved.status_code == 200, saved.text
    body = {**saved.json(), "interview_accent": "scottish"}
    patched = await engagements["owner"].patch(f"/projects/{SLUG_A}/settings", json=body)
    assert patched.status_code == 200, patched.text
    assert patched.json()["interview_accent"] == "scottish"

    seen = _catalogue_wire(monkeypatch)
    res = await engagements["owner"].get(f"/projects/{SLUG_A}/voices")
    assert res.status_code == 200, res.text
    assert res.json()["accent"] == "scottish"

    assert any(r.url.params.get("accent") == "scottish" for r in _library_calls(seen))


@pytest.mark.asyncio
async def test_an_explicit_accent_beats_the_projects_and_an_empty_one_clears_it(
    engagements, monkeypatch
):
    """Omitted and empty are different, and the picker needs both.

    Omitted means "you decide" and resolves to the project's setting; empty means the
    consultant has cleared the filter and wants every accent. Collapsing them - which a
    `default=""` on the query parameter would do - makes the project setting unclearable from
    the picker, and makes it impossible to browse the library for an accent the project has
    not chosen yet.
    """
    seen = _catalogue_wire(monkeypatch)
    res = await engagements["owner"].get(f"/projects/{SLUG_A}/voices?accent=irish")
    assert res.status_code == 200, res.text
    assert res.json()["accent"] == "irish"
    assert res.json()["accent_source"] == "request"
    assert any(r.url.params.get("accent") == "irish" for r in _library_calls(seen))

    cleared = _catalogue_wire(monkeypatch)
    res = await engagements["owner"].get(f"/projects/{SLUG_A}/voices?accent=")
    assert res.status_code == 200, res.text
    assert res.json()["accent"] == ""
    calls = _library_calls(cleared)
    assert calls, "the library was never asked, so 'no accent went out' is vacuous"
    assert all("accent" not in r.url.params for r in calls), _urls(cleared)
    # And the account list is not narrowed either, so clearing really does show everything.
    assert len(res.json()["account"]) == len(ACCOUNT_BODY["voices"])


@pytest.mark.asyncio
async def test_gender_is_forwarded_to_the_api_and_never_answered_from_a_list(
    engagements, monkeypatch
):
    """`labels.gender` is the authority on sex, and the filter is a query parameter.

    A curated map of which voice is which sex would be the sixth declaration of voice facts on
    a branch that exists to end the first five - and it would be wrong the first time a project
    overrode an interviewer's voice, which is the entire point of `project_agent_config`.
    """
    seen = _catalogue_wire(monkeypatch)

    res = await engagements["owner"].get(f"/projects/{SLUG_A}/voices?accent=&gender=female")
    assert res.status_code == 200, res.text

    assert any(r.url.params.get("gender") == "female" for r in _library_calls(seen))

    # The account endpoint takes no parameters at all, so the same narrowing has to happen
    # here - against the `labels.gender` the provider itself returned, which is reading its
    # answer rather than holding an opinion about its voices.
    assert [v["name"] for v in res.json()["account"]] == ["Alba Mac - Animated Scottish"]


@pytest.mark.asyncio
async def test_the_account_listing_is_narrowed_on_the_labels_the_api_returned(
    engagements, monkeypatch
):
    """Scottish is a label on the account voice, not a fact this codebase holds.

    Driven by *changing the provider's answer*: the same voice id, relabelled british, must
    stop matching. A local table would keep matching, which is the difference this asserts.
    """
    relabelled = json.loads(json.dumps(ACCOUNT_BODY))
    relabelled["voices"][1]["labels"]["accent"] = "british"

    _catalogue_wire(monkeypatch)
    res = await engagements["owner"].get(f"/projects/{SLUG_A}/voices?accent=scottish")
    assert [v["voice_id"] for v in res.json()["account"]] == ["acct-alba"]

    _catalogue_wire(monkeypatch, account=relabelled)
    res = await engagements["owner"].get(f"/projects/{SLUG_A}/voices?accent=scottish")
    assert res.json()["account"] == []


# --- What each listing can and cannot say ----------------------------------------------------


@pytest.mark.asyncio
async def test_the_rate_comes_from_the_library_and_the_account_says_nothing(
    engagements, monkeypatch
):
    """`rate` is `None` on an account voice, never `0.0`.

    "This listing does not say what the voice costs" and "this voice is free" are different
    statements, and `available_for_tiers` was `[]` on all 32 account voices on 4 September - so
    a substituted default would present every account voice as free on a picker whose whole job
    includes showing the cost.
    """
    _catalogue_wire(monkeypatch)
    res = await engagements["owner"].get(f"/projects/{SLUG_A}/voices?accent=")
    body = res.json()

    assert all(v["rate"] is None for v in body["account"]), body["account"]
    assert all(v["free_users_allowed"] is None for v in body["account"])
    assert [v["rate"] for v in body["library"]] == [0.6, 0.0]
    assert [v["free_users_allowed"] for v in body["library"]] == [True, False]
    # The one account voice whose rate is genuinely 0.0 in the library proves the distinction
    # is between None and 0.0 rather than between "falsy" and "set".
    assert body["library"][1]["rate"] == 0.0


@pytest.mark.asyncio
async def test_accent_and_sex_are_read_from_whichever_place_the_endpoint_puts_them(
    engagements, monkeypatch
):
    """`/v1/voices` nests them under `labels`; `/v1/shared-voices` has them at the top level.

    One normalised shape, so a picker does not have to know which listing an entry came from -
    and one place where that disagreement is absorbed rather than two.
    """
    _catalogue_wire(monkeypatch)
    body = (await engagements["owner"].get(f"/projects/{SLUG_A}/voices?accent=")).json()

    assert {(v["name"], v["accent"], v["gender"]) for v in body["account"]} == {
        ("Daniel", "british", "male"),
        ("Alba Mac - Animated Scottish", "scottish", "female"),
    }
    assert ("Seamus", "irish", "male") in {
        (v["name"], v["accent"], v["gender"]) for v in body["library"]
    }


@pytest.mark.asyncio
async def test_a_library_voice_already_in_the_account_is_marked_from_the_two_answers(
    engagements, monkeypatch
):
    """`in_account` is computed by comparing ids the two calls returned.

    Not from any list held here - which is what makes it right on a deployment whose account
    this repository has never seen.
    """
    _catalogue_wire(monkeypatch)
    body = (await engagements["owner"].get(f"/projects/{SLUG_A}/voices?accent=")).json()

    by_id = {v["voice_id"]: v for v in body["library"]}
    assert by_id["acct-daniel"]["in_account"] is True
    assert by_id["lib-seamus"]["in_account"] is False


@pytest.mark.asyncio
async def test_the_accent_options_come_from_the_unfiltered_account_listing(
    engagements, monkeypatch
):
    """The picker's accent dropdown is derived from the provider's answer, never declared.

    Derived from the **unfiltered** listing on purpose: computing it after narrowing would
    answer only the accent already selected, and the dropdown would offer one option.
    """
    _catalogue_wire(monkeypatch)
    body = (await engagements["owner"].get(f"/projects/{SLUG_A}/voices?accent=british")).json()

    assert body["account_accents"] == ["british", "scottish"]
    assert [v["voice_id"] for v in body["account"]] == ["acct-daniel"]


@pytest.mark.asyncio
async def test_an_accent_only_the_library_has_is_still_offered(engagements, monkeypatch):
    """**Irish is one of the four planned engagements and lives only in the library.**

    The first version of this door derived the options from the account listing alone, so a
    picker built on it could never offer Irish - and the only routes left were to hardcode a
    list of accents, which is the sixth declaration of voice facts on a branch that exists to
    end them, or to type it as free text, which is weight the open `interview_accent`
    vocabulary was not chosen to carry.

    The default filter is `british`, so the *result* is the one British library voice and the
    Irish one is genuinely absent from it - the stub narrows exactly as the endpoint does. The
    option is still there, which is the property: **what you can filter to is not the same
    question as what came back.**
    """
    _catalogue_wire(monkeypatch)
    body = (await engagements["owner"].get(f"/projects/{SLUG_A}/voices")).json()

    assert body["accent"] == "british"
    assert "irish" not in {v["accent"] for v in body["library"]}
    assert "irish" not in body["account_accents"]
    assert "irish" in body["library_accents"]
    assert "irish" in body["accent_options"]
    assert body["accent_options"] == ["british", "irish", "scottish"]


@pytest.mark.asyncio
async def test_the_accent_probe_is_unfiltered_and_the_result_set_is_not(
    engagements, monkeypatch
):
    """Two questions, two requests - and the probe must carry no accent.

    A probe that inherited the applied filter would answer "british" for a british query, and
    the dropdown would offer exactly the option already selected. That failure looks identical
    to a working picker until somebody needs a second accent, which is how Irish went missing
    the first time.
    """
    seen = _catalogue_wire(monkeypatch)
    await engagements["owner"].get(f"/projects/{SLUG_A}/voices?accent=scottish&gender=male")

    calls = _library_calls(seen)
    assert len(calls) == 2, _urls(seen)
    unfiltered = [r for r in calls if not {"accent", "gender"} & set(r.url.params)]
    narrowed = [r for r in calls if r.url.params.get("accent") == "scottish"]
    assert len(unfiltered) == 1, _urls(seen)
    assert len(narrowed) == 1, _urls(seen)


@pytest.mark.asyncio
async def test_the_projects_own_accent_is_always_among_its_options(
    engagements, monkeypatch
):
    """A picker must not apply a filter its own control cannot show.

    `library_accents` reads a *page* of the library rather than enumerating it, so an accent
    held by few voices can be missing from the probe - and the library call can fail outright.
    In both cases the applied accent is still the state the picker is in, and a dropdown that
    omits it disagrees with the filter it is displaying.
    """
    _catalogue_wire(monkeypatch, library=502)
    body = (await engagements["owner"].get(f"/projects/{SLUG_A}/voices?accent=irish")).json()

    assert body["library_accents"] == []
    assert body["library_error"]
    assert "irish" in body["accent_options"]


@pytest.mark.asyncio
async def test_an_empty_accent_puts_no_empty_option_in_the_list(engagements, monkeypatch):
    """Clearing the filter is a state, not an accent.

    `applied_accent` joins the options, and `""` is a legitimate value for it - so without the
    falsy filter the dropdown would gain a blank entry that means "every accent" and reads as
    a voice with no accent.
    """
    _catalogue_wire(monkeypatch)
    body = (await engagements["owner"].get(f"/projects/{SLUG_A}/voices?accent=")).json()

    assert "" not in body["accent_options"]
    assert body["accent_options"] == ["british", "irish", "scottish"]


@pytest.mark.asyncio
async def test_a_failed_accent_probe_still_leaves_a_full_narrowed_result_set(
    engagements, monkeypatch
):
    """The probe is auxiliary, so its failure must not suppress the primary query.

    The two library calls shared one `try` for a single commit, and that made the *heavier*
    request gate the lighter one: the probe is the unfiltered hundred-voice page and the
    result set is a narrowed query, so the call more likely to fail was the one deciding
    whether the other was attempted at all. Driven here by failing only the unfiltered call.

    The observable is the **result set**, not a call count: a picker showing no voices at all
    because a dropdown could not be populated is the failure, and it looks from the outside
    like an empty library.
    """
    seen = _catalogue_wire(monkeypatch, library_probe=502)

    res = await engagements["owner"].get(f"/projects/{SLUG_A}/voices?accent=british")
    assert res.status_code == 200, res.text
    body = res.json()

    assert [v["voice_id"] for v in body["library"]] == ["acct-daniel"], body["library"]
    assert body["library_error"] is None
    # The probe's failure is visible where it belongs: the options are not the whole
    # vocabulary. It is not `library_error`, which names a failure of the result set - and
    # were it, an account failure alongside it would be a 502 with a good listing in hand.
    assert body["library_accents"] == []
    assert body["accent_options_partial"] is True
    assert "british" in body["accent_options"]
    # The two fields answer different questions and must not share a source: the probe
    # failed (accent_options_partial above), but the result set is a full, un-truncated
    # page - `library_has_more` must come from the result set, never the probe.
    assert body["library_has_more"] is False

    narrowed = [r for r in _library_calls(seen) if r.url.params.get("accent") == "british"]
    assert len(narrowed) == 1, _urls(seen)


@pytest.mark.asyncio
async def test_a_warm_accent_probe_survives_a_failure_of_the_result_set(
    engagements, monkeypatch
):
    """A cached, known-good answer is not discarded because a different call failed.

    The shared `except` set `lib_accents = []` unconditionally, so a failure of the narrowed
    call threw away a probe that had already succeeded - and what went with it was precisely
    `irish`, the option the probe exists to add. `test_the_projects_own_accent_is_always_
    among_its_options` cannot see this: it asserts only that the **applied** accent survives,
    which `applied_accent` guarantees by a different route entirely.
    """
    _catalogue_wire(monkeypatch)
    warm = (await engagements["owner"].get(f"/projects/{SLUG_A}/voices")).json()
    assert warm["accent_options"] == ["british", "irish", "scottish"]

    seen = _catalogue_wire(monkeypatch, library=502)
    body = (await engagements["owner"].get(f"/projects/{SLUG_A}/voices")).json()

    assert body["library_error"] and "502" in body["library_error"]
    assert body["library"] == []
    assert "irish" in body["accent_options"], body["accent_options"]
    assert body["accent_options"] == ["british", "irish", "scottish"]
    assert body["library_accents"] == ["british", "irish"]

    # The cache really is what answered - one library request went out on the second listing,
    # the narrowed one. Without this the test could pass against a probe that was re-asked and
    # happened to succeed.
    assert len(_library_calls(seen)) == 1, _urls(seen)


@pytest.mark.asyncio
async def test_a_bounded_page_says_whether_there_is_more(engagements, monkeypatch):
    """`LIBRARY_PAGE_SIZE` and no pagination, so a first page must not read as the whole answer.

    A consumer handed a bare list cannot tell a complete answer from a truncated one and will
    eventually present one as the other - which on a picker reads as "that voice is not in the
    library" rather than "narrow your filters". Both directions are asserted, so a field
    hardcoded either way fails.
    """
    from api.services.voice_catalogue import forget_library_accents

    _catalogue_wire(monkeypatch)
    whole = (await engagements["owner"].get(f"/projects/{SLUG_A}/voices")).json()
    assert whole["library_has_more"] is False
    assert whole["accent_options_partial"] is False

    # The probe is cached per process, so its `has_more` is too - and that is correct: it
    # describes the page that was actually read. Dropped here so the second listing re-asks.
    forget_library_accents()
    _catalogue_wire(monkeypatch, library={**LIBRARY_BODY, "has_more": True})
    truncated = (await engagements["owner"].get(f"/projects/{SLUG_A}/voices")).json()
    assert truncated["library_has_more"] is True
    assert truncated["accent_options_partial"] is True


# --- Failure is reported, never hidden -------------------------------------------------------


@pytest.mark.asyncio
async def test_an_unreachable_library_is_named_rather_than_shown_as_no_voices(
    engagements, monkeypatch
):
    """A partial answer says which half is missing.

    A picker silently showing the account's two voices when it should show ninety is the
    failure that gets diagnosed as "there are no Scottish voices in the library", and sends an
    operator to reconfigure something that was never wrong. The same distinction
    `VoiceSexAnswer` draws one module along.
    """
    _catalogue_wire(monkeypatch, library=502)
    res = await engagements["owner"].get(f"/projects/{SLUG_A}/voices?accent=")

    assert res.status_code == 200, res.text
    body = res.json()
    assert body["library"] == []
    assert body["library_error"] and "502" in body["library_error"]
    assert body["account_error"] is None
    assert len(body["account"]) == 2


@pytest.mark.asyncio
async def test_both_listings_failing_is_a_502_naming_both(engagements, monkeypatch):
    """Nothing to show is not an empty picker."""
    _catalogue_wire(monkeypatch, account=500, library=502)
    res = await engagements["owner"].get(f"/projects/{SLUG_A}/voices")

    assert res.status_code == 502, res.text
    assert "500" in res.json()["detail"] and "502" in res.json()["detail"]


@pytest.mark.asyncio
async def test_no_api_key_is_a_503_and_not_an_empty_catalogue(engagements, monkeypatch):
    """"This deployment has no key" must not be presented as "you have no voices".

    The same rule `synthesise` and `voice_gender` already follow, and the reason they do: the
    two send an operator to two different repairs, and only one of them is theirs to make.
    """
    _catalogue_wire(monkeypatch)
    settings = get_settings()
    monkeypatch.setattr(settings, "elevenlabs_api_key", "", raising=False)

    res = await engagements["owner"].get(f"/projects/{SLUG_A}/voices")
    assert res.status_code == 503, res.text
    assert "ELEVENLABS_API_KEY" in res.json()["detail"]


# --- Who may open the door, and who may spend money through it -------------------------------


@pytest.mark.asyncio
async def test_a_foreign_org_admin_cannot_read_this_projects_voices(engagements, monkeypatch):
    """`check_project_access` is the **first** line, before anything reaches the provider.

    Driven with a real, fully-privileged org_admin of another organisation - the caller that
    isolates the rule. An anonymous request is refused by the dependency and would pass this
    test against a door with no floor at all.

    The wire assertion is the point: a refusal raised *after* the listing has been fetched is
    still a 403, and this branch has already shipped exactly that shape once (a gate moved to
    after synthesis, answering 403 while the private voice was spoken).
    """
    seen = _catalogue_wire(monkeypatch)

    res = await engagements["stranger"].get(f"/projects/{SLUG_A}/voices")
    assert res.status_code == 403, res.text
    assert seen == [], _urls(seen)


@pytest.mark.asyncio
async def test_adding_a_library_voice_is_platform_tier_and_not_project_administration(
    engagements, monkeypatch
):
    """A `project_admin` of this very engagement is refused, and that is deliberate.

    Adding a library voice copies it into the **deployment's** single ElevenLabs account,
    shared by every client on it: it spends the consultancy's credit and changes what every
    other engagement's picker shows. That is the shape `require_writable_tier` refuses at the
    sector tier - the only store whose readership is other clients - so the door is one tier
    tighter than the design's "same authority as any other project configuration change".

    The wire assertion holds the refusal to the same standard as the read door's: nothing may
    reach ElevenLabs before the caller is refused, or the credit is spent and the 403 is
    cosmetic.
    """
    seen = _catalogue_wire(monkeypatch)

    res = await engagements["project_admin"].post(
        f"/projects/{SLUG_A}/voices/library",
        json={"public_owner_id": "owner-1", "voice_id": "lib-seamus", "name": "Seamus"},
    )
    assert res.status_code == 403, res.text
    assert seen == [], _urls(seen)


@pytest.mark.asyncio
async def test_the_project_admin_really_does_administer_this_engagement(engagements):
    """The control for the test above, and the reason it is not vacuous.

    Without this, a `project_admin` fixture that was silently *not* a project_admin - a
    missing membership row, a flag that never landed - would refuse the add door for the wrong
    reason and the assertion would pass while proving nothing.

    Proved against a door that actually takes `require_project_administration`, rather than
    against `/my-permissions`, which reports the roles a caller may *grant* and not the ones
    they hold. The body is round-tripped unchanged so the platform-tier guard on
    `_PLATFORM_TIER_SETTINGS` has nothing to refuse - what is being asserted is the
    administration axis, not that axis' one carve-out.
    """
    current = await engagements["project_admin"].get(f"/projects/{SLUG_A}/settings")
    assert current.status_code == 200, current.text

    res = await engagements["project_admin"].patch(
        f"/projects/{SLUG_A}/settings", json={**current.json(), "client_name": "Alpha Rail"}
    )
    assert res.status_code == 200, res.text
    assert res.json()["client_name"] == "Alpha Rail"


@pytest.mark.asyncio
async def test_a_foreign_org_admin_cannot_add_a_voice_through_someone_elses_slug(
    engagements, monkeypatch
):
    """The platform role passes the dependency; the membership floor is what refuses.

    The door is mounted under a slug, and a platform tier says nothing about whether the
    caller is on this engagement - so `check_project_access` runs first here exactly as it
    does on the read.
    """
    seen = _catalogue_wire(monkeypatch)

    res = await engagements["stranger"].post(
        f"/projects/{SLUG_A}/voices/library",
        json={"public_owner_id": "owner-1", "voice_id": "lib-seamus", "name": "Seamus"},
    )
    assert res.status_code == 403, res.text
    assert seen == [], _urls(seen)


@pytest.mark.asyncio
async def test_an_org_admin_of_this_engagement_adds_the_voice_and_the_request_says_so(
    engagements, monkeypatch
):
    """The permitted arm, asserted on the request that goes out.

    Without it the two refusals above would pass against a door that refuses everybody. The
    **new** `voice_id` comes back rather than the library one, because the account assigns its
    own and a project's configuration must hold that one.
    """
    seen = _catalogue_wire(monkeypatch, added={"voice_id": "acct-seamus"})

    res = await engagements["owner"].post(
        f"/projects/{SLUG_A}/voices/library",
        json={"public_owner_id": "owner-1", "voice_id": "lib-seamus", "name": "Seamus"},
    )
    assert res.status_code == 201, res.text
    assert res.json()["voice_id"] == "acct-seamus"

    posts = [r for r in seen if r.method == "POST"]
    assert len(posts) == 1
    assert posts[0].url.path == "/v1/voices/add/owner-1/lib-seamus"
    assert json.loads(posts[0].content) == {"new_name": "Seamus"}
    assert posts[0].headers["xi-api-key"] == "test-key"


# --- Where a project's accent comes from -----------------------------------------------------


@pytest.mark.asyncio
async def test_a_project_with_no_setting_answers_the_british_default(engagements):
    """British English is the default for a new project, and this is the control.

    Without it, a resolver that answered `""` for everything would pass every override test
    above by never filtering, and would silently show a French engagement the whole library.
    """
    assert await project_interview_accent(SLUG_A) == "british"


@pytest.mark.asyncio
async def test_a_blank_slug_is_refused_rather_than_answered(engagements):
    """The rule `project_llm_mode` was corrected to, and `resolve_agent_config` follows.

    A caller that lost its slug must not be handed the defaults: the same silent answer in the
    LLM seam sent a sensitive engagement's interview answers to a hosted model.
    """
    for slug in ("", "   ", "\t"):
        with pytest.raises(ValueError):
            await project_interview_accent(slug)


@pytest.mark.asyncio
async def test_an_unknown_slug_answers_the_default_and_creates_no_database(
    engagements, tmp_path
):
    """The opposite arm, and deliberately not the same one.

    A project that genuinely does not exist has no configuration, and answering the default
    for it is what avoids materialising one database file per guessed slug - the guard
    `caller_roles` already carries.
    """
    assert await project_interview_accent("no-such-engagement") == "british"
    assert not (tmp_path / "data" / "no-such-engagement.db").exists()


@pytest.mark.asyncio
async def test_an_empty_accent_is_a_choice_and_not_an_absent_one(engagements, monkeypatch):
    """`''` is the project saying "every accent"; a missing key is it having said nothing.

    Testing truthiness would collapse the two and quietly reinstate `british` over a decision
    somebody made - `_override` in `agent_config_service` draws the same line for the same
    reason.
    """
    async with get_connection(SLUG_A) as conn:
        await conn.execute(
            "UPDATE projects SET config_json=? WHERE slug=?",
            (json.dumps({"interview_accent": ""}), SLUG_A),
        )
        await conn.commit()

    assert await project_interview_accent(SLUG_A) == ""


# --- The table is gone, and did not come back corrected --------------------------------------


def _code_constants(path: Path) -> list[str]:
    """Every string literal in a module **except** its docstrings.

    Prose recording that Rachel was the wrong voice is the history of the defect and is worth
    keeping; a literal naming her is the defect. `#` comments never reach the AST at all, and
    a bare string expression is a docstring, so skipping those two leaves exactly the strings
    the code can act on.
    """
    tree = ast.parse(path.read_text())
    docstrings = {
        id(node.value)
        for node in ast.walk(tree)
        if isinstance(node, ast.Expr)
        and isinstance(node.value, ast.Constant)
        and isinstance(node.value.value, str)
    }
    return [
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and id(node) not in docstrings
    ]


def test_no_python_module_names_a_retired_voice_id_in_code():
    """The prompt table is gone, and it did not come back with corrected numbers.

    Correcting the ids was the obvious repair and it is the wrong one: it leaves a fifth
    declaration of voice facts that happens to be right on the day it is written, which is
    exactly the state that produced four disagreeing copies. This asserts on the **union of
    both** retired tables, so restoring either one fails - including the twin's four
    disagreeing entries, which a guard written against the Python table alone would miss.
    """
    offenders: dict[str, list[str]] = {}
    for path in list((REPO / "agents").rglob("*.py")) + list((REPO / "api").rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        found = [c for c in _code_constants(path) if any(v in c for v in RETIRED_VOICE_IDS)]
        if found:
            offenders[str(path.relative_to(REPO))] = found
    assert offenders == {}, offenders


# The two shapes that are a voice **fact** rather than wording about voices. Neither has any
# legitimate reason to appear in a prompt in any of the modules below, whatever the prose
# around it: one is an address for a voice and the other is the left-hand column of a table
# that maps something to one.
ELEVENLABS_ID_SHAPE = re.compile(r"\b[A-Za-z0-9]{20}\b")
LOCALE_PAIR_SHAPE = re.compile(r"\b[a-z]{2}[/_-][A-Z]{2}\b")


def _class_names_under(root: Path) -> frozenset[str]:
    """Every class name this repository defines under `root`, derived rather than listed.

    An ElevenLabs voice id is twenty characters of base62, and so - by coincidence that is
    not going to be the last of its kind - are `InterviewSessionTool` and
    `PowerPointOutputTool`, both of which prompts name because an agent has to call them.
    Excusing them by **derivation** leaves the id shape itself intact: a token is excused only
    because this codebase defines a class of that name, which a provider-generated id never
    is. It also fails in the safe direction - a derivation that broke and returned nothing
    makes the guard stricter rather than laxer, and says so by failing.
    """
    names: set[str] = set()
    for path in root.rglob("*.py"):
        if "__pycache__" in path.parts:
            continue
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.ClassDef):
                names.add(node.name)
    return frozenset(names)


def _voice_facts_in(text: str, *, exempt: frozenset[str]) -> list[str]:
    """The voice facts one string declares - a **pure function over given text**.

    Pure so it can be driven with text of the reviewer's choosing rather than only against
    the source it guards. Three times on this branch a guard's own account of its coverage has
    been wrong - the mode-name inventory, sp58's `public_url` walk, and sp59's Settings walk,
    whose opener list omitted `<button` while the comment beside it said otherwise. A walk
    that can only be run against the real files is a walk that cannot be asked what it saw.
    """
    return [t for t in ELEVENLABS_ID_SHAPE.findall(text) if t not in exempt] + (
        LOCALE_PAIR_SHAPE.findall(text)
    )


def _voice_fact_free_modules() -> list[Path]:
    """Every module whose strings become part of what a discovery interviewing agent is told.

    The discovery agents are enumerated by **glob**, so a new one is guarded on the day it is
    added rather than on the day somebody remembers this list. The crew factory is named
    because it is one file and a glob over `agents/crews` would guard nine crews this rule was
    not reasoned about - but it is the file that assembles these agents, and injecting through
    a factory parameter is the one-level-up move that produced the finding this widening
    closes.
    """
    return sorted((REPO / "agents" / "discovery").glob("*.py")) + [
        REPO / "agents" / "crews" / "discovery_interviews_crew.py"
    ]


def test_no_discovery_module_declares_a_voice_fact_in_a_string_it_can_send():
    """Widened from Taylor's five strings to every prompt on the crew that speaks to people.

    `test_nothing_taylor_is_given_chooses_a_voice_in_any_vocabulary` is one **file** wide,
    which is the shape of the finding it was written for, one level up: a correct-id
    locale-to-voice table was green when written straight into
    `agents/discovery/stakeholder_interviewer.py`, and green when declared in
    `agents/crews/discovery_interviews_crew.py` and injected into Taylor through
    `discovery_brief=`. Both reach the model; neither is Taylor's own prompt.

    **Only the two axes that are about data are widened, and that is deliberate.** A voice id
    and a locale pairing express a voice *fact*, and no prompt in these modules has a reason
    to carry either. The vocabulary axis - the words `voice` and `elevenlabs`, and the stock
    voice names - does **not** generalise and must not be copied here:
    `stakeholder_interviewer.py` legitimately says "voice interview" and carries `voice_config`
    as the passthrough shape Avery must copy verbatim, and `interaction_designer.py` uses
    "customer voice", "audit voice" and "frontline voice" throughout. A copied rule would fire
    on every one of them, and a guard that has to be softened is a guard that gets deleted.

    **What this deliberately does not reach**, so the next reader meets the edge rather than
    rediscovering it: a mapping paraphrased with no id and no locale pair - *"For interviewees
    in Dublin, use the warm narrator; in Edinburgh, the measured broadcaster"* - passes. It
    names no id, so nothing downstream could act on it, and `InterviewSessionTool._create`
    resolves the interviewer itself and never reads a `voice_config` out of the plan, so the
    whole class is inert at run time. Closing it would mean forbidding ordinary English in
    files that have ordinary reasons to use it. A guard that claims more than it delivers is
    worse than one that states its edge.
    """
    exempt = _class_names_under(REPO / "agents")
    assert exempt, "the class-name derivation found nothing, so the exemption is not derived"

    modules = _voice_fact_free_modules()
    assert len(modules) >= 3, modules
    assert all(p.exists() for p in modules), [str(p) for p in modules if not p.exists()]

    offenders: dict[str, list[str]] = {}
    for path in modules:
        found = [
            fact
            for constant in _code_constants(path)
            for fact in _voice_facts_in(constant, exempt=exempt)
        ]
        if found:
            offenders[str(path.relative_to(REPO))] = found
    assert offenders == {}, offenders


def test_the_voice_fact_walk_sees_both_axes_and_excuses_only_what_it_claims_to():
    """The walk driven over given text, gated and ungated, one of each kind.

    A one-sided test passes against a walk that reports everything and against one that
    reports nothing, so both directions are here. The last case is the conceded edge above,
    asserted as a **fact about the guard** rather than left as a sentence in a docstring that
    nothing checks - if it ever starts being caught, this fails and the docstring gets fixed.
    """
    exempt = _class_names_under(REPO / "agents")

    assert _voice_facts_in("use onwK4e9ZLuTAKqWW03F9 for this one", exempt=exempt) == [
        "onwK4e9ZLuTAKqWW03F9"
    ]
    assert _voice_facts_in("en/GB, en_US and en-AU", exempt=exempt) == [
        "en/GB", "en_US", "en-AU"
    ]
    assert len(_voice_facts_in("en/GB -> onwK4e9ZLuTAKqWW03F9", exempt=exempt)) == 2

    # A tool an agent is told to call, and the phrasing every one of these prompts uses.
    assert _voice_facts_in(
        "Use InterviewSessionTool with operation='create', sessions=[...]", exempt=exempt
    ) == []
    assert _voice_facts_in("Copy voice_config exactly as returned.", exempt=exempt) == []

    # The edge, stated and therefore checked: no id, no pairing, not caught.
    assert _voice_facts_in(
        "For interviewees in Dublin, use the warm narrator; in Edinburgh, the measured "
        "broadcaster.",
        exempt=exempt,
    ) == []


def test_the_dead_typescript_twin_is_gone_and_nothing_declares_a_locale_to_voice_map():
    """`ui/src/utils/voiceLocale.ts` had no importers and disagreed with the prompt table on
    four of eight locales, so "the voice for a French interview" already had two answers.

    Deleting one copy is not the property; having none is. This walks the front end for both
    the retired ids and the two names either copy went by, so a reinstated map fails whatever
    it is called and whichever ids it holds.
    """
    assert not (REPO / "ui" / "src" / "utils" / "voiceLocale.ts").exists()

    offenders: dict[str, list[str]] = {}
    for path in (REPO / "ui" / "src").rglob("*.ts*"):
        if "__tests__" in path.parts:
            continue
        text = path.read_text()
        # Comment lines are the record of the defect; code naming it is the defect.
        code = "\n".join(
            line for line in text.splitlines() if not line.lstrip().startswith("//")
        )
        found = [
            token
            for token in list(RETIRED_VOICE_IDS) + ["VOICE_LOCALE_MAP", "getVoiceId"]
            if token in code
        ]
        if found:
            offenders[str(path.relative_to(REPO))] = found
    assert offenders == {}, offenders


# Anything that puts synthesis within reach of the voices path, in every spelling an import
# can take. `speak` and `synthesise` are the two functions; the two **modules** are here
# because `from api.services import interview_service` imports neither name and reaches both -
# and that is precisely the form of the route deliberately left unmutated during the
# power-checks, so the guard was blind to the one case most care had been taken over.
SYNTHESIS_HANDLES = {
    "speak",
    "synthesise",
    "interview_service",
    "api.services.interview_service",
    "tts_cache",
    "api.services.tts_cache",
}


def _import_handles(path: Path) -> set[str]:
    """Every name an import statement binds or names, in both dotted and bare form.

    `from api.services import interview_service` yields `interview_service` *and*
    `api.services.interview_service`; `import api.services.interview_service` yields the
    dotted name and each of its prefixes. Collecting both forms is what makes the guard
    independent of how the import happens to be written, which was the whole defect.
    """
    handles: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text())):
        if isinstance(node, ast.ImportFrom):
            for alias in node.names:
                handles.add(alias.name)
                if node.module:
                    handles.add(f"{node.module}.{alias.name}")
                    handles.add(node.module)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                parts = alias.name.split(".")
                handles.update(".".join(parts[: i + 1]) for i in range(len(parts)))
    return handles


def test_the_voices_path_imports_nothing_that_can_synthesise():
    """A source guard beside the wire assertion, and the two cover different things.

    The wire test catches any synthesis call that goes through the shared client - any module,
    any import spelling - and that reach is established by
    `test_the_wire_recorder_sees_a_synthesis_call_from_another_module` rather than asserted
    here. What it cannot see is a caller that builds its own `httpx.AsyncClient`, which
    `voice_metadata.py` shows is a thing this codebase does on purpose. **That gap is this
    test's**, and it is why the pair exists rather than either alone. This one also fails
    earlier and more legibly for the specific mistake somebody is most likely to make:
    reaching for `speak` or `synthesise` to "make preview work properly".

    It is name-keyed, and therefore blind to a handle assembled at run time or to a module it
    does not list - the standing weakness of every guard on this project that walks source. It
    is stated because the earlier version of this docstring called the other one
    "form-agnostic by construction" and pointed a reader at the wrong guard, when the injection
    that motivated the pair was in fact caught by this one alone.

    It searched for the two function names only, which is one vocabulary deep in exactly the
    way the coordinator guard was: `from api.services import interview_service` imports
    neither name and reaches both. It now asks about the modules as well, in every spelling.
    """
    for module in ("api/services/voice_catalogue.py", "api/routers/voices.py"):
        handles = _import_handles(REPO / module)
        assert not (SYNTHESIS_HANDLES & handles), (module, sorted(SYNTHESIS_HANDLES & handles))
