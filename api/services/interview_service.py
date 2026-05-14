# api/services/interview_service.py
"""Service layer for voice interview public endpoints.

Provides session lookup, TTS (ElevenLabs), STT token generation (Deepgram),
LLM elaboration press, and session completion helpers.
"""
from __future__ import annotations

import json
from pathlib import Path

import aiosqlite
import httpx

from api.config import get_settings
from api.database import fetch_interview_session, complete_interview_session


async def _find_session_db(session_token: str) -> str | None:
    """Scan all project DB files to find the one containing session_token.

    Returns the absolute path string of the matching DB, or None.
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
            async with aiosqlite.connect(str(db_path)) as conn:
                conn.row_factory = aiosqlite.Row
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

    settings = get_settings()

    # Derive slug from db filename (e.g. "myproject.db" → "myproject")
    slug = Path(db_path).stem

    config: dict = {}
    async with aiosqlite.connect(db_path) as conn:
        conn.row_factory = aiosqlite.Row
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

    # interview_scripts are written by SQLiteStateTool as a JSON file at:
    # {projects_dir}/{slug}/outputs/interview_scripts.json
    scripts_path = (
        Path(settings.projects_dir) / slug / "outputs" / "interview_scripts.json"
    )
    script = None
    if scripts_path.exists():
        try:
            scripts = json.loads(scripts_path.read_text())
            node_label = session_row.get("node_label") if isinstance(session_row, dict) else session_row["node_label"]
            script = scripts.get(node_label)
        except (json.JSONDecodeError, KeyError):
            pass

    branding = {
        "header_image_url": config.get("brand_header_image_url", ""),
        "primary_color": config.get("brand_primary_color", "#0d9488"),
        "text_color": config.get("brand_text_color", "#1f2937"),
    }

    session_dict = dict(session_row)

    # Fetch questionnaire template for this node if assigned
    questionnaire = None
    try:
        from api.database import fetch_node_template_assignments, get_system_db_path, init_system_db, fetch_template
        import json as _json_inner

        # Re-open the DB to get project id and node assignments
        async with aiosqlite.connect(db_path) as qconn:
            qconn.row_factory = aiosqlite.Row
            async with qconn.execute("SELECT id FROM projects LIMIT 1") as cur:
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
                            questionnaire = _json_inner.loads(tpl["schema_json"])
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


async def speak(text: str, voice_id: str) -> bytes:
    """Call ElevenLabs TTS API and return raw audio bytes."""
    settings = get_settings()
    if not settings.elevenlabs_api_key:
        raise ValueError("ELEVENLABS_API_KEY not configured")
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}",
            headers={
                "xi-api-key": settings.elevenlabs_api_key,
                "Content-Type": "application/json",
            },
            json={
                "text": text,
                "model_id": "eleven_monolingual_v1",
                "voice_settings": {"stability": 0.5, "similarity_boost": 0.75},
            },
            timeout=30.0,
        )
        resp.raise_for_status()
        return resp.content


async def elaboration_press(
    question_text: str,
    response_text: str,
    probing_instructions: str,
    stakeholder_name: str = "",
) -> str:
    """Generate a follow-up press question via Claude Haiku."""
    from anthropic import AsyncAnthropic

    client = AsyncAnthropic()
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
    response = await client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=150,
        messages=[{"role": "user", "content": prompt}],
    )
    return response.content[0].text.strip()


async def complete_session(session_token: str, qa_pairs: list[dict]) -> bool:
    """Write the Q&A transcript and mark the session as completed.

    Returns True on success, False if the session was not found.
    """
    db_path = await _find_session_db(session_token)
    if not db_path:
        return False
    async with aiosqlite.connect(db_path) as conn:
        transcript_json = json.dumps(qa_pairs)
        await complete_interview_session(conn, session_token, transcript_json)
    return True
