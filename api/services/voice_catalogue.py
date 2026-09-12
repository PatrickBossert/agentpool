# api/services/voice_catalogue.py
"""The voices a project may choose from, asked of ElevenLabs rather than listed here.

**Two listings, and they are not interchangeable.** Established by calling the API on 4
September rather than assumed:

| | `GET /v1/voices` | `GET /v1/shared-voices` |
|---|---|---|
| Holds | the voices **in this account** | the whole Voice Library |
| Accents | british, american, australian, new zealand, scottish | those plus **irish** |
| Languages | `verified_languages`, a list of objects | that, plus a top-level `language` |
| Rate | `available_for_tiers`, and it is `[]` on every one | **`rate`**, `fiat_rate` |
| Filters | none | `accent`, `gender`, `language`, `search` |
| Preview | `preview_url` | `preview_url` |

So the rate exists only on the library, and Irish exists only on the library. A picker built
on one of them is missing either the cost or half the accents, which is why
`fetch_voice_catalogue` asks both and the door returns both.

**`language` and `accent` are two axes and only one of them is a narrowing.** `en` is the
language; `british`, `irish`, `american` and `new zealand` are accents *of* it, and ElevenLabs
keeps them as separate query parameters for that reason. Treating the accent as the axis a
picker opens on showed 6 of 41 account voices on 7 September, because five voices in six are
English in some accent other than the one a project happened to store. The default is now on
the language - see `DEFAULT_LIBRARY_LANGUAGE` - and the accent is an opt-in.

**Nothing here restates a fact about a voice.** No map of which voice is which sex, which
accent, or which language - those are `labels.gender`, `labels.accent`, and
`verified_languages`, and they are the provider's to answer. This branch exists because four
copies of "the voice for a French interview" had grown and two of them disagreed; a fifth that
happens to be right today is the same defect with better luck.

**Where the filters are applied differs between the two, and it has to.** The library endpoint
takes `accent`, `gender`, `language` and `search` as query parameters, so they go on the wire
unmodified - the caller's word reaches ElevenLabs, and no clause in this file decides what
`scottish` means. The account endpoint accepts no parameters at all, so the same filter is
applied here to the `labels` the API itself returned. That is not the "filter afterwards"
the design warns against: what it warns against is deciding a voice's accent locally, and
reading the accent the provider sent back is the opposite of that.

**Absent is not zero.** An account voice's `rate` is `None`, never `0.0`: "this listing does
not say what the voice costs" and "this voice is free" are different statements, and a
substituted default would show every account voice as free on a picker whose job is to show
the cost.

**Adding a library voice copies it into the account**, which is a write against the *deployment's*
single ElevenLabs account - see the door in `api/routers/voices.py` for why that is
platform-tier rather than project configuration.

**No synthesis happens anywhere in this module.** Preview plays `preview_url`, which the API
already hosts for every voice, so speaking a sample through `synthesise` would spend characters
on audio that exists - and the cheap implementation and the expensive one sound identical to a
listener, so only a test can tell them apart.
"""
from __future__ import annotations

import json
from typing import Any, NamedTuple

import httpx

from api.config import get_settings
from api.services.http_clients import get_tts_client
from api.services.process_cache import register_cache
from api.services.voice_metadata import ELEVENLABS_V1, VOICES_URL

SHARED_VOICES_URL = f"{ELEVENLABS_V1}/shared-voices"
# ElevenLabs' "add sharing voice": POST /v1/voices/add/{public_user_id}/{voice_id}.
ADD_SHARED_VOICE_URL = f"{VOICES_URL}/add"

# What the library endpoint is asked for in one page. The picker shows a filtered list rather
# than the whole library, and a caller wanting more narrows the filters.
#
# **100 is the provider's ceiling, not a choice.** 500 and 1000 are both answered 400 Bad
# Request (measured 7 September), so paging is the only way to see past it.
LIBRARY_PAGE_SIZE = 100

# How many pages the **vocabulary probe** reads before giving up and declaring itself partial.
#
# One page was not enough, and the way it failed is the reason this constant exists rather than
# a bigger `page_size`. The library's first page is a *moving* selection: on 7 September at
# 04:44 it carried irish, and by 15:00 it did not - same account, same query, no code change.
# Measured paging explicitly that afternoon, cumulative distinct accents were 22 after page 0,
# 46 after page 1, 54 after page 2 and 64 after page 3. So the accent dropdown silently lost
# Irish, which is reachable *only* through the library half and is one of the four planned
# engagements: the difference between that engagement being configurable and not.
#
# Bounded rather than exhaustive because this is a dropdown's option list, not an inventory,
# and the probe is cached for process life - so the cost is a handful of requests per process,
# not per listing and certainly not per keystroke. Stopping early when the provider says
# `has_more` is false is what keeps the ordinary case at one request.
#
# **Four does not make the answer complete, and nothing here may pretend it does.** A probe
# that stops with `has_more` still true reports `partial`, which is `accent_options_partial`
# and `language_options_partial` on the door and a notice in the picker. Raising this number
# narrows the gap and never closes it; the honest report is the mechanism, not the bound.
LIBRARY_PROBE_PAGES = 4

# The language the library is asked for when a caller names none.
#
# **This is a default, not a table.** It says which language a picker opens on, and nothing
# here maps a voice, an accent or a country to a language - those are `verified_languages` and
# `labels.accent` on the provider's own payload, and reading them is what `languages_present`
# and `accents_present` do.
#
# It exists because `language` and `accent` are different axes and only one of them narrows
# usefully by default. The library holds voices in many languages, so a consultant choosing an
# interviewer for an English engagement should not scroll past them; but `british`, `irish`,
# `american` and `new zealand` are all `en`, so narrowing by accent hid five voices in six.
# `""` reaches here as "every language", which is why the door keeps omitted and empty apart.
DEFAULT_LIBRARY_LANGUAGE = "en"


class VoiceCatalogueUnavailable(RuntimeError):
    """ElevenLabs could not be asked, or refused.

    Distinct from "the answer is an empty list", which is a real answer and means this account
    or this filter has no voices. Collapsing the two is the shape `VoiceSexAnswer` exists to
    avoid one module along: an operator told "no Scottish voices" when the provider was
    unreachable goes and reconfigures something that was never wrong.
    """


def _api_key() -> str:
    """The configured key, or a `ValueError` - matching `synthesise` and `voice_gender`.

    A deployment that cannot reach ElevenLabs cannot conduct a voice interview either, so
    answering an empty catalogue here would present "you have no voices" for what is actually
    "this deployment has no key".
    """
    key = get_settings().elevenlabs_api_key
    if not key:
        raise ValueError("ELEVENLABS_API_KEY not configured")
    return key


def _text(value: Any) -> str | None:
    """A trimmed string, or None. Never `''` - an empty label is the provider saying nothing."""
    if not isinstance(value, str):
        return None
    trimmed = value.strip()
    return trimmed or None


def _from_account(voice: dict[str, Any]) -> dict[str, Any]:
    """One entry of `GET /v1/voices`, in the shape both listings share.

    `rate` and `free_users_allowed` are `None` because this listing does not carry them, and
    `available_for_tiers` is passed through verbatim even though it was `[]` on all 32 voices
    in the account on 4 September. Replacing it with a note saying so would be this file
    asserting a fact about the account, which is exactly what it must not do - the day it
    stops being empty, a passthrough is right and a note is wrong.
    """
    labels = voice.get("labels")
    labels = labels if isinstance(labels, dict) else {}
    return {
        "voice_id": voice.get("voice_id"),
        "name": voice.get("name"),
        "accent": _text(labels.get("accent")),
        "gender": _text(labels.get("gender")),
        "preview_url": voice.get("preview_url"),
        "description": voice.get("description"),
        "category": voice.get("category"),
        "rate": None,
        "fiat_rate": None,
        "free_users_allowed": None,
        "available_for_tiers": voice.get("available_for_tiers"),
        "public_owner_id": None,
        "verified_languages": voice.get("verified_languages") or [],
        "source": "account",
    }


def _from_library(voice: dict[str, Any], *, account_ids: frozenset[str]) -> dict[str, Any]:
    """One entry of `GET /v1/shared-voices`, in the same shape.

    `accent` and `gender` are top-level here rather than under `labels` - the two endpoints
    disagree about where they live, and this is the one place that difference is absorbed.

    `in_account` is computed by comparing ids the two calls returned, not from any list held
    here, and it is what lets the picker say "already yours" without a second declaration of
    what the account holds.
    """
    voice_id = voice.get("voice_id")
    return {
        "voice_id": voice_id,
        "name": voice.get("name"),
        "accent": _text(voice.get("accent")),
        "gender": _text(voice.get("gender")),
        "preview_url": voice.get("preview_url"),
        "description": voice.get("description"),
        "category": voice.get("category"),
        "rate": voice.get("rate"),
        "fiat_rate": voice.get("fiat_rate"),
        "free_users_allowed": voice.get("free_users_allowed"),
        "available_for_tiers": None,
        "public_owner_id": voice.get("public_owner_id"),
        "verified_languages": voice.get("verified_languages") or [],
        "language": voice.get("language"),
        "in_account": voice_id in account_ids,
        "source": "library",
    }


async def _get(url: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    """One GET to ElevenLabs, with every failure arriving as `VoiceCatalogueUnavailable`.

    The shared client is right here and wrong in `voice_metadata`: that module is called from
    a CrewAI worker thread on its own short-lived event loop, and an httpx pool is bound to
    the loop that created it. This one is only ever called from a request handler, on the
    serving loop, which is the pool's whole purpose.
    """
    # Read **before** the try, so a missing key stays the `ValueError` every other ElevenLabs
    # caller raises rather than being reclassified as "the provider is unavailable". They send
    # an operator to two different repairs, and `json.JSONDecodeError` is a `ValueError`, so a
    # blanket `except ValueError` here would quietly swallow the deployment fault.
    headers = {"xi-api-key": _api_key()}
    client = get_tts_client()
    try:
        resp = await client.get(url, params=params or None, headers=headers, timeout=20.0)
        resp.raise_for_status()
        return resp.json()
    except httpx.HTTPStatusError as exc:
        raise VoiceCatalogueUnavailable(
            f"ElevenLabs answered {exc.response.status_code} for {url}"
        ) from exc
    except (httpx.HTTPError, json.JSONDecodeError) as exc:
        raise VoiceCatalogueUnavailable(f"ElevenLabs could not be reached at {url}") from exc


async def fetch_account_voices() -> list[dict[str, Any]]:
    """Every voice in this deployment's ElevenLabs account, unfiltered.

    Unfiltered deliberately: the endpoint takes no parameters, and the door needs the whole
    list to report which accents the account actually holds. Narrowing happens above.
    """
    body = await _get(VOICES_URL)
    voices = body.get("voices")
    return [_from_account(v) for v in voices if isinstance(v, dict)] if isinstance(voices, list) else []


class LibraryPage(NamedTuple):
    """One page of the Voice Library, and whether the provider says there is another.

    **A bare list cannot say "and there are more."** Every call here is bounded by
    `LIBRARY_PAGE_SIZE` and there is no pagination, so a consumer handed a list has no way to
    tell a complete answer from a first page and will eventually present one as the other -
    which on a picker reads as "that voice is not in the library" rather than as "narrow your
    filters". `has_more` is ElevenLabs' own answer about its own listing, passed through
    unread, the same rule every other field in this module follows.
    """

    voices: list[dict[str, Any]]
    has_more: bool


async def fetch_library_voices(
    *,
    accent: str | None = None,
    gender: str | None = None,
    language: str | None = None,
    search: str | None = None,
    page: int = 0,
    account_ids: frozenset[str] = frozenset(),
) -> LibraryPage:
    """The Voice Library, filtered **by the API**, as one bounded page.

    Every filter this takes is a query parameter ElevenLabs itself accepts, and each one is
    forwarded verbatim. Nothing in this function decides what `scottish` or `female` mean, and
    a filter value this codebase has never heard of reaches the provider unaltered - which is
    the point. A closed vocabulary here would be a restatement of ElevenLabs' own, stale the
    first time they add an accent.

    Returns a `LibraryPage` rather than a list so the truncation is visible to every caller -
    see that class for why a list was the wrong return type.

    `page` is zero-based and always sent, because the request should say which page it means
    rather than rely on a default that is the provider's to change. Only the vocabulary probe
    passes anything but `0`: the picker's result set is one page with a `has_more` beside it,
    and a caller wanting more narrows the filters.
    """
    params: dict[str, Any] = {"page_size": LIBRARY_PAGE_SIZE, "page": page}
    for key, value in (
        ("accent", accent), ("gender", gender), ("language", language), ("search", search)
    ):
        if value:
            params[key] = value
    body = await _get(SHARED_VOICES_URL, params)
    has_more = bool(body.get("has_more"))
    voices = body.get("voices")
    if not isinstance(voices, list):
        return LibraryPage([], has_more)
    return LibraryPage(
        [_from_library(v, account_ids=account_ids) for v in voices if isinstance(v, dict)],
        has_more,
    )


def filter_account_voices(
    voices: list[dict[str, Any]],
    *,
    accent: str | None = None,
    gender: str | None = None,
) -> list[dict[str, Any]]:
    """Narrow the account listing on the labels the provider sent back.

    `GET /v1/voices` accepts no filter parameters, so this is the only place the same
    narrowing can happen for it. It compares against `labels.accent` and `labels.gender` from
    the response - the provider's own answer about its own voice - and holds no opinion about
    which voice is which. Matching is case-insensitive because the two listings' spellings
    are the provider's and a caller should not have to know them.
    """
    def keeps(voice: dict[str, Any]) -> bool:
        for wanted, field in ((accent, "accent"), (gender, "gender")):
            if not wanted:
                continue
            have = voice.get(field)
            if not isinstance(have, str) or have.strip().lower() != wanted.strip().lower():
                return False
        return True

    return [v for v in voices if keeps(v)]


def accents_present(voices: list[dict[str, Any]]) -> list[str]:
    """The distinct accents in a listing, sorted - derived from the answer, never declared.

    It is what a picker's accent dropdown is built from, so the options a consultant sees are
    the accents that exist rather than a list in this repository that has to be maintained
    against the account.
    """
    return sorted({v["accent"] for v in voices if isinstance(v.get("accent"), str)})


def languages_present(voices: list[dict[str, Any]]) -> list[str]:
    """The distinct languages in a listing, sorted - derived from the answer, never declared.

    **Two places, because the two endpoints put it in two places**, exactly as they do for the
    accent and the sex. A library entry carries a top-level `language`; an account voice
    carries `verified_languages`, a list of objects each naming a `language` alongside the
    `model_id` it was verified against. Both are read, and neither is interpreted - this
    function holds no opinion about which voice speaks what, and a code it has never seen
    reaches a picker's dropdown unaltered.

    It is what the language control is built from, so what a consultant is offered is what the
    listings hold rather than a vocabulary maintained in this repository against theirs.
    """
    found: set[str] = set()
    for voice in voices:
        direct = voice.get("language")
        if isinstance(direct, str) and direct.strip():
            found.add(direct.strip())
        verified = voice.get("verified_languages")
        if not isinstance(verified, list):
            continue
        for entry in verified:
            # A list of objects on every voice observed so far, but a bare string is the
            # obvious shape for them to move to and costs one branch to accept.
            code = entry.get("language") if isinstance(entry, dict) else entry
            if isinstance(code, str) and code.strip():
                found.add(code.strip())
    return sorted(found)


class LibraryProbe(NamedTuple):
    """The vocabularies an unfiltered page of the library holds, and whether it was the lot.

    **Two axes off one walk**, because that is what the unfiltered requests answer. It was
    `AccentProbe` while the accent was the only axis a picker offered; making it two was the
    alternative to a second walk asking the same pages the same question.

    `partial` is the last page's `has_more` under the name that says what it *means* here:
    both lists are read off a bounded walk, so a `True` is the probe saying "this is not the
    library's whole vocabulary" - of either axis, since the pages the walk did not reach were
    not read for either. A picker may render the options either way; it must not present them
    as exhaustive when this is set.
    """

    accents: list[str]
    languages: list[str]
    partial: bool


# What the Voice Library holds, once per process. See `library_axes` for why this is cached
# and why only a successful answer is stored.
_LIBRARY_PROBE: LibraryProbe | None = None


def forget_library_probe() -> None:
    """Drop the cached library vocabularies. For tests, and for a long-lived process."""
    global _LIBRARY_PROBE
    _LIBRARY_PROBE = None


# Registered so `conftest.reset_process_caches` empties it between tests. Without it a test
# that warmed the cache would answer for the next test's differently-stocked library, and the
# second test would pass because of the first rather than because of the code.
register_cache(forget_library_probe)


async def library_axes() -> LibraryProbe:
    """The accents and languages the Voice Library holds, asked **unfiltered**.

    This exists because deriving the picker's options from the account listing alone made
    **Irish unreachable**, and Irish is one of the four planned engagements. The account holds
    british, american, australian, new zealand and scottish; irish exists only in the library.
    So a dropdown built from the account can never offer it, and the only two ways to reach an
    Irish voice were to type the accent as free text - which is not what an open vocabulary was
    chosen for - or to hardcode a list of accents, which would be the sixth declaration of
    voice facts on a branch that exists to end them.

    **Unfiltered, and that is the whole point.** The narrowed library call cannot answer this:
    asked with `accent=british` it reports british, so a dropdown derived from it offers
    exactly the option already selected. The two calls ask different questions and both are
    needed, which is the same reason the door asks two endpoints rather than one.

    **The language axis arrived with the same argument and it is worth stating separately.**
    The narrowed call now carries `language=en` by default, so a language dropdown derived
    from it would offer `en` and nothing else - the identical failure the accent half already
    had, on the axis that exists precisely to be widened. The probe carries neither, so it can
    answer both.

    **Cached per process**, because which accents exist in the Voice Library is a fact about
    the provider rather than about this request, and a picker that narrows as a consultant
    types would otherwise make one of these per keystroke. Only a **successful** answer is
    stored, matching `voice_metadata`'s rule: a timeout says nothing about the library, and
    caching it would make one bad minute permanent for the life of the process.

    **Several pages of the library, not an enumeration of it.** `LIBRARY_PROBE_PAGES` bounds
    the walk and `partial` reports whether it ran out of pages or ran out of patience. The
    requested accent is added to the options by the door regardless, so a caller's own choice
    is never missing from their own picker.

    **One page was not enough, and it failed in the way that is hardest to notice.** The
    library's first page is a moving selection, so the accent dropdown's vocabulary changed
    without anybody changing anything: on 7 September irish was on page 0 at 04:44 and on page
    1 by 15:00. Patrick opened the picker and Irish was simply gone - not an error, not an
    empty list, just an option that had been there in the morning. `?accent=irish` against the
    same door returned 85 library voices throughout; only the probe was blind to them.

    That is why the walk stops on `has_more` rather than after a fixed number of requests: the
    common case stays one request, and the pages are only paid for when the provider says
    there are more. And it is why `partial` remains - four pages is a wider window, not a
    complete answer, and a control told the list is exhaustive when it is not is exactly the
    failure this repaired.

    **The four accents this has to serve are split across the two listings**, which is why the
    union in the door needs both halves and neither is redundant. Irish reaches the picker only
    through this probe and Scottish only through the account listing. **No accent is named in
    any decision here**, and none may be: a list of accents in this repository is the sixth
    declaration of voice facts, and it would be wrong the first time the provider adds one.
    The repair for a missing accent is a wider window and an honest `partial`, never a name.
    """
    global _LIBRARY_PROBE
    if _LIBRARY_PROBE is not None:
        return LibraryProbe(
            list(_LIBRARY_PROBE.accents),
            list(_LIBRARY_PROBE.languages),
            _LIBRARY_PROBE.partial,
        )

    accents: set[str] = set()
    languages: set[str] = set()
    # The provider's own "there is more behind this", carried out of the loop. It is the
    # *last* page's answer rather than any accumulated flag: reaching a page that says
    # `has_more` is false means the walk saw the end of the library, whichever page that was,
    # and reaching the bound with it still true means it did not.
    partial = False
    failed = False
    for index in range(LIBRARY_PROBE_PAGES):
        try:
            page = await fetch_library_voices(page=index)
        except VoiceCatalogueUnavailable:
            # **A walk has more chances to fail than a single request did**, and the repair
            # for that must not be to throw away what already arrived - that would make this
            # probe *more* fragile than the one-page version it replaced, showing up as the
            # same "Irish has disappeared" it was written to fix.
            #
            # Page 0 is the exception and stays a raise: nothing was gathered, so there is no
            # partial answer to keep, and the door already turns it into `partial` without
            # suppressing the result set beside it.
            if index == 0:
                raise
            failed = True
            partial = True
            break
        accents.update(accents_present(page.voices))
        languages.update(languages_present(page.voices))
        partial = page.has_more
        if not partial:
            break

    probe = LibraryProbe(sorted(accents), sorted(languages), partial)
    # **Only a complete walk is cached**, which is `voice_metadata`'s rule applied to a loop:
    # a page that timed out says nothing about the library, and storing the short answer would
    # make one bad minute permanent for the life of the process - precisely the accent going
    # missing until somebody restarts the server. A truncation is different and *is* cached:
    # `has_more` is the provider's own answer about its own listing, not a failure.
    if not failed:
        _LIBRARY_PROBE = probe
    return probe


async def add_library_voice(
    *, public_owner_id: str, voice_id: str, name: str
) -> dict[str, Any]:
    """Copy a Voice Library voice into this deployment's ElevenLabs account.

    A write, and not a project-scoped one - see `api/routers/voices.py`. The new voice gets a
    **new** `voice_id` in the account, which is why the response is returned rather than
    discarded: it is the id a project's configuration must then hold, and the library id is
    not usable in its place.
    """
    headers = {"xi-api-key": _api_key(), "Content-Type": "application/json"}
    client = get_tts_client()
    url = f"{ADD_SHARED_VOICE_URL}/{public_owner_id}/{voice_id}"
    try:
        resp = await client.post(url, headers=headers, json={"new_name": name}, timeout=30.0)
        resp.raise_for_status()
        return resp.json()
    except httpx.HTTPStatusError as exc:
        raise VoiceCatalogueUnavailable(
            f"ElevenLabs answered {exc.response.status_code} adding voice {voice_id}"
        ) from exc
    except (httpx.HTTPError, json.JSONDecodeError) as exc:
        raise VoiceCatalogueUnavailable(
            f"ElevenLabs could not be reached to add voice {voice_id}"
        ) from exc
