# api/services/tts_cache.py
"""Content-addressed cache for synthesised speech.

Scripted questions are identical for every interviewee on a script. The live model holds
16 scripts and 300 distinct question texts, so a 300-person campaign asked ElevenLabs to
synthesise 300 strings roughly 5,700 times.

Only elaboration presses are dynamic, and they are the only thing that should reach the
provider while somebody is waiting.
"""
import hashlib
import json
import logging
from pathlib import Path

from api.config import get_settings
from agents.tools._db import current_output_path

_log = logging.getLogger(__name__)


def _cache_dir() -> Path:
    d = Path(get_settings().data_dir) / "tts_cache"
    d.mkdir(parents=True, exist_ok=True)
    return d


def cache_key(voice_id: str, text: str) -> str:
    """A key over both the voice and the words.

    The null byte is a separator, not decoration: without it, voice 'ab' with text 'c' and
    voice 'a' with text 'bc' hash identically and one interviewee hears another's voice.
    """
    digest = hashlib.sha256(f"{voice_id}\x00{text}".encode()).hexdigest()
    return digest


def cached_audio(key: str) -> bytes | None:
    path = _cache_dir() / f"{key}.mp3"
    try:
        return path.read_bytes()
    except OSError:
        return None


def store_audio(key: str, audio: bytes) -> None:
    """Write via a temporary file and rename.

    Two interviewees can miss on the same key at the same moment. Rename is atomic on the
    same filesystem, so the loser overwrites with identical bytes rather than leaving a
    half-written file for a third reader.
    """
    directory = _cache_dir()
    tmp = directory / f".{key}.partial"
    try:
        tmp.write_bytes(audio)
        tmp.replace(directory / f"{key}.mp3")
    except OSError:
        _log.warning("tts_cache: could not store %s", key)
        tmp.unlink(missing_ok=True)


async def prewarm_script_audio(slug: str, script_id: str, voice_id: str) -> int:
    """Synthesise a script's questions ahead of time. Returns how many were newly stored.

    Sub-project A calls this when it releases an invite, minutes to days before the
    interviewee clicks, so scripted playback makes no network call at all. Idempotent:
    invites can be retried, and a warm key is skipped rather than re-synthesised.
    """
    from api.services.interview_service import synthesise

    path = current_output_path(slug, "interview_scripts")
    if path is None:
        return 0
    try:
        scripts = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return 0
    script = scripts.get(script_id)
    if not isinstance(script, dict):
        return 0

    stored = 0
    for section in script.get("sections", []):
        for question in section.get("questions", []):
            text = question.get("text") or question.get("question") or ""
            if not text:
                continue
            key = cache_key(voice_id, text)
            if cached_audio(key) is not None:
                continue
            try:
                store_audio(key, await synthesise(text, voice_id))
                stored += 1
            except Exception:
                # A pre-warm failure costs a cache miss later, never the invite.
                _log.warning("tts_cache: prewarm failed for %s/%s", slug, script_id)
    return stored
