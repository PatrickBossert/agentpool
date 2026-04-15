# api/routers/ws.py
import asyncio
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from api.services.project_service import get_project_status

router = APIRouter(tags=["websocket"])

# In-memory log queues per slug. No eviction — acceptable for single-instance MVP.
_log_queues: dict[str, asyncio.Queue] = {}


def get_log_queue(slug: str) -> asyncio.Queue:
    if slug not in _log_queues:
        _log_queues[slug] = asyncio.Queue()
    return _log_queues[slug]


async def push_log(slug: str, message: str) -> None:
    """Called by agents to push a log line to connected WebSocket clients."""
    q = get_log_queue(slug)
    await q.put(message)


@router.websocket("/ws/{slug}")
async def websocket_log_stream(websocket: WebSocket, slug: str):
    await websocket.accept()
    status = await get_project_status(slug)
    if not status:
        await websocket.close(code=4004)
        return
    q = get_log_queue(slug)
    try:
        while True:
            try:
                msg = await asyncio.wait_for(q.get(), timeout=30.0)
                await websocket.send_text(msg)
            except asyncio.TimeoutError:
                await websocket.send_text("ping")
    except WebSocketDisconnect:
        pass
