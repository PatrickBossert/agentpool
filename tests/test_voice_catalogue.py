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
from api.models import ProjectSettings
from api.services import voice_metadata
from api.services.voice_catalogue import DEFAULT_LIBRARY_LANGUAGE, LIBRARY_PROBE_PAGES

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
    library_probe: dict | int | list[dict | int] | None = None,
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

    **It takes a list to answer the vocabulary walk page by page.** A body or a status code
    answers every page the same way, which cannot distinguish a probe that reads one page
    from one that reads four - and the live defect was exactly an accent that had moved from
    page 0 to page 1 between two readings on one day. A list is indexed by the request's own
    `page`, and pages past its end answer empty with `has_more` false, so a walk that runs
    past the stub's pages ends rather than repeating its last one.
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
        if path.startswith("/v1/voices/") and not path.startswith("/v1/voices/add/"):
            # One voice's metadata, which is what `voice_metadata.voice_gender` asks for. It
            # answers out of the same `account` body the listing does, so a test cannot set a
            # voice's sex in the listing and have this contradict it - the door and the crew
            # read one source and the fixture must not be the place they diverge. A voice the
            # account does not hold is 404, exactly as the provider answers, which
            # `ask_voice_sex` turns into "could not ask" rather than into a sex.
            wanted = path.rsplit("/", 1)[-1]
            body = account if isinstance(account, dict) else {"voices": []}
            for voice in body["voices"]:
                if voice["voice_id"] == wanted:
                    return httpx.Response(200, json=voice)
            return httpx.Response(404, json={"detail": f"no such voice {wanted}"})
        if path == "/v1/shared-voices":
            narrowing = {"accent", "gender", "language", "search"} & set(request.url.params)
            if library_probe is not None and not narrowing:
                spec = library_probe
                if isinstance(spec, list):
                    # A **list** is one body per page, which is what makes the vocabulary
                    # walk observable. A single body answers every page identically, so a
                    # stub built that way cannot tell a probe that reads one page from one
                    # that reads four - and that is exactly the bug: page 0 carried irish in
                    # the morning and page 1 carried it by the afternoon.
                    index = int(request.url.params.get("page") or 0)
                    spec = (
                        spec[index]
                        if index < len(spec)
                        else {"voices": [], "has_more": False}
                    )
                return _narrow(spec, request)
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

    # `voice_metadata` builds its **own** client rather than asking `get_tts_client()`, for
    # event-loop reasons of its own, so the line above cannot reach it - the docstring above
    # named that as this recorder's blind spot while nothing on this path used it. The voices
    # door now does, for `voice_sex`, and the gap stopped being theoretical the moment it did:
    # the fixture writes a **non-empty** api key onto the shared settings object, which is the
    # only thing standing between `voice_gender` and a real request to api.elevenlabs.io. A
    # fixture that arms the provider is worse than no fixture, which this file has already
    # learned once about `synthesise`. A fresh client per call, because `_client()`'s callers
    # close it.
    monkeypatch.setattr(
        "api.services.voice_metadata._client",
        lambda: httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )

    settings = get_settings()
    monkeypatch.setattr(settings, "elevenlabs_api_key", "test-key", raising=False)
    monkeypatch.setattr("api.services.voice_catalogue.get_settings", lambda: settings)
    monkeypatch.setattr("api.services.voice_metadata.get_settings", lambda: settings)
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
async def test_the_door_opens_on_the_language_and_narrows_by_no_accent(
    engagements, monkeypatch
):
    """A bare request carries `language=en` to the library and **no accent at all**.

    This is sp64's whole subject, asserted on the wire rather than on the response. The door
    used to apply the project's `interview_accent` - `british` by default - which showed 6 of
    41 account voices, because `en` is the language and `british` is one of four accents of
    it. The axis that should broaden was being used as one that narrows.

    Both halves are needed and neither implies the other. A door that dropped the accent and
    sent no language would leave a consultant scrolling the library's other languages for an
    English interviewer; a door that sent `language=en` and kept the accent default would have
    fixed nothing at all.
    """
    seen = _catalogue_wire(monkeypatch)

    res = await engagements["owner"].get(f"/projects/{SLUG_A}/voices")
    assert res.status_code == 200, res.text
    assert res.json()["accent"] == ""
    assert res.json()["language"] == DEFAULT_LIBRARY_LANGUAGE == "en"

    calls = _library_calls(seen)
    narrowed = [r for r in calls if r.url.params.get("language") == "en"]
    assert len(narrowed) == 1, _urls(seen)
    assert all("accent" not in r.url.params for r in calls), _urls(seen)


@pytest.mark.asyncio
async def test_choosing_an_accent_narrows_and_clearing_it_broadens_again(
    engagements, monkeypatch
):
    """The control, without which "it opens unfiltered" is satisfied by ignoring the accent.

    A door that dropped the parameter on the floor would pass the test above and every
    assertion about the response body it makes. Only driving the accent in and back out again
    can tell that apart from a door that applies what it is asked for.

    Both spellings of "no accent" are driven, because sp64 collapsed a distinction that used
    to be load-bearing: omitted meant "the project's setting" and empty meant "every accent".
    There is no setting now, so the two must mean the same thing - and a door that kept them
    apart would be carrying a difference nothing can explain.
    """
    seen = _catalogue_wire(monkeypatch)
    res = await engagements["owner"].get(f"/projects/{SLUG_A}/voices?accent=irish")
    assert res.status_code == 200, res.text
    assert res.json()["accent"] == "irish"
    assert any(r.url.params.get("accent") == "irish" for r in _library_calls(seen))
    # And the narrowing really narrowed: the account's British and Scottish voices are gone.
    assert res.json()["account"] == []

    for cleared_query in ("accent=", ""):
        cleared = _catalogue_wire(monkeypatch)
        res = await engagements["owner"].get(
            f"/projects/{SLUG_A}/voices?{cleared_query}"
        )
        assert res.status_code == 200, res.text
        assert res.json()["accent"] == ""
        calls = _library_calls(cleared)
        assert calls, "the library was never asked, so 'no accent went out' is vacuous"
        assert all("accent" not in r.url.params for r in calls), _urls(cleared)
        # And the account list is not narrowed either, so clearing really does show everything.
        assert len(res.json()["account"]) == len(ACCOUNT_BODY["voices"])


@pytest.mark.asyncio
async def test_an_explicit_language_beats_the_default_and_an_empty_one_clears_it(
    engagements, monkeypatch
):
    """Omitted and empty are different, and the language axis is where they have to be.

    Omitted means "you decide" and resolves to `DEFAULT_LIBRARY_LANGUAGE`; empty means the
    consultant cleared it and wants every language. Collapsing them - which a `default=""` on
    the query parameter would do - would make the default unclearable from the picker, which
    is the defect this change removed from the accent, reinstated one axis over.

    The accent lost that distinction in the same change and it is not an inconsistency: it no
    longer has a default to be cleared *of*, so a door keeping the two apart there would carry
    a difference with nothing behind it.
    """
    seen = _catalogue_wire(monkeypatch)
    res = await engagements["owner"].get(f"/projects/{SLUG_A}/voices?language=fr")
    assert res.status_code == 200, res.text
    assert res.json()["language"] == "fr"
    assert any(r.url.params.get("language") == "fr" for r in _library_calls(seen))

    cleared = _catalogue_wire(monkeypatch)
    res = await engagements["owner"].get(f"/projects/{SLUG_A}/voices?language=")
    assert res.status_code == 200, res.text
    assert res.json()["language"] == ""
    calls = _library_calls(cleared)
    assert calls, "the library was never asked, so 'no language went out' is vacuous"
    assert all("language" not in r.url.params for r in calls), _urls(cleared)


@pytest.mark.asyncio
async def test_the_account_listing_is_never_narrowed_by_language(engagements, monkeypatch):
    """The deployment's own voices are shown whole, whatever language is applied.

    All 41 were deliberately added by somebody, so narrowing them by the library's default
    would reintroduce exactly the hidden-voices defect on the listing that has no reason to
    carry it. Structural on the door - `filter_account_voices` is not passed a language - and
    this is what proves the structure rather than the intention.

    `acct-alba` is the case that matters: the account body gives her **no**
    `verified_languages` at all, so any implementation that filtered the account on a language
    would drop her, and dropping a voice for saying nothing is the worst version of it.
    """
    for query in ("", "?language=en", "?language=fr"):
        _catalogue_wire(monkeypatch)
        body = (await engagements["owner"].get(f"/projects/{SLUG_A}/voices{query}")).json()
        assert [v["voice_id"] for v in body["account"]] == ["acct-daniel", "acct-alba"], query


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


# --- The sex of the voice the caller already has --------------------------------------------
#
# `voice_sex` answers "what sex is the voice this agent is already configured with", so the
# picker can open on voices of the same sex. It lives on **this** door and not on
# `GET /projects/{slug}/agents/{agent_id}/config`, which is read once per agent panel on every
# render - and a third-party lookup on that read is paid by everybody who opens the section, to
# serve a value only whoever clicks "Change voice" consumes. Since failed lookups are not
# cached, an outage was re-paid on every render.
#
# The unit-level cases live with the function, in `resolved_voice_sex` below the door tests.


@pytest.mark.asyncio
async def test_the_door_answers_the_sex_of_the_voice_it_was_given(engagements, monkeypatch):
    """Both arms, and the request that carries the answer is on the wire.

    Two voices of different sexes in the same account body, so a door that answered a constant,
    or answered from the first voice in the listing, fails one arm. The wire assertion is what
    distinguishes "asked the provider about this voice" from "found it in a list I already
    had": the shortcut of reading the sex out of `account` looks identical in the response and
    fails silently for a voice the accent filter excluded.
    """
    for voice_id, expected in (("acct-daniel", "male"), ("acct-alba", "female")):
        seen = _catalogue_wire(monkeypatch)
        res = await engagements["owner"].get(
            f"/projects/{SLUG_A}/voices?current_voice_id={voice_id}"
        )
        assert res.status_code == 200, res.text
        assert res.json()["voice_sex"] == expected, voice_id
        assert f"/v1/voices/{voice_id}" in [r.url.path for r in seen], voice_id


@pytest.mark.asyncio
async def test_a_voice_the_accent_filter_excluded_is_still_answered(engagements, monkeypatch):
    """The reason the sex is asked for rather than read out of the listing.

    Alba is Scottish, and this request applies the project's british accent, so she is **not**
    in `account` - which is exactly the state a project that configured an accent is in for
    every voice of another one. A picker deriving the sex from its own listing would find
    nothing and open unfiltered, silently, for precisely those projects. Asserted both ways:
    the sex comes back, and the voice it belongs to is absent from the answer.
    """
    seen = _catalogue_wire(monkeypatch)

    res = await engagements["owner"].get(
        f"/projects/{SLUG_A}/voices?accent=british&current_voice_id=acct-alba"
    )
    assert res.status_code == 200, res.text
    assert "acct-alba" not in [v["voice_id"] for v in res.json()["account"]]
    assert res.json()["voice_sex"] == "female"
    assert "/v1/voices/acct-alba" in [r.url.path for r in seen]


@pytest.mark.asyncio
async def test_no_current_voice_costs_no_request_and_answers_none(engagements, monkeypatch):
    """The picker opens for an agent that has no voice yet, and asks nobody about it.

    Asserted on the request that is **not** made: `null` is cheap to produce by accident - a
    door that looked the voice up and swallowed the failure would answer identically - so the
    absence of the lookup is the property, not the value.
    """
    seen = _catalogue_wire(monkeypatch)

    res = await engagements["owner"].get(f"/projects/{SLUG_A}/voices")
    assert res.status_code == 200, res.text
    assert res.json()["voice_sex"] is None
    assert not [r for r in seen if r.url.path.startswith("/v1/voices/")]


@pytest.mark.asyncio
async def test_a_voice_the_provider_does_not_know_opens_the_picker_unfiltered(
    engagements, monkeypatch
):
    """A 404 from the provider is not a sex, and it is not an error either.

    The listing is still served in full and `voice_sex` is `null`, which the picker reads as
    "open unfiltered". **Showing nothing because a lookup failed is the worst outcome
    available** - it is indistinguishable from an account with no voices, and it sends a
    consultant to diagnose a picker that is working.
    """
    seen = _catalogue_wire(monkeypatch)

    res = await engagements["owner"].get(
        f"/projects/{SLUG_A}/voices?current_voice_id=a-voice-this-account-never-had"
    )
    assert res.status_code == 200, res.text
    assert res.json()["voice_sex"] is None
    assert res.json()["account"], "a failed sex lookup must not empty the listing"
    assert "/v1/voices/a-voice-this-account-never-had" in [r.url.path for r in seen]


@pytest.mark.asyncio
async def test_a_sex_this_product_cannot_filter_on_opens_the_picker_unfiltered(
    engagements, monkeypatch
):
    """ElevenLabs' vocabulary is wider than this product's, and the wide half must not leak.

    Driven by *changing the provider's answer* - Daniel relabelled `Non-Binary`, which is a
    real value in `labels.gender`. Passed through, the picker would pre-set `gender=non-binary`
    on its own listing, the listing would answer nothing, and the picker would open **empty**:
    the one outcome the design forbids, reached by way of a perfectly correct provider answer
    and a field typed as though only two existed.
    """
    relabelled = json.loads(json.dumps(ACCOUNT_BODY))
    relabelled["voices"][0]["labels"]["gender"] = "Non-Binary"
    _catalogue_wire(monkeypatch, account=relabelled)

    res = await engagements["owner"].get(
        f"/projects/{SLUG_A}/voices?accent=&current_voice_id=acct-daniel"
    )
    assert res.status_code == 200, res.text
    assert res.json()["voice_sex"] is None


@pytest.mark.asyncio
async def test_the_sex_is_asked_of_the_same_function_the_crew_selects_with(
    engagements, monkeypatch
):
    """One source, asserted by replacing it and watching the door follow.

    `interviewer_selection`'s `always_male`/`always_female` reads `ask_voice_sex`, and so does
    this door - so a project cannot be told one thing by its picker and another by the crew
    that issues its sessions. Held by monkeypatching `ask_voice_sex` **on `voice_metadata`**,
    where `resolved_voice_sex` looks it up, and asserting the door's answer moves with it; a
    door that had grown its own lookup would go on answering `male`.
    """
    from api.services import voice_metadata

    _catalogue_wire(monkeypatch)

    async def one_source(voice_id):
        return voice_metadata.VoiceSexAnswer(label="female", answered=True)

    monkeypatch.setattr(voice_metadata, "ask_voice_sex", one_source)

    res = await engagements["owner"].get(
        f"/projects/{SLUG_A}/voices?current_voice_id=acct-daniel"
    )
    assert res.status_code == 200, res.text
    assert res.json()["voice_sex"] == "female", (
        "the door answered without asking ask_voice_sex - the picker and the crew can now "
        "disagree about what a voice is"
    )


# --- `resolved_voice_sex`, case by case -----------------------------------------------------
#
# Four routes in and two answers out, and the three that answer `None` do so for different
# reasons. One test cannot witness them, and the one that matters most is the one that stays
# `None` because the provider was never asked.


def _stub_ask_voice_sex(monkeypatch, answer) -> list[str | None]:
    """Replace `ask_voice_sex` **where `resolved_voice_sex` looks it up**, and record the ask.

    Both live in `voice_metadata`, so the module global is the lookup site - which is the same
    rule that made the previous home of this function patch `agent_config_service` rather than
    `api.services.voice_metadata`. CLAUDE.md records four crew tests that patched a definition
    site while the module held its own reference and passed anyway, hiding a live production
    bug for as long as they were green.

    `answer` may be a `VoiceSexAnswer` to return or an exception to raise.
    """
    asked: list[str | None] = []

    async def fake(voice_id):
        asked.append(voice_id)
        if isinstance(answer, BaseException):
            raise answer
        return answer

    monkeypatch.setattr(voice_metadata, "ask_voice_sex", fake)
    return asked


@pytest.mark.asyncio
async def test_a_voice_the_provider_gives_a_sex_for_answers_that_sex(monkeypatch):
    """The control for the three `None` cases below.

    Without it, an implementation answering `None` unconditionally would pass every other test
    in this section and the picker would open unfiltered for ever while looking correct.
    """
    asked = _stub_ask_voice_sex(monkeypatch, voice_metadata.VoiceSexAnswer("female", True))

    assert await voice_metadata.resolved_voice_sex("a-voice") == "female"
    assert asked == ["a-voice"], "the sex was answered without asking about the voice"


@pytest.mark.asyncio
async def test_a_voice_the_provider_gives_no_sex_for_answers_none(monkeypatch):
    """The provider answered and simply does not classify this voice.

    `None` rather than a guess: the picker opens unfiltered, which shows every voice the
    account has. Pre-setting a filter from an unlabelled voice would hide half of them on the
    strength of nothing.
    """
    _stub_ask_voice_sex(monkeypatch, voice_metadata.VoiceSexAnswer(None, True))

    assert await voice_metadata.resolved_voice_sex("an-unlabelled-voice") is None


@pytest.mark.parametrize("label", [None, "male"])
@pytest.mark.asyncio
async def test_a_lookup_that_could_not_be_made_answers_none_rather_than_a_sex(
    monkeypatch, label
):
    """Unreachable, refused, or unparseable - and this says nothing about the voice.

    A distinct test from the one above because `ask_voice_sex` distinguishes the two on
    purpose, and one test cannot witness both: "the provider says nothing about this voice" and
    "the provider was not asked" are different facts with different repairs. They agree only in
    what the picker does with them.

    The second parameter is the reason `answered` is tested before `label` rather than after.
    `ask_voice_sex` never pairs a label with `answered=False` today, so without it the branch
    would be indistinguishable from the one below and could be deleted with the suite green -
    a branch that documents an intention rather than holding one. Driven, it holds the real
    property: **a sex is never reported from a lookup that did not happen**, whatever the
    answer object claims.
    """
    _stub_ask_voice_sex(monkeypatch, voice_metadata.VoiceSexAnswer(label, False))

    assert await voice_metadata.resolved_voice_sex("a-voice-nobody-could-ask-about") is None


@pytest.mark.parametrize("label", ["non-binary", "neutral", "MALE"])
@pytest.mark.asyncio
async def test_a_label_this_product_cannot_act_on_answers_none(monkeypatch, label):
    """ElevenLabs' vocabulary is not this repository's, and only the actionable part is used.

    `MALE` is in the list deliberately: `voice_gender` lower-cases what it reads, so an
    upper-cased label never reaches here in practice - and a comparison written against the raw
    string would pass every other test in this file while failing this one. Asserting the case
    rule at the seam that depends on it is cheaper than discovering it from a picker that
    opened unfiltered for a voice plainly labelled male.
    """
    _stub_ask_voice_sex(monkeypatch, voice_metadata.VoiceSexAnswer(label, True))

    assert await voice_metadata.resolved_voice_sex("a-voice") is None


@pytest.mark.asyncio
async def test_a_voice_that_is_absent_answers_none_and_asks_nobody(monkeypatch):
    """Driven through the **real** `ask_voice_sex` rather than a stub.

    A voice that is not there has no sex, which is a fact rather than an outage - and the fact
    is established without a request, so this asserts on the request that is not made. Stubbed
    at `voice_metadata._client` rather than at `ask_voice_sex`, because a stub of the function
    under test would make "nothing was asked" true by construction: the client spy is the only
    thing that can tell an early return from a swallowed answer.
    """
    def refuse_to_build_a_client():
        raise AssertionError("an absent voice must not be looked up at ElevenLabs")

    monkeypatch.setattr(voice_metadata, "_client", refuse_to_build_a_client)

    assert await voice_metadata.resolved_voice_sex(None) is None
    assert await voice_metadata.resolved_voice_sex("") is None


@pytest.mark.asyncio
async def test_a_deployment_with_no_elevenlabs_key_answers_none_rather_than_failing(
    monkeypatch,
):
    """The picker must still open on a deployment that has never configured ElevenLabs.

    `ask_voice_sex` lets `ValueError` out on purpose - for the session stamp a missing key
    would otherwise turn "always female" into whoever the shuffle produced, permanently, since
    the choice is stamped. This reader has the opposite obligation, so the refusal is caught at
    this call site and nowhere near where it is raised.
    """
    _stub_ask_voice_sex(monkeypatch, ValueError("ELEVENLABS_API_KEY not configured"))

    assert await voice_metadata.resolved_voice_sex("a-voice") is None


@pytest.mark.asyncio
async def test_any_other_value_error_is_not_swallowed(monkeypatch):
    """The catch is narrowed to the sentence it documents, and this is what holds it there.

    `ValueError` is a wide net - `json.JSONDecodeError` is one of its subclasses - so an
    unqualified `except ValueError` would report any future failure under `ask_voice_sex` as
    "this voice has no sex". A `None` that means "something broke" is the shape a picker cannot
    distinguish from a fact, and the missing-key case is the only one that has been reasoned
    about.
    """
    _stub_ask_voice_sex(monkeypatch, ValueError("something else went wrong entirely"))

    with pytest.raises(ValueError, match="something else"):
        await voice_metadata.resolved_voice_sex("a-voice")


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
    end them, or to type it as free text.

    **sp64 had to leave this untouched while removing the accent default**, which is why both
    halves are driven here. Narrowed to `british` the Irish voice is genuinely absent from the
    result and the *option* is still offered - what you can filter to is not the same question
    as what came back, and it is the union of both listings that answers it. Unnarrowed, which
    is now how the picker opens, the Irish voice is simply in the result: retiring the default
    made Irish reachable without anybody touching the union that made it *offerable*.
    """
    _catalogue_wire(monkeypatch)
    body = (await engagements["owner"].get(f"/projects/{SLUG_A}/voices?accent=british")).json()

    assert body["accent"] == "british"
    assert "irish" not in {v["accent"] for v in body["library"]}
    assert "irish" not in body["account_accents"]
    assert "irish" in body["library_accents"]
    assert "irish" in body["accent_options"]
    assert body["accent_options"] == ["british", "irish", "scottish"]

    opened = (await engagements["owner"].get(f"/projects/{SLUG_A}/voices")).json()
    assert "lib-seamus" in {v["voice_id"] for v in opened["library"]}
    assert opened["accent_options"] == ["british", "irish", "scottish"]


@pytest.mark.asyncio
async def test_the_accent_probe_is_unfiltered_and_the_result_set_is_not(
    engagements, monkeypatch
):
    """Two questions, two requests - and the probe must carry no accent and no language.

    A probe that inherited the applied filter would answer "british" for a british query, and
    the dropdown would offer exactly the option already selected. That failure looks identical
    to a working picker until somebody needs a second accent, which is how Irish went missing
    the first time.

    **The language axis makes it unavoidable rather than merely likely.** A bare request now
    carries `language=en` to the result set, so a language dropdown built from that answer
    would offer `en` alone - on the one axis whose whole purpose is to be widened. `language`
    is in the exclusion set below for that reason: without it, a probe that had picked up the
    default would still be counted as unfiltered here.
    """
    seen = _catalogue_wire(monkeypatch)
    await engagements["owner"].get(f"/projects/{SLUG_A}/voices?accent=scottish&gender=male")

    calls = _library_calls(seen)
    assert len(calls) == 2, _urls(seen)
    unfiltered = [
        r for r in calls if not {"accent", "gender", "language"} & set(r.url.params)
    ]
    narrowed = [r for r in calls if r.url.params.get("accent") == "scottish"]
    assert len(unfiltered) == 1, _urls(seen)
    assert len(narrowed) == 1, _urls(seen)
    assert narrowed[0].url.params.get("language") == "en", _urls(seen)


def _probe_calls(seen: list[httpx.Request]) -> list[httpx.Request]:
    """The vocabulary walk's requests, told apart from the result set by what they carry.

    Selected by the absence of every narrowing parameter, exactly as the fixture routes them,
    rather than by index or by `page` - a walk that had picked up the applied accent would
    still carry a `page`, and counting those would call it a probe.
    """
    return [
        r
        for r in _library_calls(seen)
        if not {"accent", "gender", "language", "search"} & set(r.url.params)
    ]


@pytest.mark.asyncio
async def test_the_vocabulary_walk_reaches_an_accent_that_is_not_on_the_first_page(
    engagements, monkeypatch
):
    """**The live defect, reproduced.** Irish left page 0 and the dropdown lost it.

    Measured on 7 September: at 04:44 `irish` was on the library's first unfiltered page and
    by 15:00 it was not, with no change to the account, the query or this code. The page is a
    moving selection. Cumulative distinct accents that afternoon were 22 after page 0 and 46
    after page 1, so a one-page probe was seeing about a third of the vocabulary and a
    different third at different hours. `?accent=irish` returned 85 library voices throughout
    - the voices never went anywhere, only the probe's sight of them.

    It matters more than a missing option usually would: Irish is reachable **only** through
    the library half, since the account holds none, and an Irish engagement is one of the four
    planned. So the dropdown losing the word is that engagement becoming unconfigurable.

    **The stub is two pages and the accent is on the second**, which is what stops this
    passing vacuously. A single-page stub would pass against the very bug it describes, and
    the first assertion below says so in the test rather than in prose about the fixture.
    """
    page_0 = {
        "voices": [
            {
                "public_owner_id": "owner-9",
                "voice_id": "lib-page0",
                "name": "On the first page",
                "accent": "british",
                "gender": "female",
                "language": "en",
            }
        ],
        "has_more": True,
    }
    page_1 = {"voices": LIBRARY_BODY["voices"], "has_more": False}
    # The control on the fixture: had the walk stopped at one page, there would be no irish to
    # find, so this is what makes the assertion below a statement about the walk.
    assert "irish" not in {v["accent"] for v in page_0["voices"]}
    assert "irish" in {v["accent"] for v in page_1["voices"]}

    seen = _catalogue_wire(monkeypatch, library_probe=[page_0, page_1])
    body = (await engagements["owner"].get(f"/projects/{SLUG_A}/voices?accent=british")).json()

    assert "irish" in body["library_accents"]
    assert "irish" in body["accent_options"]
    # The walk stopped where the provider said it had reached the end, so the ordinary case
    # stays cheap and the vocabulary is not reported as truncated when it is not.
    assert [r.url.params.get("page") for r in _probe_calls(seen)] == ["0", "1"]
    assert body["accent_options_partial"] is False


@pytest.mark.asyncio
async def test_the_walk_stops_at_its_bound_and_says_the_vocabulary_is_partial(
    engagements, monkeypatch
):
    """Bounded, and honest about being bounded - the two halves of one decision.

    Reading pages until the library runs out would make opening a picker an unbounded number
    of requests against a third party. Reading a fixed few and presenting the result as the
    whole vocabulary is the failure this walk exists to repair, moved four pages along. So the
    bound is real and `partial` carries the provider's own "there is more" out to the door and
    into the picker's notice.

    **Raising `LIBRARY_PROBE_PAGES` must not make this pass by accident**, so the stub answers
    `has_more` on more pages than the bound rather than on exactly as many.
    """
    endless = [{"voices": LIBRARY_BODY["voices"], "has_more": True}] * (
        LIBRARY_PROBE_PAGES + 3
    )
    seen = _catalogue_wire(monkeypatch, library_probe=endless)
    body = (await engagements["owner"].get(f"/projects/{SLUG_A}/voices?accent=british")).json()

    assert len(_probe_calls(seen)) == LIBRARY_PROBE_PAGES, _urls(seen)
    assert body["accent_options_partial"] is True
    assert body["language_options_partial"] is True
    # And it is a *partial* answer rather than no answer: what the walk did see is served.
    assert body["library_accents"] == ["british", "irish"]


@pytest.mark.asyncio
async def test_a_page_that_fails_mid_walk_keeps_what_arrived_and_is_not_cached(
    engagements, monkeypatch
):
    """A walk has four chances to fail where one request had one, and that must not cost more.

    Discarding pages 0 and 1 because page 2 timed out would make this probe **more** fragile
    than the single-page version it replaced, and it would show up as the same symptom: an
    accent that was there this morning and is not now. So the walk keeps what arrived, reports
    `partial`, and - the half that a response-body assertion cannot see - **does not cache the
    short answer**, or one bad minute becomes permanent until somebody restarts the server.

    Page 0 failing is deliberately the other arm: nothing was gathered, so there is no partial
    answer to keep and it stays the raise the door already turns into `partial`. That arm is
    `test_a_failed_accent_probe_still_leaves_a_full_narrowed_result_set`.
    """
    page_0 = {"voices": LIBRARY_BODY["voices"], "has_more": True}
    seen = _catalogue_wire(monkeypatch, library_probe=[page_0, 502])
    body = (await engagements["owner"].get(f"/projects/{SLUG_A}/voices?accent=british")).json()

    assert body["library_accents"] == ["british", "irish"]
    assert body["accent_options_partial"] is True
    assert body["library_error"] is None, "the result set is unaffected by a probe failure"

    # Not cached: the next listing walks again rather than serving the short answer forever.
    # Asserted on the wire, because the body of a second identical request looks the same
    # either way - which is how a cached failure survives every response-shaped assertion.
    before = len(_probe_calls(seen))
    healed = _catalogue_wire(monkeypatch, library_probe=[page_0, {"voices": [], "has_more": False}])
    again = (await engagements["owner"].get(f"/projects/{SLUG_A}/voices?accent=british")).json()
    assert before == 2, _urls(seen)
    assert len(_probe_calls(healed)) == 2, _urls(healed)
    assert again["accent_options_partial"] is False


@pytest.mark.asyncio
async def test_the_applied_accent_and_language_are_always_among_their_options(
    engagements, monkeypatch
):
    """A picker must not apply a filter its own control cannot show.

    `library_axes` reads a *page* of the library rather than enumerating it, so a value held
    by few voices can be missing from the probe - and the library call can fail outright. In
    both cases the applied value is still the state the picker is in, and a dropdown that
    omits it disagrees with the filter it is displaying.

    **Both axes, and the language matters more.** The accent is whatever the caller asked for,
    so a missing option is a control disagreeing with a choice somebody made. The language has
    a *default* nobody chose, so a missing option is a filter with no way out - the shape of
    the defect sp64 removed from the accent, waiting to be reintroduced one axis over.

    **Both applied values are ones no surviving listing carries**, and that is what makes the
    assertion mean anything. `irish` is not in the account; `fr` is not either, since both
    account voices are English or say nothing. Driven first with `language=en` - which the
    account *does* carry - the language half passed against a door that had stopped joining
    `applied_language` to its own options at all: the option was there, put there by a
    listing, and the property under test was invisible. A value the listings supply cannot
    distinguish "the applied value is always offered" from "this value happened to be offered".
    """
    _catalogue_wire(monkeypatch, library=502)
    body = (
        await engagements["owner"].get(f"/projects/{SLUG_A}/voices?accent=irish&language=fr")
    ).json()

    assert body["library_accents"] == []
    assert body["library_languages"] == []
    assert body["library_error"]
    assert "irish" not in body["account_accents"]
    assert "irish" in body["accent_options"]
    assert body["language"] == "fr"
    assert "fr" not in body["account_languages"]
    assert "fr" in body["language_options"]


@pytest.mark.asyncio
async def test_the_language_options_are_read_off_both_listings(engagements, monkeypatch):
    """Derived from the provider's answer on both endpoints, never declared here.

    **Two places, because the two endpoints put it in two places** - the same absorption the
    accent and the sex already needed. A library entry carries a top-level `language`; an
    account voice carries `verified_languages`, a list of objects. An implementation reading
    only one of them looks correct against whichever fixture it was written from.

    Driven with a code this codebase has never heard of, for the reason the sex half of
    `ui/src/__tests__/VoicePicker.test.tsx` was rewritten: a fixture built from the values a
    hardcoded list would contain cannot tell a derived list from a declared one.
    """
    account = {
        "voices": [
            {
                "voice_id": "acct-only-verified",
                "name": "Verified only",
                "labels": {"accent": "british", "gender": "female"},
                "verified_languages": [{"language": "cy", "model_id": "eleven_v2"}],
            }
        ]
    }
    library = {
        "voices": [
            {
                "public_owner_id": "owner-1",
                "voice_id": "lib-top-level",
                "name": "Top level only",
                "accent": "irish",
                "gender": "male",
                "language": "gd",
            }
        ]
    }
    _catalogue_wire(monkeypatch, account=account, library=library)
    body = (await engagements["owner"].get(f"/projects/{SLUG_A}/voices?language=")).json()

    assert body["account_languages"] == ["cy"]
    assert body["library_languages"] == ["gd"]
    # The union, and nothing else - so an implementation offering its own list *plus* what
    # arrived fails here as well as one offering its own list instead.
    assert body["language_options"] == ["cy", "gd"]


@pytest.mark.asyncio
async def test_an_empty_accent_puts_no_empty_option_in_the_list(engagements, monkeypatch):
    """Clearing the filter is a state, not an accent.

    `applied_accent` joins the options, and `""` is a legitimate value for it - so without the
    falsy filter the dropdown would gain a blank entry that means "every accent" and reads as
    a voice with no accent.
    """
    _catalogue_wire(monkeypatch)
    body = (
        await engagements["owner"].get(f"/projects/{SLUG_A}/voices?accent=&language=")
    ).json()

    assert "" not in body["accent_options"]
    assert body["accent_options"] == ["british", "irish", "scottish"]
    # The same on the axis that arrived with sp64, because `applied_language` joins its
    # options by the same line and `""` is a legitimate value for it too.
    assert "" not in body["language_options"]
    assert body["language_options"] == ["en"]


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
    from api.services.voice_catalogue import forget_library_probe

    _catalogue_wire(monkeypatch)
    whole = (await engagements["owner"].get(f"/projects/{SLUG_A}/voices")).json()
    assert whole["library_has_more"] is False
    assert whole["accent_options_partial"] is False

    # The probe is cached per process, so its `has_more` is too - and that is correct: it
    # describes the page that was actually read. Dropped here so the second listing re-asks.
    forget_library_probe()
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


# --- The retired setting, and the projects that may still be carrying it ---------------------


def test_neither_side_declares_the_retired_interview_accent_setting():
    """`ProjectSettings` no longer declares it, and `ui/src/types.ts` no longer declares it.

    **Both, in one assertion, because one without the other is the drift this project has now
    recorded four times.** A field removed from the model and left on the type is sent on
    every save and silently dropped; left on the model and removed from the type it is
    overwritten with the server default by every save the page makes. Neither fails anything.

    `api/services/voice_settings.py` is asserted gone rather than merely unimported: it existed
    only to resolve this setting, and a module left behind is one a later reader wires back in
    because it looks like an accessor somebody forgot to call.
    """
    assert "interview_accent" not in ProjectSettings.model_fields

    types_ts = (REPO / "ui" / "src" / "types.ts").read_text()
    declaration = re.compile(r"^\s*interview_accent\??\s*:", re.MULTILINE)
    assert not declaration.search(types_ts), (
        "ui/src/types.ts still declares interview_accent on a settings type while "
        "api/models.py has retired it. The Settings page sends what the type declares, and "
        "the server ignores what it does not model, so the field would ride every save and "
        "reach nothing."
    )

    assert not (REPO / "api" / "services" / "voice_settings.py").exists()


@pytest.mark.asyncio
async def test_a_project_still_storing_an_interview_accent_loads_and_saves(
    engagements, monkeypatch
):
    """The key is **ignored, not an error** - retiring a field must strand no configuration.

    No live project stores one, checked across every database in `data/` on 7 September. That
    is a fact about a day rather than a property, so the hand-written config below is what
    makes the guarantee hold for a deployment this branch has not seen - and for the operator
    who hand-edits a `config_json`, which is the case `project_interview_accent` used to carry
    a whole branch for.

    Three doors, because a settings body travels through all three and only the third is
    obvious: the read must not raise on the stored key, the write must accept a body carrying
    it, and the **voices** door must still open unfiltered rather than picking it up from
    somewhere. That last one is the assertion that would catch a resolver quietly left in
    place - a repair that removed the field from the model and kept reading `config_json`
    would pass the first two and reinstate the entire defect.
    """
    # The key added to whatever the project already holds, which is the state a deployment
    # that upgrades through this change is actually in - not a config replaced wholesale.
    async with get_connection(SLUG_A) as conn:
        row = await fetch_project(conn, slug=SLUG_A)
        stored = json.loads(row["config_json"] or "{}")
        await conn.execute(
            "UPDATE projects SET config_json=? WHERE slug=?",
            (json.dumps({**stored, "interview_accent": "scottish"}), SLUG_A),
        )
        await conn.commit()

    read = await engagements["owner"].get(f"/projects/{SLUG_A}/settings")
    assert read.status_code == 200, read.text
    assert "interview_accent" not in read.json()

    # Sent back exactly as a page holding a stale copy would send it.
    saved = await engagements["owner"].patch(
        f"/projects/{SLUG_A}/settings", json={**read.json(), "interview_accent": "scottish"}
    )
    assert saved.status_code == 200, saved.text
    assert "interview_accent" not in saved.json()

    seen = _catalogue_wire(monkeypatch)
    body = (await engagements["owner"].get(f"/projects/{SLUG_A}/voices")).json()
    assert body["accent"] == ""
    assert all("accent" not in r.url.params for r in _library_calls(seen)), _urls(seen)
    assert len(body["account"]) == len(ACCOUNT_BODY["voices"])


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
