# api/services/voice_catalogue.py
"""The voices a project may choose from, asked of ElevenLabs rather than listed here.

**Two listings, and they are not interchangeable.** Established by calling the API on 4
September rather than assumed:

| | `GET /v1/voices` | `GET /v1/shared-voices` |
|---|---|---|
| Holds | the voices **in this account** | the whole Voice Library |
| Accents | british, american, australian, new zealand, scottish | those plus **irish** |
| Rate | `available_for_tiers`, and it is `[]` on every one | **`rate`**, `fiat_rate` |
| Filters | none | `accent`, `gender`, `language`, `search` |
| Preview | `preview_url` | `preview_url` |

So the rate exists only on the library, and Irish exists only on the library. A picker built
on one of them is missing either the cost or half the accents, which is why
`fetch_voice_catalogue` asks both and the door returns both.

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
from typing import Any

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
LIBRARY_PAGE_SIZE = 100


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


async def fetch_library_voices(
    *,
    accent: str | None = None,
    gender: str | None = None,
    language: str | None = None,
    search: str | None = None,
    account_ids: frozenset[str] = frozenset(),
) -> list[dict[str, Any]]:
    """The Voice Library, filtered **by the API**.

    Every filter this takes is a query parameter ElevenLabs itself accepts, and each one is
    forwarded verbatim. Nothing in this function decides what `scottish` or `female` mean, and
    a filter value this codebase has never heard of reaches the provider unaltered - which is
    the point. A closed vocabulary here would be a restatement of ElevenLabs' own, stale the
    first time they add an accent.
    """
    params: dict[str, Any] = {"page_size": LIBRARY_PAGE_SIZE}
    for key, value in (
        ("accent", accent), ("gender", gender), ("language", language), ("search", search)
    ):
        if value:
            params[key] = value
    body = await _get(SHARED_VOICES_URL, params)
    voices = body.get("voices")
    if not isinstance(voices, list):
        return []
    return [_from_library(v, account_ids=account_ids) for v in voices if isinstance(v, dict)]


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


# The accents the Voice Library holds, once per process. See `library_accents` for why this
# is cached and why only a successful answer is stored.
_LIBRARY_ACCENTS: list[str] | None = None


def forget_library_accents() -> None:
    """Drop the cached library accents. For tests, and for a long-lived process."""
    global _LIBRARY_ACCENTS
    _LIBRARY_ACCENTS = None


# Registered so `conftest.reset_process_caches` empties it between tests. Without it a test
# that warmed the cache would answer for the next test's differently-stocked library, and the
# second test would pass because of the first rather than because of the code.
register_cache(forget_library_accents)


async def library_accents() -> list[str]:
    """The accents the Voice Library holds, asked **unfiltered**.

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

    **Cached per process**, because which accents exist in the Voice Library is a fact about
    the provider rather than about this request, and a picker that narrows as a consultant
    types would otherwise make one of these per keystroke. Only a **successful** answer is
    stored, matching `voice_metadata`'s rule: a timeout says nothing about the library, and
    caching it would make one bad minute permanent for the life of the process.

    **It is a page of the library, not an enumeration of it.** `LIBRARY_PAGE_SIZE` bounds it,
    so an accent held by only a handful of voices beyond the first page will not appear. That
    is a real limit and it is stated rather than hidden - the alternative is a declared list,
    which is worse, and the requested accent is added to the options by the door regardless so
    a project's own choice is never missing from its own picker.
    """
    global _LIBRARY_ACCENTS
    if _LIBRARY_ACCENTS is None:
        _LIBRARY_ACCENTS = accents_present(await fetch_library_voices())
    return list(_LIBRARY_ACCENTS)


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
