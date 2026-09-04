# api/services/voice_metadata.py
"""What ElevenLabs says about a voice, asked rather than restated.

One question is answered here today - **a voice's sex** - and it is answered by asking the
provider, because the provider is where the fact lives. `GET /v1/voices/{voice_id}` returns a
`labels` object carrying `gender`, `accent`, `age` and `description`, and `labels.gender` is
the authority the interviewer selection reads.

**Why this is not a table.** The obvious implementation of "always female" is two lines mapping
`stakeholder_interviewer` to male and `second_interviewer` to female. That table would be the
sixth declaration of voice facts on a branch that exists to end the first five, and it would be
wrong the first time a project overrides an interviewer's voice - which is the entire point of
`project_agent_config`. The sex belongs to the **voice**, and the voice is a per-project
setting, so the only correct answer is the one the resolved voice's own metadata gives. Task 2
named Laura `second_interviewer` rather than `female_interviewer` for exactly this reason: her
id says where she sits on the roster, and nothing about how she sounds.

**Cached, because a voice's sex does not change.** The cache is per process and keyed on the
voice id. It records the answer to a *successful* lookup only, including a successful lookup
that found no `gender` label at all - that is the provider saying "no answer", which is itself
a stable fact. A failed request is not cached: a timeout or a 500 says nothing about the voice
and caching it would make one bad minute permanent for the life of the process.

**Nothing here reaches ElevenLabs unless a project has asked for a sex.** `random` is the
shipped default and needs no metadata, so an ordinary deployment makes no call from this module.

The client is `get_tts_client()`, the same shared `httpx.AsyncClient` `synthesise` uses - one
client, one place a test installs a `MockTransport`, and one place a timeout is configured.
Building a second client here is how a request ends up with a different timeout, a different
header set, or (as `llm_client` learned expensively) a different wire protocol entirely.
"""
from __future__ import annotations

import json

import httpx

from api.config import get_settings
from api.services.http_clients import get_tts_client
from api.services.process_cache import register_cache

_VOICES_URL = "https://api.elevenlabs.io/v1/voices"

# voice_id -> the gender label ElevenLabs answered with, or None where it carries none.
_GENDER_CACHE: dict[str, str | None] = {}


def forget_voice_metadata() -> None:
    """Drop the cache. For tests, and for an operator who has re-labelled a voice."""
    _GENDER_CACHE.clear()


# Registered so `conftest.reset_process_caches` empties it between tests. It matters here more
# than the name suggests: a test that establishes Alice as female would otherwise answer for
# the next test's differently-labelled Alice, and the second test would pass because of the
# first rather than because of the code.
register_cache(forget_voice_metadata)


async def voice_gender(voice_id: str) -> str | None:
    """The `labels.gender` ElevenLabs holds for this voice, lowercased, or None.

    None means "the provider does not say", and callers must treat it as *unknown* rather than
    as "not the sex I asked for". The two are different and only one of them is a reason to
    refuse.

    Raises `ValueError` when no API key is configured, matching `synthesise` - a deployment
    that cannot reach ElevenLabs cannot conduct a voice interview either, so answering a
    confident default here would only move the failure to a worse place.
    """
    if voice_id in _GENDER_CACHE:
        return _GENDER_CACHE[voice_id]

    settings = get_settings()
    if not settings.elevenlabs_api_key:
        raise ValueError("ELEVENLABS_API_KEY not configured")

    client = get_tts_client()
    resp = await client.get(
        f"{_VOICES_URL}/{voice_id}",
        headers={"xi-api-key": settings.elevenlabs_api_key},
        timeout=15.0,
    )
    resp.raise_for_status()
    labels = resp.json().get("labels") or {}
    gender = labels.get("gender") if isinstance(labels, dict) else None
    answer = gender.strip().lower() if isinstance(gender, str) and gender.strip() else None
    _GENDER_CACHE[voice_id] = answer
    return answer


async def voice_gender_or_unknown(voice_id: str | None) -> str | None:
    """`voice_gender`, but a transport failure is None rather than an exception.

    The distinction a caller needs is "this voice is female" against "I could not establish
    that this voice is female", and an unreachable API, an unparseable body and a voice with
    no `gender` label all land in the second.

    A **missing key is not swallowed**. That is a deployment fault rather than a fact about a
    voice, it is the one an operator can fix, and it is the one that would otherwise turn
    "always female" into "whoever the shuffle produces" on every deployment that has not
    configured ElevenLabs - silently, and permanently, because the choice is stamped.
    """
    if not voice_id:
        return None
    try:
        return await voice_gender(voice_id)
    except (httpx.HTTPError, json.JSONDecodeError, KeyError, TypeError):
        return None
