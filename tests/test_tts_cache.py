# tests/test_tts_cache.py
"""Tests for the content-addressed speech cache and its pre-warm entry point.

Scripted questions are identical for every interviewee on a script, so caching removes
almost all ElevenLabs calls, and pre-warming at dispatch removes them from the request
path entirely. The property that matters is not that the cache round-trips in isolation
(that's cheap and proves little) but that `speak` actually consults it, and that
`prewarm_script_audio` stores audio under the exact key `speak` will look up later.
"""
import pytest
from api.config import get_settings


@pytest.fixture(autouse=True)
def cache_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    get_settings.cache_clear()
    yield tmp_path
    get_settings.cache_clear()


def test_the_key_separates_voice_from_text():
    """Concatenation alone would collide: voice 'ab' + text 'c' and voice 'a' + text 'bc'
    are different requests that must not share an entry."""
    from api.services.tts_cache import cache_key
    assert cache_key("ab", "c") != cache_key("a", "bc")


def test_a_miss_returns_none_and_a_stored_key_returns_the_audio():
    from api.services.tts_cache import cache_key, cached_audio, store_audio
    k = cache_key("voice-1", "What does a good day look like?")
    assert cached_audio(k) is None
    store_audio(k, b"AUDIO")
    assert cached_audio(k) == b"AUDIO"


@pytest.mark.asyncio
async def test_a_cache_hit_makes_no_provider_call(monkeypatch):
    """The property that matters: a warm cache must not touch ElevenLabs at all."""
    from api.services import interview_service as svc
    from api.services.tts_cache import cache_key, store_audio
    store_audio(cache_key("voice-1", "Hello"), b"CACHED")

    called = False

    def explode(*a, **k):
        nonlocal called
        called = True
        raise AssertionError("provider called on a cache hit")

    monkeypatch.setattr(svc, "get_tts_client", explode)
    assert await svc.speak("Hello", "voice-1") == b"CACHED"
    assert called is False


@pytest.mark.asyncio
async def test_a_cache_miss_synthesises_and_then_stores_it(monkeypatch):
    """The other half of the same property: a cold cache must reach the provider exactly
    once, and the result must be retrievable afterwards under the same key."""
    from api.services import interview_service as svc
    from api.services.tts_cache import cache_key, cached_audio

    async def fake_synthesise(text, voice_id):
        return b"FRESH"

    monkeypatch.setattr(svc, "synthesise", fake_synthesise)
    assert await svc.speak("Brand new question", "voice-2") == b"FRESH"
    assert cached_audio(cache_key("voice-2", "Brand new question")) == b"FRESH"


@pytest.mark.asyncio
async def test_prewarm_is_idempotent(tmp_path, monkeypatch):
    """A dispatch retry must not re-synthesise a script that is already warm."""
    import json
    from api.services import tts_cache
    monkeypatch.setenv("PROJECTS_DIR", str(tmp_path / "projects"))
    get_settings.cache_clear()
    outputs = tmp_path / "projects" / "warm" / "outputs"
    outputs.mkdir(parents=True)
    scripts = {"SC-001": {"script_id": "SC-001", "sections":
               [{"questions": [{"text": "One?"}, {"text": "Two?"}]}]}}
    (outputs / "interview_scripts_v1.json").write_text(json.dumps(scripts))
    monkeypatch.setattr(tts_cache, "current_output_path",
                        lambda slug, t: outputs / "interview_scripts_v1.json")

    calls = []

    async def fake_synth(text, voice_id):
        calls.append(text)
        return b"AUDIO"

    monkeypatch.setattr("api.services.interview_service.synthesise", fake_synth)
    assert await tts_cache.prewarm_script_audio("warm", "SC-001", "v1") == 2
    assert await tts_cache.prewarm_script_audio("warm", "SC-001", "v1") == 0
    assert len(calls) == 2, "second pre-warm re-synthesised an already warm script"


@pytest.mark.asyncio
async def test_prewarm_stores_audio_under_the_key_speak_would_look_up(tmp_path, monkeypatch):
    """A count proves nothing about whether the audio is actually retrievable afterwards.
    Pre-warm a script, then look it up the same way `speak` does: via `cache_key(voice_id,
    text)`. If prewarm ever wrote under a different key (e.g. hashed only the text, or only
    the question id), this is the test that would catch it - the idempotency test above
    would still pass, since it only counts calls."""
    import json
    from api.services import tts_cache
    from api.services.tts_cache import cache_key, cached_audio
    monkeypatch.setenv("PROJECTS_DIR", str(tmp_path / "projects"))
    get_settings.cache_clear()
    outputs = tmp_path / "projects" / "warm2" / "outputs"
    outputs.mkdir(parents=True)
    scripts = {"SC-001": {"script_id": "SC-001", "sections":
               [{"questions": [{"question": "What does a good day look like?"}]}]}}
    (outputs / "interview_scripts_v1.json").write_text(json.dumps(scripts))
    monkeypatch.setattr(tts_cache, "current_output_path",
                        lambda slug, t: outputs / "interview_scripts_v1.json")

    async def fake_synth(text, voice_id):
        return b"WARM-AUDIO"

    monkeypatch.setattr("api.services.interview_service.synthesise", fake_synth)
    assert await tts_cache.prewarm_script_audio("warm2", "SC-001", "voice-9") == 1

    key = cache_key("voice-9", "What does a good day look like?")
    assert cached_audio(key) == b"WARM-AUDIO"
