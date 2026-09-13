# api/services/speech_policy.py
"""Whether this engagement's interviews may fall back to the browser's own recogniser.

The interview page has always had two recognisers. Deepgram is the first choice, streamed under
a stated contract with retention disabled; when it cannot be had, `SpeechRecognition` takes over -
and **Chrome streams that audio to Google, Safari to Apple**, with no contract, no retention
undertaking and no provider this deployment chose. sp66 made the Deepgram undertaking specific
and confident on the privacy page while leaving the alternative silent, which is the shape
`agents/egress.py` already warns about: a row that names one shape reads as an assurance about
all of them.

The policy decided on 13 September, implemented here:

| Engagement | Deepgram unavailable |
|---|---|
| granted `HOSTED_INFERENCE` | the browser's recogniser, as today, with the amber notice |
| not granted it | **the interview does not happen** - apologise, preserve, alert |

**Derived here and sent to the browser as a policy, never as a mode.** The participant's page has
no login and no business knowing an engagement's posture, so `get_session_with_script` answers
`speech_policy` and the page reads that. This is the rule CLAUDE.md states for
`writable_knowledge_tiers` - never restate the rule in TypeScript - and it has the same second
benefit: there is one answer, and nothing for two sides to spell differently.

**`project_permits`, never `mode == "sensitive"`.** A fourth mode is planned and a name
comparison hands it the wrong branch; and a mode is not the last word, since
`force_local_inference` narrows a `standard` engagement to exactly the posture this refuses the
fallback for. `agents/egress.py` derives `BROWSER_SPEECH_EGRESS`'s destination from the same
capability for the same reason, so the declaration cannot drift from the decision.

## Two things the probe asks, not one

The page probes at **device setup**, before a participant has answered anything - the owner's
words were that they should be told before they start, not after thirty answers. It asks two
questions and either one failing refuses a sensitive engagement:

1. **Is Deepgram reachable and in credit?** Answered by minting a grant, which is the same call
   the interview makes, so a refused key or an exhausted account fails here rather than at the
   first question.
2. **Can this browser produce a container Deepgram accepts?** `f914bc56` made a browser that
   records none of webm/opus, webm or ogg/opus decline the socket rather than stream MP4/AAC into
   a connection configured for Opus. Safari and iOS record MP4/AAC. So on a sensitive engagement
   **an iPhone or iPad cannot be interviewed**, and that is an accepted operational constraint
   rather than a defect: the alternative is the participant's voice going to Apple.

## The alert: three legs

- **The log**, at ERROR, carrying the diagnosis. A token limit exceeded, an expired card and a
  refused key are different problems and an operator must be told which.
- **The interview session row.** `interview_sessions.speech_failure` is read back by
  `GET /api/interviews/sessions/{slug}`, which is what the consultant running the engagement is
  already looking at - and they are the person who would chase the participant. Mail reaches an
  administrator; this reaches whoever has to ring the interviewee back.
- **Platform mail**, when `ADMIN_ALERT_EMAIL` is set.

**`send_platform_mail`, never `send_project_mail`, and the reason is not that one of them is
broken.** Project mail is held by `dev_mode`, which **defaults to `True`** - so an outage alert
routed that way is silently redirected to the operator's own inbox, and its absence reads as "no
outage", which is worse than no alert at all. Nor is it governance mail: `send_project_mail(slug,
GOVERNANCE, ...)` signs as PAM and goes to the project's governors, and "your transcription
provider is out of credit" is not a governor's business.

Platform mail sends from `FROM_EMAIL` **entire**, which is the `noreply@` address on a domain
Resend has verified - so this leg delivers today, and it does not depend on the one thing about
Resend that is still assumed rather than confirmed, namely whether arbitrary local parts may send
on a verified domain. Do not invent an `alerts@` or `sysadmin@` sender here.

There is no Slack channel yet, though the owner named Slack and a future MS Teams beside email.

Nothing here may raise into the caller. An alert that fails must not also take down the refusal
it is reporting, and the refusal is what protects the participant.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

import httpx

from api.config import get_settings
from api.services.deployment_modes import Capability, project_permits

_log = logging.getLogger(__name__)

# What the browser is told. Never a mode name, and never `llm_mode` itself.
SPEECH_REQUIRED = "required"
BROWSER_PERMITTED = "browser_permitted"


def speech_policy_for(slug: str) -> str:
    """Whether this engagement's interviews may use the browser's own recogniser.

    The slug is required and is not defaulted, for the reason `project_completion` gives one
    module over: a forgotten slug resolving to "standard" is a silent grant of the widest
    behaviour, and here that behaviour is a participant's voice going to Google.
    """
    if not slug or not slug.strip():
        raise ValueError(
            "speech_policy_for requires the project slug: it decides whether an interview may "
            "fall back to the browser's own recogniser, which streams the participant's speech "
            "to their browser vendor. Defaulting would grant that to a sensitive engagement."
        )
    return BROWSER_PERMITTED if project_permits(slug, Capability.HOSTED_INFERENCE) else SPEECH_REQUIRED


# What the browser can tell us that the server cannot see for itself. Kept small and closed: the
# page reports *which* half of the probe failed, and the sentence an operator reads is composed
# here rather than sent up from a participant's browser - a free-text reason from an
# unauthenticated door would put an attacker's words into an administrator's alert.
_BROWSER_DIAGNOSES: dict[str, str] = {
    "unsupported_container": (
        "this participant's browser records none of the audio containers Deepgram is opened for "
        "(webm/opus, webm, ogg/opus). Safari and iOS record MP4/AAC, so an iPhone or iPad cannot "
        "conduct an interview on an engagement that requires Deepgram"
    ),
    "no_streaming_support": (
        "this participant's browser has no MediaRecorder or no WebSocket, so it cannot stream "
        "audio to Deepgram at all"
    ),
    "socket_failed": (
        "this participant's browser could not hold a streaming connection to Deepgram open - it "
        "was refused, or it dropped and would not reopen"
    ),
}
# The one an unrecognised value resolves to. Named rather than defaulted to a free-text echo.
_UNKNOWN_BROWSER_DIAGNOSIS = (
    "this participant's browser reported a transcription failure this deployment has no "
    "description for"
)


def describe_browser_failure(reason: str) -> str:
    """The operator's sentence for a failure only the browser could have seen."""
    return _BROWSER_DIAGNOSES.get(reason, _UNKNOWN_BROWSER_DIAGNOSIS)


def describe_deepgram_failure(exc: BaseException) -> str:
    """What actually went wrong at Deepgram, in words that name the remedy.

    **The whole point of this function is that these are different problems.** A 401 is a key the
    operator must replace, a 402 is an account somebody must pay for, a 429 is a limit that will
    clear on its own, and an unreachable host is a network problem - and an alert that said only
    "Deepgram unavailable" would send an operator to check all four. The status code is the one
    piece of evidence that distinguishes them and it is available exactly here, where the call is
    made, and nowhere downstream.
    """
    if isinstance(exc, ValueError):
        # `generate_deepgram_token`'s own refusal: DEEPGRAM_API_KEY is not set at all.
        return f"Deepgram is not configured on this deployment ({exc})"
    if isinstance(exc, httpx.HTTPStatusError):
        status = exc.response.status_code
        known = {
            401: "Deepgram refused the API key this deployment holds (401) - it is wrong, "
                 "revoked, or has no transcription scope",
            403: "Deepgram refused this deployment's project or scope (403) - the key is valid "
                 "but is not permitted to mint streaming grants",
            402: "Deepgram reports this account has no credit (402) - the balance is exhausted "
                 "or the card has expired",
            429: "Deepgram is rate-limiting or has exceeded this account's token limit (429) - "
                 "this one clears on its own, unlike the others",
        }
        if status in known:
            return known[status]
        if 500 <= status < 600:
            return f"Deepgram returned a server error ({status}) - the fault is at their end"
        return f"Deepgram refused the request for a grant with HTTP {status}"
    if isinstance(exc, httpx.HTTPError):
        return f"Deepgram could not be reached from this server ({type(exc).__name__}: {exc})"
    return f"Deepgram failed for a reason this deployment does not recognise ({type(exc).__name__}: {exc})"


def _record(*, slug: str, session_token: str, diagnosis: str, at: str) -> str:
    """The JSON blob written to `interview_sessions.speech_failure`.

    A blob rather than three columns because nothing queries its parts - the consultant's panel
    renders the sentence and the time, and a schema that had to grow a column per field is a
    schema that will be got wrong once.
    """
    return json.dumps({"slug": slug, "at": at, "diagnosis": diagnosis, "token": session_token})


async def alert_speech_unavailable(
    *, db_path: str, slug: str, session_token: str, diagnosis: str
) -> None:
    """Tell everyone who can act that a sensitive engagement's interview could not go ahead.

    Called from the token door when a `required` engagement cannot mint a grant, and from
    `POST /{session_token}/speech-failure` when the browser is the half that failed. Every leg is
    independently guarded: the participant has already been refused by the time this runs, and an
    alert that raised would turn a handled refusal into a 500 on a public door.
    """
    at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    _log.error(
        "interview speech unavailable [%s] session=%s: %s. The interview was not conducted - "
        "this engagement is not granted hosted inference, so the browser's own recogniser (which "
        "streams to the browser vendor) is refused rather than used as a fallback.",
        slug, session_token, diagnosis,
    )

    # The leg the consultant actually reads. `interview_db_connection` runs no migrations by
    # design, so a project database not yet opened through `get_connection` has no column to
    # write - which must cost the alert its quietest leg, not raise on a public door.
    try:
        from api.database import interview_db_connection, record_session_speech_failure

        async with interview_db_connection(db_path) as conn:
            await record_session_speech_failure(
                conn, session_token, _record(slug=slug, session_token=session_token, diagnosis=diagnosis, at=at)
            )
    except Exception:
        _log.exception(
            "interview speech unavailable [%s]: could not record the failure on the session row; "
            "the log line above is the record", slug,
        )

    to = get_settings().admin_alert_email.strip()
    if not to:
        # Not a guess. `admin_username` is a login and is routinely not an address, and
        # `dev_mode_address` is where *held* mail goes, which is a different question - so there
        # is no existing setting that honestly means "the system administrator". Until one is
        # set, this leg is loudly absent rather than quietly misaddressed.
        _log.error(
            "interview speech unavailable [%s]: no ADMIN_ALERT_EMAIL is set, so no message was "
            "sent. Set it to reach an administrator by mail; the log and the interview session "
            "row carry this alert either way.", slug,
        )
        return
    try:
        from api.services.outbound_mail import send_platform_mail

        # Platform mail, never project mail: `dev_mode` defaults to True and would redirect this
        # to the operator's own inbox, which is not an alert.
        await send_platform_mail(
            to=to,
            subject=f"Interview could not be conducted on {slug} - transcription unavailable",
            body=(
                f"An interview on the engagement '{slug}' was stopped because speech "
                f"transcription could not be reached.\n\n"
                f"What went wrong: {diagnosis}\n\n"
                f"Session token: {session_token}\n"
                f"When: {at}\n\n"
                f"This engagement is not granted hosted inference, so the browser's own speech "
                f"recogniser - which streams the participant's audio to Google or Apple - is "
                f"refused rather than used as a fallback. The participant was asked to try again "
                f"later and anything they had already answered has been preserved.\n\n"
                f"The interview sessions panel on this project records the same failure."
            ),
        )
    except Exception:
        _log.exception(
            "interview speech unavailable [%s]: the alert message to %s could not be sent. The "
            "log line above and the interview session row still carry the alert.", slug, to,
        )
