# api/services/health_checks.py
"""What this deployment depends on, whether it is working, and who is told when it is not.

The registry half of the decision recorded in `operator_alert.py`: a registry plus one delivery
seam, and no agent. Declaring a check is adding a `HealthCheck` here, not standing up a service.

**One member today - the vector store.** The other three the owner named are deliberately not
implemented, because designing for four members while having one is how a registry becomes a
framework. What each would need is written at the bottom of this docstring so the next one is a
function rather than a design exercise.

## Why the vector store first, and why this is not hypothetical

Measured on this deployment, 17 September 2026. `data/sp-gs-am.db` holds **229 interview answers
across 3 sessions**. The Chroma collection those answers are indexed into,
`sp-gs-am_interviews`, **does not exist** - the store holds `sp-gs-am_docs` and four collections
belonging to test projects, and nothing else. So three real interviews were conducted, every
answer was written to SQLite, not one reached the vector store, and **nothing anywhere said
so**. The launcher had been reporting that ChromaDB needed Docker, which was untrue, and the
vector store had simply not been running.

The code did exactly what it was written to do. `index_answers` catches, logs and returns 0 -
correctly, because the SQLite rows are the system of record and failing there would lose an
interview a person has already given. The defect is not the swallow; it is that the swallow was
the end of it. A log line in a server that nobody tails is not a person being told.

## Where the check belongs, and where it does not

**At the point where the absence matters, on a real failure - not on a timer and not at
startup.** A check at startup alone is nearly worthless: the store can go down at any moment,
and this one was down for days. A synthetic probe on a timer is better but still answers a
question nobody asked, and it can be wrong in both directions - reporting healthy between polls
while a real query fails, or reporting a failure nothing was affected by.

So the alert fires where an operation that *needed* the store did not get it: an interview's
answers not indexed, a document not ingested, a crew agent's retrieval returning nothing. Those
are real failures with a real consequence, and there is no false positive available.

`check_vector_store` exists as an active probe anyway, because the call sites need a *diagnosis*
- "is this a store that is down, or a query that was wrong?" is exactly the question an operator
is going to ask, and the answer is cheap to get at the moment of failure and impossible to get
afterwards. It is not called on a timer by anything.

## Two urgencies, and only one of them is built

A blocking failure during a run must reach somebody promptly, and that is what this module does.
The rest - a review gate that has been waiting eleven hours, a credit balance trending towards
zero - is a **digest**, and a digest is not built here. Note for whoever builds it:
`run_pam_daily_report` is the wrong home. Its `REVIEW_FLAGS` resolve recipients to stakeholders
carrying `is_reviewer`, `is_approver` or `is_governor` - the client's governance. Service health
has a different audience and must not ride in that email.

## The other three members, so the next one is a function

- **Deepgram unavailable.** Already implemented, bespoke, in `speech_policy.py`, which has its
  own third leg (the `interview_sessions.speech_failure` row) and a far better diagnosis
  function than this module's - `describe_deepgram_failure` distinguishes a wrong key from an
  exhausted balance from a rate limit, because an alert saying only "Deepgram unavailable" sends
  an operator to check all four. Adopting this registry there means keeping that third leg, so
  it is a change with its own tests rather than a rename.
- **Token and credit limits.** Needs a source of truth this deployment does not have: nothing
  records spend, and the providers report it on endpoints nothing calls. The check is easy; the
  *number* is the work.
- **A review gate waiting with nobody told.** `HumanInputTool` writes a review and polls it for
  up to twenty-four hours, and the webhook that used to relay a nudge to Slack was retired in
  SP50 with no channel replacing it - so an agent can sit on a gate for the full timeout with
  nobody aware. This is the digest case rather than the prompt one, and unlike the other three
  its audience is arguably the *reviewer* rather than the operator, which is a question to
  settle before writing it and not while.
"""
from __future__ import annotations

import logging
import socket
from collections.abc import Callable
from dataclasses import dataclass

from api.config import get_settings
from api.services.operator_alert import alert_operator

_log = logging.getLogger(__name__)

# The incident key for the vector store, and the reason it carries no slug.
#
# A vector store that is down is down for **every** engagement at once, so keying the rate limit
# per project would multiply one incident by the number of live projects - which is precisely
# the mail storm the limit exists to prevent. The slug still reaches the operator, in the body,
# because "which interview lost its answers" is what they will want to know; it is simply not
# part of the identity of the incident.
VECTOR_STORE = "vector_store"


@dataclass(frozen=True)
class HealthResult:
    """Whether a dependency is working, and the operator's sentence if it is not."""

    ok: bool
    diagnosis: str = ""


@dataclass(frozen=True)
class HealthCheck:
    """One declared dependency of this deployment.

    `key` is the incident key the delivery seam rate-limits on. `probe` answers whether the
    thing is working *now*; it is called at the moment of a real failure to tell an operator
    which kind of failure it was, and deliberately not on a timer.
    """

    key: str
    label: str
    probe: Callable[[], HealthResult]


def check_vector_store() -> HealthResult:
    """Whether this deployment's vector store is reachable.

    Chroma Cloud is reported reachable without a probe. That is honest rather than lazy: the
    failure this module exists for is a local server that is not running, the cloud client's own
    errors are already specific, and opening a socket to a third party to decide whether to send
    an email is a worse trade than trusting the exception the caller already has.

    Never raises: it is called from inside `except` blocks whose original failure is the thing
    worth having.
    """
    try:
        settings = get_settings()
        if settings.chroma_api_key:
            return HealthResult(ok=True)
        host, port = settings.chroma_host, settings.chroma_port
    except Exception as exc:  # pragma: no cover - configuration is loaded long before this
        return HealthResult(ok=False, diagnosis=f"the vector store settings could not be read ({exc})")

    try:
        socket.create_connection((host, port), timeout=3.0).close()
    except OSError as exc:
        return HealthResult(
            ok=False,
            diagnosis=(
                f"ChromaDB is not reachable at {host}:{port} ({exc}). Nothing is listening, so "
                f"it is not running rather than failing. Start it with './start.sh', or "
                f"directly with './venv/bin/chroma run --host localhost --port {port} "
                f"--path data/chroma'. ChromaDB does not need Docker - it ships a CLI, and the "
                f"venv already has it"
            ),
        )
    return HealthResult(ok=True)


# Every dependency this deployment declares. One member; the docstring says what the other
# three would need. A new one is a function and a line here.
HEALTH_CHECKS: tuple[HealthCheck, ...] = (
    HealthCheck(key=VECTOR_STORE, label="Vector store (ChromaDB)", probe=check_vector_store),
)


def describe_vector_store_failure(exc: BaseException | None) -> str:
    """The operator's sentence for a vector store operation that failed.

    Probes first, because the two cases want different remedies and only the probe can tell them
    apart: a store that is not running is a service to start, while a store that is answering
    and still refused the write is a problem with the request or the collection, and sending an
    operator to restart a server that is already up wastes the one thing the alert bought.
    """
    result = check_vector_store()
    if not result.ok:
        return result.diagnosis
    detail = f" ({type(exc).__name__}: {exc})" if exc is not None else ""
    return (
        f"the vector store is answering, but the operation failed anyway{detail}. This is not a "
        f"service that is down - check the collection and the request rather than restarting "
        f"ChromaDB"
    )


def report_vector_store_failure(
    *, operation: str, slug: str = "", exc: BaseException | None = None, consequence: str = ""
) -> None:
    """Tell the operator that something needed the vector store and did not get it.

    Never raises, and never blocks: both properties belong to `alert_operator`, and this wrapper
    adds a third guard of its own because it is called from inside `except` blocks where an
    exception would replace a handled failure with an unhandled one.

    `consequence` is what the deployment lost, in the caller's own words - "229 answers from a
    completed interview are not searchable" is a different message from "one agent's retrieval
    came back empty", and an operator triaging at 9am needs to know which.
    """
    try:
        diagnosis = describe_vector_store_failure(exc)
        where = f" on engagement '{slug}'" if slug else ""
        alert_operator(
            key=VECTOR_STORE,
            subject="Vector store unavailable - retrieval and indexing are failing",
            diagnosis=f"{operation}{where} could not reach the vector store: {diagnosis}",
            body=(
                f"An operation on this deployment needed the vector store and could not reach "
                f"it.\n\n"
                f"What failed: {operation}{where}\n\n"
                f"What went wrong: {diagnosis}\n\n"
                + (f"What this cost: {consequence}\n\n" if consequence else "")
                + "The underlying records are unaffected - SQLite is the system of record "
                "throughout, and anything that failed to index can be re-indexed once the "
                "store is back. What is lost until then is retrieval: agents querying the "
                "knowledge base will find nothing, and interview answers written while the "
                "store was down will not be searchable until they are re-indexed.\n\n"
                "This message is rate-limited to three per hour for this incident. The server "
                "log carries every occurrence."
            ),
        )
    except Exception:
        _log.exception(
            "report_vector_store_failure: the alert itself failed for %s%s. The original "
            "failure stands and is unaffected.", operation, f" [{slug}]" if slug else "",
        )
