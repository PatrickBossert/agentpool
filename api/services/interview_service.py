# api/services/interview_service.py
"""Service layer for voice interview public endpoints.

Provides session lookup, TTS (ElevenLabs), STT token generation (Deepgram),
LLM elaboration press, and session completion helpers.
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from pathlib import Path

import aiosqlite
import httpx
from anthropic import AsyncAnthropic

from api.config import get_settings
from api.services.chroma_client import project_llm_mode
from api.services.http_clients import get_tts_client, get_anthropic_client
from api.services.interview_answer_service import record_answers, script_for_session
from api.database import (
    complete_interview_session,
    fetch_interview_session,
    fetch_node_template_assignments,
    fetch_template,
    get_system_db_path,
    init_system_db,
    interview_db_connection,
    save_interview_checkpoint,
)

_log = logging.getLogger(__name__)


def interview_url(session_token: str) -> str:
    """The link an interviewee follows.

    public_url, not frontend_url: frontend_url is unset in every deployment and defaults to
    localhost. And /dashboard, because that is the SPA's vite base and router basename - a
    link without it 404s. Two of the three hand-built versions of this string got one or
    both wrong, and only the reminder email produced a working link.
    """
    return f"{get_settings().public_url.rstrip('/')}/dashboard/interview/{session_token}"


async def _find_session_db(session_token: str) -> str | None:
    """Scan all project DB files to find the one containing session_token.

    Returns the absolute path string of the matching DB, or None.

    Opens each candidate with wal=False: this loop touches every project database in the
    directory on every lookup, not just the one holding the session, and PRAGMA
    journal_mode=WAL is a write - briefly exclusive, and it leaves -wal/-shm files behind.
    Flipping that on every database a scan merely passes over (most of which are not the
    session's) is a cost with no matching benefit here; busy_timeout is applied regardless,
    since it is cheap and per-connection, and it stops the scan itself failing outright if it
    catches an unrelated database mid-write. The database this call is actually looking for
    gets WAL from the very next connection opened against it - get_session_with_script or
    complete_session, both of which use the default wal=True.
    """
    settings = get_settings()
    db_dir = Path(settings.database_dir)
    if not db_dir.exists():
        return None

    # Scan top-level .db files (one db per project slug)
    candidate_paths: list[Path] = list(db_dir.glob("*.db"))
    # Also one level down, just in case layout varies
    candidate_paths.extend(db_dir.glob("*/*.db"))

    for db_path in candidate_paths:
        try:
            async with interview_db_connection(str(db_path), wal=False) as conn:
                async with conn.execute(
                    "SELECT id FROM interview_sessions WHERE session_token=?",
                    (session_token,),
                ) as cur:
                    row = await cur.fetchone()
                if row:
                    return str(db_path)
        except Exception:
            # Skip files that aren't valid databases or lack the table
            continue
    return None


async def get_session_with_script(session_token: str) -> dict | None:
    """Fetch interview session row plus its script from the state store.

    Returns ``{"session": <row dict>, "script": <script dict or None>}``
    or ``None`` if the session is not found.
    """
    db_path = await _find_session_db(session_token)
    if not db_path:
        return None

    # Derive slug from db filename (e.g. "myproject.db" → "myproject")
    slug = Path(db_path).stem

    config: dict = {}
    async with interview_db_connection(db_path) as conn:
        session_row = await fetch_interview_session(conn, session_token)
        if not session_row:
            return None

        # Read project config for branding fields in the same connection
        try:
            async with conn.execute(
                "SELECT config_json FROM projects WHERE slug=?", (slug,)
            ) as cur:
                proj_row = await cur.fetchone()
            if proj_row and proj_row["config_json"]:
                config = json.loads(proj_row["config_json"])
        except Exception:
            pass

        # Resolved exactly as the completion path resolves it. These must agree: a session
        # served from one script and recorded against another tags every answer with the
        # wrong node, discipline and level, and nothing reports the mismatch.
        script = await script_for_session(conn, slug, dict(session_row))

    branding = {
        "header_image_url": config.get("brand_header_image_url", ""),
        "primary_color": config.get("brand_primary_color", "#0d9488"),
        "text_color": config.get("brand_text_color", "#1f2937"),
        "interviewer_image_url": config.get("brand_interviewer_image_url", ""),
        "interviewer_name": config.get("brand_interviewer_name", "Avery Singh"),
        "interviewer_tagline": config.get("brand_interviewer_tagline", "I'll be guiding our conversation today"),
    }

    session_dict = dict(session_row)
    if session_dict.get("voice_config"):
        try:
            session_dict["voice_config"] = json.loads(session_dict["voice_config"])
        except (json.JSONDecodeError, TypeError):
            session_dict["voice_config"] = None

    # Fetch questionnaire template for this node if assigned
    questionnaire = None
    try:
        # Re-open the DB to get project id and node assignments
        async with interview_db_connection(db_path) as qconn:
            async with qconn.execute("SELECT id FROM projects WHERE slug=?", (slug,)) as cur:
                proj_row = await cur.fetchone()
            if proj_row:
                node_assignments = await fetch_node_template_assignments(qconn, proj_row["id"])
                node_label = session_dict["node_label"]
                node_assignment = next(
                    (a for a in node_assignments if a["node_label"] == node_label), None
                )
                if node_assignment and node_assignment["questionnaire_template_id"]:
                    qid = node_assignment["questionnaire_template_id"]
                    sys_db_path = get_system_db_path()
                    async with aiosqlite.connect(str(sys_db_path)) as sys_conn:
                        sys_conn.row_factory = aiosqlite.Row
                        await init_system_db(sys_conn)
                        tpl = await fetch_template(sys_conn, qid)
                    if tpl:
                        try:
                            questionnaire = json.loads(tpl["schema_json"])
                        except Exception:
                            questionnaire = None
    except Exception:
        pass

    return {"session": session_dict, "script": script, "branding": branding, "questionnaire": questionnaire}


async def generate_deepgram_token() -> str:
    """Create a short-lived Deepgram streaming token via the REST API."""
    settings = get_settings()
    if not settings.deepgram_api_key:
        raise ValueError("DEEPGRAM_API_KEY not configured")
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            "https://api.deepgram.com/v1/auth/grant",
            headers={"Authorization": f"Token {settings.deepgram_api_key}"},
            json={"grant_type": "instant"},
            timeout=10.0,
        )
        resp.raise_for_status()
        return resp.json()["key"]


async def synthesise(text: str, voice_id: str) -> bytes:
    """Call ElevenLabs and return raw audio. No caching - the cache wraps this."""
    settings = get_settings()
    if not settings.elevenlabs_api_key:
        raise ValueError("ELEVENLABS_API_KEY not configured")
    client = get_tts_client()
    resp = await client.post(
        f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}",
        headers={
            "xi-api-key": settings.elevenlabs_api_key,
            "Content-Type": "application/json",
        },
        json={
            "text": text,
            "model_id": "eleven_turbo_v2",
            "voice_settings": {
                "stability": 0.40,
                "similarity_boost": 0.75,
                "style": 0.25,
                "use_speaker_boost": True,
            },
        },
        timeout=30.0,
    )
    resp.raise_for_status()
    return resp.content


async def speak(text: str, voice_id: str) -> bytes:
    """Cached speech. Scripted questions are identical across every interviewee."""
    from api.services.tts_cache import cache_key, cached_audio, store_audio
    key = cache_key(voice_id, text)
    hit = cached_audio(key)
    if hit is not None:
        return hit
    audio = await synthesise(text, voice_id)
    store_audio(key, audio)
    return audio


async def _press_call(prompt: str, slug: str) -> str:
    """The provider call, split out so the budget in elaboration_press can wrap it."""
    settings = get_settings()
    if project_llm_mode(slug) == "sensitive":
        client = AsyncAnthropic(base_url=settings.llamacpp_base_url, api_key="not-needed")
        model = settings.local_llm_model
    else:
        client = get_anthropic_client()
        model = "claude-haiku-4-5-20251001"
    response = await client.messages.create(
        model=model, max_tokens=150, messages=[{"role": "user", "content": prompt}]
    )
    return response.content[0].text.strip()


async def elaboration_press(
    question_text: str,
    response_text: str,
    probing_instructions: str,
    stakeholder_name: str = "",
    *,
    slug: str = "",
    timeout_seconds: float = 8.0,
) -> str:
    """Generate a follow-up press, or return "" if it cannot be produced in time.

    The press sits on the request path with a person waiting, and in secure mode the model
    behind it is local: slower, and serving far fewer parallel requests. An elaboration
    press is an enhancement rather than part of the instrument, so a missed one costs depth
    on a single answer while a long silence costs the interviewee's confidence in the whole
    conversation. Returning "" is the deliberate trade; the caller moves to the next
    scripted question.

    Both the success and the skip path log how long the call took. In secure mode this is the
    fast model answering a person in real time, so a duration series - and a skip count
    greppable from one campaign's logs - is the evidence a later decision about allowing a
    hosted model for follow-ups would need.
    """
    name_clause = f" {stakeholder_name}" if stakeholder_name else ""
    prompt = (
        f"You are a polite but insistent interviewer.{name_clause} has given an "
        f"insufficient answer to the following question.\n\n"
        f"Question: {question_text}\n\n"
        f"Their answer: {response_text}\n\n"
        f"Probing instructions: {probing_instructions}\n\n"
        "Generate one natural follow-up question (max 2 sentences) that presses for "
        "elaboration without being confrontational. Return only the question text, no preamble."
    )
    started = time.perf_counter()
    try:
        result = await asyncio.wait_for(_press_call(prompt, slug), timeout=timeout_seconds)
        _log.info(
            "elaboration_press[%s]: %.2fs, %d chars",
            slug, time.perf_counter() - started, len(result),
        )
        return result
    except asyncio.TimeoutError:
        _log.warning(
            "elaboration_press[%s]: SKIPPED after %.2fs (budget %.1fs)",
            slug, time.perf_counter() - started, timeout_seconds,
        )
        return ""


async def complete_session(
    session_token: str,
    qa_pairs: list[dict],
    ratings: list[dict] | None = None,
) -> bool:
    """Write the Q&A transcript and mark the session as completed.

    Returns True on success, False if the session was not found.
    """
    db_path = await _find_session_db(session_token)
    if not db_path:
        return False
    # The slug is the db filename. record_answers needs it to find the scripts on disk and
    # to index into that project's own Chroma collection.
    slug = Path(db_path).stem

    async with interview_db_connection(db_path) as conn:
        transcript_json = json.dumps(qa_pairs)
        ratings_json = json.dumps(ratings) if ratings is not None else None
        await complete_interview_session(conn, session_token, transcript_json, ratings_json)
        await save_interview_checkpoint(conn, session_token, None)

        # The transcript blob stays for the review and email screens; the rows are what
        # anything queries. A session whose script cannot be resolved writes no rows and is
        # logged - the blob still holds everything the interviewee said, so nothing is lost
        # and the rows can be backfilled once the script is found.
        async with conn.execute(
            "SELECT * FROM interview_sessions WHERE session_token = ?", (session_token,)
        ) as cur:
            row = await cur.fetchone()
        session = dict(row) if row else None

        if session:
            script = await script_for_session(conn, slug, session)
            if script:
                await record_answers(conn, slug, session["id"], qa_pairs, script=script)
            else:
                _log.warning(
                    "complete_session[%s]: no script resolved for session %s - transcript "
                    "saved, no answer rows written", slug, session_token,
                )
    return True
