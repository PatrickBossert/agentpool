# api/services/voice_metadata.py
"""What ElevenLabs says about a voice, asked rather than restated.

One question is answered here today - **a voice's sex** - and it is answered by asking the
provider, because the provider is where the fact lives. `GET /v1/voices/{voice_id}` returns a
`labels` object carrying `gender`, `accent`, `age` and `description`, and `labels.gender` is
the authority the interviewer selection reads.

Two callers ask it and they need different answers, so there are two functions rather than one
with a flag. `ask_voice_sex` reports **whether the provider answered** as well as what, because
the interviewer selection refuses a batch of sessions on the difference and has to say which of
three things went wrong. `resolved_voice_sex` narrows the same answer to the single value a
voice picker can pre-set a filter from, and answers `None` for everything else. Both read one
lookup; neither is a second source.

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

# Where ElevenLabs is. Declared here because this module held the first of these URLs, and
# `api/services/voice_catalogue.py` imports both rather than typing the host a second time -
# two modules holding the same literal is the duplication this branch exists to end, one
# category along from the four disagreeing voice tables. The text-to-speech URL in
# `interview_service.synthesise` is deliberately left where it is: this is a listing seam and
# does not touch the synthesis path.
ELEVENLABS_V1 = "https://api.elevenlabs.io/v1"
VOICES_URL = f"{ELEVENLABS_V1}/voices"

# voice_id -> what the provider answered about it, cached only when it answered.
_GENDER_CACHE: dict[str, str | None] = {}

# The sexes this product can act on. **Not a vocabulary this repository owns** - it is the
# subset of ElevenLabs' `labels.gender` that anything here can do something with, and the two
# places that act on a sex both handle exactly these: `interviewer_selection`'s `always_male`
# and `always_female`, and the voice picker's own gender filter. A voice labelled anything else
# is a voice whose sex is not actionable, which `resolved_voice_sex` reports as no answer.
#
# It is deliberately **not** used to narrow `voice_gender`, which reports what the provider
# said. "What ElevenLabs holds for this voice" and "what this product can filter on" are two
# questions, and collapsing them would make an unrecognised label indistinguishable from an
# unlabelled voice at the one seam that still has both facts in hand.
ACTIONABLE_VOICE_SEXES = frozenset({"male", "female"})


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
            f"{VOICES_URL}/{voice_id}",
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


async def resolved_voice_sex(voice_id: str | None) -> str | None:
    """One voice's sex where it can be established **and acted on**, for a picker to pre-set.

    `ask_voice_sex` reports whether the provider answered as well as what; this narrows that to
    the single value a filter can be pre-set from, and answers `None` for everything else. Four
    routes in, two answers out:

    | Route | Answer | What a picker does |
    |---|---|---|
    | the provider gave `male` or `female` | that sex | opens on voices of that sex |
    | the provider gave some other label | None | opens unfiltered |
    | the provider carries no `gender` label, or there is no voice to ask about | None | opens unfiltered |
    | the provider could not be asked, including for want of an API key | None | opens unfiltered |

    **Only the first pre-sets a filter, and the rest open unfiltered rather than empty.**
    Showing nothing because a lookup failed is the worst outcome available - it is
    indistinguishable from an account with no voices, and it sends a consultant to diagnose a
    picker that is working.

    **The third row is why the label is narrowed here rather than passed through.** A voice
    labelled `Non-Binary` is a real answer from the provider, and `non-binary` is not among the
    options the listing offers - so pre-setting it would send `gender=non-binary` to the
    listing, which answers nothing, and the picker would open **empty**: the one outcome the
    design forbids, reached by way of a perfectly correct provider answer.

    **It is a default, not a lock.** A project that gives an interviewer a voice of the other
    sex has said something, and `interviewer_selection` says so in writing; nothing here
    refuses anything, it only reports what the voice already is.

    **A missing API key is answered here and not swallowed in `ask_voice_sex`.** That function
    lets `ValueError` out on purpose, because for the session stamp a deployment with no key
    would otherwise turn "always female" into whoever the shuffle produced - permanently, since
    the choice is stamped. This caller has the opposite obligation: it decorates a listing a
    consultant asked for, and a 503 for want of a sex would take the whole voice picker down
    over a field that only pre-sets a default. The refusal is right where it is raised and
    wrong here, so it is caught at this call site rather than removed from that one. It is
    caught narrowly - `ValueError` is a wide net, `json.JSONDecodeError` is one of its
    subclasses, and only the missing-key sentence belongs to this branch.

    Callers monkeypatching `ask_voice_sex` should patch it **on this module**, which is where
    this function looks it up.
    """
    try:
        answer = await ask_voice_sex(voice_id)
    except ValueError as exc:
        if "ELEVENLABS_API_KEY" not in str(exc):
            raise
        # No key configured. Nothing was asked, so nothing is known - the same answer as a
        # lookup that failed, and for the same reason.
        return None
    if not answer.answered:
        # Unreachable, refused, or unparseable. This says nothing about the voice, so it must
        # not be reported as a fact about it.
        return None
    if answer.label is None:
        # Asked and answered: either this voice carries no `gender` label, or there was no
        # voice to ask about - "an agent with no voice has no sex, which is a fact rather than
        # an outage". Neither is a sex, and neither is a filter.
        return None
    if answer.label not in ACTIONABLE_VOICE_SEXES:
        # A real answer this product cannot act on. Reported as no answer rather than passed
        # through, so it opens the picker unfiltered instead of filtering it to nothing.
        return None
    return answer.label
