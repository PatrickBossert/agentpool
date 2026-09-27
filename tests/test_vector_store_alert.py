# tests/test_vector_store_alert.py
"""An unreachable vector store reaches a person, and never costs the thing it is reporting on.

Written against the properties rather than against the call, because this file's whole subject
is a mechanism that fires inside `except` blocks: the question CLAUDE.md tells us to ask is
"would this test fail if the code were wrong?", and for an alert the ways of being wrong are
(a) it does not go, (b) it goes too often, (c) it goes but says something useless, and (d) it
takes the caller down with it. There is a test for each.

**No real third-party call anywhere in this file.** Resend is blocked at the seam and the
blocking is proven in both directions - `test_the_mail_seam_is_really_blocked` asserts the
double would have been seen had a send happened, so every "no mail was sent" assertion below is
evidence rather than an artefact of a double nothing reaches.
"""
from __future__ import annotations

import asyncio
import logging

import pytest

from api.services import health_checks, operator_alert


@pytest.fixture(autouse=True)
def _no_real_mail_and_a_clean_limiter(monkeypatch):
    """Block the mail seam, and empty the rate-limit ledger on both sides of every test.

    The ledger accumulates for the life of the process, so a test that sends three messages
    would otherwise silence the next test that expects one - the `_transcript_email_log` trap
    `process_cache` was written for, arriving in a second module.
    """
    operator_alert._alert_mail_log.clear()
    sent: list[dict] = []

    async def _fake_send(*, to: str, subject: str, body: str) -> bool:
        sent.append({"to": to, "subject": subject, "body": body})
        return True

    # Patched where it is *looked up*. `_send_off_the_request_path` imports `send_platform_mail`
    # from `outbound_mail` inside the coroutine, so the import happens at call time and the
    # binding that matters is the one on the outbound_mail module itself.
    monkeypatch.setattr("api.services.outbound_mail.send_platform_mail", _fake_send)
    yield sent
    operator_alert._alert_mail_log.clear()


@pytest.fixture
def mail(_no_real_mail_and_a_clean_limiter):
    return _no_real_mail_and_a_clean_limiter


@pytest.fixture
def alert_address(monkeypatch):
    """Configure an operator address, which is what makes the mail leg live at all."""
    from api.config import get_settings

    settings = get_settings()
    monkeypatch.setattr(settings, "admin_alert_email", "ops@example.com", raising=False)
    return "ops@example.com"


@pytest.fixture
def store_is_down(monkeypatch):
    """Make the store this deployment uses unreachable, without touching any real one.

    Points the *local* client at a dead port rather than stubbing the check, so the production
    path really does try to build a client and really does fail. Port 1 is reserved and nothing
    binds it, so the refusal is immediate.

    `chromadb.HttpClient` connects during construction, so this fails at the build rather than
    at `heartbeat()` - which is exactly the case the check must not report as misconfiguration,
    and is why the two share one verdict.

    The api_key is blanked so the local branch is taken. `tests/conftest.py` already blanks it
    process-wide, and its own comment says why: "a real CHROMA_API_KEY flips ingest_service to
    CloudClient". That is the whole finding this file was rewritten for, and the suite has been
    guarding against it since long before anybody wrote this module.
    """
    from api.config import get_settings

    settings = get_settings()
    monkeypatch.setattr(settings, "chroma_api_key", "", raising=False)
    monkeypatch.setattr(settings, "chroma_host", "127.0.0.1", raising=False)
    monkeypatch.setattr(settings, "chroma_port", 1, raising=False)


# ── The double is real ───────────────────────────────────────────────────────────────────────

def test_the_mail_seam_is_really_blocked(mail, alert_address):
    """Establish the double, so every "no mail" assertion below means something.

    CLAUDE.md's rule: a walk, or a recorder, must be driven in *both* directions - a one-sided
    test passes against a recorder that sees everything and against one that sees nothing.
    """
    operator_alert.alert_operator(
        key="probe", subject="s", diagnosis="d", body="b"
    )
    assert len(mail) == 1, "the double did not see a send, so it cannot witness their absence"
    assert mail[0]["to"] == "ops@example.com"


def test_no_test_in_this_file_can_reach_resend(monkeypatch):
    """The blocking is at the seam, so even an unpatched path cannot post to a real host."""
    import httpx

    def _refuse(*a, **k):
        raise AssertionError("a real HTTP call was attempted")

    monkeypatch.setattr(httpx.AsyncClient, "post", _refuse)
    # With the send double in place this is a no-op; without it, this would fire.
    operator_alert.alert_operator(key="probe", subject="s", diagnosis="d", body="b")


# ── The probe asks the seam the application asks ─────────────────────────────────────────────

def test_the_check_asks_the_same_seam_the_application_asks(monkeypatch):
    """**The regression test for the worst defect this module has had.**

    The first version probed `settings.chroma_host:chroma_port` directly and short-circuited to
    "healthy" whenever `CHROMA_API_KEY` was set. On a deployment with the key set - which the
    development machine is - that made the whole check a no-op that always answered healthy,
    while its fallback probed a `localhost:8002` the application never speaks to.

    A health check that examines a different store from the code is not checking the code, so
    the property is asserted directly: the check calls `get_chroma_client`, with this project's
    slug, and reaches its verdict from that client.
    """
    called: list[str] = []

    class _Client:
        def heartbeat(self):
            return 1

    def _seam(slug):
        called.append(slug)
        return _Client()

    monkeypatch.setattr("api.services.chroma_client.get_chroma_client", _seam)
    assert health_checks.check_vector_store("acme").ok is True
    assert called == ["acme"], "the check must resolve its client through get_chroma_client"


def test_a_cloud_deployment_is_really_probed_rather_than_assumed_healthy(monkeypatch):
    """With a cloud key set, an unreachable store must still be reported down.

    This is the exact shape of the original bug: `if settings.chroma_api_key: return ok` made
    every cloud deployment permanently healthy, so the alert could never fire on the only store
    that deployment actually uses.
    """
    from api.config import get_settings

    monkeypatch.setattr(get_settings(), "chroma_api_key", "ck-test", raising=False)

    class _DeadCloud:
        def heartbeat(self):
            raise RuntimeError("cloud is unreachable")

    monkeypatch.setattr("api.services.chroma_client.get_chroma_client", lambda _s: _DeadCloud())
    result = health_checks.check_vector_store("acme")
    assert result.ok is False, "a cloud key must not be treated as proof the cloud is up"


def test_the_cloud_remedy_does_not_send_an_operator_to_start_a_local_server(monkeypatch):
    """The remedy has to match the store, or the alert costs an operator an hour."""
    from api.config import get_settings

    monkeypatch.setattr(get_settings(), "chroma_api_key", "ck-test", raising=False)
    monkeypatch.setattr(
        health_checks, "store_kind", lambda _s: "cloud"
    )

    class _DeadCloud:
        def heartbeat(self):
            raise RuntimeError("boom")

    monkeypatch.setattr("api.services.chroma_client.get_chroma_client", lambda _s: _DeadCloud())
    diagnosis = health_checks.check_vector_store("acme").diagnosis
    assert "Chroma Cloud" in diagnosis
    assert "chroma run" not in diagnosis, "starting a local server does not fix a cloud outage"
    assert "will not help" in diagnosis


def test_a_local_store_that_is_not_listening_is_reported_with_the_local_remedy(store_is_down):
    """Driven through the real client against a dead port - no stub in the path at all."""
    result = health_checks.check_vector_store("acme")
    assert result.ok is False
    assert "chroma run" in result.diagnosis
    # The remedy must not send an operator to Docker - the false message this branch removes.
    assert "does not need Docker" in result.diagnosis


def test_a_reachable_store_is_reported_healthy(monkeypatch):
    """The healthy answer is established too, so the check is driven in both directions."""
    class _Live:
        def heartbeat(self):
            return 1789

    monkeypatch.setattr("api.services.chroma_client.get_chroma_client", lambda _s: _Live())
    assert health_checks.check_vector_store("acme").ok is True


def test_the_incident_key_separates_the_two_stores(monkeypatch):
    """A deployment can have a cloud store and a local store failing independently.

    A `sensitive` engagement is refused CLOUD_VECTOR_STORE and uses the local server while a
    `standard` one uses the cloud, so collapsing both into one key would let a local outage
    spend the budget that a cloud outage needed.
    """
    monkeypatch.setattr(health_checks, "store_kind", lambda _s: "cloud")
    cloud = health_checks.incident_key("acme")
    monkeypatch.setattr(health_checks, "store_kind", lambda _s: "local")
    local = health_checks.incident_key("acme")
    assert cloud != local
    assert cloud.startswith(health_checks.VECTOR_STORE)


def test_store_kind_follows_the_key_and_the_projects_grant(monkeypatch):
    """`store_kind` must agree with `get_chroma_client`'s branch, which is the pair it labels."""
    from api.config import get_settings

    monkeypatch.setattr(get_settings(), "chroma_api_key", "", raising=False)
    assert health_checks.store_kind("acme") == "local", "no key means no cloud, whatever the grant"

    monkeypatch.setattr(get_settings(), "chroma_api_key", "ck-test", raising=False)
    monkeypatch.setattr(health_checks, "project_permits", lambda *a, **k: False)
    assert health_checks.store_kind("acme") == "local", (
        "a project refused CLOUD_VECTOR_STORE uses the local server even with a key set"
    )


def test_a_store_that_answers_is_diagnosed_differently_from_one_that_is_down(monkeypatch):
    """The two need different remedies, which is the entire reason the probe runs at all."""
    monkeypatch.setattr(
        health_checks, "check_vector_store", lambda _s: health_checks.HealthResult(ok=True)
    )
    answering = health_checks.describe_vector_store_failure("acme", RuntimeError("bad collection"))
    assert "is answering" in answering
    assert "restart" in answering.lower()

    monkeypatch.setattr(
        health_checks,
        "check_vector_store",
        lambda _s: health_checks.HealthResult(ok=False, diagnosis="not reachable at all"),
    )
    assert health_checks.describe_vector_store_failure("acme", None) == "not reachable at all"


# ── The alert reaches a person ───────────────────────────────────────────────────────────────

def test_a_failure_mails_the_operator_with_the_diagnosis_and_the_cost(
    mail, alert_address, store_is_down
):
    health_checks.report_vector_store_failure(
        operation="indexing interview answers",
        slug="acme",
        consequence="229 answers are not searchable",
    )
    assert len(mail) == 1
    message = mail[0]
    assert message["to"] == "ops@example.com"
    # The slug reaches the operator in the body even though it is not part of the incident key.
    assert "acme" in message["body"]
    assert "indexing interview answers" in message["body"]
    assert "229 answers are not searchable" in message["body"]
    # It must say the records are safe, or an operator reads this as data loss.
    assert "system of record" in message["body"]


def test_a_failure_is_logged_at_error_even_with_no_address_configured(caplog, mail, monkeypatch):
    """The log leg always happens - it is the one that does not depend on configuration."""
    from api.config import get_settings

    monkeypatch.setattr(get_settings(), "admin_alert_email", "", raising=False)
    with caplog.at_level(logging.ERROR):
        health_checks.report_vector_store_failure(operation="a retrieval", slug="acme")
    assert not mail, "no address is configured, so nothing may be sent"
    text = caplog.text
    assert "a retrieval" in text
    assert "ADMIN_ALERT_EMAIL" in text, "the absent leg must name the setting that would fix it"


# ── It does not become a mail storm ──────────────────────────────────────────────────────────

def test_repeated_failures_are_rate_limited_to_three(mail, alert_address, store_is_down):
    """A crew run asking forty times during one synthesis is one incident, not forty."""
    for _ in range(40):
        health_checks.report_vector_store_failure(operation="a retrieval", slug="acme")
    assert len(mail) == operator_alert.MAIL_LIMIT == 3


def test_the_limit_is_keyed_on_the_service_and_not_on_the_project(
    mail, alert_address, store_is_down
):
    """A vector store that is down is down for every engagement at once.

    This is the assertion that fails if somebody "improves" the key by adding the slug to it -
    which looks like better attribution and multiplies one incident by the number of live
    projects.
    """
    for slug in ("alpha", "bravo", "charlie", "delta", "echo"):
        health_checks.report_vector_store_failure(operation="a retrieval", slug=slug)
    assert len(mail) == 3, "five projects noticing one outage is still one incident"


# ── It never costs the caller ────────────────────────────────────────────────────────────────

def test_the_alert_never_raises_even_when_every_leg_fails(monkeypatch, caplog):
    """A side effect must not veto the thing it is a side effect of.

    Driven by breaking the seam itself rather than by trusting the `except` - the failure is
    made to happen inside `alert_operator`, which is where a real one would be.
    """
    def _explode(**kwargs):
        raise RuntimeError("the alerting mechanism is itself broken")

    monkeypatch.setattr(health_checks, "alert_operator", _explode)
    with caplog.at_level(logging.ERROR):
        health_checks.report_vector_store_failure(operation="a retrieval", slug="acme")
    assert "the alert itself failed" in caplog.text


def test_a_failing_mail_send_does_not_raise_on_the_synchronous_path(
    monkeypatch, alert_address, caplog
):
    """Resend being down must not turn a handled failure into an unhandled one.

    This is the *synchronous* caller - `index_answers` in a worker thread, and a crew tool -
    where there is no running loop and the send happens inline.
    """
    async def _fail_send(**kwargs):
        raise RuntimeError("resend is down")

    monkeypatch.setattr("api.services.outbound_mail.send_platform_mail", _fail_send)
    with caplog.at_level(logging.ERROR):
        operator_alert.alert_operator(key="k", subject="s", diagnosis="d", body="b")


@pytest.mark.asyncio
async def test_a_failing_mail_send_is_logged_on_the_async_path(
    monkeypatch, alert_address, caplog
):
    """The production path, where the send is a task - and where the guard's job is the log.

    The test above cannot see this. With a running loop the send is scheduled, so an exception
    inside it never reaches the caller *whatever* the code does - it would become an
    "exception was never retrieved" warning on a task nobody awaits, and the operator would be
    told nothing at all about an alert that silently failed to go.

    So the property here is not "does not raise" but **"says so"**, and it is asserted on the
    log. Found by mutation: narrowing that `except` left the synchronous test green, because a
    second guard one level out was catching it and the assertion was one layer away from the
    property it named.
    """
    async def _fail_send(**kwargs):
        raise RuntimeError("resend is down")

    monkeypatch.setattr("api.services.outbound_mail.send_platform_mail", _fail_send)
    with caplog.at_level(logging.ERROR):
        operator_alert.alert_operator(key="k", subject="s", diagnosis="d", body="b")
        # The send is a task; nothing has run it yet. Drain it the way production's loop would.
        pending = list(operator_alert._pending_alerts)
        assert pending, "the send should have been scheduled as a task"
        await asyncio.gather(*pending, return_exceptions=True)

    assert "could not be sent" in caplog.text, (
        "an alert whose mail leg failed must say so - otherwise a broken alerting path is "
        "indistinguishable from a healthy deployment"
    )


def test_indexing_answers_still_returns_zero_rather_than_raising(monkeypatch, mail, store_is_down):
    """The production caller's contract is unchanged: `index_answers` never raises.

    This is the property the alert could most plausibly have broken, because it was added inside
    the `except` block that guarantees it.
    """
    from api.services import interview_answer_service

    def _broken_client(_slug):
        raise RuntimeError("chroma is down")

    monkeypatch.setattr(interview_answer_service, "get_chroma_client", _broken_client)
    indexed = interview_answer_service.index_answers("acme", [{"id": 1, "answer_text": "hello"}])
    assert indexed == 0


def test_indexing_answers_alerts_and_names_what_was_lost(
    monkeypatch, mail, alert_address, store_is_down
):
    """Answers reach SQLite, fail to reach the store, and somebody is told how many.

    The size matters because this path is silent by design: indexing must never fail an
    interview a participant has already given, so the swallow stays and the alert is what
    carries the number. "229 answers are not searchable" and "one retrieval came back empty"
    send an operator to different places.

    An earlier version of this docstring claimed this had *happened* on `sp-gs-am` - that all
    229 answers were missing from Chroma. They were not: they are in Chroma Cloud, which is the
    store `get_chroma_client` builds when `CHROMA_API_KEY` is set, and the three stale local
    stores everyone kept measuring are not the ones the application uses. The scenario is real,
    the incident was not, and the difference is left recorded rather than quietly deleted.
    """
    from api.services import interview_answer_service

    def _broken_client(_slug):
        raise RuntimeError("chroma is down")

    monkeypatch.setattr(interview_answer_service, "get_chroma_client", _broken_client)
    rows = [{"id": i, "answer_text": "a"} for i in range(229)]
    interview_answer_service.index_answers("acme", rows)

    assert len(mail) == 1
    body = mail[0]["body"]
    assert "229 answers" in body, "the operator must be told the size of what went unindexed"
    assert "acme" in body


def test_the_retrieval_tool_alerts_and_tells_the_agent_the_truth(
    monkeypatch, mail, alert_address, store_is_down
):
    """A crew agent's retrieval during a run is the blocking case, and it must reach somebody.

    It also asserts the agent's own message no longer sends anybody to Docker, which was the
    same false claim `start.sh` was making.
    """
    from agents.tools import chroma_query

    monkeypatch.setattr(chroma_query, "_chroma_reachable", lambda *a, **k: False)
    tool = chroma_query.ChromaQueryTool(slug="acme", sector="energy", agent_name="alex")
    answer = tool._run(query="anything")

    assert "docker" not in answer.lower(), "the old message sent operators to install Docker"
    assert "not reachable" in answer.lower()
    assert len(mail) == 1
    assert "alex" in mail[0]["body"]


def test_the_retrieval_tool_does_not_alert_when_the_store_is_fine(monkeypatch, mail, alert_address):
    """The alert fires on a real failure, never merely on a query being made.

    Without this, every one of the assertions above is satisfied by a mechanism that alerts
    unconditionally - which would mail three times an hour, for ever, on a healthy deployment.
    """
    from agents.tools import chroma_query

    monkeypatch.setattr(chroma_query, "_chroma_reachable", lambda *a, **k: True)

    class _NoCollection:
        def get_collection(self, _name):
            raise RuntimeError("no such collection")

    monkeypatch.setattr(chroma_query, "get_chroma_client", lambda _slug: _NoCollection())
    tool = chroma_query.ChromaQueryTool(slug="acme", sector="energy", agent_name="alex")
    tool._run(query="anything")
    assert not mail, "a reachable store must not raise an outage alert"


# ── The registry ─────────────────────────────────────────────────────────────────────────────

def test_the_registry_declares_the_vector_store_and_its_probe_runs(monkeypatch):
    """One member, declared, with a probe that is actually callable.

    Asserted as *behaviour* - the probe is invoked - rather than as a count, so a member added
    with a broken or missing probe fails here rather than at the moment of an outage.
    """
    class _Live:
        def heartbeat(self):
            return 1

    # Stubbed so the registry test does not depend on whether a local ChromaDB happens to be
    # running on the machine it is run on.
    monkeypatch.setattr("api.services.chroma_client.get_chroma_client", lambda _s: _Live())

    keys = {check.key for check in health_checks.HEALTH_CHECKS}
    assert health_checks.VECTOR_STORE in keys
    for check in health_checks.HEALTH_CHECKS:
        assert check.label, f"{check.key} has no operator-readable label"
        assert isinstance(check.probe("acme"), health_checks.HealthResult)


def test_nothing_calls_the_probe_on_a_timer():
    """The check is declared, not scheduled - a startup or timer probe was explicitly declined.

    Guards the decision rather than the code: a scheduler registration added later would make
    this fail and force the argument to be had again rather than drifting in.
    """
    import pathlib

    scheduler_sources = [
        pathlib.Path("api/services/scheduler.py"),
        pathlib.Path("api/services/pam_report_job.py"),
    ]
    for path in scheduler_sources:
        if path.exists():
            text = path.read_text()
            assert "health_checks" not in text, (
                f"{path} references health_checks. Service health has a different audience from "
                f"PAM's report, whose recipients are the client's governance - see the module "
                f"docstring before wiring a digest here."
            )
