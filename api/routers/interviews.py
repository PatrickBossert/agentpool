# api/routers/interviews.py
"""Public interview endpoints — no auth required.

Session tokens (UUID4) serve as the access credential.
"""
from __future__ import annotations

import aiosqlite
from fastapi import APIRouter, HTTPException, Response
from pydantic import BaseModel

from api.config import get_settings
from api.database import (
    fetch_interview_sessions_for_run,
    get_connection,
    update_interview_session_status,
)
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
# Endpoint 7: GET /sessions/{slug}  — declared FIRST to avoid catch-all clash
# ---------------------------------------------------------------------------

_EMPTY_SUMMARY = {"pending": 0, "active": 0, "completed": 0, "abandoned": 0}


@router.get("/sessions/{slug}")
async def get_sessions_for_project(slug: str):
    """Return all interview sessions for the latest orchestration run of a project."""
    async with get_connection(slug) as conn:
        # 1. Look up project by slug
        async with conn.execute(
            "SELECT id FROM projects WHERE slug=?", (slug,)
        ) as cur:
            project_row = await cur.fetchone()
        if not project_row:
            raise HTTPException(status_code=404, detail="Project not found")

        # 2. Find latest orchestration run
        async with conn.execute(
            "SELECT id FROM orchestration_runs WHERE project_id=? ORDER BY started_at DESC LIMIT 1",
            (project_row["id"],),
        ) as cur:
            run_row = await cur.fetchone()

        if not run_row:
            return {
                "orchestration_run_id": None,
                "sessions": [],
                "summary": {**_EMPTY_SUMMARY},
            }

        orchestration_run_id = run_row["id"]

        # 3. Fetch sessions
        rows = await fetch_interview_sessions_for_run(conn, orchestration_run_id)

    # 4. Build response
    frontend_url = get_settings().frontend_url
    summary = {**_EMPTY_SUMMARY}
    sessions = []
    for row in rows:
        status = row["status"]
        if status in summary:
            summary[status] += 1
        sessions.append({
            "id": row["id"],
            "stakeholder_id": row["stakeholder_id"],
            "name": row["name"],
            "node_label": row["node_label"],
            "session_token": row["session_token"],
            "status": status,
            "interview_url": f"{frontend_url}/interview/{row['session_token']}",
            "started_at": row["started_at"],
            "completed_at": row["completed_at"],
            "created_at": row["created_at"],
        })

    return {
        "orchestration_run_id": orchestration_run_id,
        "sessions": sessions,
        "summary": summary,
    }


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

