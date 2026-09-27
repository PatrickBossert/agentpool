# api/services/provider_health.py
"""Why a paid provider refused us, in the words that send an operator to the right place.

The owner's requirement, 18 September: *"chromadb on the web has usage credits that may run out.
Silent failure of chroma, elevenlabs, deepgram and claude must all be reported - they all require
usage-based credit top-ups."*

Registry members for `health_checks.py`, delivered through the seam in `operator_alert.py`.

## A balance is a poll; an exhaustion is an event

The reliable signal is not a balance reading - it is the refusal the provider already sends us,
and which this codebase has been swallowing at every one of these call sites. Polling says "12%
left" and is only as fresh as the last poll; a 402 is the ground truth, arriving exactly when it
becomes true.

It also covers causes a balance cannot see. Three Deepgram grants failed at the handshake on 17
September, the browser fallback engaged silently, the interview completed and nothing reached a
person - **and no balance poll would have caught it, because there was credit.** The request was
malformed.

So: capture at the call site first, because it is a guarantee. Leading indicators second, and
only where they are free - see `_LEADING_INDICATORS` at the foot of this module for what each
provider actually exposes, which is less than anybody assumes.

## The three outcomes, which is the whole value of this module

Conflating these is **worse than silence**, because each sends an operator somewhere different
and two of the three cost money or time to act on wrongly:

| Fault | What the operator must do | What they must NOT do |
|---|---|---|
| `OUT_OF_CREDIT` | top up the account | wait for it to clear |
| `RATE_LIMITED` | back off and retry | top up - it changes nothing |
| `MALFORMED_REQUEST` | fix the code; this is a defect | top up, or wait |
| `AUTH_REFUSED` | replace or re-scope the key | top up |
| `UNREACHABLE` | check the network or the provider's status | anything involving the account |

An operator told to top up when the request was malformed spends money and still has the fault.

## Why this is not a table of status codes

It very nearly was, and it would have been wrong for the two providers that matter most here.

- **Anthropic answers a credit exhaustion with `400`**, not `402` - `invalid_request_error`
  carrying *"Your credit balance is too low to access the Anthropic API"*. A plain
  `400 -> MALFORMED_REQUEST` rule reports the single most expensive condition in the system as a
  code defect, and sends somebody to debug a request that was perfectly well formed.
- **ElevenLabs answers a quota exhaustion with `401`**, carrying `{"detail": {"status":
  "quota_exceeded"}}` - the same status it uses for a bad key. A plain `401 -> AUTH_REFUSED`
  rule sends an operator to replace a key that is working.

So the classifier reads the **body** as well as the status, and the message-sniffing is
load-bearing rather than defensive. It is a pure function over `(provider, exception)` - no
network, no settings, no clock - so every one of these cases is driven directly in
`tests/test_provider_health.py` rather than being hoped for.

**Where a provider's own documented spelling is unknown, the classifier falls to `UNKNOWN` and
says so**, rather than guessing a remedy. An alert that says "this deployment does not recognise
this refusal" and quotes it is honest; one that guesses "top up" is not.

That promise **includes the two ambiguous pairs above**, and did not when it was first written:
an Anthropic 400 or an ElevenLabs 401 whose body did not match a credit phrase fell straight
through to `MALFORMED_REQUEST` and `AUTH_REFUSED`, whose remedies say in bold *do not top up*
and *replace the key*. A reworded message - or a body that could not be read, which a streamed
response makes routine - turned the two most expensive conditions in the system into confident
instructions to do the wrong thing. `_AMBIGUOUS_STATUSES` is the fix: for those pairs the body
must affirmatively say which cause it is, or the operator is told to read the response.

## What is deliberately not built

No dashboard, no history table, no forecasting, no auto-top-up, and no trend. The registry, the
members, and the seam that already exists.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

import httpx

_log = logging.getLogger(__name__)

# The providers this deployment pays for. Chroma is declared here as a *provider* as well as
# having its own reachability check in `health_checks.py`: those answer different questions, and
# a cloud account can be reachable and out of quota at the same moment.
ANTHROPIC = "anthropic"
DEEPGRAM = "deepgram"
ELEVENLABS = "elevenlabs"
CHROMA = "chroma"

PROVIDERS = (ANTHROPIC, DEEPGRAM, ELEVENLABS, CHROMA)

# The outcomes. Strings rather than an Enum so they can be an incident key without ceremony.
OUT_OF_CREDIT = "out_of_credit"
RATE_LIMITED = "rate_limited"
MALFORMED_REQUEST = "malformed_request"
AUTH_REFUSED = "auth_refused"
UNREACHABLE = "unreachable"
UNKNOWN = "unknown"

# Substrings that mean "the account has run out", checked against the response body.
#
# Checked **before** the status code for exactly the two cases the module docstring names, and
# kept as a list of provider-observed phrases rather than one clever regex: each entry is a claim
# about what a provider actually says, and a reader should be able to see which provider put it
# there.
_CREDIT_PHRASES = (
    "credit balance is too low",   # Anthropic, on a 400
    "quota_exceeded",              # ElevenLabs, on a 401
    "quota exceeded",
    "insufficient credit",
    "insufficient_quota",
    "out of credit",
    "payment required",
    "billing",
)

# Substrings that mean "slow down". Separate from credit because the remedy is the opposite:
# waiting fixes this one and money does not.
_RATE_PHRASES = (
    "rate limit",
    "rate_limit",
    "too many requests",
    "concurrent",
)

# `(provider, status)` pairs where the provider reuses one status for an exhausted account and
# for something with the opposite remedy. Declared rather than inferred: it is a fact about each
# provider's API, and a third entry should be added by somebody who has seen the provider do it.
_AMBIGUOUS_STATUSES = {
    (ANTHROPIC, 400),     # credit exhaustion, or a genuinely malformed request
    (ELEVENLABS, 401),    # quota exhaustion, or a bad key
}

# Affirmative signals that resolve an ambiguous pair. Only phrases a provider actually uses -
# "invalid_request_error" is deliberately absent, because Anthropic carries it on the credit
# message too and so discriminates nothing.
_AUTH_PHRASES = (
    "invalid_api_key",
    "invalid api key",
    "authentication_error",
    "invalid x-api-key",
    "could not be authenticated",
)
_MALFORMED_PHRASES = (
    "malformed",
    "is not valid json",
    "unexpected keyword",
    "field required",
    "input should be",
)


@dataclass(frozen=True)
class ProviderFault:
    """What went wrong with a paid provider, and what to do about it."""

    provider: str
    fault: str
    detail: str

    @property
    def incident_key(self) -> str:
        """One incident per provider per fault.

        Not per call site: a crew run and an interview both hitting an exhausted Anthropic
        account is one thing to fix. Not per provider alone either - an account that is rate
        limited *and* nearly out of credit are two different jobs, and collapsing them would let
        the noisy one hide the expensive one.
        """
        return f"provider:{self.provider}:{self.fault}"


def _body_text(exc: BaseException) -> str:
    """Whatever the provider said, lowercased, or '' if it said nothing readable.

    Never raises: this runs inside failure handling, and a body that cannot be read must not
    become a second failure on top of the first.
    """
    # **The provider's words, not ours.** `str(exc)` on an httpx error contains the request URL,
    # so a path containing "billing" - `/v1/billing/usage` - would match `_CREDIT_PHRASES` and
    # flip the remedy on a refusal that had nothing to do with credit. When there is a response,
    # its body is the only thing read; `str(exc)` is the fallback for errors that carry no
    # response at all, where it is the only text there is.
    response = getattr(exc, "response", None)
    if response is not None:
        try:
            return (response.text or "").lower()
        except Exception:
            # A streamed response raises `ResponseNotRead` here. Deliberately resolves to "" -
            # an unreadable body must not be matched against `str(exc)`, which would reintroduce
            # the URL, and `_AMBIGUOUS_STATUSES` is what stops "" becoming a confident guess.
            return ""
    return str(exc).lower()


def _status_of(exc: BaseException) -> int | None:
    """The HTTP status, from an httpx error or from an SDK error that carries one."""
    response = getattr(exc, "response", None)
    if response is not None:
        status = getattr(response, "status_code", None)
        if isinstance(status, int):
            return status
    status = getattr(exc, "status_code", None)
    return status if isinstance(status, int) else None


def classify(provider: str, exc: BaseException) -> ProviderFault:
    """Why the provider refused us. Pure: no network, no settings, no clock.

    Order is load-bearing and is the argument in the module docstring made executable. The body
    is consulted **before** the status, because the two most expensive conditions in this system
    are both spelled with a status that means something else: Anthropic's credit exhaustion is a
    400, and ElevenLabs' quota exhaustion is a 401.
    """
    text = _body_text(exc)
    status = _status_of(exc)

    if any(phrase in text for phrase in _CREDIT_PHRASES):
        return ProviderFault(provider, OUT_OF_CREDIT, _detail(exc, status))
    if status == 402:
        return ProviderFault(provider, OUT_OF_CREDIT, _detail(exc, status))

    if status == 429 or any(phrase in text for phrase in _RATE_PHRASES):
        return ProviderFault(provider, RATE_LIMITED, _detail(exc, status))

    # **The two pairs where the provider uses one status for two opposite causes.**
    #
    # Anthropic spells an exhausted balance `400`, the same status as a malformed request;
    # ElevenLabs spells an exhausted quota `401`, the same status as a bad key. The credit
    # phrases above catch the exhaustion *when the body says so* - but a body that has been
    # reworded, or that could not be read at all (a streamed response raises `ResponseNotRead`,
    # which `_body_text` swallows to ""), then falls through to a remedy that says in bold **do
    # not top up** while the balance is zero, or **replace the key** while the key is fine.
    #
    # A wrong-but-unrecognised refusal is cheap; a confidently wrong one is not. So for these
    # pairs an unmatched body resolves to `UNKNOWN`, whose remedy tells the operator to read the
    # response before assuming a cause - unless the body affirmatively says which it is.
    if (provider, status) in _AMBIGUOUS_STATUSES:
        if any(phrase in text for phrase in _AUTH_PHRASES):
            return ProviderFault(provider, AUTH_REFUSED, _detail(exc, status))
        if any(phrase in text for phrase in _MALFORMED_PHRASES):
            return ProviderFault(provider, MALFORMED_REQUEST, _detail(exc, status))
        return ProviderFault(
            provider,
            UNKNOWN,
            f"{_detail(exc, status)} - and {provider} uses HTTP {status} for an exhausted "
            f"{'balance' if provider == ANTHROPIC else 'quota'} as well as for the obvious "
            f"cause, so this deployment will not guess between them",
        )

    if status == 400:
        # Deepgram's "Keyterm limit exceeded" lives here, and it is a defect in what we sent
        # rather than anything about the account.
        return ProviderFault(provider, MALFORMED_REQUEST, _detail(exc, status))
    if status in (401, 403):
        return ProviderFault(provider, AUTH_REFUSED, _detail(exc, status))

    if isinstance(exc, httpx.HTTPError) and not isinstance(exc, httpx.HTTPStatusError):
        return ProviderFault(provider, UNREACHABLE, _detail(exc, status))
    if status is not None and 500 <= status < 600:
        return ProviderFault(provider, UNREACHABLE, _detail(exc, status))

    return ProviderFault(provider, UNKNOWN, _detail(exc, status))


def _detail(exc: BaseException, status: int | None) -> str:
    where = f"HTTP {status}" if status is not None else type(exc).__name__
    return f"{where}: {exc}"


# The remedy sentence per fault. Written so the first clause names the action and the second
# names what *not* to do, because the wrong action is the expensive half.
_REMEDIES = {
    OUT_OF_CREDIT: (
        "this account has run out of credit or quota - **top it up**. This will not clear on "
        "its own, and every call to this provider is failing until it is done"
    ),
    RATE_LIMITED: (
        "this account is being rate limited - **back off and retry**. Topping up changes "
        "nothing here; the limit is on the rate, not on the balance"
    ),
    MALFORMED_REQUEST: (
        "the provider rejected the *request* as malformed - **this is a defect in this "
        "deployment, not a billing problem**. Do not top up and do not wait; the same request "
        "will fail again. Deepgram's 'Keyterm limit exceeded' is the known example"
    ),
    AUTH_REFUSED: (
        "the provider refused this deployment's API key - **replace it, or re-scope it**. The "
        "key is wrong, revoked, or lacks the permission this call needs. This is not a balance "
        "problem"
    ),
    UNREACHABLE: (
        "the provider could not be reached, or answered a server error - **check this host's "
        "outbound network and the provider's status page**. Nothing about the account is "
        "implicated"
    ),
    UNKNOWN: (
        "the provider refused this call in a way this deployment does not recognise. The exact "
        "response is quoted below - **read it before assuming a cause**, because the three "
        "ordinary causes (no credit, rate limited, malformed request) need opposite actions"
    ),
}


# Every declared fault, so the table above can be held complete rather than assumed complete.
FAULTS = (OUT_OF_CREDIT, RATE_LIMITED, MALFORMED_REQUEST, AUTH_REFUSED, UNREACHABLE, UNKNOWN)


def remedy(fault: ProviderFault) -> str:
    """The operator's sentence. Never guesses: an unrecognised refusal says it is unrecognised.

    The `.get` default is **unreachable today** and is kept deliberately, because the risk it
    covers is a future fault constant added without a remedy - which would otherwise be a
    `KeyError` raised inside failure handling, turning a reported provider outage into an
    unhandled exception. Being unreachable, it cannot be power-checked: mutating it to return the
    wrong sentence leaves the suite green, which is exactly what happened when it was tried.
    What *is* checked is the invariant that makes it unreachable -
    `test_every_declared_fault_has_its_own_remedy` - so the guard and the reason it is idle are
    both asserted rather than one being hoped for.
    """
    return _REMEDIES.get(fault.fault, _REMEDIES[UNKNOWN])


# Which reader answers "how much was left?" for each provider.
#
# **This mapping is what gives `provider_quota`'s readers a production caller at all.** Being a
# member of `HEALTH_CHECKS` is not a caller: nothing outside `tests/` iterates that registry, so
# both readers were reachable only from a test that enumerated the registry and asserted each
# returned a `HealthResult` - which reads as coverage and proves only that a function is
# callable. CLAUDE.md's *a helper with no production caller is a helper that will drift from
# production*, arriving through a registry rather than through a test helper.
#
# Anthropic is absent because no balance endpoint exists; Chroma because its cloud publishes no
# quota endpoint at all. Both are argued in `provider_quota`'s docstring.
_QUOTA_READERS = {
    ELEVENLABS: "check_speech_quota",
    DEEPGRAM: "check_transcription_usage",
}

# The faults where "how much was left?" is the operator's next question.
#
# Not every fault: a rate limit is about the rate and a malformed request is about the code, so
# reading a balance for either would cost a network call to answer a question nobody asked, and
# would put a number in front of an operator that has nothing to do with their problem.
_QUOTA_RELEVANT_FAULTS = (OUT_OF_CREDIT, AUTH_REFUSED)


def _quota_reading(provider: str, fault: "ProviderFault") -> str:
    """What the provider says about its own remaining credit, if it will say anything.

    Called lazily from the alert body, so it runs at most three times an hour per incident
    rather than once per refused call.

    Never raises and never blocks the alert: a reader that fails costs the message one
    paragraph, and the classification and remedy above it are unaffected.
    """
    if fault.fault not in _QUOTA_RELEVANT_FAULTS:
        return ""
    reader_name = _QUOTA_READERS.get(provider)
    if not reader_name:
        return ""
    try:
        from api.services import provider_quota

        result = getattr(provider_quota, reader_name)("")
        if result.degraded:
            headline = "What the account says (this could not be read in full)"
        elif result.ok:
            headline = "What the account says"
        else:
            headline = "What the account says (and it agrees something is wrong)"
        return f"{headline}: {result.diagnosis}\n\n"
    except Exception:
        _log.exception("provider quota reading failed for %s", provider)
        return (
            "What the account says: this deployment could not read it. The refusal above "
            "stands on its own.\n\n"
        )


def report_provider_failure(
    *, provider: str, operation: str, exc: BaseException, slug: str = "", consequence: str = ""
) -> ProviderFault | None:
    """Tell the operator a paid provider refused us. Never raises; returns the classification.

    Guarded end to end for the reason CLAUDE.md gives - *a side effect must not veto the thing
    it is a side effect of*. Every caller is inside an `except`, and a crew run must not die
    because an alert could not be sent. Returns None only if the classification itself failed,
    which is logged.
    """
    try:
        from api.services.operator_alert import alert_operator

        fault = classify(provider, exc)
        where = f" on engagement '{slug}'" if slug else ""
        action = remedy(fault)

        def _compose_body() -> str:
            # Resolved by `alert_operator` **after** the rate limit, never before - see
            # `_quota_reading`, which makes a network call. Forty refused queries in one crew
            # synthesis therefore read a quota at most three times, not forty.
            return (
                f"A paid provider refused a call this deployment made.\n\n"
                f"Provider: {provider}\n"
                f"What failed: {operation}{where}\n"
                f"Classification: {fault.fault}\n"
                f"What the provider said: {fault.detail}\n\n"
                f"What to do: {action}\n\n"
                + (f"What this cost: {consequence}\n\n" if consequence else "")
                + _quota_reading(provider, fault)
                + "These three causes need opposite actions - topping up does not fix a rate "
                "limit or a malformed request, and waiting does not fix an exhausted balance - "
                "so the classification above is worth reading before acting.\n\n"
                "This message is rate-limited to three per hour for this provider and fault. "
                "The server log carries every occurrence."
            )

        alert_operator(
            key=fault.incident_key,
            subject=f"{provider} refused this deployment - {fault.fault.replace('_', ' ')}",
            diagnosis=f"{operation}{where} was refused by {provider} ({fault.detail}): {action}",
            body=_compose_body,
            summary=f"{provider} {fault.fault} during {operation}{where}.",
        )
        return fault
    except Exception:
        _log.exception(
            "report_provider_failure: the alert itself failed for %s/%s. The original failure "
            "stands and is unaffected.", provider, operation,
        )
        return None


# ── Leading indicators: what each provider actually exposes ──────────────────────────────────
#
# Measured against the live accounts on 18 September by the coordinator, read-only. Recorded here
# because the gap between what people assume is available and what is actually available is the
# reason the call-site capture above is the guarantee and this is the extra.
#
#   Anthropic    no balance endpoint. But **every response carries rate-limit headers** -
#                `anthropic-ratelimit-{input-tokens,output-tokens,requests,tokens}-{limit,
#                remaining,reset}` - so the leading indicator is free, on responses already
#                being made. See `note_anthropic_headers`. Never poll: a "balance check" that
#                sends a message spends tokens to ask how many tokens are left.
#   Deepgram     `/v1/projects/{id}/balances` answers **403** for this key, which is a Member;
#                it needs Admin or Owner. `/v1/projects/{id}/usage` answers 200 with hours per
#                day. Pollable, sparingly - it is a real request.
#   ElevenLabs   `/v1/user` and `/v1/user/subscription` both answer **401**, *"the API key is
#                missing the permission"*. `character_count` / `character_limit` would work with
#                a re-scoped key. Any reader must degrade to "cannot read - the key lacks
#                permission" and say so, never report healthy and never raise.
#   Chroma       **no quota endpoint exists.** `/usage`, `/quota` and `/billing/usage` all 404.
#                `/api/v2/auth/identity` answers 200 with the tenant and database. Reachability
#                plus call-site capture is the whole of what is available; do not invent an
#                endpoint and do not scrape the dashboard.
_LEADING_INDICATORS = "see the comment above - three of the four are unavailable or unscoped"

# The floor at which a remaining-token headroom is worth telling somebody about.
#
# A fraction rather than an absolute, because the limits differ by two orders of magnitude
# between the token buckets and the request bucket. Ten per cent is a judgement, not a
# measurement: low enough that an ordinary burst does not trip it, high enough that there is
# time to act.
ANTHROPIC_HEADROOM_FLOOR = 0.10


def note_anthropic_headers(headers, *, slug: str = "") -> str | None:
    """Read Anthropic's rate-limit headers off a response we were making anyway.

    **Free, and therefore the one leading indicator worth having.** No request is made: these
    arrive on every successful completion, so this costs a dictionary lookup.

    Returns the bucket name that tripped the floor, or None. Never raises - it is called on the
    success path, where an exception would turn a working completion into a failed one, which is
    the worst possible trade for a monitoring nicety.

    It alerts on *headroom*, not on a balance: Anthropic exposes no balance, and a remaining
    count against a limit is the closest thing that exists. `reset` is carried into the message
    because "this clears at 14:05" is the difference between an operator waiting and an operator
    escalating.
    """
    try:
        for bucket in ("input-tokens", "output-tokens", "requests", "tokens"):
            raw_remaining = _header(headers, f"anthropic-ratelimit-{bucket}-remaining")
            raw_limit = _header(headers, f"anthropic-ratelimit-{bucket}-limit")
            if raw_remaining is None or raw_limit is None:
                continue
            remaining, limit = int(raw_remaining), int(raw_limit)
            if limit <= 0 or remaining / limit > ANTHROPIC_HEADROOM_FLOOR:
                continue

            from api.services.operator_alert import alert_operator

            reset = _header(headers, f"anthropic-ratelimit-{bucket}-reset") or "unknown"
            where = f" (seen on engagement '{slug}')" if slug else ""
            alert_operator(
                # Keyed on the bucket, so the input-token bucket running low does not silence
                # the request bucket doing the same.
                key=f"provider:{ANTHROPIC}:headroom:{bucket}",
                subject=f"Anthropic {bucket} headroom low - {remaining} of {limit} remaining",
                diagnosis=(
                    f"Anthropic reports {remaining} of {limit} {bucket} remaining"
                    f"{where}, below the {int(ANTHROPIC_HEADROOM_FLOOR * 100)}% floor. "
                    f"Resets at {reset}"
                ),
                body=(
                    f"Anthropic's own rate-limit headers report this deployment is close to a "
                    f"limit.\n\n"
                    f"Bucket: {bucket}\n"
                    f"Remaining: {remaining} of {limit}\n"
                    f"Resets: {reset}\n\n"
                    f"**This is a rate limit, not a balance.** Anthropic exposes no balance "
                    f"endpoint, so this is a leading indicator of throttling rather than of "
                    f"running out of money - topping up will not raise it. If calls are already "
                    f"being refused, the alert for that says so separately and names the "
                    f"difference.\n\n"
                    f"Read from headers on a response this deployment was making anyway; "
                    f"nothing was polled."
                ),
            )
            return bucket
    except Exception:
        _log.debug("note_anthropic_headers: could not read rate-limit headers", exc_info=True)
    return None


def _header(headers, name: str):
    """Read one header from an httpx-style or plain mapping, case-insensitively."""
    try:
        getter = getattr(headers, "get", None)
        return getter(name) if getter else None
    except Exception:
        return None
