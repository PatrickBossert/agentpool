# api/routers/skill_notes.py
"""Agent skill notes — global learnings extracted from rejection feedback."""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from anthropic import Anthropic
from api.auth import require_any_auth
from api.database import get_system_db, insert_skill_note, fetch_skill_notes
from api.config import get_settings

router = APIRouter(prefix="/agent-skill-notes", tags=["skill-notes"])

_EXTRACT_SYSTEM = (
    "You extract concise, actionable skill improvement notes from rejection feedback. "
    "Write in second person using imperative language ('Must...', 'Should...', 'Avoid...'). "
    "Focus only on what the agent should do differently in future — not on why it was wrong. "
    "Output 1–3 sentences maximum. No preamble."
)


class SkillNoteCreate(BaseModel):
    agent_name: str    # snake_case agent key, e.g. 'value_chain_mapper'
    raw_input: str     # free-text feedback from the human reviewer


@router.post("", status_code=201)
async def create_skill_note(
    req: SkillNoteCreate,
    payload: dict = Depends(require_any_auth),
    conn=Depends(get_system_db),
):
    if not req.raw_input.strip():
        raise HTTPException(status_code=422, detail="raw_input is required")

    settings = get_settings()
    client = Anthropic(api_key=settings.anthropic_api_key)
    msg = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=256,
        system=_EXTRACT_SYSTEM,
        messages=[{"role": "user", "content": req.raw_input}],
    )
    note = msg.content[0].text.strip()

    note_id = await insert_skill_note(conn, agent_name=req.agent_name, note=note, raw_input=req.raw_input)
    return {"id": note_id, "agent_name": req.agent_name, "note": note}


@router.get("")
async def list_skill_notes(
    agent_name: str | None = None,
    payload: dict = Depends(require_any_auth),
    conn=Depends(get_system_db),
):
    return await fetch_skill_notes(conn, agent_name=agent_name)
