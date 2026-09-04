# api/routers/interviews.py
"""Public interview endpoints - no auth required, with one exception.

Session tokens (UUID4) serve as the access credential for the interview flow itself.
GET /sessions/{slug}, however, lists every session_token for a project - the sole
credential the rest of this API relies on - so it requires an authenticated caller
(require_any_auth) rather than trusting the slug alone.
"""
from __future__ import annotations

import json
import re
import time
from collections import defaultdict

from fastapi import APIRouter, Depends, HTTPException, Response
from pathlib import Path
from pydantic import BaseModel, Field

from agents.identity import DEFAULT_TTS_MODEL_ID
from api.auth import check_project_access, require_any_auth
from api.services.agent_config_service import UnknownAgent, resolve_agent_config
from api.config import get_settings
from api.database import (
    fetch_interview_sessions_for_run,
    get_connection,
    interview_db_connection,
    save_interview_checkpoint,
    update_interview_session_status,
)
from api.services.interview_service import (
    _find_session_db,
    complete_session,
    elaboration_press,
    generate_deepgram_token,
    get_session_with_script,
    interview_url,
    speak,
)
from api.services.outbound_mail import STAKEHOLDERS, send_project_mail
from api.services.process_cache import register_cache

router = APIRouter(prefix="/api/interviews", tags=["interviews"])


# ---------------------------------------------------------------------------
# Endpoint 7: GET /sessions/{slug}  — declared FIRST to avoid catch-all clash
# ---------------------------------------------------------------------------

_EMPTY_SUMMARY = {"pending": 0, "active": 0, "completed": 0, "abandoned": 0}


@router.get("/sessions/{slug}")
async def get_sessions_for_project(slug: str, payload: dict = Depends(require_any_auth)):
    """Return all interview sessions for the latest orchestration run of a project.

    Requires auth: this is the one endpoint in an otherwise-public router that returns
    session_token values, and a token is the only credential the rest of the interview
    API checks.

    Which is why `require_any_auth` alone was never enough. It asks whether the caller has
    a login, not which engagement that login is on, so any valid token could read every
    interview credential for any slug - and then walk in through the public half of this
    router as the interviewee. `check_project_access` is the membership floor and answers
    the question that was missing.

    It also runs before `get_connection`, which creates a project database on first touch:
    without it, a caller guessing slugs materialised a database file per guess. That is
    the same side effect the `get_db_path(...).exists()` guard closes in `caller_roles`.
    """
    await check_project_access(slug, payload)
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
            "interview_url": interview_url(row["session_token"]),
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
# Test interview endpoints (JWT auth — no session required)
# ---------------------------------------------------------------------------

@router.get("/test/script")
async def get_test_interview_script(payload: dict = Depends(require_any_auth)):
    """Return the smoke-test interview script for the built-in test interview."""
    scripts_path = (
        Path(get_settings().projects_dir) / "smoke-test" / "outputs" / "interview_scripts.json"
    )
    if not scripts_path.exists():
        raise HTTPException(
            status_code=404,
            detail="Smoke-test script not found — run discovery_mapping on the smoke-test project first.",
        )
    try:
        data = json.loads(scripts_path.read_text())
        first_key = next(iter(data))
        return data[first_key]
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


class TestSpeakRequest(BaseModel):
    text: str
    # Required, min_length=1, and exactly the rule the sibling elaboration-press door already
    # carries. The rehearsal dialog is opened from a real project's setup tab and holds the
    # slug in its props, so there is no honest caller without one - and `resolve_agent_config`
    # refuses a blank slug rather than quietly answering the defaults for it.
    slug: str = Field(min_length=1)
    # The permanent snake key, never a display name. It defaults to the interviewer because
    # that is whose rehearsal button exists today; Laura's setup tab passes her own id rather
    # than needing a second door.
    agent_id: str = "stakeholder_interviewer"

    # There is deliberately **no `voice_id`**. It had one, with a default corrected from
    # ElevenLabs' stock Rachel to Avery's - and the correction reached nobody, because the only
    # caller passed `voice_id` explicitly from a *second* constant also called `AVERY_VOICE_ID`
    # (`TestInterviewDialog.tsx`), holding George. Avery rehearsed as one man and interviewed
    # as another, under one variable name, and every gate was green. A field the client fills
    # is a field the client decides; the voice is the project's, so the server resolves it.


@router.post("/test/speak")
async def test_speak_text(body: TestSpeakRequest, payload: dict = Depends(require_any_auth)):
    """TTS for the built-in test interview — no session token required.

    The voice and the synthesis model are resolved from the project through
    `resolve_agent_config`, so a consultant rehearsing an agent hears what that agent is
    configured to sound like.

    **This is currently the only production caller of `resolve_agent_config`**, and saying so
    matters more than it looks: configuring a voice changes what this door speaks in and
    nothing else. The live interview portal does *not* resolve through here - it reads
    `session.voice_config` and falls back to its own constant - and nothing stamps that column
    yet, so a crew-created session still carries whatever Taylor's `VOICE_LOCALE_TABLE` gave
    it. Two things close that loop and neither is this door: Task 3 stamps the resolved
    configuration onto the session at creation, and Task 4 retires the prompt table so Taylor
    resolves through here too. An earlier version of this docstring claimed the portal and the
    stamp already used this function, which would have told the next reader the chain was
    joined up when it is not.

    `check_project_access` is the **first** line, before the slug reaches a database. This door
    took a slug in its body only recently; before that there was nothing to scope, and adding
    the slug added the exposure - an org_admin of an unrelated organisation could name any slug
    and hear its configured voice, while the sibling door twelve lines below refused them. A
    refusal raised after the project's database has been opened and its configuration read is
    not a refusal.

    It is also the second door on this codebase that takes its slug from the **body** rather
    than the path, which CLAUDE.md records as invisible to the route sweep - the sweep counts
    routes whose *path* holds `{slug}`. Enumerating by path would not find this one.
    """
    await check_project_access(body.slug, payload)
    try:
        config = await resolve_agent_config(body.slug, body.agent_id)
    except UnknownAgent:
        raise HTTPException(status_code=404, detail=f"Unknown agent: {body.agent_id}")
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    if not config["voice_id"]:
        raise HTTPException(
            status_code=422, detail=f"{body.agent_id} has no voice configured"
        )
    try:
        audio_bytes = await speak(body.text, config["voice_id"], config["model_id"])
        return Response(content=audio_bytes, media_type="audio/mpeg")
    except ValueError as exc:
        raise HTTPException(status_code=503, detail=str(exc))


class TestElaborationRequest(BaseModel):
    question_text: str
    response_text: str
    probing_instructions: str
    # Required, and min_length=1 so a blank one is a 422 rather than a default. The dialog is
    # opened from a real project's Avery setup tab and the consultant types real answers into
    # it; without the slug there is no llm_mode, and no llm_mode resolves to standard - which
    # sent a sensitive engagement's answers to a hosted model.
    slug: str = Field(min_length=1)


@router.post("/test/elaboration-press")
async def test_elaboration_press(
    body: TestElaborationRequest, payload: dict = Depends(require_any_auth)
):
    """Elaboration press for the built-in test interview — no session token required.

    The script is the smoke-test project's, but the routing is the caller's project's: what
    needs protecting here is the answer the consultant types, not the question they are asked.
    """
    await check_project_access(body.slug, payload)
    try:
        press_text = await elaboration_press(
            body.question_text,
            body.response_text,
            body.probing_instructions,
            "test interviewee",
            slug=body.slug,
        )
    except ValueError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    return {"press_text": press_text}


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
    """TTS for a live interview, in the voice the session was issued with.

    The model is `DEFAULT_TTS_MODEL_ID` and not yet the project's, deliberately: this door has
    a session token rather than a slug, and the session is where the answer belongs. Stamping
    the resolved configuration onto `interview_sessions` at creation is Task 3's, and the model
    is stamped beside the voice when it lands - the same argument the design gives for the
    voice itself, that an address re-derived at read time can move underneath the thing it
    points at. Naming the constant rather than repeating its literal is what keeps this a
    reference to the one place model defaults live rather than a sixth declaration.
    """
    result = await get_session_with_script(session_token)
    if not result:
        raise HTTPException(status_code=404, detail="Session not found")
    try:
        audio_bytes = await speak(body.text, body.voice_id, DEFAULT_TTS_MODEL_ID)
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
    db_path = await _find_session_db(session_token)
    if not db_path:
        raise HTTPException(status_code=404, detail="Session not found")
    # The slug is the stem of the project db file that holds this session - the same
    # resolution get_session_with_script uses internally, done directly here because the
    # budget and the routing decision both need the slug before elaboration_press is called.
    slug = Path(db_path).stem
    async with get_connection(slug) as conn:
        cur = await conn.execute("SELECT config_json FROM projects WHERE slug=?", (slug,))
        row = await cur.fetchone()
    config = json.loads(row["config_json"]) if row and row["config_json"] else {}
    budget = float(config.get("elaboration_press_timeout_seconds", 8))

    try:
        press_text = await elaboration_press(
            body.question_text,
            body.response_text,
            body.probing_instructions,
            body.stakeholder_name,
            slug=slug,
            timeout_seconds=budget,
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
    async with interview_db_connection(db_path) as conn:
        await update_interview_session_status(conn, session_token, body.status)
    return {"ok": True}


# ---------------------------------------------------------------------------
# Endpoint 5b: PATCH /{session_token}/checkpoint
# ---------------------------------------------------------------------------

class CheckpointBody(BaseModel):
    checkpoint: dict  # arbitrary JSON — stored as-is


@router.patch("/{session_token}/checkpoint")
async def save_checkpoint(session_token: str, body: CheckpointBody):
    """Persist mid-session progress so reconnecting users can resume."""
    db_path = await _find_session_db(session_token)
    if not db_path:
        raise HTTPException(status_code=404, detail="Session not found")
    async with interview_db_connection(db_path) as conn:
        await save_interview_checkpoint(conn, session_token, body.checkpoint)
    return {"saved": True}


# ---------------------------------------------------------------------------
# Endpoint 6: PATCH /{session_token}/complete
# ---------------------------------------------------------------------------

class CapturedPair(BaseModel):
    """One answer, addressed to the question that produced it.

    Typed rather than a bare dict: an untyped payload accepted a pair with no question_id
    silently, and the answer then had no question to be traced to. follow_up marks a
    generated probe or a scripted branch, which is further evidence about one question rather
    than a question of its own.
    """
    question_id: str
    question: str
    answer: str = ""
    follow_up: int = 0


class CompleteRequest(BaseModel):
    qa_pairs: list[CapturedPair]
    ratings: list[dict] | None = None


@router.patch("/{session_token}/complete")
async def complete_interview(session_token: str, body: CompleteRequest):
    success = await complete_session(
        session_token, [p.model_dump() for p in body.qa_pairs], body.ratings
    )
    if not success:
        raise HTTPException(status_code=404, detail="Session not found")
    return {"ok": True}


# Rate limit: session_token → list of send timestamps (in-memory, per-process)
_transcript_email_log: dict[str, list[float]] = defaultdict(list)
# Registered so the suite's one fixture empties it between tests. Not a cache of a resolved
# value like the other two registrants, but the same trap: it accumulates for the life of the
# process, so a test that sends three transcripts for a session token leaves any later test
# using that token answering 429 for a limit it never reached. Production never calls the
# clear-everything half - see api/services/process_cache.py.
register_cache(_transcript_email_log.clear)
_EMAIL_RATE_LIMIT = 3
_EMAIL_RATE_WINDOW = 3600  # seconds
_EMAIL_RE = re.compile(r"^[^@\s]{1,64}@[^@\s]{1,255}\.[^@\s]{1,63}$")


class TranscriptEmailRequest(BaseModel):
    email: str
    qa_pairs: list[dict]


@router.post("/{session_token}/email-transcript")
async def email_transcript(session_token: str, body: TranscriptEmailRequest):
    """Send the (possibly user-edited) transcript copy to the interviewee.

    This is a thank-you to a participant, so it goes out as stakeholder correspondence
    and carries the same face every other message that participant receives does.

    The project is derived from the database the session was found in, exactly as
    `get_session_with_script` derives it, and it is passed to `send_project_mail`
    because delivery is that function's decision: this endpoint used to post
    `body.email` straight to Resend with no `dev_mode` check, which is how a project
    that believed it was holding all outbound mail would have sent to a real address.

    Security controls:
    - Session must exist and be in 'completed' status (prevents random-token abuse).
    - Email format validated server-side.
    - Destination must match the stakeholder invited for this session. The body is
      caller-supplied so the interviewee can edit their transcript before sending;
      constraining the destination is what stops a leaked token being used to send
      attacker-controlled text from our verified sending domain.
    - Pair count and field length capped (prevents body-stuffing).
    - Rate-limited to 3 sends per session per hour (prevents relay spam).
    """
    # 1 — Validate email format
    if not _EMAIL_RE.match(body.email):
        raise HTTPException(status_code=422, detail="Invalid email address")

    # 2 — Verify session exists and is completed
    db_path = await _find_session_db(session_token)
    if not db_path:
        raise HTTPException(status_code=404, detail="Session not found")

    async with interview_db_connection(db_path) as _conn:
        async with _conn.execute(
            "SELECT s.status, s.stakeholder_id, st.email AS stakeholder_email "
            "FROM interview_sessions s "
            "JOIN stakeholders st ON st.id = s.stakeholder_id "
            "WHERE s.session_token=?",
            (session_token,),
        ) as _cur:
            row = await _cur.fetchone()

    if not row or row["status"] != "completed":
        raise HTTPException(status_code=403, detail="Session not completed")

    # 2b — Destination must be the stakeholder this session was created for.
    # Empty stored email fails closed: a stakeholder with no address on file was
    # never invited by email, so there is no legitimate destination to send to.
    if body.email.strip().lower() != (row["stakeholder_email"] or "").strip().lower():
        raise HTTPException(status_code=403, detail="Email does not match session")

    # 3 — Rate limit
    now = time.monotonic()
    sends = [t for t in _transcript_email_log[session_token] if now - t < _EMAIL_RATE_WINDOW]
    if len(sends) >= _EMAIL_RATE_LIMIT:
        raise HTTPException(status_code=429, detail="Too many requests — try again later")

    # 4 — Validate payload size
    if len(body.qa_pairs) > 100:
        raise HTTPException(status_code=422, detail="Too many pairs")
    for pair in body.qa_pairs:
        if len(str(pair.get("question", ""))) > 5000 or len(str(pair.get("answer", ""))) > 10000:
            raise HTTPException(status_code=422, detail="Pair content too long")

    # 5 — Check Resend is configured
    if not get_settings().resend_api_key:
        raise HTTPException(status_code=503, detail="Email delivery not configured")

    # 6 — Build plain-text body (no HTML — prevents injection)
    lines: list[str] = ["Thank you for completing the interview.\n\nHere is a copy of your responses:\n"]
    for i, pair in enumerate(body.qa_pairs, 1):
        lines.append(f"Q{i}: {str(pair.get('question', ''))[:5000]}")
        lines.append(f"A{i}: {str(pair.get('answer', '') or 'No response recorded')[:10000]}")
        lines.append("")

    try:
        posted = await send_project_mail(
            slug=Path(db_path).stem,
            audience=STAKEHOLDERS,
            to=[body.email],
            subject="Your interview transcript",
            body="\n".join(lines),
            # The interviewee this session belongs to, so a reply to their transcript
            # routes back to them and to this project.
            stakeholder_id=row["stakeholder_id"],
        )
    except Exception:
        raise HTTPException(status_code=502, detail="Email delivery failed") from None
    if not posted:
        raise HTTPException(status_code=502, detail="Email delivery failed")

    # Record send timestamp only on success
    sends.append(now)
    _transcript_email_log[session_token] = sends

    return {"sent": True}

