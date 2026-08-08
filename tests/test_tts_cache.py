# tests/test_tts_cache.py
"""Tests for the content-addressed speech cache and its pre-warm entry point.

Scripted questions are identical for every interviewee on a script, so caching removes
almost all ElevenLabs calls, and pre-warming at dispatch removes them from the request
path entirely. The property that matters is not that the cache round-trips in isolation
(that's cheap and proves little) but that `speak` actually consults it, and that
`prewarm_script_audio` stores audio under the exact key `speak` will look up later.
"""
import threading

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


def test_concurrent_writers_on_the_same_key_do_not_corrupt_each_others_payload():
    """A fixed temp filename derived only from `key` (e.g. `.{key}.partial`) is shared by
    every writer racing on that key: a `--workers N>1` deployment, or a pre-warm run
    sharing a cache directory with a live server that independently misses the same
    question. Two writers opening and writing that shared path around the same moment can
    interleave into a mixture of both payloads before either renames - the final rename is
    atomic, but atomicity of the rename says nothing about what ends up *in* the file being
    renamed. `store_audio` must give each call its own temp file, so this drives many
    overlapping (thread, key) pairs and requires every stored result to be exactly one
    writer's complete payload, never a splice of both and never truncated.
    """
    from api.services.tts_cache import cache_key, cached_audio, store_audio

    # Large and clearly distinguishable so a splice (any byte from the other payload, or a
    # short read) is detectable rather than accidentally looking like a clean result.
    payload_a = b"A" * 300_000
    payload_b = b"B" * 300_000

    for trial in range(10):
        key = cache_key("voice-race", f"concurrent question {trial}")
        barrier = threading.Barrier(2)

        def write(payload):
            barrier.wait()  # both threads reach store_audio at the same moment
            store_audio(key, payload)

        threads = [
            threading.Thread(target=write, args=(payload_a,)),
            threading.Thread(target=write, args=(payload_b,)),
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        result = cached_audio(key)
        assert result in (payload_a, payload_b), (
            f"trial {trial}: stored bytes are neither writer's payload intact - "
            f"got {len(result) if result is not None else 'None'} bytes, "
            "which means the two writers' temp files collided"
        )


def test_store_audio_gives_each_call_its_own_temp_file(monkeypatch):
    """The mechanism the property above depends on, tested directly.

    The end-to-end test above exercises real concurrent writers and never observed a
    spliced result even against the pre-fix implementation, on this filesystem: macOS
    serialises whole-buffer write() calls to a regular file closely enough that "last
    writer wins" held in every trial rather than ever interleaving - so that test alone
    cannot be trusted to catch a regression back to a shared temp name on this platform.
    This test targets the actual guarantee instead: two calls to `store_audio` for the
    same key must go through two distinct temporary files, never a name derived only from
    `key` (which every writer racing on that key would share, regardless of platform write
    semantics - and unlike a single process's threads, separate `--workers` processes have
    no shared serialisation to fall back on).
    """
    import tempfile as tempfile_module
    from api.services.tts_cache import cache_key, store_audio

    seen: list[str] = []
    real_mkstemp = tempfile_module.mkstemp

    def spy(*args, **kwargs):
        fd, name = real_mkstemp(*args, **kwargs)
        seen.append(name)
        return fd, name

    monkeypatch.setattr(tempfile_module, "mkstemp", spy)

    key = cache_key("voice-x", "same question, twice")
    store_audio(key, b"first")
    store_audio(key, b"second")

    assert len(seen) == 2, "store_audio did not go through tempfile.mkstemp both times"
    assert seen[0] != seen[1], (
        "two store_audio calls on the same key produced the same temp file name - "
        "concurrent writers on this key would collide"
    )


def test_store_audio_swallows_a_disk_failure_instead_of_raising(monkeypatch):
    """mkstemp is a real filesystem call (unlike the path arithmetic it replaced), so it
    can raise OSError on its own - disk full, permission denied, fd exhaustion, or the
    cache directory vanishing between _cache_dir()'s mkdir and mkstemp. The cache is an
    optimisation, never a requirement, so store_audio must absorb that failure rather than
    let it escape."""
    import tempfile as tempfile_module
    from api.services.tts_cache import cache_key, store_audio

    def explode(*args, **kwargs):
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(tempfile_module, "mkstemp", explode)

    key = cache_key("voice-full-disk", "does this raise?")
    store_audio(key, b"AUDIO")  # must return normally, not raise


@pytest.mark.asyncio
async def test_speak_still_returns_audio_when_the_cache_write_fails(monkeypatch):
    """The property the interviewee actually experiences, exercised through the real
    speak() -> store_audio() path (not a mocked-out store_audio, which would only prove
    speak lacks its own try/except - never the point). Simulate the reported failure at
    its actual source, mkstemp, and confirm a cache-write failure on a miss costs nothing
    but the optimisation: speak() still hands back the freshly synthesised audio rather
    than failing the turn."""
    import tempfile as tempfile_module
    from api.services import interview_service as svc

    async def fake_synthesise(text, voice_id):
        return b"FRESH-DESPITE-DISK-FULL"

    def explode(*args, **kwargs):
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(svc, "synthesise", fake_synthesise)
    monkeypatch.setattr(tempfile_module, "mkstemp", explode)

    assert await svc.speak("A brand new question", "voice-1") == b"FRESH-DESPITE-DISK-FULL"
