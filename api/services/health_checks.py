# api/services/health_checks.py
"""What this deployment depends on, whether it is working, and who is told when it is not.

The registry half of the decision recorded in `operator_alert.py`: a registry plus one delivery
seam, and no agent. Declaring a check is adding a `HealthCheck` here, not standing up a service.

**One member today - the vector store.** The other three the owner named are deliberately not
implemented, because designing for four members while having one is how a registry becomes a
framework. What each would need is written at the bottom of this docstring so the next one is a
function rather than a design exercise.

## Why the vector store first: three readers, three stores, three wrong answers

**The indexing works and has been working.** This section previously said the opposite, at
length, and the story of how it came to is the actual argument for this module.

Over one day, three people asked "is this engagement's material in the vector store?" and
measured, carefully, and reached three confident and incompatible answers:

| What was examined | `sp-gs-am_docs` | `sp-gs-am_interviews` | Does the app use it? |
|---|---|---|---|
| Chroma Cloud - what `get_chroma_client` returns | 896 | **229** | **yes** |
| `localhost:8002` over raw HTTP | 48 | absent | no |
| `data/chroma/chroma.sqlite3` on disk | 48 | absent | no |

All three measurements were correct. Two of the three stores are stale leftovers that nothing
has spoken to in months. **`CHROMA_API_KEY` is set, so `get_chroma_client` builds a
`CloudClient` and the application never opens a connection to `localhost:8002` at all** - and
nobody asked which client the code builds until the third wrong answer had already been written
into a commit message.

The corroboration that settled it is behavioural rather than a count, and is the better habit:
**run 39 cited 68 `answer_id`s that all resolve, with accurate quotes, across all three
interviews.** Casey reads the corpus through `ChromaQueryTool`. He could not have done that
against a store with no interviews collection.

So the lesson this module is built around is not "the store was down". It is that **a question
about a store is meaningless until you know which client the code builds**, because that is a
branch on a setting and the answer moves every measurement with it. That is exactly why
`check_vector_store` below goes through `get_chroma_client` rather than probing a host and port
of its own - a check that examines a different store from the code is not checking the code, and
the first version of this file made precisely that mistake while documenting the mistake.

The `index_answers` swallow is still worth an alert, and the reasoning is undamaged: it catches,
logs and returns 0 - correctly, because SQLite is the system of record and failing there would
lose an interview a person has already given. A log line in a server nobody tails is not a person
being told. What is *not* claimed any more is that this has already cost this deployment
anything.

## Where the check belongs, and where it does not

**At the point where the absence matters, on a real failure - not on a timer and not at
startup.** A check at startup alone is nearly worthless: the store can go down at any moment,
and a provider account can start refusing between one query and the next. A synthetic probe on a
timer is better but still answers a
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
from collections.abc import Callable
from dataclasses import dataclass

from api.config import get_settings
from api.services.deployment_modes import Capability, project_permits
from api.services.operator_alert import alert_operator

_log = logging.getLogger(__name__)

# The incident *family* for the vector store. The key an alert is rate-limited on is
# `incident_key(slug)`, which narrows this to the store that project actually uses - see there
# for why one deployment can have two vector stores failing independently.
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
    probe: Callable[[str], HealthResult]


def store_kind(slug: str) -> str:
    """Which store this project resolves to - `cloud` or `local`.

    **Only ever used for the operator's wording and for the incident key.** Reachability is
    never decided here: that comes from the seam, below, so the check cannot disagree with the
    code about which server it is talking to.

    It restates `get_chroma_client`'s branch, which is a real duplication and is why it is
    confined to labelling. If the two ever drift the cost is a message naming the wrong store,
    not a wrong verdict - and `test_the_probe_and_the_client_agree_about_which_store` drives
    both against the same settings so the drift fails a test rather than an operator.
    """
    try:
        if get_settings().chroma_api_key and project_permits(slug, Capability.CLOUD_VECTOR_STORE):
            return "cloud"
    except Exception:
        pass
    return "local"


def incident_key(slug: str) -> str:
    """The rate-limit key for this project's vector store.

    **There is not one vector store on this deployment; there is one per project's grants.** A
    `sensitive` engagement is refused `CLOUD_VECTOR_STORE` and uses the local server, while a
    `standard` one uses Chroma Cloud - so "the vector store is down" is two different incidents
    that can happen independently, and collapsing them would let a local outage silence the
    alerts for a cloud one.

    Still deliberately **not** keyed on the slug: one cloud outage is one incident across every
    engagement using the cloud, which is what keeps a provider outage from sending one message
    per project.
    """
    return f"{VECTOR_STORE}:{store_kind(slug)}"


def check_vector_store(slug: str) -> HealthResult:
    """Whether the vector store **this project actually uses** is reachable.

    **Asks `get_chroma_client(slug)` - the same seam the application asks - and that is the whole
    point of the function.** The first version of this check probed
    `settings.chroma_host:chroma_port` and short-circuited to "healthy" whenever
    `CHROMA_API_KEY` was set. On a deployment with the key set, which is this one, that made it a
    no-op that always answered healthy, while its fallback probed a `localhost:8002` the
    application never speaks to: it would have reported healthy throughout a Cloud outage, and
    unhealthy while everything worked. A health check that does not use the seam the code uses is
    not checking the code.

    `heartbeat()` because it is the cheapest call both clients implement and it needs no
    collection to exist - measured at 0.21s against the live cloud account. A collection-based
    probe would confuse "the store is down" with "nothing has been ingested yet", which are
    different problems with different remedies.

    Never raises: it is called from inside `except` blocks whose original failure is the thing
    worth having.
    """
    # Building the client and asking it for a heartbeat are **one** question, not two.
    # `chromadb.HttpClient` connects during construction and raises `ValueError("Could not
    # connect to a Chroma server")` there, so an unreachable local server never reaches
    # `heartbeat()` at all. Split across two `except` blocks - which is how this was first
    # written - the commonest real failure on an on-premises deployment lands in the arm meant
    # for misconfiguration and is reported as one, sending the operator to read settings that
    # are perfectly correct.
    try:
        from api.services.chroma_client import get_chroma_client

        get_chroma_client(slug).heartbeat()
    except Exception as exc:
        detail = f"{type(exc).__name__}: {exc}"
        if store_kind(slug) == "cloud":
            return HealthResult(
                ok=False,
                diagnosis=(
                    f"Chroma Cloud is not answering for '{slug}' ({detail}). This deployment has "
                    f"CHROMA_API_KEY set, so the engagement's vectors live in the cloud account "
                    f"and not on any local server - check the key, the account's status and this "
                    f"host's outbound network. Starting a local ChromaDB will not help"
                ),
            )
        settings = get_settings()
        return HealthResult(
            ok=False,
            diagnosis=(
                f"the local ChromaDB is not answering for '{slug}' at "
                f"{settings.chroma_host}:{settings.chroma_port} ({detail}). Start it with "
                f"'./start.sh', or directly with './venv/bin/chroma run --host localhost --port "
                f"{settings.chroma_port} --path data/chroma'. ChromaDB does not need Docker - it "
                f"ships a CLI, and the venv already has it"
            ),
        )
    return HealthResult(ok=True)


# Every dependency this deployment declares. One member; the docstring says what the other
# three would need. A new one is a function and a line here.
HEALTH_CHECKS: tuple[HealthCheck, ...] = (
    HealthCheck(key=VECTOR_STORE, label="Vector store (ChromaDB)", probe=check_vector_store),
)


def describe_vector_store_failure(slug: str, exc: BaseException | None) -> str:
    """The operator's sentence for a vector store operation that failed.

    Takes the slug because the store is a property of the project, not of the deployment: the
    same failure means "start the local server" on a sensitive engagement and "check the cloud
    account" on a standard one.

    Probes first, because the two cases want different remedies and only the probe can tell them
    apart: a store that is not running is a service to start, while a store that is answering
    and still refused the write is a problem with the request or the collection, and sending an
    operator to restart a server that is already up wastes the one thing the alert bought.
    """
    result = check_vector_store(slug)
    if not result.ok:
        return result.diagnosis
    detail = f" ({type(exc).__name__}: {exc})" if exc is not None else ""
    return (
        f"the vector store is answering, but the operation failed anyway{detail}. This is not a "
        f"service that is down - check the collection and the request rather than restarting "
        f"ChromaDB"
    )


def report_vector_store_failure(
    *, operation: str, slug: str, exc: BaseException | None = None, consequence: str = ""
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
        diagnosis = describe_vector_store_failure(slug, exc)
        where = f" on engagement '{slug}'" if slug else ""
        alert_operator(
            key=incident_key(slug),
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
