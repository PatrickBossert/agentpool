# api/routers/ws.py
"""The agent log stream.

Three properties this module has to hold, none of which it used to:

**It is authorised.** The handler used to `accept()` as its first statement, with no
dependency and no token, so anyone who could reach the port streamed every agent log line
for any slug - and agent logs carry client material verbatim. Secure mode exists on this
project so a sensitive engagement does not leave the building; an open log socket made that
guarantee decorative. `get_project_status(slug)` was the only check here and it is an
existence check, not an authorisation one.

The credential arrives in `Sec-WebSocket-Protocol`, as two offered protocol names - the
literal `bearer` followed by the JWT. A browser cannot set an `Authorization` header on a
handshake, which is why this was left open in the first place, and the obvious alternative
(`?token=`) is worse than the hole: sessions here roll for thirty days, and a URL lands in
proxy logs, browser history, and referrers. A header does not. Starlette exposes
`websocket.headers` *before* `accept()`, so a refusal never accepts the connection at all -
an unauthenticated caller cannot hold a socket open.

**It is a broadcast, not a work queue.** There used to be one `asyncio.Queue` per slug and
the handler did `await q.get()`, which *removes* the item. Two tabs open on one run each saw
an arbitrary half of the log. Every attached viewer now holds a queue of its own and
`push_log` fans out to all of them.

**An unwatched run costs nothing.** The old per-slug queue was created by `get_log_queue` for
any slug ever asked about, was never evicted, and was unbounded with nothing draining it while
nobody watched - so the common case (a crew running for hours with no browser attached)
accumulated every line it ever emitted, forever. A slug appears in `_viewers` only while
somebody is attached to it and the key is deleted when the last viewer leaves, so `push_log`
on an unwatched run iterates an empty tuple and drops the line. Dropping is the correct
behaviour, not a compromise: this is a live tail, and there is nobody to tail it to.
"""
import asyncio
import contextlib
from collections.abc import Iterator

from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect

from api.auth import check_project_access, decode_token
from api.config import get_settings
from api.services.project_service import get_project_status

router = APIRouter(tags=["websocket"])

# The protocol name the client offers ahead of its token, and the one echoed back on accept.
# What is echoed must be a *name* the client offered and never the token: the browser drops a
# connection whose selected subprotocol was not on offer, so echoing the token would appear to
# work - while writing the credential into a response header, which is the class of leak the
# query string was rejected for.
_BEARER = "bearer"

# Lines a single viewer may fall behind by. Reached only by a browser that has stopped reading
# while a crew keeps talking; past it the oldest line is dropped so the viewer keeps seeing the
# live tail rather than an ever-growing backlog of history it will never catch up on.
MAX_BUFFERED_LINES = 500

# Seconds of silence before a keepalive. The client discards these (see useWebSocket.ts).
PING_INTERVAL_SECONDS = 30.0

# One queue per attached viewer, grouped by slug. A slug is present here only while at least
# one viewer is attached - see the module docstring for why that, rather than eviction, is
# what keeps an unwatched run free.
_viewers: dict[str, set[asyncio.Queue[str]]] = {}


@contextlib.contextmanager
def _attach(slug: str) -> Iterator[asyncio.Queue[str]]:
    """Register a viewer's own queue for the life of the block, and detach on the way out."""
    queue: asyncio.Queue[str] = asyncio.Queue(maxsize=MAX_BUFFERED_LINES)
    _viewers.setdefault(slug, set()).add(queue)
    try:
        yield queue
    finally:
        attached = _viewers.get(slug)
        if attached is not None:
            attached.discard(queue)
            if not attached:
                del _viewers[slug]


async def push_log(slug: str, message: str) -> None:
    """Called by agents to push a log line to every viewer attached to this slug.

    A copy of the set is iterated because a viewer may detach while this runs.
    """
    for queue in list(_viewers.get(slug, ())):
        try:
            queue.put_nowait(message)
        except asyncio.QueueFull:
            with contextlib.suppress(asyncio.QueueEmpty):
                queue.get_nowait()
            with contextlib.suppress(asyncio.QueueFull):
                queue.put_nowait(message)


def _offered_token(websocket: WebSocket) -> str | None:
    """The token from `Sec-WebSocket-Protocol: bearer, <jwt>`, or None if it is not there.

    Every value of the header is joined, since a client may split its offer across repeated
    headers, and exactly two names are required - `bearer` alone carries no credential.
    """
    raw = ",".join(websocket.headers.getlist("sec-websocket-protocol"))
    offered = [name.strip() for name in raw.split(",") if name.strip()]
    if len(offered) != 2 or offered[0].lower() != _BEARER:
        return None
    return offered[1]


async def _forward_lines(websocket: WebSocket, queue: asyncio.Queue[str]) -> None:
    while True:
        try:
            line = await asyncio.wait_for(queue.get(), timeout=PING_INTERVAL_SECONDS)
        except asyncio.TimeoutError:
            line = "ping"
        await websocket.send_text(line)


async def _wait_for_disconnect(websocket: WebSocket) -> None:
    """Read until the browser goes away.

    A viewer never sends anything, so this exists only to notice the departure. An ASGI app
    learns of a disconnect by receiving it and by no other means - without this the handler
    would sit in its send loop after the tab closed, holding its queue attached and its slug
    in `_viewers`, which is the leak this module is meant to have stopped.
    """
    with contextlib.suppress(WebSocketDisconnect):
        while True:
            message = await websocket.receive()
            if message["type"] == "websocket.disconnect":
                return


@router.websocket("/ws/{slug}")
async def websocket_log_stream(websocket: WebSocket, slug: str):
    token = _offered_token(websocket)
    if token is None:
        await websocket.close(code=1008, reason="Authentication required")
        return
    try:
        payload = decode_token(token, get_settings().jwt_secret)
        # The membership floor, the same one every other project-scoped door carries. A log
        # stream is a project-scoped read, so the floor and no content gate.
        await check_project_access(slug, payload)
    except HTTPException as exc:
        await websocket.close(code=1008, reason=str(exc.detail))
        return

    if not await get_project_status(slug):
        await websocket.close(code=4004, reason="No such project")
        return

    # Attached before accepting, not after. The client is unblocked by the accept, so a line
    # pushed the instant it returns would fall into the gap between the two and be lost - a
    # crew emits its first step within milliseconds of a viewer opening the panel.
    with _attach(slug) as queue:
        await websocket.accept(subprotocol=_BEARER)
        forwarder = asyncio.create_task(_forward_lines(websocket, queue))
        watcher = asyncio.create_task(_wait_for_disconnect(websocket))
        try:
            # Either half finishing ends the stream: the watcher when the browser leaves, the
            # forwarder if a send fails on a connection that has already gone.
            await asyncio.wait({forwarder, watcher}, return_when=asyncio.FIRST_COMPLETED)
        finally:
            for task in (forwarder, watcher):
                task.cancel()
            await asyncio.gather(forwarder, watcher, return_exceptions=True)
