# tests/test_interview_speech_policy.py
"""An engagement that keeps its material on the premises does not hand interviews to Google.

The interview page has two recognisers. Deepgram is the first choice, streamed under a stated
contract; the browser's own `SpeechRecognition` is the fallback, and **Chrome streams that audio
to Google while Safari streams it to Apple** - no contract, no retention undertaking, no provider
this deployment chose. sp66 made the Deepgram undertaking specific and confident on the privacy
page and left the alternative silent, which is the shape `agents/egress.py` already warns about.

The policy, decided by the project owner on 13 September and driven here:

  * not granted `HOSTED_INFERENCE` - probe before the interview begins; refuse if either half
    fails; stop rather than fall back if it fails mid-interview; tell an administrator which of a
    refused key, an exhausted balance and a rate limit it was.
  * granted it - the fallback, exactly as before.

**No test in this file reaches a real third party.** `no_network` below refuses name resolution
and every outbound connect, and `test_the_network_block_actually_blocks` proves the block in both
directions - a guard asserted only by the absence of a call is a guard that passes against a
block that does nothing.

**A note on the session tokens**, which are `tok-alpha`, `tok-beta` and `tok-gamma` rather than
anything descriptive. They were named after the engagements they belong to, and
`test_the_payload_never_carries_the_mode_itself` - which asserts the string "sensitive" never
reaches a participant's browser - then failed against its own fixture, because the token was
called `tok-sensitive` and travels in the payload by design. That is CLAUDE.md's "a sentinel
drawn from the system's own defaults cannot fail" arriving from the other side: a fixture name
that collides with the thing being forbidden makes the assertion unfalsifiable in one direction
and unpassable in the other. The names carry no vocabulary the assertions search for.
"""
from __future__ import annotations

import json
import socket
import sqlite3
from pathlib import Path

import httpx
import pytest
from httpx import ASGITransport, AsyncClient

from api.config import get_settings
from api.services.chroma_client import forget_project_mode
from api.services.speech_policy import (
    BROWSER_PERMITTED,
    SPEECH_REQUIRED,
    describe_browser_failure,
    describe_deepgram_failure,
    speech_policy_for,
)


# ---------------------------------------------------------------------------
# The network block, and the proof that it is one
# ---------------------------------------------------------------------------

class _RefusedSocket(OSError):
    """Raised in place of reaching the network.

    `OSError` rather than `Exception`, and not for tidiness: a blocked network really does
    surface as an `OSError`, and that is what `httpx` maps into `ConnectError`. Raising a plain
    `Exception` made the block look like a *bug* to every layer above it rather than like an
    unreachable host - so the token door's `httpx.HTTPError` handler did not catch it and the
    door answered 500 where a real outage answers 503. The fake has to fail the way the real
    thing fails, which is the same rule `FakeRecorder` in the frontend fakes is written under.
    """


@pytest.fixture
def no_network(monkeypatch):
    """Nothing in this file may reach a third party, and the block is established, not described.

    Blocked at **resolution and connection** rather than at the `socket.socket` constructor, and
    that is a correctness point rather than a preference: asyncio builds its own self-pipe out of
    `socket.socket` when a loop is created, so refusing the constructor takes the event loop down
    before any test runs. Refusing `getaddrinfo`, `connect`, `connect_ex` and `create_connection`
    stops every outbound call while leaving a loop buildable.

    It catches a call whatever library makes it - httpx, a bare `urllib`, something added later -
    which is what stubbing `generate_deepgram_token` alone cannot do: that proves the one call
    was diverted and says nothing about a second one beside it.
    """
    def refuse(*args, **kwargs):
        raise _RefusedSocket("this test may not reach the network")

    monkeypatch.setattr(socket, "getaddrinfo", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)
    monkeypatch.setattr(socket.socket, "connect", refuse)
    monkeypatch.setattr(socket.socket, "connect_ex", refuse)
    return refuse


def test_the_network_block_actually_blocks(no_network):
    """The other direction, without which the block could be a no-op and every test still green.

    CLAUDE.md's rule for a guard: drive it both gated and ungated, because a one-sided assertion
    passes against a guard that reports everything and against one that reports nothing. Both
    routes out are driven, because a block on one of them is not a block.
    """
    with pytest.raises(_RefusedSocket):
        socket.create_connection(("api.deepgram.com", 443))
    with pytest.raises(_RefusedSocket):
        socket.getaddrinfo("api.deepgram.com", 443)


@pytest.mark.asyncio
async def test_a_real_http_call_is_refused_under_the_block(no_network):
    """And through the client this code would actually use, not only through the primitive.

    `httpx` is what `generate_deepgram_token` builds, so this is the route a regression would
    take. It must raise - anything else means the block sits somewhere the real call goes past.
    """
    with pytest.raises(Exception) as caught:
        async with httpx.AsyncClient() as client:
            await client.post("https://api.deepgram.com/v1/auth/grant", timeout=1.0)
    assert not isinstance(caught.value, AssertionError)


@pytest.mark.asyncio
async def test_the_token_door_is_the_one_that_would_have_gone_out(no_network, engagements):
    """Establishes that the block is on the path this file's other tests stub rather than beside it.

    Those tests replace `generate_deepgram_token`, which is the right seam for driving each
    failure - but a stub proves nothing about where the unstubbed function goes. This one leaves
    it alone, gives the deployment a key so the "not configured" branch is not what answers, and
    watches the real call be refused at the socket. Without it, "no real third-party call" is a
    claim about the stubs rather than about the code.
    """
    from api.main import app

    monkeypatch_key = get_settings()
    original = monkeypatch_key.deepgram_api_key
    object.__setattr__(monkeypatch_key, "deepgram_api_key", "a-key-that-is-never-used")
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/api/interviews/tok-beta/deepgram-token")
    finally:
        object.__setattr__(monkeypatch_key, "deepgram_api_key", original)

    # Refused because the network was blocked, not because the key was missing - the branch that
    # answers for a missing key says "not configured", and this must not be that sentence.
    assert resp.status_code == 503
    assert "not configured" not in resp.json()["detail"].lower()


# ---------------------------------------------------------------------------
# Fixtures: two engagements that differ only in what they are granted
# ---------------------------------------------------------------------------

_SESSIONS_DDL = """
CREATE TABLE IF NOT EXISTS projects (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    slug TEXT UNIQUE NOT NULL,
    llm_mode TEXT NOT NULL DEFAULT 'standard',
    force_local_inference INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS interview_sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_token TEXT UNIQUE,
    node_label TEXT,
    voice_config TEXT,
    status TEXT DEFAULT 'pending',
    transcript_json TEXT,
    ratings_json TEXT,
    checkpoint_json TEXT,
    speech_failure TEXT,
    completed_at TEXT
);
"""


def _seed(db_dir: Path, slug: str, *, mode: str, force_local: int = 0, token: str) -> None:
    db_dir.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_dir / f"{slug}.db")
    conn.executescript(_SESSIONS_DDL)
    conn.execute(
        "INSERT OR REPLACE INTO projects (id, slug, llm_mode, force_local_inference) "
        "VALUES (1, ?, ?, ?)",
        (slug, mode, force_local),
    )
    conn.execute(
        "INSERT OR REPLACE INTO interview_sessions (session_token, node_label, voice_config) "
        "VALUES (?, 'Connections Delivery', ?)",
        (token, json.dumps({"elevenlabs_voice_id": "V", "language": "en", "country_code": "GB"})),
    )
    conn.commit()
    conn.close()
    forget_project_mode(slug)


@pytest.fixture
def engagements(tmp_path, monkeypatch):
    """Three projects: one sensitive, one standard, one standard forcing local inference.

    The third is the one a mode-name comparison gets wrong, and it exists today - CLAUDE.md
    records `sp-gs-am` as exactly this shape. A test with only the first two would pass against
    `mode == "sensitive"`, which is the implementation this policy must not have.
    """
    db_dir = tmp_path / "db"
    monkeypatch.setenv("DATABASE_DIR", str(db_dir))
    monkeypatch.setenv("PROJECTS_DIR", str(tmp_path / "projects"))
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    get_settings.cache_clear()

    _seed(db_dir, "locked-down", mode="sensitive", token="tok-alpha")
    _seed(db_dir, "ordinary", mode="standard", token="tok-beta")
    _seed(db_dir, "measuring-local", mode="standard", force_local=1, token="tok-gamma")

    yield db_dir

    for slug in ("locked-down", "ordinary", "measuring-local"):
        forget_project_mode(slug)
    get_settings.cache_clear()


def _failure_on(db_dir: Path, slug: str, token: str) -> dict | None:
    conn = sqlite3.connect(db_dir / f"{slug}.db")
    row = conn.execute(
        "SELECT speech_failure FROM interview_sessions WHERE session_token=?", (token,)
    ).fetchone()
    conn.close()
    return json.loads(row[0]) if row and row[0] else None


# ---------------------------------------------------------------------------
# The policy itself
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "slug,expected",
    [
        ("locked-down", SPEECH_REQUIRED),
        ("ordinary", BROWSER_PERMITTED),
        # The case a mode-name comparison answers wrongly, and the reason this asks
        # `project_permits` rather than reading `llm_mode`. `standard` declares hosted
        # inference; this project has narrowed it away, and the browser's recogniser is hosted
        # inference in the only sense that matters here - somebody else's model, off the
        # premises, holding the client's words.
        ("measuring-local", SPEECH_REQUIRED),
    ],
)
def test_the_policy_follows_the_grant_and_not_the_mode_name(engagements, slug, expected):
    assert speech_policy_for(slug) == expected


def test_a_mode_that_grants_nothing_refuses_the_fallback(engagements, monkeypatch):
    """A fourth mode is planned, and it must not inherit the permissive branch by not being named.

    `EGRESS_GRANTS` answers nothing for an undeclared mode, so this is the miss falling towards
    containment - and it is asserted rather than reasoned about, because the whole argument for
    resolving a capability instead of comparing a name is about the mode nobody has written yet.
    """
    _seed(engagements, "from-the-future", mode="sovereign-ish", token="tok-delta")
    assert speech_policy_for("from-the-future") == SPEECH_REQUIRED


def test_a_blank_slug_raises_rather_than_permitting(engagements):
    """The rule `project_completion` and `elaboration_press` already carry, one seam over.

    A forgotten slug resolving to the permissive answer is how the test-interview dialog sent a
    sensitive engagement's answers to Anthropic. Here the same defect would stream a
    participant's voice to their browser vendor.
    """
    with pytest.raises(ValueError, match="requires the project slug"):
        speech_policy_for("")
    with pytest.raises(ValueError):
        speech_policy_for("   ")


# ---------------------------------------------------------------------------
# What crosses to the participant's browser
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
@pytest.mark.parametrize(
    "slug,token,expected",
    [
        ("locked-down", "tok-alpha", SPEECH_REQUIRED),
        ("ordinary", "tok-beta", BROWSER_PERMITTED),
    ],
)
async def test_the_session_payload_carries_the_policy(engagements, slug, token, expected):
    from api.services.interview_service import get_session_with_script

    result = await get_session_with_script(token)
    assert result is not None
    assert result["speech_policy"] == expected


@pytest.mark.asyncio
async def test_the_payload_never_carries_the_mode_itself(engagements):
    """The participant's page has no login and no business knowing an engagement's posture.

    Asserted over the **whole serialised payload** rather than over a key, because the defect
    this forbids is a mode arriving somewhere nobody looked - inside `session`, inside
    `branding`, as a second key beside the policy. A `"llm_mode" not in result` test would pass
    against every one of those.
    """
    from api.services.interview_service import get_session_with_script

    result = await get_session_with_script("tok-alpha")
    assert result is not None
    wire = json.dumps(result, default=str)
    assert "llm_mode" not in wire
    assert "sensitive" not in wire
    assert "force_local_inference" not in wire
    # And the thing that *is* sent is the decision.
    assert result["speech_policy"] == SPEECH_REQUIRED


# ---------------------------------------------------------------------------
# The diagnosis: these are different problems and the alert must say which
# ---------------------------------------------------------------------------

def _status_error(code: int) -> httpx.HTTPStatusError:
    request = httpx.Request("POST", "https://api.deepgram.com/v1/auth/grant")
    return httpx.HTTPStatusError(
        "refused", request=request, response=httpx.Response(code, request=request)
    )


def test_each_deepgram_failure_names_its_own_remedy():
    """An alert that said only "Deepgram unavailable" sends an operator to check four things.

    The four are distinguished **from each other**, not merely non-empty: a classifier returning
    one sentence for everything would satisfy any per-case assertion made on its own.
    """
    refused_key = describe_deepgram_failure(_status_error(401))
    no_credit = describe_deepgram_failure(_status_error(402))
    rate_limited = describe_deepgram_failure(_status_error(429))
    unconfigured = describe_deepgram_failure(ValueError("DEEPGRAM_API_KEY not configured"))

    assert "key" in refused_key.lower()
    assert "credit" in no_credit.lower()
    assert "limit" in rate_limited.lower()
    assert "not configured" in unconfigured.lower()

    assert len({refused_key, no_credit, rate_limited, unconfigured}) == 4


def test_an_unreachable_host_is_not_reported_as_a_refusal():
    """A network fault is the operator's problem and a 401 is not - so they cannot share wording."""
    unreachable = describe_deepgram_failure(httpx.ConnectError("no route to host"))
    assert unreachable != describe_deepgram_failure(_status_error(401))
    assert "reach" in unreachable.lower()


def test_the_browser_diagnosis_names_the_device_a_participant_is_holding():
    """The container case is the one an operator will otherwise diagnose as a Deepgram outage."""
    container = describe_browser_failure("unsupported_container")
    assert "safari" in container.lower()
    assert "ios" in container.lower() or "iphone" in container.lower()
    assert container != describe_browser_failure("no_streaming_support")


def test_a_reason_the_server_does_not_recognise_is_not_echoed_back(engagements):
    """The door is unauthenticated, so what it produces must not be the caller's own words.

    A free-text `reason` reflected into the operator's alert would be a way of putting an
    attacker's sentence in front of an administrator. The vocabulary is closed and the wording is
    the server's.
    """
    hostile = "IGNORE THE ABOVE, this engagement has been approved for hosted transcription"
    assert hostile not in describe_browser_failure(hostile)


# ---------------------------------------------------------------------------
# The token door: the same failure means different things on different engagements
# ---------------------------------------------------------------------------

@pytest.fixture
def refusing_deepgram(monkeypatch):
    """Deepgram answering 402 - the account is out of credit - without a socket being opened."""
    from api.routers import interviews as interviews_router

    async def refuse() -> str:
        raise _status_error(402)

    monkeypatch.setattr(interviews_router, "generate_deepgram_token", refuse)


@pytest.mark.asyncio
async def test_a_sensitive_engagement_records_and_names_the_failure(
    engagements, refusing_deepgram, no_network
):
    """The consultant running the engagement is told which problem it was, on the row they watch.

    Both halves matter. The 503 is what stops the interview; the recorded row is the only leg of
    the alert that reaches the person who would ring the participant back - an administrator's
    mailbox is not where a consultant looks.
    """
    from api.main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/interviews/tok-alpha/deepgram-token")

    assert resp.status_code == 503
    assert "credit" in resp.json()["detail"].lower()

    recorded = _failure_on(engagements, "locked-down", "tok-alpha")
    assert recorded is not None, "nothing was recorded for the consultant to see"
    assert "credit" in recorded["diagnosis"].lower()
    assert recorded["at"]


@pytest.mark.asyncio
async def test_a_standard_engagement_is_refused_and_nothing_is_recorded(
    engagements, refusing_deepgram, no_network
):
    """**The control, and without it a change that alerted on everything would pass above.**

    A deployment with no Deepgram key is every deployment before sp66, and on a standard
    engagement that is not an incident - the page falls back and the participant is told which
    recogniser is listening. An alert per fallback there would be noise that buries the real one.
    """
    from api.main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/interviews/tok-beta/deepgram-token")

    # Still refused - the door has no grant to give - but it is the routine refusal.
    assert resp.status_code == 503
    assert _failure_on(engagements, "ordinary", "tok-beta") is None


@pytest.mark.asyncio
async def test_the_project_forcing_local_inference_is_treated_as_the_strict_one(
    engagements, refusing_deepgram, no_network
):
    """`standard` by mode, narrow by resolution - and the door must follow the resolution."""
    from api.main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/interviews/tok-gamma/deepgram-token")

    assert resp.status_code == 503
    assert _failure_on(engagements, "measuring-local", "tok-gamma") is not None


# ---------------------------------------------------------------------------
# The door the browser reports its own half of the probe to
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_a_successful_grant_clears_a_failure_recorded_earlier(engagements, monkeypatch, no_network):
    """**A recorded failure is a statement about now, and nothing was clearing it.**

    09:00 Deepgram is out of credit and the participant is refused. Credit is restored; they are
    interviewed at 14:00. Without this the consultant's panel shows the amber "Not interviewed -
    no credit (402)" for ever, beside whatever the session becomes - so they chase somebody
    already interviewed, or distrust a good transcript.

    Driven as the **sequence**, which is the only way to see it: record through the real door,
    then succeed through the real door, then read the row.
    """
    from api.main import app
    from api.routers import interviews as interviews_router

    # 09:00 - no credit.
    async def refuse() -> str:
        raise _status_error(402)

    monkeypatch.setattr(interviews_router, "generate_deepgram_token", refuse)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        await client.get("/api/interviews/tok-alpha/deepgram-token")
    assert _failure_on(engagements, "locked-down", "tok-alpha") is not None

    # 14:00 - credit restored, and the same door answers.
    async def grant() -> str:
        return "jwt-for-the-browser"

    monkeypatch.setattr(interviews_router, "generate_deepgram_token", grant)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/interviews/tok-alpha/deepgram-token")

    assert resp.status_code == 200
    assert _failure_on(engagements, "locked-down", "tok-alpha") is None, (
        "the panel would show 'Not interviewed' beside a completed interview"
    )


@pytest.mark.asyncio
async def test_a_session_that_never_failed_is_unaffected_by_the_clearing(engagements, monkeypatch, no_network):
    """The control: clearing must be a clearing, not a write that happens to leave NULL.

    A door that always wrote NULL would pass the test above and would also erase a failure
    recorded a moment earlier for a *different* session on the same project, which is the case
    that matters when forty stakeholders share one outage.
    """
    from api.main import app
    from api.routers import interviews as interviews_router

    async def refuse() -> str:
        raise _status_error(402)

    # tok-alpha fails and stays failed.
    monkeypatch.setattr(interviews_router, "generate_deepgram_token", refuse)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        await client.get("/api/interviews/tok-alpha/deepgram-token")

    # A second session on the same project succeeds. Its clearing must not reach tok-alpha.
    _seed(engagements, "locked-down", mode="sensitive", token="tok-epsilon")
    conn = sqlite3.connect(engagements / "locked-down.db")
    conn.execute(
        "INSERT OR IGNORE INTO interview_sessions (session_token, node_label) VALUES ('tok-epsilon','x')"
    )
    conn.commit()
    conn.close()

    async def grant() -> str:
        return "jwt"

    monkeypatch.setattr(interviews_router, "generate_deepgram_token", grant)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        await client.get("/api/interviews/tok-epsilon/deepgram-token")

    assert _failure_on(engagements, "locked-down", "tok-alpha") is not None, (
        "one session's success erased another session's recorded failure"
    )


@pytest.mark.asyncio
async def test_the_browser_half_of_the_probe_is_recorded_on_a_sensitive_engagement(
    engagements, no_network
):
    """Safari records MP4/AAC, so it declines the socket - and only the browser can say so.

    This is the half of the probe the server cannot see for itself, and on this kind of
    engagement it has the same consequence as Deepgram being down: the interview does not happen.
    """
    from api.main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post(
            "/api/interviews/tok-alpha/speech-failure",
            json={"reason": "unsupported_container"},
        )

    assert resp.status_code == 200
    assert resp.json()["recorded"] is True
    recorded = _failure_on(engagements, "locked-down", "tok-alpha")
    assert recorded is not None
    assert "safari" in recorded["diagnosis"].lower()


@pytest.mark.asyncio
async def test_the_same_report_records_nothing_on_a_standard_engagement(engagements, no_network):
    """The control. There the browser's recogniser is the designed answer, not an incident."""
    from api.main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post(
            "/api/interviews/tok-beta/speech-failure",
            json={"reason": "unsupported_container"},
        )

    assert resp.status_code == 200
    assert resp.json()["recorded"] is False
    assert _failure_on(engagements, "ordinary", "tok-beta") is None


@pytest.mark.asyncio
async def test_an_unknown_token_is_a_404_rather_than_an_alert(engagements, no_network):
    """Otherwise this door is a way of making a deployment alert about sessions that do not exist."""
    from api.main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post(
            "/api/interviews/no-such-token/speech-failure", json={"reason": "socket_failed"}
        )
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# A halted interview keeps what it captured - F4
# ---------------------------------------------------------------------------

_PAIRS = [
    {"question_id": "SC-014.S1.Q1", "question": "What slows connections down?",
     "answer": "Wayleaves, mostly.", "follow_up": 0},
    {"question_id": "SC-014.S1.Q2", "question": "Who decides the order of works?",
     "answer": "The programme board, quarterly.", "follow_up": 0},
]


def _session_row(db_dir: Path, slug: str, token: str) -> dict:
    conn = sqlite3.connect(db_dir / f"{slug}.db")
    conn.row_factory = sqlite3.Row
    row = conn.execute(
        "SELECT * FROM interview_sessions WHERE session_token=?", (token,)
    ).fetchone()
    conn.close()
    return dict(row) if row else {}


@pytest.mark.asyncio
async def test_a_halted_interview_keeps_the_answers_it_captured(engagements, no_network):
    """**The halt screen promises this, so it has to be true.**

    Before the repair a halt wrote a `checkpoint_json` that nothing in `api/`, `ui/src` or
    `agents/` ever read, and `interview_answers` stayed empty - so the transcript the crews read
    was empty and forty minutes of a participant's time was discarded behind the sentence
    "everything you answered has been saved".

    Asserted on the **transcript the server now holds**, not on the request having been accepted.
    """
    from api.main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post(
            "/api/interviews/tok-alpha/speech-failure",
            json={"reason": "socket_failed", "qa_pairs": _PAIRS},
        )

    assert resp.status_code == 200
    assert resp.json()["preserved"] is True

    row = _session_row(engagements, "locked-down", "tok-alpha")
    assert "Wayleaves, mostly." in (row["transcript_json"] or "")
    assert "The programme board, quarterly." in (row["transcript_json"] or "")


@pytest.mark.asyncio
async def test_a_halted_interview_is_not_recorded_as_one_that_happened(engagements, no_network):
    """**The reason this does not simply call `/complete`.**

    That door stamps `status='completed'` and `completed_at`, which would tell the consultant,
    the crews and every coverage count that a twelve-of-sixty interview had finished - trading a
    false sentence to the participant for a false one about them, which is the same defect one
    person over. `abandoned` is the honest state: real answers, and a stakeholder who still has
    not been interviewed.
    """
    from api.main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        await client.post(
            "/api/interviews/tok-alpha/speech-failure",
            json={"reason": "socket_failed", "qa_pairs": _PAIRS},
        )

    row = _session_row(engagements, "locked-down", "tok-alpha")
    assert row["status"] == "abandoned"
    assert row["status"] != "completed"
    assert not row["completed_at"], "a halted interview was stamped with a completion time"


@pytest.mark.asyncio
async def test_the_words_with_no_question_are_kept_where_only_the_checkpoint_can_hold_them(
    engagements, no_network
):
    """The checkpoint survives a halt, unlike a completion, and that is the one thing it is for.

    A completion clears `checkpoint_json` because every answer has become a row. A halt cannot:
    the words spoken into the failing socket have no question id, since the interview loop builds
    the pair after the listen resolves and it never will. Clearing it here - which is what
    reusing the completion path wholesale would have done - would discard exactly the sentence
    the participant was speaking when the service went.
    """
    from api.database import interview_db_connection, save_interview_checkpoint
    from api.main import app

    db_path = str(engagements / "locked-down.db")
    async with interview_db_connection(db_path) as conn:
        await save_interview_checkpoint(
            conn, "tok-alpha", {"partial_answer": "the half sentence nothing else holds"}
        )

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        await client.post(
            "/api/interviews/tok-alpha/speech-failure",
            json={"reason": "socket_failed", "qa_pairs": _PAIRS},
        )

    row = _session_row(engagements, "locked-down", "tok-alpha")
    assert "the half sentence nothing else holds" in (row["checkpoint_json"] or "")


@pytest.mark.asyncio
async def test_the_kept_answers_reach_the_thing_that_writes_interview_answers_rows(
    engagements, no_network, monkeypatch
):
    """The transcript blob is not what the crews read - `interview_answers` is.

    A halt that stored the blob and never reached `record_answers` would leave the interview
    invisible to every agent downstream, which is the state this repair exists to end, and every
    assertion above would still pass. Asserted at the seam because these fixtures carry no script
    artefact for the resolver to find; `complete_session` reaches the identical helper, so the
    row-writing itself is the path the completion tests already cover.
    """
    from api.services import interview_service

    handed: list[list[dict]] = []

    async def capture(conn, slug, session_id, qa_pairs, *, script):
        handed.append(qa_pairs)

    async def a_script(conn, slug, session):
        return {"script_id": "SC-014", "sections": []}

    monkeypatch.setattr(interview_service, "record_answers", capture)
    monkeypatch.setattr(interview_service, "script_for_session", a_script)

    assert await interview_service.preserve_partial_interview("tok-alpha", _PAIRS) is True

    assert len(handed) == 1
    assert [p["answer"] for p in handed[0]] == [
        "Wayleaves, mostly.", "The programme board, quarterly.",
    ]


@pytest.mark.asyncio
async def test_a_completion_still_clears_the_checkpoint_and_says_completed(engagements, no_network):
    """The control for the two above. `/complete` is untouched, and must stay so.

    Without this, a change that made completion behave like a halt - `abandoned`, checkpoint
    left standing - would pass every assertion above while breaking every real interview.
    """
    from api.main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.patch(
            "/api/interviews/tok-alpha/complete", json={"qa_pairs": _PAIRS}
        )

    assert resp.status_code == 200
    row = _session_row(engagements, "locked-down", "tok-alpha")
    assert row["status"] == "completed"
    assert row["completed_at"]
    assert row["checkpoint_json"] is None


# ---------------------------------------------------------------------------
# Where the alert goes
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_the_alert_is_platform_mail_and_never_project_mail(engagements, monkeypatch):
    """`dev_mode` defaults to True, so project mail would silently redirect an outage alert.

    That is worse than no alert: the operator receives it and the administrator does not, and the
    absence reads as "no outage". Asserted on **which seam was called**, because both would
    return truthfully and a test on "a message was sent" cannot tell them apart. Governance mail
    is refused for a second reason - it signs as PAM and goes to the project's governors, who are
    not the people who renew a transcription contract.
    """
    from api.services import speech_policy as module
    import api.services.outbound_mail as outbound

    monkeypatch.setattr(get_settings(), "admin_alert_email", "ops@example.test", raising=False)

    platform: list[dict] = []

    async def fake_platform(*, to, subject, body):
        platform.append({"to": to, "subject": subject, "body": body})
        return True

    async def refuse_project(*args, **kwargs):
        raise AssertionError(
            "the alert went out as project mail, which dev_mode can hold - see this test's "
            "docstring"
        )

    monkeypatch.setattr(outbound, "send_platform_mail", fake_platform)
    monkeypatch.setattr(outbound, "send_project_mail", refuse_project)

    await module.alert_speech_unavailable(
        db_path=str(engagements / "locked-down.db"),
        slug="locked-down",
        session_token="tok-alpha",
        diagnosis="Deepgram reports this account has no credit (402)",
    )

    assert len(platform) == 1
    assert platform[0]["to"] == "ops@example.test"
    # The diagnosis reaches the person who can act on it, not just a "something failed".
    assert "no credit" in platform[0]["body"]
    assert "locked-down" in platform[0]["subject"]


@pytest.mark.asyncio
async def test_an_alert_that_cannot_be_sent_does_not_take_the_refusal_with_it(
    engagements, monkeypatch, caplog
):
    """A side effect must not veto the thing it is a side effect of.

    The participant has already been refused by the time this runs. An alert that raised would
    turn a handled refusal on a public door into a 500 - and the row, which is the leg the
    consultant reads, would never be written either.
    """
    import api.services.outbound_mail as outbound

    from api.services import speech_policy as module

    monkeypatch.setattr(get_settings(), "admin_alert_email", "ops@example.test", raising=False)

    async def explode(**kwargs):
        raise RuntimeError("the mail provider is down too")

    monkeypatch.setattr(outbound, "send_platform_mail", explode)

    await module.alert_speech_unavailable(
        db_path=str(engagements / "locked-down.db"),
        slug="locked-down",
        session_token="tok-alpha",
        diagnosis="Deepgram refused the API key this deployment holds (401)",
    )

    # No exception, and the leg that does not depend on mail still landed.
    recorded = _failure_on(engagements, "locked-down", "tok-alpha")
    assert recorded is not None
    assert "401" in recorded["diagnosis"]


@pytest.mark.asyncio
async def test_with_no_address_configured_the_row_still_carries_the_alert(
    engagements, monkeypatch
):
    """Blank `ADMIN_ALERT_EMAIL` is a deliberate absence, not a guess at `admin_username`.

    `admin_username` is a login and is routinely not an address; `dev_mode_address` is where
    *held* mail goes. Neither honestly means "the system administrator", so nothing is sent - and
    the two legs that do not need an address still work.
    """
    from api.services import speech_policy as module

    monkeypatch.setattr(get_settings(), "admin_alert_email", "", raising=False)

    await module.alert_speech_unavailable(
        db_path=str(engagements / "locked-down.db"),
        slug="locked-down",
        session_token="tok-alpha",
        diagnosis="Deepgram could not be reached from this server",
    )

    assert _failure_on(engagements, "locked-down", "tok-alpha") is not None


# ---------------------------------------------------------------------------
# The migration
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_a_database_at_version_21_gains_the_speech_failure_column(tmp_path, monkeypatch):
    """Pinned at 21 **as a literal**, which is the whole of what this proves.

    `_SCHEMA_VERSION - 1` is always the version below the constant and so passes under a constant
    that never moved; an older number passes too, because `get_connection` re-runs the whole
    block whenever `user_version` is lower. Only the literal immediately below the constant can
    tell "the migration works" from "the bump covers it", and CLAUDE.md records sp60 nearly
    shipping exactly that with twenty-two green tests over it.
    """
    from api.database import _SCHEMA_VERSION, get_connection

    monkeypatch.setenv("DATABASE_DIR", str(tmp_path / "db"))
    monkeypatch.setenv("PROJECTS_DIR", str(tmp_path / "projects"))
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    get_settings.cache_clear()
    try:
        db_dir = tmp_path / "db"
        db_dir.mkdir(parents=True, exist_ok=True)
        path = db_dir / "already-open.db"
        conn = sqlite3.connect(path)
        conn.executescript(
            """
            CREATE TABLE interview_sessions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_token TEXT UNIQUE,
                node_label TEXT
            );
            """
        )
        conn.execute("PRAGMA user_version = 21")
        conn.commit()
        conn.close()

        async with get_connection("already-open"):
            pass

        conn = sqlite3.connect(path)
        cols = {row[1] for row in conn.execute("PRAGMA table_info(interview_sessions)")}
        version = conn.execute("PRAGMA user_version").fetchone()[0]
        conn.close()

        assert "speech_failure" in cols
        assert version == _SCHEMA_VERSION
    finally:
        get_settings.cache_clear()


@pytest.mark.asyncio
async def test_a_fresh_database_has_the_column_without_the_migration_running(tmp_path, monkeypatch):
    """The other half of CLAUDE.md's rule for a new column: the CREATE TABLE carries it too.

    A column added only by `ALTER` exists on every upgraded deployment and on no new one, and the
    difference surfaces the first time somebody creates a project rather than at deployment.
    """
    from api.database import get_connection

    monkeypatch.setenv("DATABASE_DIR", str(tmp_path / "db"))
    monkeypatch.setenv("PROJECTS_DIR", str(tmp_path / "projects"))
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    get_settings.cache_clear()
    try:
        async with get_connection("brand-new"):
            pass
        conn = sqlite3.connect(tmp_path / "db" / "brand-new.db")
        create = conn.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='interview_sessions'"
        ).fetchone()[0]
        conn.close()
        assert "speech_failure" in create
    finally:
        get_settings.cache_clear()


# ---------------------------------------------------------------------------
# The declaration
# ---------------------------------------------------------------------------

def test_the_browser_speech_reach_is_declared_and_names_where_the_audio_goes():
    """Following `PARTICIPANT_SPEECH_EGRESS`, which is the row that made this one necessary.

    The sentence has to name **both vendors**, because an auditor reading "the browser's own
    recogniser" would not know that means Google for one participant and Apple for another - and
    "a row that names one shape reads as an assurance about all of them" is the rule this whole
    finding turns on.
    """
    from agents.egress import BROWSER_SPEECH_EGRESS, Reach

    assert BROWSER_SPEECH_EGRESS.reaches is Reach.BROWSER_SPEECH
    sends = BROWSER_SPEECH_EGRESS.sends.lower()
    assert "speech" in sends, "the audio is not named"
    assert "google" in sends and "apple" in sends, "the destinations are not named"
    # The half a reader would otherwise have to infer: nothing undertakes to discard this.
    assert "retain" in sends


def test_the_browser_speech_reach_is_the_one_participant_reach_a_grant_moves():
    """And it is asserted as a *difference*, not as two labels that happen to be worded apart.

    `PARTICIPANT_BROWSER` and `PARTICIPANT_TRANSCRIPTION` resolve to the same object in both
    columns because no grant stands between them and where they go - that sameness is their
    finding. This one is genuinely refused on an engagement without hosted inference, so
    `_is_gated` must derive `True` from the table rather than from a wording.
    """
    from agents.egress import ALL_GRANTS, NO_GRANTS, Reach, _destination, _is_gated

    granted = _destination(Reach.BROWSER_SPEECH, ALL_GRANTS)
    withheld = _destination(Reach.BROWSER_SPEECH, NO_GRANTS)

    assert granted is not withheld
    assert granted.leaves_deployment is True
    assert withheld.leaves_deployment is False
    assert _is_gated(Reach.BROWSER_SPEECH) is True

    # The two reaches beside it are unchanged, so this did not quietly regrade them.
    assert _is_gated(Reach.PARTICIPANT_TRANSCRIPTION) is False
    assert _is_gated(Reach.PARTICIPANT_BROWSER) is False


def test_the_new_reach_resolves_in_both_columns():
    """`test_every_reach_resolves_whether_or_not_its_grant_is_held` already walks every reach.

    Restated here against this reach by name so that the file introducing it fails on its own,
    rather than depending on a walk in another file noticing - the walk is the general guard and
    this is the specific one, and CLAUDE.md's note about a parametrisation that silently shrinks
    applies to any test keyed on an enumeration.
    """
    from agents.egress import _DESTINATION, Reach

    assert (Reach.BROWSER_SPEECH, True) in _DESTINATION
    assert (Reach.BROWSER_SPEECH, False) in _DESTINATION
