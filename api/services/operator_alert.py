# api/services/operator_alert.py
"""One way to tell the deployment's operator that something they own has stopped working.

The owner's decision, 17 September, when asked whether a support agent should own monitoring,
reporting and remediation: **a registry plus one delivery seam, and no agent.** The reasoning is
worth keeping next to the code, because "add an agent" is the answer that will be proposed again:

- **Monitoring is not a reasoning task.** "Is Chroma answering?", "is Deepgram in quota?", "are
  the keyterms under the token budget?" have definite answers. A model is slower, costlier and
  non-deterministic on questions that are not.
- **Remediation is an authority question, not a capability one.** An agent acting with
  production credentials is a new principal class sitting outside both of this codebase's
  authority axes - the administration axis and the content axis - and neither has a place to put
  it. It is not being built.
- **What scales with the list is a registry.** Declaring a check becomes adding a function
  rather than standing up a service.

This module is the delivery half. `api/services/health_checks.py` is the registry half.

## Who this reaches, and who it must not

The audience is **the deployment's operator** - whoever holds the Deepgram key, pays the Chroma
bill, and restarts a server. That is not the client's governance, and the distinction decides
the mechanism:

- **`send_platform_mail`, never `send_project_mail`.** Project mail is held by `dev_mode`, which
  **defaults to `True`**, so an outage alert routed that way is silently redirected to the
  operator's own inbox and its absence reads as "no outage". Worse than no alert.
- **Not PAM's daily report.** `run_pam_daily_report` already runs on a schedule and looks like a
  free ride, and it is the wrong home: `REVIEW_FLAGS` resolves its recipients to stakeholders
  carrying `is_reviewer`, `is_approver` or `is_governor` - the **client's** governance. "Your
  transcription provider is out of credit" is not a governor's business, and service health has
  a different audience that must not ride in that email.

`ADMIN_ALERT_EMAIL` is the address, and blank sends nothing and says so at ERROR. That is
deliberate rather than a gap: `ADMIN_USERNAME` is a login and is routinely not an address, and
`DEV_MODE_ADDRESS` is where *held* mail goes, which is a different question - so no existing
setting honestly means "the system administrator", and a guess would be worse than an absence.

## Three properties, each of which has cost something on this codebase before

**Nothing here may raise into the caller.** CLAUDE.md states it as *a side effect must not veto
the thing it is a side effect of*. A crew run must not die because an alert could not be sent,
and an interview must not 500 because Resend was slow. Every leg is independently guarded and
the function returns None in all paths.

**The send goes off the request path.** `send_platform_mail` posts to Resend through an `httpx`
client with a fifteen-second timeout. Awaited inline from a request - or from inside a crew
run - a slow provider becomes the caller's latency. This is the rule CLAUDE.md states for
`deliver_reset` in as many words.

**It is rate-limited, and on the key rather than on the caller.** An outage produces one alert
per *query* otherwise: a crew run asking Chroma forty times during a synthesis would send forty
messages about one incident. The key is what the incident is, not who noticed it - see
`health_checks.VECTOR_STORE`, which keys on the service and deliberately not on the slug,
because a vector store that is down is down for every engagement at once.

## What this is not

No severity taxonomy, no alert history table, no UI, and no retry policy beyond the one attempt
`send_platform_mail` makes. Those were considered and declined as gold-plating for a mechanism
with one member. When there are four, the shape of the answer may be clearer than it is now.

This is deliberately *not* wired into `speech_policy.alert_speech_unavailable` yet, which
predates it and carries a third leg of its own - the `interview_sessions.speech_failure` row a
consultant reads. Adopting this seam there is a separate change with its own tests, and doing it
speculatively while the seam has one member would make the seam harder to change, not easier.
"""
from __future__ import annotations

import asyncio
import logging
import time
from collections import defaultdict

from api.config import get_settings
from api.services.process_cache import register_cache

_log = logging.getLogger(__name__)

# How many messages one incident may generate, and over what window.
#
# Three, for the reason `speech_policy` gives: the first tells an operator the service is down,
# and the next two are the evidence it is not a one-off. Everything above that is in the log,
# which is not rate-limited - the log is the complete record and the mail is the nudge.
MAIL_LIMIT = 3
MAIL_WINDOW_SECONDS = 3600

# key -> the monotonic times messages were sent for it.
_alert_mail_log: dict[str, list[float]] = defaultdict(list)
register_cache(_alert_mail_log.clear)


def _may_mail_about(key: str) -> bool:
    """Whether another message may go out for this incident, and record it if so.

    Records on the way out rather than on success, deliberately: a provider that is timing out
    is exactly when this is called most, and a limit that counted only successful sends would
    not bound the attempts - which is where the cost and the latency are.
    """
    now = time.monotonic()
    recent = [t for t in _alert_mail_log[key] if now - t < MAIL_WINDOW_SECONDS]
    if len(recent) >= MAIL_LIMIT:
        _alert_mail_log[key] = recent
        return False
    recent.append(now)
    _alert_mail_log[key] = recent
    return True


# The sends that have been scheduled and not yet finished.
#
# Held so the event loop does not garbage-collect a task nothing is awaiting - `asyncio` keeps
# only a weak reference to a bare task - and it is what a test awaits to see a send land.
_pending_alerts: set[asyncio.Task] = set()


def _send_off_the_request_path(*, key: str, to: str, subject: str, body: str) -> None:
    """Schedule the message and do not wait for it. Never raises.

    Falls back to sending inline when there is no running loop, which is only ever a
    synchronous caller - `index_answers` runs in a worker thread, and a crew tool is
    synchronous throughout. Production async callers reach this from inside a request.
    """
    async def deliver() -> None:
        try:
            from api.services.outbound_mail import send_platform_mail

            await send_platform_mail(to=to, subject=subject, body=body)
        except Exception:
            _log.exception(
                "operator alert [%s]: the message to %s could not be sent. The log line "
                "above is still the record.", key, to,
            )

    try:
        task = asyncio.get_running_loop().create_task(deliver())
    except RuntimeError:
        # No running loop. `asyncio.run` is safe here precisely because there is none.
        try:
            asyncio.run(deliver())
        except Exception:
            _log.exception("operator alert [%s]: inline send failed", key)
        return
    _pending_alerts.add(task)
    task.add_done_callback(_pending_alerts.discard)


def _resolve(value):
    """A string, or a callable answering one. Never raises: a diagnosis that cannot be built
    must not take down the alert it was for."""
    if not callable(value):
        return value
    try:
        return value()
    except Exception:
        _log.exception("operator alert: composing the message failed")
        return "(this deployment could not compose the diagnosis for this alert)"


def alert_operator(
    *,
    key: str,
    subject: str,
    diagnosis,
    body,
    summary: str = "",
) -> None:
    """Tell the operator that `key` has failed. Returns None in every path, raises in none.

    `key` names the incident and is what the rate limit is keyed on, so two call sites reporting
    the same outage share a budget rather than each having their own.

    **`diagnosis` and `body` may be callables, and the rate limit is consulted before they are
    resolved.** That ordering is the whole point of allowing callables. Composing them is not
    always cheap: the vector store's diagnosis builds a Chroma client and makes a network call,
    and the provider alerts read a quota endpoint. Resolved eagerly, forty refused queries in one
    crew synthesis meant three messages - correct - and **forty client constructions and forty
    heartbeat timeouts inside the agent's loop**, because the expensive leg sat in front of the
    limiter this module's own comments call "what makes this safe to put on a per-query path".

    `summary` is the cheap sentence logged when an alert is suppressed. Every occurrence still
    produces a log line; a suppressed one carries what was already known rather than paying to
    find out more, which is the trade that makes the limiter worth having.
    """
    if not _may_mail_about(key):
        _log.error(
            "operator alert [%s]: suppressing the message - %d have already been sent for this "
            "incident within the last %d minutes, and they are one incident. %s",
            key, MAIL_LIMIT, MAIL_WINDOW_SECONDS // 60,
            summary or "The earlier alerts carry the diagnosis.",
        )
        return

    diagnosis = _resolve(diagnosis)
    body = _resolve(body)
    _log.error("operator alert [%s]: %s", key, diagnosis)

    try:
        to = get_settings().admin_alert_email.strip()
    except Exception:
        _log.exception("operator alert [%s]: could not read ADMIN_ALERT_EMAIL", key)
        return

    if not to:
        _log.error(
            "operator alert [%s]: no ADMIN_ALERT_EMAIL is set, so no message was sent. Set it "
            "to reach an administrator by mail; the log carries this alert either way.", key,
        )
        return

    _send_off_the_request_path(key=key, to=to, subject=subject, body=body)
