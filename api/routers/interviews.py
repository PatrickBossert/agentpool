# api/routers/interviews.py
"""Public interview endpoints — no auth required.

Session tokens (UUID4) serve as the access credential.
"""
from __future__ import annotations

import aiosqlite
from fastapi import APIRouter, HTTPException, Response
from pydantic import BaseModel

from api.database import update_interview_session_status
from api.services.interview_service import (
    _find_session_db,
    complete_session,
    elaboration_press,
    generate_deepgram_token,
    get_session_with_script,
    speak,
)

router = APIRouter(prefix="/api/interviews", tags=["interviews"])


# ---------------------------------------------------------------------------
# Endpoint 1: GET /{session_token}
# ---------------------------------------------------------------------------

@router.get("/{session_token}")
async def get_interview_session(session_token: str):
    result = await get_session_with_script(session_token)
    if not result:
        raise HTTPException(status_code=404, detail="Session not found")
    return result


# ---------------------------------------------------------------------------
# Endpoint 2: GET /{session_token}/deepgram-token
# ---------------------------------------------------------------------------

@router.get("/{session_token}/deepgram-token")
async def get_deepgram_token(session_token: str):
    result = await get_session_with_script(session_token)
    if not result:
        raise HTTPException(status_code=404, detail="Session not found")
    try:
        token = await generate_deepgram_token()
        return {"token": token}
    except ValueError as e:
        raise HTTPException(status_code=503, detail=str(e))


# ---------------------------------------------------------------------------
# Endpoint 3: POST /{session_token}/speak
# ---------------------------------------------------------------------------

class SpeakRequest(BaseModel):
    text: str
    voice_id: str


@router.post("/{session_token}/speak")
async def speak_text(session_token: str, body: SpeakRequest):
    result = await get_session_with_script(session_token)
    if not result:
        raise HTTPException(status_code=404, detail="Session not found")
    try:
        audio_bytes = await speak(body.text, body.voice_id)
        return Response(content=audio_bytes, media_type="audio/mpeg")
    except ValueError as e:
        raise HTTPException(status_code=503, detail=str(e))


# ---------------------------------------------------------------------------
# Endpoint 4: POST /{session_token}/elaboration-press
# ---------------------------------------------------------------------------

class ElaborationPressRequest(BaseModel):
    question_text: str
    response_text: str
    probing_instructions: str
    stakeholder_name: str = ""


@router.post("/{session_token}/elaboration-press")
async def get_elaboration_press(session_token: str, body: ElaborationPressRequest):
    result = await get_session_with_script(session_token)
    if not result:
        raise HTTPException(status_code=404, detail="Session not found")
    try:
        press_text = await elaboration_press(
            body.question_text,
            body.response_text,
            body.probing_instructions,
            body.stakeholder_name,
        )
    except ValueError as e:
        raise HTTPException(status_code=503, detail=str(e))
    return {"press_text": press_text}


# ---------------------------------------------------------------------------
# Endpoint 5: PATCH /{session_token}/status
# ---------------------------------------------------------------------------

class StatusUpdateRequest(BaseModel):
    status: str


@router.patch("/{session_token}/status")
async def update_session_status(session_token: str, body: StatusUpdateRequest):
    db_path = await _find_session_db(session_token)
    if not db_path:
        raise HTTPException(status_code=404, detail="Session not found")
    async with aiosqlite.connect(db_path) as conn:
        await update_interview_session_status(conn, session_token, body.status)
    return {"ok": True}


# ---------------------------------------------------------------------------
# Endpoint 6: PATCH /{session_token}/complete
# ---------------------------------------------------------------------------

class CompleteRequest(BaseModel):
    qa_pairs: list[dict]


@router.patch("/{session_token}/complete")
async def complete_interview(session_token: str, body: CompleteRequest):
    success = await complete_session(session_token, body.qa_pairs)
    if not success:
        raise HTTPException(status_code=404, detail="Session not found")
    return {"ok": True}
