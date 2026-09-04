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

**The client is deliberately not the shared one**, and `_client` below says why at length: this
module is called from a CrewAI worker thread running its own short-lived event loop, and an
httpx connection pool is bound to the loop that created it. It was `get_tts_client()` when this
landed, and that would have failed a live participant's `POST /speak` with "Event loop is
closed" - invisibly to every test, because a `MockTransport` has no pool.
"""
from __future__ import annotations

import json
from dataclasses import dataclass

import httpx

from api.config import get_settings
from api.services.process_cache import register_cache

_VOICES_URL = "https://api.elevenlabs.io/v1/voices"

# voice_id -> what the provider answered about it, cached only when it answered.
_GENDER_CACHE: dict[str, str | None] = {}


def _client() -> httpx.AsyncClient:
    """A short-lived client for this one lookup, deliberately **not** `get_tts_client()`.

    The shared client is a process-global keep-alive `httpx.AsyncClient`, and an httpx
    connection pool holds anyio primitives bound to the event loop that created them. This
    module is called from `InterviewSessionTool._create`, which runs on a CrewAI worker thread
    under its own `asyncio.run` - a *different, short-lived* loop from the one serving
    requests. Borrowing the shared pool there poisons it in both directions: the lookup itself
    fails with "bound to a different event loop" if a request pooled a connection first, and
    the next participant's `POST /speak` fails with "Event loop is closed" if the crew went
    first. That second one is a **500 to a participant**, and the portal treats a failed
    `/speak` as "skip the audio and continue", so the question is displayed and never spoken.

    A once-per-batch metadata call has nothing to gain from a shared pool - the whole reason
    `http_clients` exists is the per-utterance TLS handshake on the interview request path, and
    this is two requests per interview *programme*. So it opens its own, and closes it.

    No test could have caught the original defect, which is the part worth remembering: every
    test installs a `MockTransport`, and a `MockTransport` has no connection pool. The mock was
    one layer away from the thing that breaks.
    """
    return httpx.AsyncClient(timeout=15.0)


@dataclass(frozen=True)
class VoiceSexAnswer:
    """What the provider said about one voice's sex, and whether it said anything at all.

    Three states, and the third is the one a single `str | None` cannot express:

    | `answered` | `label` | Means |
    |---|---|---|
    | True | `"female"` | the provider says this voice is female |
    | True | None | the provider answered, and carries no `gender` label for it |
    | False | None | we could not ask - unreachable, refused, 404, unparseable |

    Collapsing the last two is what let a refusal claim "no interviewer's voice is female
    **according to ElevenLabs**" when ElevenLabs had not been asked. That sentence sends an
    operator to change a correctly-configured voice, and it arrives inside a tool result to a
    language model mid-run, so it may be the only thing anybody ever reads about the failure.
    """

    label: str | None
    answered: bool

    @property
    def established(self) -> bool:
        """True when the provider gave a sex for this voice."""
        return self.answered and self.label is not None


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
    confident default here would only move the failure to a worse place. Every other failure -
    transport, status, body - propagates, and `ask_voice_sex` is where it becomes "we could not
    ask" rather than "the answer is no".
    """
    if voice_id in _GENDER_CACHE:
        return _GENDER_CACHE[voice_id]

    settings = get_settings()
    if not settings.elevenlabs_api_key:
        raise ValueError("ELEVENLABS_API_KEY not configured")

    async with _client() as client:
        resp = await client.get(
            f"{_VOICES_URL}/{voice_id}",
            headers={"xi-api-key": settings.elevenlabs_api_key},
        )
        resp.raise_for_status()
        body = resp.json()
    labels = body.get("labels") or {}
    gender = labels.get("gender") if isinstance(labels, dict) else None
    answer = gender.strip().lower() if isinstance(gender, str) and gender.strip() else None
    _GENDER_CACHE[voice_id] = answer
    return answer


async def ask_voice_sex(voice_id: str | None) -> VoiceSexAnswer:
    """Ask the provider about one voice, and report *whether it answered* as well as what.

    A **missing key is not swallowed**. That is a deployment fault rather than a fact about a
    voice, it is the one an operator can fix, and it is the one that would otherwise turn
    "always female" into "whoever the shuffle produces" on every deployment that has not
    configured ElevenLabs - silently, and permanently, because the choice is stamped.

    A voice id that is absent is not a failed lookup - there is nothing to ask about - so it
    answers `answered=True, label=None`: an agent with no voice has no sex, which is a fact
    rather than an outage.
    """
    if not voice_id:
        return VoiceSexAnswer(label=None, answered=True)
    try:
        return VoiceSexAnswer(label=await voice_gender(voice_id), answered=True)
    except (httpx.HTTPError, json.JSONDecodeError, KeyError, TypeError):
        return VoiceSexAnswer(label=None, answered=False)
