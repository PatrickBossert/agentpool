"""The agent log stream, over real WebSocket connections.

`GET /ws/{slug}` accepted every handshake that reached it. No dependency, no token, not even
`require_any_auth` - so anyone who could reach the port streamed every agent log line for any
slug, and those lines carry client material verbatim. The cross-project case is the one that
matters and the one an "anonymous is refused" test would miss entirely: `admin_a` below is a
real, fully-privileged org_admin whose organisation owns project A, and it must be refused
project B's stream. That refusal is `check_project_access` and nothing else, exactly as in
tests/test_milestone_door_authority.py, whose fixtures this module follows.

Refusals are asserted on the close reason as well as the code, because three different gates
answer 1008 here and a caller refused by the wrong one tells you nothing:

  "Authentication required"       - no credential offered in Sec-WebSocket-Protocol
  "Invalid or expired token"      - decode_token
  "Access denied to this project" - check_project_access, the membership floor

Two of the properties below are not about authentication at all, and no authentication test
would have caught either:

  Two viewers on one slug both receive the same line. The old handler kept one queue per slug
  and did `await q.get()`, which removes the item - two tabs on one run each saw an arbitrary
  half of the log.

  A run nobody is watching buffers nothing. The old per-slug queue was created on first push,
  never evicted, unbounded, and drained by nobody while no viewer was attached, so the common
  case - a crew running for hours with no browser open - accumulated every line forever.

Driven through starlette's TestClient rather than by calling the handler, which is what makes
the subprotocol handshake real: the credential has to survive being written into a header and
parsed back out, and the accept has to echo a protocol name the client offered or a browser
drops the connection.
"""
import threading
import time
from datetime import datetime, timedelta, timezone

import pytest
from jose import jwt
from starlette.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

import api.routers.ws as ws_module
from api.auth import create_access_token
from api.config import get_settings
from api.database import (
    fetch_project,
    fetch_user,
    get_connection,
    get_system_connection,
    insert_organisation,
    insert_project_registry,
    insert_stakeholder,
    insert_user,
    link_membership,
)
from api.routers.ws import push_log

SLUG_A = "log-stream-alpha"
SLUG_B = "log-stream-beta"

SECRET = "test-secret"

NO_CREDENTIAL = "Authentication required"
BAD_TOKEN = "Invalid or expired token"
ACCESS_DENIED = "Access denied to this project"


def _project_body(slug: str) -> dict:
    return {
        "client_slug": slug,
        "llm_mode": "standard",
        "sector": "transport",
        "stakeholder_groups": [],
        "value_stream_labels": [],
        "crews_enabled": ["requirements"],
        "review_gates": True,
        "slack_channel": "",
    }


async def _seed_member(slug: str, *, username: str, **flags) -> None:
    """A login wired the whole way - users row, membership, stakeholder on this project."""
    async with get_connection(slug) as conn:
        project = await fetch_project(conn, slug=slug)
        stakeholder_id = await insert_stakeholder(
            conn, project_id=project["id"], name=username,
            email=f"{username}@example.com", **flags,
        )
    async with get_system_connection() as sys_conn:
        await insert_user(
            sys_conn, username=username, email=f"{username}@example.com",
            role="reviewer", hashed_pw="x",
        )
        user = await fetch_user(sys_conn, username=username)
        await link_membership(
            sys_conn, user_id=user["id"], project_slug=slug, stakeholder_id=stakeholder_id
        )


async def _seed_organisations() -> tuple[int, int]:
    async with get_system_connection() as sys_conn:
        org_a = await insert_organisation(sys_conn, slug="ws-org-alpha", name="Alpha")
        org_b = await insert_organisation(sys_conn, slug="ws-org-beta", name="Beta")
        await insert_project_registry(
            sys_conn, slug=SLUG_A, org_id=org_a, display_name=SLUG_A
        )
        await insert_project_registry(
            sys_conn, slug=SLUG_B, org_id=org_b, display_name=SLUG_B
        )
        await insert_user(
            sys_conn, username="ws-outsider", email="ws-outsider@example.com",
            role="reviewer", hashed_pw="x",
        )
        await sys_conn.commit()
    await _seed_member(SLUG_A, username="ws-member", is_participant=True)
    return org_a, org_b


class _Stream:
    """The TestClient plus the tokens the tests connect with."""

    def __init__(self, client: TestClient, org_a: int, org_b: int) -> None:
        self.client = client
        self.member = create_access_token("ws-member", "reviewer", SECRET)
        self.outsider = create_access_token("ws-outsider", "reviewer", SECRET)
        self.admin_a = create_access_token("ws-admin-a", "org_admin", SECRET, org_id=org_a)
        self.admin_b = create_access_token("ws-admin-b", "org_admin", SECRET, org_id=org_b)

    def watch(self, slug: str, token: str | None):
        """Open the stream, offering `bearer` and the token as subprotocols - the handshake a
        browser makes. `None` offers nothing at all, which is the unauthenticated caller."""
        subprotocols = ["bearer", token] if token is not None else None
        return self.client.websocket_connect(f"/ws/{slug}", subprotocols=subprotocols)

    def emit(self, slug: str, message: str) -> None:
        """Push a log line from inside the app's event loop, which is where a crew's step
        callback pushes from. `portal` is the loop every connection below also runs on."""
        self.client.portal.call(push_log, slug, message)


@pytest.fixture
def stream(tmp_path, monkeypatch):
    """Two projects owned by two different organisations, and four real logins.

    DATABASE_DIR and PROJECTS_DIR are redirected at this test's own tmp_path: the system
    database holding `users`, `project_memberships` and `project_registry` otherwise lives at
    the shared, persistent /tmp/agentpool_test, and these fixtures insert users by a fixed
    username - which passes once and fails on every run afterwards.

    TestClient is entered as a context manager deliberately. That is what gives it a single
    blocking portal, so every WebSocket session and every `emit` below runs on one event loop -
    without it each session would get a portal and a loop of its own, and two viewers could not
    share the fan-out they are here to prove.
    """
    monkeypatch.setenv("DATABASE_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("PROJECTS_DIR", str(tmp_path / "projects"))
    get_settings.cache_clear()

    from api.main import app

    # Module state, shared by every test in the process. Cleared on both sides so a viewer
    # left attached by a failing test cannot make the next one pass.
    ws_module._viewers.clear()

    sysadmin = {"Authorization": f"Bearer {create_access_token('admin', 'sysadmin', SECRET)}"}
    with TestClient(app) as client:
        for slug in (SLUG_A, SLUG_B):
            resp = client.post("/projects", json=_project_body(slug), headers=sysadmin)
            assert resp.status_code in (200, 201), resp.text
        org_a, org_b = client.portal.call(_seed_organisations)
        yield _Stream(client, org_a, org_b)

    ws_module._viewers.clear()
    get_settings.cache_clear()


def _receive_text(session, timeout: float = 5.0) -> str:
    """`session.receive_text()` with a deadline.

    WebSocketTestSession reads a plain `queue.Queue` and blocks for ever, so a regression in
    the fan-out would hang the suite instead of failing it - which is the difference between a
    red build and a build nobody can run. The reader is a daemon thread precisely because it
    may still be blocked when the test ends.
    """
    received: list = []

    def _read() -> None:
        try:
            received.append(session.receive_text())
        except BaseException as exc:  # noqa: BLE001 - re-raised on the calling thread
            received.append(exc)

    reader = threading.Thread(target=_read, daemon=True)
    reader.start()
    reader.join(timeout)
    if not received:
        pytest.fail(f"no line arrived within {timeout}s")
    if isinstance(received[0], BaseException):
        raise received[0]
    return received[0]


def _detached_within(slug: str, seconds: float) -> bool:
    """Whether the slug leaves `_viewers` inside the deadline.

    Detaching happens on the app's event loop, so the assertion has to be given a moment to
    become true rather than read once - polled, not slept through, so a passing case costs
    milliseconds and a failing one costs the deadline.
    """
    deadline = time.monotonic() + seconds
    while slug in ws_module._viewers and time.monotonic() < deadline:
        time.sleep(0.02)
    return slug not in ws_module._viewers


def _refusal(stream: _Stream, slug: str, token: str | None) -> tuple[int, str]:
    """The close code and reason of a handshake that was refused.

    A stream that was *not* refused is reported rather than raised, so a gate that stops
    refusing fails on the assertion instead of on an unrelated error.
    """
    try:
        with stream.watch(slug, token):
            return (0, "<accepted>")
    except WebSocketDisconnect as exc:
        return exc.code, exc.reason


# ── Controls ──────────────────────────────────────────────────────────────────
#
# Every refusal below is only worth reading if these hold. Without them a handler that
# refused everybody - or accepted everybody and sent nothing - would satisfy the module.

def test_a_member_of_this_engagement_receives_the_lines(stream):
    with stream.watch(SLUG_A, stream.member) as viewer:
        stream.emit(SLUG_A, "alex: started")
        assert _receive_text(viewer) == "alex: started"


def test_an_administrator_of_this_engagement_may_watch_it(stream):
    with stream.watch(SLUG_A, stream.admin_a) as viewer:
        stream.emit(SLUG_A, "maya: drafting")
        assert _receive_text(viewer) == "maya: drafting"


def test_the_accept_echoes_a_protocol_name_and_never_the_token(stream):
    """A browser drops a connection whose selected subprotocol was not one it offered, so
    echoing the token back would *work* - while writing a thirty-day credential into a
    response header, which is the leak the query string was rejected for. `bearer` was also
    offered, so both halves of this assertion are needed to tell the two apart."""
    with stream.watch(SLUG_A, stream.member) as viewer:
        assert viewer.accepted_subprotocol == "bearer"
        assert viewer.accepted_subprotocol != stream.member


# ── No credential, and a bad one ──────────────────────────────────────────────

def test_a_handshake_offering_no_credential_is_refused(stream):
    assert _refusal(stream, SLUG_A, None) == (1008, NO_CREDENTIAL)


def test_offering_bearer_without_a_token_is_refused(stream):
    """`['bearer']` alone is a well-formed offer carrying nothing. It must not read as
    "authenticated with an empty token"."""
    with pytest.raises(WebSocketDisconnect) as exc:
        with stream.client.websocket_connect(f"/ws/{SLUG_A}", subprotocols=["bearer"]):
            pass
    assert (exc.value.code, exc.value.reason) == (1008, NO_CREDENTIAL)


def test_a_malformed_token_is_refused(stream):
    assert _refusal(stream, SLUG_A, "not-a-jwt") == (1008, BAD_TOKEN)


def test_an_expired_token_is_refused(stream):
    """A real signature over real claims, aged out. Signed with the deployment's own secret,
    so the only thing wrong with it is the `exp` - which is what makes this a test of expiry
    rather than a second test of a bad signature."""
    stale = datetime.now(timezone.utc) - timedelta(days=1)
    expired = jwt.encode(
        {"sub": "ws-member", "role": "reviewer", "exp": stale, "iat": stale - timedelta(days=31)},
        SECRET,
        algorithm="HS256",
    )
    assert _refusal(stream, SLUG_A, expired) == (1008, BAD_TOKEN)


def test_a_token_signed_with_another_secret_is_refused(stream):
    forged = create_access_token("ws-member", "reviewer", "some-other-secret")
    assert _refusal(stream, SLUG_A, forged) == (1008, BAD_TOKEN)


# ── The membership floor, and the cross-project hole ──────────────────────────

def test_a_caller_with_no_membership_anywhere_cannot_watch(stream):
    assert _refusal(stream, SLUG_A, stream.outsider) == (1008, ACCESS_DENIED)


def test_an_administrator_of_another_engagement_cannot_watch_this_one(stream):
    """The point of the whole module.

    `admin_a` holds a legitimate, fully-privileged org_admin session - it clears every
    login-role check in the API on its role alone, and it watches project A perfectly well two
    tests above. It is refused project B for one reason: `check_project_access`. Remove that
    call and this becomes a success while every other test here still passes, which is exactly
    the state the door was in before this branch.
    """
    assert _refusal(stream, SLUG_B, stream.admin_a) == (1008, ACCESS_DENIED)
    # And the mirror, so the refusal is scoping rather than something peculiar to project B.
    assert _refusal(stream, SLUG_A, stream.admin_b) == (1008, ACCESS_DENIED)


def test_a_refused_caller_is_attached_to_nothing(stream):
    """A close code says the handshake was refused; it does not say no viewer was registered.

    If the refusal happened after `_attach`, a rejected caller would still hold a queue that
    every subsequent `push_log` wrote client material into - refused at the door and served
    through the window.
    """
    for token in (None, "not-a-jwt", stream.outsider, stream.admin_b):
        _refusal(stream, SLUG_A, token)
    stream.emit(SLUG_A, "alex: confidential")
    assert ws_module._viewers == {}


# ── The broadcast ─────────────────────────────────────────────────────────────

def test_two_viewers_on_one_slug_both_receive_the_same_line(stream):
    """Defect 2, and no authentication test would notice it. The handler used to share one
    queue per slug and `get` it, so this line reached exactly one of these two viewers -
    whichever the event loop woke first - and the other tab silently missed it."""
    with stream.watch(SLUG_A, stream.member) as first, stream.watch(SLUG_A, stream.admin_a) as second:
        stream.emit(SLUG_A, "alex: tool_use ChromaQuery")
        assert _receive_text(first) == "alex: tool_use ChromaQuery"
        assert _receive_text(second) == "alex: tool_use ChromaQuery"


def test_a_viewer_of_one_engagement_never_sees_another(stream):
    """The fan-out must not have become a fan-out to everybody. A line pushed on project B
    reaches nobody watching project A, so the next line A's viewer sees is A's own."""
    with stream.watch(SLUG_A, stream.member) as viewer:
        stream.emit(SLUG_B, "beta: confidential")
        stream.emit(SLUG_A, "alpha: ordinary")
        assert _receive_text(viewer) == "alpha: ordinary"


# ── An unwatched run costs nothing ────────────────────────────────────────────

def test_a_run_nobody_is_watching_buffers_nothing(stream):
    """Defect 3, asserted where the lines would have to live if it were still there.

    `_viewers` is the only structure in the module that holds a message, so an empty one after
    a thousand pushes is the whole property. The old `get_log_queue` created a queue on the
    first push for any slug, kept every line in it, and never evicted the slug.
    """
    for i in range(1000):
        stream.emit(SLUG_A, f"alex: step {i}")

    assert ws_module._viewers == {}, "an unwatched run is holding log lines in memory"


def test_a_viewer_that_has_gone_leaves_nothing_behind(stream):
    """The same property one step on: the run *was* watched, and the tab was closed.

    `_attach`'s `finally` is what this holds: however the handler ends - the disconnect read,
    a send failing on a departed connection, or the task being cancelled - the queue is
    discarded and the slug leaves `_viewers` with it. Remove that detach and the run below
    goes on buffering five hundred lines into a queue nobody will ever read.
    """
    with stream.watch(SLUG_A, stream.member) as viewer:
        stream.emit(SLUG_A, "alex: started")
        assert _receive_text(viewer) == "alex: started"
        assert SLUG_A in ws_module._viewers, "precondition: the viewer really was attached"

    for i in range(500):
        stream.emit(SLUG_A, f"alex: step {i}")

    assert _detached_within(SLUG_A, 5.0), (
        "a departed viewer is still attached and still buffering"
    )


def test_a_closed_tab_detaches_at_once_rather_than_at_the_next_keepalive(stream):
    """`_wait_for_disconnect`, isolated - and isolating it takes some care.

    `_forward_lines` is the *other* way this handler notices a departure: under uvicorn a send
    on a connection whose client has gone raises, so the next keepalive would end the stream
    on its own within PING_INTERVAL_SECONDS. Any test that pushes a line, or waits a ping
    interval, or simply leaves the `with` block - which cancels the app task outright - is
    therefore satisfied by a handler carrying no watcher at all. The test above is one of
    those, and for a while this module claimed it covered the watcher when it covered the
    detach.

    So: nothing pushed, nothing waited out, and the session deliberately not exited.
    `viewer.close()` puts a `websocket.disconnect` on the handler's receive queue and returns.
    Inside the next few seconds the only thing that can detach this viewer is a handler that
    is reading for it.
    """
    with stream.watch(SLUG_A, stream.member) as viewer:
        assert SLUG_A in ws_module._viewers, "precondition: the viewer really was attached"

        viewer.close(1000)

        assert _detached_within(SLUG_A, 3.0), (
            "the closed tab is still attached - the handler is not reading for the "
            "disconnect, and will not notice until a keepalive fails up to "
            f"{ws_module.PING_INTERVAL_SECONDS}s from now"
        )


def test_the_server_sends_a_keepalive_while_a_run_is_quiet(stream, monkeypatch):
    """The keepalive, which is load-bearing twice over and was asserted nowhere.

    ui/src/__tests__/useWebSocket.test.tsx proves the hook *discards* a line reading `ping`;
    nothing proved anything ever sends one, so a stream that had quietly stopped sending them
    would have satisfied both suites. It is the backstop that ends the stream for a viewer
    whose disconnect never arrives, and it is what stops a proxy timing an idle socket out
    during the long quiet stretch while an agent thinks.

    The interval is patched down rather than waited out: `_forward_lines` reads
    PING_INTERVAL_SECONDS on every pass, so the value at connect time is the one that binds.
    """
    monkeypatch.setattr(ws_module, "PING_INTERVAL_SECONDS", 0.05)

    with stream.watch(SLUG_A, stream.member) as viewer:
        assert _receive_text(viewer) == "ping"


@pytest.mark.asyncio
async def test_a_viewer_that_stops_reading_cannot_grow_without_bound():
    """The bound itself, on the one path that can still accumulate: a viewer that is attached
    but has stopped draining - a laptop asleep with the run panel open, while a crew talks for
    hours. Asserted against `push_log` and `_attach`, which are the production writer and the
    production subscriber; there is no third thing between them to test instead.
    """
    ws_module._viewers.clear()
    slug = "log-stream-backlog"
    overflow = ws_module.MAX_BUFFERED_LINES * 3

    with ws_module._attach(slug) as queue:
        for i in range(overflow):
            await push_log(slug, f"line {i}")

        assert queue.qsize() == ws_module.MAX_BUFFERED_LINES
        # And what survived is the live tail, not the first few hundred lines of history: a
        # bound that dropped the newest line would keep the buffer small and the panel stuck.
        assert queue.get_nowait() == f"line {overflow - ws_module.MAX_BUFFERED_LINES}"

    assert ws_module._viewers == {}
