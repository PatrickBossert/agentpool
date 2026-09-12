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
import os
import tempfile
from pathlib import Path

from api.config import get_settings
from agents.tools._db import current_output_path

_log = logging.getLogger(__name__)


def _cache_dir() -> Path:
    d = Path(get_settings().data_dir) / "tts_cache"
    d.mkdir(parents=True, exist_ok=True)
    return d


def cache_key(voice_id: str, model_id: str, text: str) -> str:
    """A key over the voice, the synthesis model, and the words.

    The null byte is a separator, not decoration: without it, voice 'ab' with text 'c' and
    voice 'a' with text 'bc' hash identically and one interviewee hears another's voice.

    `model_id` joins the key for the same class of reason rather than for tidiness. The same
    words in the same voice through two different models are two different recordings, so a
    key that omitted it would serve a project on `eleven_multilingual_v2` the audio a project
    on `eleven_turbo_v2` had already stored - and the cache never expires, so the wrong
    rendering would be permanent. It is a required argument, not an appended optional one:
    a default would let a caller silently key on the wrong model.
    """
    digest = hashlib.sha256(f"{voice_id}\x00{model_id}\x00{text}".encode()).hexdigest()
    return digest


def cached_audio(key: str) -> bytes | None:
    path = _cache_dir() / f"{key}.mp3"
    try:
        return path.read_bytes()
    except OSError:
        return None


def store_audio(key: str, audio: bytes) -> None:
    """Write via a uniquely-named temporary file, then rename onto the final path.

    Two interviewees can miss on the same key at the same moment - and once pre-warm and a
    live server share a cache directory, a pre-warm run and a live miss can too. The rename
    is atomic on the same filesystem, so a reader never sees a half-renamed target: it gets
    either the old content (or none) or the complete new content, never a partial one. But
    that guarantee covers only the rename step. `tempfile.mkstemp` is what protects the
    write step before it: it hands each call a name unique to that call (mkstemp itself
    picks it and creates the file exclusively, so a fixed name shared across concurrent
    writers - e.g. one derived from `key` alone - cannot happen), so two writers on the same
    key write to two different files and cannot interleave into each other's payload.
    Whichever call reaches `replace()` last simply publishes its own complete bytes.

    The cache is an optimisation, never a requirement: `speak()` (interview_service.py)
    calls this synchronously on the live request path after it already has the freshly
    synthesised audio in hand, so any failure here - disk full, permission denied, fd
    exhaustion, or the cache directory vanishing between `_cache_dir()`'s `mkdir` and
    `mkstemp` - must be swallowed rather than propagated. `mkstemp` itself can raise
    `OSError` (it is a real filesystem call, unlike the path arithmetic it replaced), so it
    has to sit inside the same try/except as the write and the rename - a bare `tmp =
    tempfile.mkstemp(...)` ahead of the try block would let exactly that exception escape
    uncaught and fail the interview turn a cache miss was never supposed to be able to
    fail. `tmp` starts as None so the except handler can tell "never created" from "created,
    then failed" and only unlink in the latter case.
    """
    directory = _cache_dir()
    tmp: Path | None = None
    try:
        fd, tmp_name = tempfile.mkstemp(dir=directory, prefix=f".{key}.", suffix=".partial")
        tmp = Path(tmp_name)
        with os.fdopen(fd, "wb") as f:
            f.write(audio)
        tmp.replace(directory / f"{key}.mp3")
    except OSError:
        _log.warning("tts_cache: could not store %s", key)
        if tmp is not None:
            tmp.unlink(missing_ok=True)


async def prewarm_script_audio(
    slug: str, script_id: str, voice_id: str, model_id: str
) -> int:
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
            key = cache_key(voice_id, model_id, text)
            if cached_audio(key) is not None:
                continue
            try:
                store_audio(key, await synthesise(text, voice_id, model_id))
                stored += 1
            except Exception:
                # A pre-warm failure costs a cache miss later, never the invite.
                _log.warning("tts_cache: prewarm failed for %s/%s", slug, script_id)
    return stored
