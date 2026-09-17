# tests/test_provider_health.py
"""A paid provider's refusal is classified into the action it needs, and reaches a person.

The valuable property here is **not** "an alert was sent". It is that the three ordinary causes
are told apart, because they need opposite actions and two of them cost money or time to act on
wrongly: topping up does not fix a rate limit or a malformed request, and waiting does not fix an
exhausted balance.

`classify` is a pure function over `(provider, exception)` - no network, no settings, no clock -
so every case below is driven directly. **No test in this file makes a real third-party call**;
the blocking is proven in both directions in `test_vector_store_alert.py` and re-established here
for the mail seam.
"""
from __future__ import annotations

import asyncio
import logging

import httpx
import pytest

from api.services import operator_alert, provider_health
from api.services.provider_health import (
    ANTHROPIC,
    AUTH_REFUSED,
    CHROMA,
    DEEPGRAM,
    ELEVENLABS,
    MALFORMED_REQUEST,
    OUT_OF_CREDIT,
    RATE_LIMITED,
    UNKNOWN,
    UNREACHABLE,
    classify,
)


def _http_error(status: int, body: str = "") -> httpx.HTTPStatusError:
    """A real `httpx.HTTPStatusError`, so the classifier is driven against the type it will meet."""
    request = httpx.Request("POST", "https://provider.example/v1/thing")
    response = httpx.Response(status, text=body, request=request)
    return httpx.HTTPStatusError(f"{status}", request=request, response=response)


@pytest.fixture(autouse=True)
def _no_real_mail(monkeypatch):
    operator_alert._alert_mail_log.clear()
    sent: list[dict] = []

    async def _fake_send(*, to: str, subject: str, body: str) -> bool:
        sent.append({"to": to, "subject": subject, "body": body})
        return True

    monkeypatch.setattr("api.services.outbound_mail.send_platform_mail", _fake_send)
    from api.config import get_settings

    monkeypatch.setattr(get_settings(), "admin_alert_email", "ops@example.com", raising=False)
    yield sent
    operator_alert._alert_mail_log.clear()


@pytest.fixture
def mail(_no_real_mail):
    return _no_real_mail


async def _drain_alerts() -> None:
    """Let scheduled alert sends run.

    Under a running loop `_send_off_the_request_path` creates a task and does not await it - by
    design, so a slow provider never becomes the caller's latency. A test that ends immediately
    afterwards therefore sees the log line and no mail, which looks exactly like a suppressed
    alert. Production's loop keeps running; a test has to drain it.
    """
    await asyncio.gather(*list(operator_alert._pending_alerts), return_exceptions=True)


# ── The two cases a status-code table gets wrong ─────────────────────────────────────────────

def test_anthropic_credit_exhaustion_is_a_400_and_must_not_read_as_a_code_defect():
    """**The single most expensive misclassification available.**

    Anthropic answers an exhausted balance with `400 invalid_request_error` carrying "Your
    credit balance is too low to access the Anthropic API" - not a 402. A plain
    `400 -> MALFORMED_REQUEST` rule reports it as a defect and sends somebody to debug a request
    that was perfectly well formed, while every call in the system goes on failing.
    """
    exc = _http_error(
        400,
        '{"type":"error","error":{"type":"invalid_request_error","message":'
        '"Your credit balance is too low to access the Anthropic API."}}',
    )
    assert classify(ANTHROPIC, exc).fault == OUT_OF_CREDIT


def test_elevenlabs_quota_exhaustion_is_a_401_and_must_not_read_as_a_bad_key():
    """ElevenLabs uses 401 for an exhausted quota as well as for a bad key.

    Classified as auth, the operator replaces a key that is working and the fault remains.
    """
    exc = _http_error(401, '{"detail":{"status":"quota_exceeded","message":"quota exceeded"}}')
    assert classify(ELEVENLABS, exc).fault == OUT_OF_CREDIT


def test_a_genuinely_bad_key_is_still_auth_refused():
    """The counterpart, so the body check has not simply swallowed the auth case.

    Without this, a classifier that answered OUT_OF_CREDIT for every 401 would pass the test
    above perfectly.
    """
    exc = _http_error(401, '{"detail":{"status":"invalid_api_key","message":"Invalid API key"}}')
    assert classify(ELEVENLABS, exc).fault == AUTH_REFUSED


# ── The three outcomes ───────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize(
    "status,body,expected",
    [
        (402, "", OUT_OF_CREDIT),
        (429, "", RATE_LIMITED),
        (400, '{"err_msg":"Keyterm limit exceeded"}', MALFORMED_REQUEST),
        (403, "", AUTH_REFUSED),
        (500, "", UNREACHABLE),
        (503, "", UNREACHABLE),
        (418, "", UNKNOWN),
    ],
)
def test_the_ordinary_statuses_classify_as_their_remedy(status, body, expected):
    assert classify(DEEPGRAM, _http_error(status, body)).fault == expected


def test_deepgrams_keyterm_refusal_is_a_defect_and_says_so():
    """The case the owner actually hit: three grants failed and nothing reached a person.

    **No balance poll would have caught this** - there was credit. The request was malformed,
    which is why call-site capture is the guarantee and polling is the extra.
    """
    fault = classify(DEEPGRAM, _http_error(400, '{"err_msg":"Keyterm limit exceeded"}'))
    assert fault.fault == MALFORMED_REQUEST
    action = provider_health.remedy(fault)
    assert "defect" in action
    assert "Do not top up" in action


def test_a_network_failure_is_unreachable_and_implicates_no_account():
    exc = httpx.ConnectError("connection refused")
    fault = classify(CHROMA, exc)
    assert fault.fault == UNREACHABLE
    assert "Nothing about the account is implicated" in provider_health.remedy(fault)


def test_an_unrecognised_refusal_says_it_is_unrecognised_rather_than_guessing():
    """An alert that guesses "top up" on an unknown refusal is worse than one that says so."""
    action = provider_health.remedy(classify(ANTHROPIC, _http_error(418, "teapot")))
    assert "does not recognise" in action
    assert "read it before assuming a cause" in action


def test_the_three_remedies_contradict_each_other_rather_than_merely_differing():
    """Each remedy must rule out the others' action, which is the point of distinguishing them."""
    credit = provider_health.remedy(classify(ANTHROPIC, _http_error(402)))
    limited = provider_health.remedy(classify(ANTHROPIC, _http_error(429)))
    malformed = provider_health.remedy(classify(ANTHROPIC, _http_error(400, "bad shape")))

    assert "top it up" in credit and "will not clear on its own" in credit
    assert "Topping up changes nothing" in limited
    assert "not a billing problem" in malformed
    assert len({credit, limited, malformed}) == 3


def test_every_declared_fault_has_its_own_remedy():
    """The invariant that keeps `remedy`'s fallback unreachable.

    A fault constant added without a remedy would otherwise fall to the "unrecognised" sentence
    - silently telling an operator this deployment does not understand a refusal it classified
    perfectly well. Distinctness is asserted too: two faults sharing a sentence is the
    conflation this whole module exists to prevent.
    """
    sentences = [provider_health._REMEDIES.get(f) for f in provider_health.FAULTS]
    missing = [f for f, sentence in zip(provider_health.FAULTS, sentences) if not sentence]
    assert not missing, f"faults with no remedy: {missing}"
    assert len(set(sentences)) == len(provider_health.FAULTS), "two faults share a remedy"


# ── Incident keys ────────────────────────────────────────────────────────────────────────────

def test_one_incident_per_provider_per_fault():
    """A rate-limited account and a nearly-empty one are two jobs; one must not hide the other."""
    limited = classify(ANTHROPIC, _http_error(429)).incident_key
    credit = classify(ANTHROPIC, _http_error(402)).incident_key
    other_provider = classify(ELEVENLABS, _http_error(429)).incident_key
    assert len({limited, credit, other_provider}) == 3


def test_repeated_refusals_are_rate_limited(mail):
    """A crew run hammering an exhausted account is one incident, not forty messages."""
    for _ in range(40):
        provider_health.report_provider_failure(
            provider=ANTHROPIC, operation="a completion", exc=_http_error(402), slug="acme"
        )
    assert len(mail) == operator_alert.MAIL_LIMIT == 3


def test_two_different_faults_do_not_share_a_budget(mail):
    for _ in range(5):
        provider_health.report_provider_failure(
            provider=ANTHROPIC, operation="a completion", exc=_http_error(402)
        )
    for _ in range(5):
        provider_health.report_provider_failure(
            provider=ANTHROPIC, operation="a completion", exc=_http_error(429)
        )
    assert len(mail) == 6, "an exhausted balance and a rate limit are two incidents"


# ── The alert carries the action ─────────────────────────────────────────────────────────────

def test_the_message_names_the_action_and_the_classification(mail):
    provider_health.report_provider_failure(
        provider=ANTHROPIC,
        operation="a fast completion",
        exc=_http_error(400, "Your credit balance is too low"),
        slug="acme",
        consequence="a crew run failed",
    )
    assert len(mail) == 1
    body = mail[0]["body"]
    assert "out_of_credit" in body
    assert "top it up" in body
    assert "acme" in body
    assert "a crew run failed" in body


def test_reporting_never_raises_even_when_the_seam_is_broken(monkeypatch, caplog):
    """A side effect must not veto the thing it is a side effect of."""
    def _explode(**kwargs):
        raise RuntimeError("the alerting mechanism is itself broken")

    monkeypatch.setattr("api.services.operator_alert.alert_operator", _explode)
    with caplog.at_level(logging.ERROR):
        result = provider_health.report_provider_failure(
            provider=ANTHROPIC, operation="a completion", exc=_http_error(402)
        )
    assert result is None
    assert "the alert itself failed" in caplog.text


# ── Anthropic headroom, read from a response already made ────────────────────────────────────

def test_low_headroom_alerts_and_says_it_is_not_a_balance(mail):
    """Anthropic exposes no balance, so this must not be presented as one.

    An operator told "you are nearly out" who then tops up has spent money on a rate limit.
    """
    headers = httpx.Headers({
        "anthropic-ratelimit-input-tokens-limit": "100000",
        "anthropic-ratelimit-input-tokens-remaining": "500",
        "anthropic-ratelimit-input-tokens-reset": "2026-09-18T14:05:00Z",
    })
    tripped = provider_health.note_anthropic_headers(headers, slug="acme")
    assert tripped == "input-tokens"
    assert len(mail) == 1
    body = mail[0]["body"]
    assert "not a balance" in body
    assert "2026-09-18T14:05:00Z" in body
    assert "nothing was polled" in body


def test_healthy_headroom_says_nothing(mail):
    """The floor must be a floor - without this, the alert fires on every successful call."""
    headers = httpx.Headers({
        "anthropic-ratelimit-input-tokens-limit": "100000",
        "anthropic-ratelimit-input-tokens-remaining": "90000",
    })
    assert provider_health.note_anthropic_headers(headers) is None
    assert not mail


def test_missing_headers_are_not_an_error(mail):
    """Called on the success path, so it must never turn a working completion into a failure."""
    assert provider_health.note_anthropic_headers(httpx.Headers({})) is None
    assert provider_health.note_anthropic_headers(None) is None
    assert not mail


def test_each_bucket_is_its_own_incident(mail):
    """The input-token bucket running low must not silence the request bucket doing the same."""
    for bucket in ("input-tokens", "requests"):
        provider_health.note_anthropic_headers(httpx.Headers({
            f"anthropic-ratelimit-{bucket}-limit": "1000",
            f"anthropic-ratelimit-{bucket}-remaining": "1",
        }))
    assert len(mail) == 2


# ── Wiring: the call sites report and do not swallow ─────────────────────────────────────────

@pytest.mark.asyncio
async def test_a_refused_completion_is_reported_and_still_raises(monkeypatch, mail):
    """Reporting is a monitoring leg, not error handling.

    Swallowing here would hand the caller an empty answer, which is the silent failure this
    whole exercise exists to remove - reintroduced by the fix for it.
    """
    from api.services import llm_client

    monkeypatch.setattr(llm_client, "resolve_model", lambda *a, **k: ("claude-x", None))

    class _Messages:
        async def create(self, **kwargs):
            raise _http_error(402, "no credit")

    class _Client:
        messages = _Messages()

    monkeypatch.setattr(llm_client, "get_anthropic_client", lambda: _Client())

    with pytest.raises(httpx.HTTPStatusError):
        await llm_client.project_completion("acme", "fast", [{"role": "user", "content": "hi"}])

    await _drain_alerts()
    assert len(mail) == 1, "the refusal must reach an operator"
    assert "out_of_credit" in mail[0]["body"]


@pytest.mark.asyncio
async def test_a_successful_completion_is_unchanged_by_the_monitoring(monkeypatch, mail):
    """The success path must be exactly as it was - same call, same return, no alert.

    Header capture lives at the transport (`http_clients.get_anthropic_client`) precisely so
    this seam is untouched; the test asserting the headers are read is
    `test_the_transport_hook_reads_headers_off_a_real_response` below.
    """
    from api.services import llm_client

    monkeypatch.setattr(llm_client, "resolve_model", lambda *a, **k: ("claude-x", None))

    class _Message:
        content = [type("B", (), {"text": "  hello  "})()]

    class _Messages:
        async def create(self, **kwargs):
            return _Message()

    class _Client:
        messages = _Messages()

    monkeypatch.setattr(llm_client, "get_anthropic_client", lambda: _Client())

    answer = await llm_client.project_completion(
        "acme", "fast", [{"role": "user", "content": "hi"}]
    )
    assert answer == "hello", "the completion's contract must not move"
    await _drain_alerts()
    assert not mail, (
        "the success path must send nothing: headroom is read at the transport, and a faked "
        "client never reaches it"
    )


def test_a_cloud_store_out_of_quota_is_not_reported_as_unreachable(monkeypatch, mail):
    """Chroma Cloud exposes no quota endpoint, so the call-site refusal is the only signal.

    Reporting it as "ChromaDB is not reachable" would send an operator to start a local server
    during a billing problem on a cloud account.
    """
    from api.services import health_checks

    health_checks.report_vector_store_failure(
        operation="indexing interview answers",
        slug="acme",
        exc=_http_error(402, "quota exceeded"),
    )
    assert len(mail) == 1
    body = mail[0]["body"]
    assert "out_of_credit" in body
    assert "not reachable" not in body
    assert "chroma run" not in body


def test_deepgram_names_a_malformed_request_as_a_defect():
    """The grant door's own diagnosis had no 400 branch, so the case the owner hit read as
    'refused the request for a grant with HTTP 400' - true, and silent about what to do."""
    from api.services.speech_policy import describe_deepgram_failure

    sentence = describe_deepgram_failure(_http_error(400, "Keyterm limit exceeded"))
    assert "defect" in sentence
    assert "Keyterm limit exceeded" in sentence
    assert "change nothing" in sentence


def test_the_transport_hook_reads_headers_off_a_real_response(monkeypatch, mail):
    """**Establish that the hook fires**, rather than asserting it exists.

    Header capture was moved to the transport so no call site has to change, which means no
    call-site test can see it - and an indicator nothing drives is exactly the "this code has
    never run" shape CLAUDE.md warns about. So this drives a real `httpx.AsyncClient` carrying
    the real hook against a `MockTransport`, with no network: the request is answered locally
    and the headers are the ones a low account would send.
    """
    import asyncio

    from api.services import http_clients

    monkeypatch.setattr(http_clients, "_anthropic_client", None, raising=False)

    captured: list[str] = []

    async def _hook(response: httpx.Response) -> None:
        provider_health.note_anthropic_headers(response.headers)
        captured.append("fired")

    def _handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, headers={
            "anthropic-ratelimit-input-tokens-limit": "1000",
            "anthropic-ratelimit-input-tokens-remaining": "5",
        }, json={"ok": True})

    async def _drive() -> None:
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(_handler), event_hooks={"response": [_hook]}
        ) as client:
            await client.post("https://api.anthropic.com/v1/messages", json={})
        await asyncio.gather(*list(operator_alert._pending_alerts), return_exceptions=True)

    asyncio.run(_drive())

    assert captured == ["fired"], "the response event hook did not run"
    assert len(mail) == 1, "low headroom on a real transport response must alert"
    assert "not a balance" in mail[0]["body"]


def test_the_real_client_is_built_with_the_response_hook(monkeypatch):
    """The hook must be wired into the client the application actually builds.

    The test above proves a hook of this shape works; this one proves the production builder
    installs one, so the two together cover "it fires" and "it is attached".
    """
    from api.services import http_clients

    monkeypatch.setattr(http_clients, "_anthropic_client", None, raising=False)
    from api.config import get_settings

    monkeypatch.setattr(get_settings(), "anthropic_api_key", "sk-test", raising=False)

    client = http_clients.get_anthropic_client()
    hooks = client._client.event_hooks.get("response") or []
    assert hooks, "the Anthropic client was built with no response hook, so no headers are read"

    monkeypatch.setattr(http_clients, "_anthropic_client", None, raising=False)
