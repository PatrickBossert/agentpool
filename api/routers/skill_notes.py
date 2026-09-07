# api/routers/skill_notes.py
"""Agent skill notes — global learnings extracted from rejection feedback.

Hosted, always: these notes are global across engagements and this endpoint carries no slug,
so there is no llm_mode to route by. Recorded as a deliberate gap in CLAUDE.md's routing table
alongside api/services/skills_service.py, which is hosted for the same reason.
"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from anthropic import Anthropic
from api.auth import require_any_auth, require_sysadmin
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
    _payload: dict = Depends(require_sysadmin),
    conn=Depends(get_system_db),
):
    """Every stored note, with the feedback it was distilled from (sysadmin only).

    **Two columns, and only one of them is global.** `note` is the imperative the extraction
    produced - it is injected into that agent's prompt on every engagement by
    `_fetch_skill_notes`, which is what makes it the agent's published instruction rather than
    one client's material. `raw_input` is the reviewer's verbatim sentence, written from
    `ReviewDialog`, and it is free to name the engagement, its people, and what went wrong on
    it: *"Maya named the Q3 outage at Iberdrola in the welcome for SC-014"* is the shape it
    actually takes. `fetch_skill_notes` is a `SELECT *`, so this returned both to any login.

    The same finding as `list_skills`' pending queue, one table over, and closed the same way:
    whoever may act on it may read it. Nothing consumes this endpoint - `skillNotesApi.list`
    in `ui/src/api/endpoints.ts` has no caller - so the whole door is narrowed rather than the
    response projected. **If a non-admin surface is ever wanted, the split is `note` yes,
    `raw_input` no**, and it is written down here so it does not have to be rediscovered.

    `POST` stays `require_any_auth`, deliberately: leaving feedback about an agent's output is
    a reviewer's job, and writing your own sentence is not reading somebody else's.
    """
    return await fetch_skill_notes(conn, agent_name=agent_name)
