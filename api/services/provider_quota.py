# api/services/provider_quota.py
"""What each provider will tell us about how much credit is left.

**A balance is a leading indicator; an exhaustion is an event.** `provider_health.classify`
already catches the event - the 400 that means "your credit balance is too low", the 401 that
means "you have exceeded your character quota" - and that is the guarantee, because it fires on
the call that was actually refused. These readers are the *warning before* that, and they are
only as fresh as the last time somebody asked.

So they are `HealthCheck` probes, called at the moment of a real failure to tell an operator
which kind it was, in the same shape and for the same reason as `check_vector_store`. **Nothing
calls them on a timer.** A quota that is fine between polls and exhausted during one is a poll
that lied, and this module would rather answer a question somebody is actually asking.

## What each provider exposes, measured on 17 September 2026 rather than recalled

| Provider | Reads a balance? | Measured |
|---|---|---|
| **Anthropic** | no endpoint exists | rate-limit headers ride every response; captured by the event hook on the shared client, not here |
| **Deepgram** | `/v1/projects/{id}/balances` → **403** with a Member key | `/v1/projects/{id}/usage` → **200**: hours consumed, which is what this reads |
| **ElevenLabs** | `/v1/user/subscription` → **401**, *"the API key is missing the permission"* | `character_count` / `character_limit` the moment the key is re-scoped |
| **Chroma Cloud** | **none** - `/usage`, `/quota`, `/billing/usage` all 404 | reachability only, which `check_vector_store` already does |

**Two of the four are blocked on a key's permissions rather than on code**, which is why both
readers below are written to answer *"I could not read this, and here is the remedy"* rather
than to raise or - far worse - to report healthy. A quota check that cannot see the quota and
says nothing is indistinguishable from one that looked and found plenty.
"""
from __future__ import annotations

import logging

from api.config import get_settings
from api.services.health_types import HealthResult

_log = logging.getLogger(__name__)

SPEECH_QUOTA = "speech_quota"
TRANSCRIPTION_USAGE = "transcription_usage"

# Warn once the account is this far through its allowance. Not a guess about how much is
# "enough" - it is the point at which a person still has time to act, which is the only thing
# a threshold on a monthly allowance can usefully mean.
_WARN_AT = 0.85

_TIMEOUT_SECONDS = 8.0

# The window for a consumption read, when the allowance itself cannot be read. Thirty days
# because ElevenLabs' allowance is monthly, so a shorter window would understate a month
# that is nearly spent and a longer one would span two resets.
_CONSUMPTION_WINDOW_DAYS = 30


def _read(url: str, headers: dict[str, str]) -> tuple[int, object]:
    """One GET, answering `(status, parsed-or-text)`. Never raises.

    Synchronous and building its own client deliberately: every caller is inside an `except`
    block on a thread that is already handling a failure, and the shared async clients belong
    to the request loop. A probe that needed an event loop could not be called from where the
    failures are.
    """
    import httpx

    try:
        r = httpx.get(url, headers=headers, timeout=_TIMEOUT_SECONDS)
    except Exception as exc:  # network, DNS, TLS - all mean "could not read"
        return 0, f"{type(exc).__name__}: {exc}"
    try:
        return r.status_code, r.json()
    except ValueError:
        return r.status_code, r.text


def check_speech_quota(_slug: str = "") -> HealthResult:
    """ElevenLabs' character allowance, if the key may read it.

    Takes an unused slug so it matches `HealthCheck.probe`'s signature: the allowance is a
    property of the **account**, not of a project, and one account serves every engagement -
    the same reason `POST /voices/library` is platform-tier rather than project-scoped.
    """
    settings = get_settings()
    key = (settings.elevenlabs_api_key or "").strip()
    if not key:
        return HealthResult(False, "ELEVENLABS_API_KEY is not set, so no speech quota can be read.")

    status, body = _read(
        "https://api.elevenlabs.io/v1/user/subscription", {"xi-api-key": key}
    )

    if status == 401:
        # Measured, not assumed: the live key synthesises and lists voices perfectly and is
        # refused this endpoint alone. Reporting it as a bad key would send an operator to
        # replace one that works - which is the same trap `classify` exists to avoid one layer
        # down, where ElevenLabs spells quota exhaustion as a 401 too.
        #
        # **Fall through to consumption rather than giving up.** The allowance needs the
        # `user_read` permission, which the account's Editor role does not carry - ElevenLabs
        # names the missing permission in the refusal, which is how this is known rather than
        # guessed. `/v1/usage/character-stats` is served to the same key and answers what has
        # been *spent*, which is worth having: it cannot say "you are nearly out", and it can
        # say "something is consuming this" and prove the account answers.
        return _speech_consumption(key)
    if status != 200 or not isinstance(body, dict):
        return HealthResult(
            False, f"Could not read the ElevenLabs character allowance (HTTP {status}): {body}"
        )

    used, limit = body.get("character_count"), body.get("character_limit")
    if not isinstance(used, int) or not isinstance(limit, int) or limit <= 0:
        return HealthResult(
            False, f"ElevenLabs answered without a usable character allowance: {body}"
        )

    fraction = used / limit
    if fraction >= _WARN_AT:
        return HealthResult(
            False,
            f"ElevenLabs is {fraction:.0%} through its character allowance "
            f"({used:,} of {limit:,} on the {body.get('tier', 'current')} tier). Interviews "
            f"stop speaking when it is exhausted - top up or raise the plan.",
        )
    return HealthResult(True, f"ElevenLabs at {fraction:.0%} of {limit:,} characters.")


def _speech_consumption(key: str, *, now_ms: int | None = None) -> HealthResult:
    """Characters spent over the last 30 days, for a key that may not read the allowance.

    The second-best answer, and the one this deployment gets today. `now_ms` is a parameter
    rather than a clock read here, so the window is deterministic in a test - this project has
    lost three tests to a `new Date()` default and the rule is to pass the clock everywhere,
    including where it cannot currently matter.
    """
    import time

    end = now_ms if now_ms is not None else int(time.time() * 1000)
    start = end - _CONSUMPTION_WINDOW_DAYS * 24 * 3600 * 1000
    status, body = _read(
        f"https://api.elevenlabs.io/v1/usage/character-stats?start_unix={start}&end_unix={end}",
        {"xi-api-key": key},
    )
    if status != 200 or not isinstance(body, dict):
        return HealthResult(
            False,
            "The ElevenLabs key can neither read the account's character allowance (it is "
            "missing the `user_read` permission) nor its usage "
            f"(HTTP {status}). Speech synthesis is unaffected and this is not a bad key: add "
            "`user_read` to the key in the ElevenLabs console to see how much allowance is "
            "left before it runs out.",
        )

    usage = body.get("usage")
    spent = 0
    if isinstance(usage, dict):
        for series in usage.values():
            if isinstance(series, list):
                spent += sum(v for v in series if isinstance(v, (int, float)))
    return HealthResult(
        True,
        f"ElevenLabs spent {spent:,.0f} characters in the last {_CONSUMPTION_WINDOW_DAYS} days. "
        "This is consumption, not the allowance remaining - the key is missing the `user_read` "
        "permission, so the limit cannot be read and no percentage can be given.",
    )


def check_transcription_usage(_slug: str = "") -> HealthResult:
    """Deepgram's consumption, because its balance needs a permission the key does not have.

    **This reports usage, not a balance, and the difference is the honest part.** The Member key
    is refused `/balances` (403) and served `/usage` (200), so what can be known is hours
    consumed rather than credit remaining. Usage alone cannot say "you are about to run out";
    it can say "something is consuming this" and it establishes that the account is answering.
    Do not let a later change present it as a balance.
    """
    settings = get_settings()
    key = (settings.deepgram_api_key or "").strip()
    if not key:
        return HealthResult(
            False, "DEEPGRAM_API_KEY is not set, so no transcription usage can be read."
        )

    headers = {"Authorization": f"Token {key}"}
    status, body = _read("https://api.deepgram.com/v1/projects", headers)
    if status != 200 or not isinstance(body, dict) or not body.get("projects"):
        return HealthResult(
            False, f"Could not reach the Deepgram account (HTTP {status}): {body}"
        )

    project_id = body["projects"][0].get("project_id")
    status, body = _read(
        f"https://api.deepgram.com/v1/projects/{project_id}/usage", headers
    )
    if status == 403:
        return HealthResult(
            False,
            "The Deepgram key cannot read this project's usage - it is missing the required "
            "scope. Transcription is unaffected: issue a key with Admin or Owner authorisation "
            "in the Deepgram console to read usage and balances.",
        )
    if status != 200 or not isinstance(body, dict):
        return HealthResult(
            False, f"Could not read Deepgram usage (HTTP {status}): {body}"
        )

    results = body.get("results")
    hours = sum(
        r.get("hours", 0) or 0 for r in results if isinstance(r, dict)
    ) if isinstance(results, list) else 0
    return HealthResult(
        True,
        f"Deepgram answered: {hours:.2f} hours transcribed between "
        f"{body.get('start', '?')} and {body.get('end', '?')}. This is consumption, not a "
        f"remaining balance - the key may not read balances.",
    )
