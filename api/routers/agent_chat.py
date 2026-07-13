# api/routers/agent_chat.py
"""POST /projects/{slug}/agent-chat — interactive agent chat endpoint."""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from api.auth import require_any_auth, check_project_access
from api.services.agent_chat_service import run_agent_chat, AGENT_PERSONAS

router = APIRouter(prefix="/projects", tags=["agent-chat"])


class ChatRequest(BaseModel):
    agent_name: str
    message: str
    history: list[dict] = []


@router.post("/{slug}/agent-chat")
async def agent_chat(
    slug: str,
    body: ChatRequest,
    payload: dict = Depends(require_any_auth),
):
    await check_project_access(slug, payload)

    if body.agent_name not in AGENT_PERSONAS:
        raise HTTPException(status_code=404, detail=f"Unknown agent: {body.agent_name!r}")

    result = await run_agent_chat(slug, body.agent_name, body.message, body.history)
    if result is None:
        raise HTTPException(status_code=404, detail=f"Project '{slug}' not found")

    return {"response": result}
