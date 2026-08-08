# Concurrent Interviews and Secure Mode Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make a corporate interview campaign of 50-300 people work when sessions overlap, and make a project marked sensitive keep its answers off third-party infrastructure.

**Architecture:** The live interview is browser JavaScript against stateless FastAPI endpoints - no agent is in the request path. Every fix therefore lands in `api/services/interview_service.py`, `api/services/interview_answer_service.py`, `api/database.py`, and two small new modules. The unifying move is to take expensive work off the moment a human is waiting: threading what blocks, caching what repeats, and pre-warming at dispatch what would otherwise happen at click.

**Tech Stack:** Python 3.13, FastAPI, aiosqlite (raw SQL, no ORM), httpx, anthropic (AsyncAnthropic), chromadb, pytest + pytest-asyncio (`asyncio_mode = strict`), React 18 + TypeScript + Vitest.

**Spec:** `docs/superpowers/specs/2026-08-08-concurrent-interviews-and-secure-mode-design.md`

## Global Constraints

- **British English throughout** - `-ise` not `-ize`, `-our` not `-or`, `organise`, `behaviour`, `centre`. Applies to comments, docstrings, error messages, and UI copy.
- **Short en dash ` - ` with spaces in prose, never an em dash `—`.**
- **Oxford comma** in lists of three or more.
- **No emoji in UI**; Lucide React icons only.
- **Python 3.13 only.** Use `./venv/bin/pytest` and `./venv/bin/python`, never system Python.
- **Async fixtures must use `@pytest_asyncio.fixture`**, not `@pytest.fixture` - `asyncio_mode = strict`.
- **`projects` has no `name` column.** Insert with `(slug, sector)` or `(slug, llm_mode, sector, config_json)`.
- **Run the backend suite twice before believing it is green.** `tests/conftest.py` points `DATABASE_DIR` at a fixed `/tmp/agentpool_test` that persists between runs.
- **Tests that need isolation** use `monkeypatch.setenv("DATABASE_DIR", str(tmp_path))` with `get_settings.cache_clear()` on both sides.
- **Never resolve an output by filename.** Use `current_output_path(slug, output_type)` from `agents/tools/_db.py`. `latest_output_path` is for first writes and hand-written files only.
- **Two config sources exist.** `load_project_config()` reads `projects/<slug>/config.yaml`; `projects.config_json` is a DB column. The interview path and the Settings page use **`projects.config_json`**. Do not mix them.
- **Integration tests are opt-in** (`pytest -m integration`) and cost real API credit. Nothing in this plan needs them.
- **Do not restart the API server while a crew run is in flight**, and run uvicorn without `--reload`.

---

## File Structure

**New files**

| File | Responsibility |
|---|---|
| `api/services/http_clients.py` | Module-level `httpx.AsyncClient` and `AsyncAnthropic` singletons, plus shutdown. Nothing else. |
| `api/services/tts_cache.py` | Content-addressed audio cache and the pre-warm entry point sub-project A will call. |
| `tests/test_interview_concurrency.py` | The overlap harness: N simultaneous sessions through the real endpoints. |
| `tests/test_secure_mode_routing.py` | Per-project routing for Chroma and the elaboration press. |
| `tests/test_tts_cache.py` | Cache hit/miss, no-provider-call-on-hit, pre-warm idempotency. |

**Modified files**

| File | Change |
|---|---|
| `api/services/interview_service.py` | Script resolution, shared clients, cache lookup, press routing and budget, `interview_url` helper |
| `api/services/interview_answer_service.py` | Index off the event loop; `get_chroma_client(slug)` |
| `api/services/chroma_client.py` | `get_chroma_client(slug)` with per-project mode resolution |
| `api/database.py` | WAL, `busy_timeout`, memoised migrations, unique index, upsert |
| `api/routers/interviews.py` | Auth on the sessions listing, slug into the press call, `interview_url` |
| `api/services/ingest_service.py`, `api/services/chat_retrieval_service.py`, `agents/tools/chroma_query.py` | Pass slug to `get_chroma_client` |
| `agents/tools/interview_session_tool.py` | Generate `session_token` in code; use `interview_url` |
| `agents/discovery/interview_coordinator.py` | Stop asking the model for a UUID |
| `ui/src/pages/Settings.tsx`, `ui/src/types.ts` | Press budget field |

---

## Task 1: Serve the script the ledger calls current

`get_session_with_script` reads a bare `projects/<slug>/outputs/interview_scripts.json` and looks scripts up by `node_label`. The file does not exist - writes are versioned to `_v13` - and the artefact is keyed by `script_id` (`SC-001`), not by label. Both are wrong, so **every session is served `script: None` and no interview can be conducted at all.** The completion path already resolves correctly via `script_for_session`; this makes the serving path agree with it, which also stops a session being served one script and having its answers tagged against another.

**Files:**
- Modify: `api/services/interview_service.py:96-108` (the `scripts_path` block inside `get_session_with_script`)
- Test: `tests/test_interview_service.py`

**Interfaces:**
- Consumes: `script_for_session(conn, slug: str, session: dict) -> dict | None` from `api.services.interview_answer_service` (already exists, already correct)
- Produces: nothing new

- [ ] **Step 1: Write the failing test**

```python
# tests/test_interview_service.py
import json
import pytest
import pytest_asyncio
from pathlib import Path
from api.config import get_settings


@pytest_asyncio.fixture
async def served_project(tmp_path, monkeypatch):
    """A project with a versioned scripts artefact and one session, wired to the ledger."""
    monkeypatch.setenv("DATABASE_DIR", str(tmp_path))
    monkeypatch.setenv("PROJECTS_DIR", str(tmp_path / "projects"))
    get_settings.cache_clear()
    slug = "served"
    outputs = tmp_path / "projects" / slug / "outputs"
    outputs.mkdir(parents=True)

    # Keyed by script_id, as Maya actually writes it - not by node_label.
    scripts = {"SC-001": {"script_id": "SC-001", "node_id": "1.F",
                          "node_label": "Frontline Interview", "level": "F",
                          "relationship": "internal", "sections": []}}
    (outputs / "interview_scripts_v3.json").write_text(json.dumps(scripts))

    from api.database import get_connection, insert_agent_output
    async with get_connection(slug) as conn:
        await conn.execute("INSERT INTO projects (slug, sector) VALUES (?,?)", (slug, "test"))
        await conn.commit()
        cur = await conn.execute("SELECT id FROM projects WHERE slug=?", (slug,))
        pid = (await cur.fetchone())[0]
        await conn.execute(
            "INSERT INTO agent_outputs (project_id, run_id, agent_name, output_type, "
            "version, is_current, file_path) VALUES (?,?,?,?,?,?,?)",
            (pid, 0, "interaction_designer", "interview_scripts", 3, 1,
             str(outputs / "interview_scripts_v3.json")),
        )
        await conn.execute(
            "INSERT INTO interview_sessions (project_id, stakeholder_id, node_label, "
            "session_token, status) VALUES (?,?,?,?,?)",
            (pid, 1, "Frontline Interview", "tok-served", "pending"),
        )
        await conn.commit()
    yield slug
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_the_session_is_served_the_current_script(served_project):
    """The serving path must resolve through the ledger, as the completion path does.

    It previously read a bare interview_scripts.json, which versioning means never exists,
    and keyed the lookup by node_label against an artefact keyed by script_id. Two
    independent faults, either of which alone returns None - so every interviewee got a
    session with no questions.
    """
    from api.services.interview_service import get_session_with_script
    result = await get_session_with_script("tok-served")
    assert result is not None
    assert result["script"] is not None, "session served with no script"
    assert result["script"]["script_id"] == "SC-001"
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `./venv/bin/pytest tests/test_interview_service.py::test_the_session_is_served_the_current_script -v`
Expected: FAIL with `AssertionError: session served with no script`

- [ ] **Step 3: Replace the bare-path lookup**

In `api/services/interview_service.py`, delete the block that builds `scripts_path` and does `scripts.get(node_label)`, and replace it with:

```python
    # Resolved exactly as the completion path resolves it. These must agree: a session
    # served from one script and recorded against another tags every answer with the wrong
    # node, discipline and level, and nothing reports the mismatch.
    from api.services.interview_answer_service import script_for_session
    script = await script_for_session(conn, slug, dict(session_row))
```

Keep the existing `conn` in scope - `script_for_session` needs it, and the function already holds an open connection at this point.

- [ ] **Step 4: Run the test to verify it passes**

Run: `./venv/bin/pytest tests/test_interview_service.py -v`
Expected: PASS

- [ ] **Step 5: Check nothing else read the bare path**

Run: `grep -rn "interview_scripts.json" api/ agents/ ui/src/`
Expected: no remaining reference that resolves a bare filename. `tests/` and comments may mention it.

- [ ] **Step 6: Commit**

```bash
git add api/services/interview_service.py tests/test_interview_service.py
git commit -m "fix(interviews): serve the script the ledger calls current

get_session_with_script read a bare interview_scripts.json and looked scripts up by
node_label. Writes are versioned to _vN so the file never exists, and the artefact is
keyed by script_id. Every session was served script: None - no interview could be
conducted. It now resolves via script_for_session, the same path completion uses, so a
session cannot be served one script and recorded against another."
```

---

## Task 2: Take Chroma indexing off the event loop

`index_answers` is synchronous and called from async code, so a completing session blocks every other session in the process. Measured at 3.66 s with Chroma unreachable; concurrent interviewees were served after 2.75 s versus 0.02 s with the call threaded.

`record_answers` keeps its `-> int` return. Moving the call into a thread frees the loop, which is the defect; the connection stays open but idle and committed, which WAL (Task 5) makes harmless for other readers. Changing the return type would touch eleven test call sites for no additional safety.

**Files:**
- Modify: `api/services/interview_answer_service.py:104-109`
- Test: `tests/test_interview_concurrency.py` (create)

**Interfaces:**
- Consumes: `index_answers(slug: str, rows: list[dict]) -> int` (sync, unchanged, never raises)
- Produces: `record_answers(conn, slug, session_id, qa_pairs, script) -> int` (signature unchanged)

- [ ] **Step 1: Write the failing test**

```python
# tests/test_interview_concurrency.py
"""Properties that only exist when interviews overlap.

Asserted against behaviour rather than against call sites. A test that asserts
asyncio.to_thread was called cannot tell whether the event loop was actually freed,
which is the entire property.
"""
import asyncio
import time
import pytest


@pytest.mark.asyncio
async def test_indexing_does_not_delay_other_sessions(monkeypatch):
    """One session completing must not stall the others.

    index_answers is stubbed with a blocking sleep standing in for a slow or unreachable
    Chroma. If it runs on the event loop, the concurrent waiter is served only after it
    finishes; if it runs in a thread, the waiter is served immediately.
    """
    from api.services import interview_answer_service as svc

    def slow_index(slug, rows):
        time.sleep(0.5)          # blocking, exactly as a Chroma round trip is
        return len(rows)

    monkeypatch.setattr(svc, "index_answers", slow_index)

    async def waiter(t0):
        await asyncio.sleep(0.01)
        return time.perf_counter() - t0

    t0 = time.perf_counter()
    _, waited = await asyncio.gather(
        svc._index_in_background("s", [{"id": 1}]),
        waiter(t0),
    )
    assert waited < 0.2, (
        f"a concurrent session waited {waited:.2f}s while another completed - "
        "indexing is still on the event loop"
    )
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `./venv/bin/pytest tests/test_interview_concurrency.py -v`
Expected: FAIL with `AttributeError: module ... has no attribute '_index_in_background'`

- [ ] **Step 3: Add the threaded wrapper and call it**

In `api/services/interview_answer_service.py`, add near `index_answers`:

```python
async def _index_in_background(slug: str, rows: list[dict]) -> int:
    """Index off the event loop.

    index_answers is synchronous and makes a network call. Called directly from async code
    it blocks every other request in the process, not just this session - and completions
    cluster at the end of a break, exactly when other people are mid-question. Measured at
    3.66s per completion with Chroma unreachable.
    """
    return await asyncio.to_thread(index_answers, slug, rows)
```

Add `import asyncio` at the top of the module. Then change the indexing block inside `record_answers` from `index_answers(slug, [...])` to:

```python
        await _index_in_background(slug, [r for r in stored if r["id"] in written])
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `./venv/bin/pytest tests/test_interview_concurrency.py tests/test_interview_answers.py -v`
Expected: PASS, and the eleven existing `record_answers` tests still pass unchanged.

- [ ] **Step 5: Commit**

```bash
git add api/services/interview_answer_service.py tests/test_interview_concurrency.py
git commit -m "fix(interviews): index answers off the event loop

index_answers is synchronous and was called from async code, so a completing session
blocked every other session in the process for the whole Chroma round trip - 3.66s with
Chroma down, measured. Concurrent interviewees were served after 2.75s; threaded, 0.02s.

The existing comment reasoned correctly that a Chroma outage must not cost the session
its data, and it does not. The cost was never to that session's data; it was to everyone
else's latency."
```

---

## Task 3: Reuse HTTP connections

`speak` and `elaboration_press` each construct a fresh client per call, paying a new TLS handshake every time. Measured 478 ms per call versus 264 ms with a shared client - 213 ms avoidable on every utterance.

**Files:**
- Create: `api/services/http_clients.py`
- Modify: `api/services/interview_service.py` (`speak`, `elaboration_press`), `api/main.py` (shutdown)
- Test: `tests/test_http_clients.py` (create)

**Interfaces:**
- Produces:
  - `get_tts_client() -> httpx.AsyncClient`
  - `get_anthropic_client() -> AsyncAnthropic`
  - `async close_http_clients() -> None`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_http_clients.py
import pytest


def test_the_tts_client_is_reused():
    """A new client per call pays a fresh TLS handshake - 213ms per utterance, measured."""
    from api.services.http_clients import get_tts_client
    assert get_tts_client() is get_tts_client()


def test_the_anthropic_client_is_reused():
    from api.services.http_clients import get_anthropic_client
    assert get_anthropic_client() is get_anthropic_client()


@pytest.mark.asyncio
async def test_closing_lets_the_next_call_rebuild():
    """Shutdown must not leave a closed client behind for a subsequent test or worker."""
    from api.services.http_clients import get_tts_client, close_http_clients
    first = get_tts_client()
    await close_http_clients()
    assert get_tts_client() is not first
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `./venv/bin/pytest tests/test_http_clients.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'api.services.http_clients'`

- [ ] **Step 3: Create the module**

```python
# api/services/http_clients.py
"""Long-lived HTTP clients for the interview request path.

Both providers were called through a client constructed per request, which meant a fresh
TLS handshake for every question spoken and every follow-up generated: 478ms per call
against 264ms shared, so 213ms wasted on every utterance. At twenty concurrent interviews
it is also twenty times the sockets and handshakes for no benefit.
"""
import httpx
from anthropic import AsyncAnthropic

_tts_client: httpx.AsyncClient | None = None
_anthropic_client: AsyncAnthropic | None = None


def get_tts_client() -> httpx.AsyncClient:
    """The shared client for ElevenLabs."""
    global _tts_client
    if _tts_client is None or _tts_client.is_closed:
        _tts_client = httpx.AsyncClient(timeout=30.0)
    return _tts_client


def get_anthropic_client() -> AsyncAnthropic:
    """The shared Anthropic client, used for the standard-mode elaboration press."""
    global _anthropic_client
    if _anthropic_client is None:
        _anthropic_client = AsyncAnthropic()
    return _anthropic_client


async def close_http_clients() -> None:
    """Close on application shutdown. Both getters rebuild on demand afterwards."""
    global _tts_client, _anthropic_client
    if _tts_client is not None and not _tts_client.is_closed:
        await _tts_client.aclose()
    _tts_client = None
    if _anthropic_client is not None:
        await _anthropic_client.close()
    _anthropic_client = None
```

- [ ] **Step 4: Use them in the interview path**

In `api/services/interview_service.py`, replace `async with httpx.AsyncClient() as client:` inside `speak` with `client = get_tts_client()` and de-indent the request. Replace `client = AsyncAnthropic()` in `elaboration_press` with `client = get_anthropic_client()`. Add `from api.services.http_clients import get_tts_client, get_anthropic_client` at the top.

Leave `get_deepgram_token`'s client alone - it is called once per session, not per utterance, and is not worth the coupling.

- [ ] **Step 5: Close on shutdown**

In `api/main.py`, inside the lifespan shutdown section (after the `yield`), add:

```python
    from api.services.http_clients import close_http_clients
    await close_http_clients()
```

- [ ] **Step 6: Run the tests**

Run: `./venv/bin/pytest tests/test_http_clients.py tests/test_interviews_router.py -v`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add api/services/http_clients.py api/services/interview_service.py api/main.py tests/test_http_clients.py
git commit -m "perf(interviews): reuse the ElevenLabs and Anthropic clients

Both were constructed per call, so every question spoken and every follow-up generated
paid a fresh TLS handshake: 478ms against 264ms shared, measured. 213ms per utterance."
```

---

## Task 4: Cache synthesised speech, and pre-warm it

Every interviewee on a script hears identical questions. The live model holds 16 scripts and 300 distinct question texts, so a 300-person campaign makes roughly 5,700 TTS calls for 300 distinct strings. Caching removes about 95% of them, and pre-warming at dispatch removes them from the request path entirely - which also puts synthesis at a rate we control rather than at the clicking rate we do not, so the ElevenLabs per-tier concurrency ceiling stops being reachable.

`prewarm_script_audio` is the hinge sub-project A calls when it releases an invite.

**Files:**
- Create: `api/services/tts_cache.py`
- Modify: `api/services/interview_service.py` (`speak`)
- Test: `tests/test_tts_cache.py` (create)

**Interfaces:**
- Consumes: `get_tts_client()` from Task 3; `current_output_path` from `agents.tools._db`
- Produces:
  - `cache_key(voice_id: str, text: str) -> str`
  - `cached_audio(key: str) -> bytes | None`
  - `store_audio(key: str, audio: bytes) -> None`
  - `async prewarm_script_audio(slug: str, script_id: str, voice_id: str) -> int` returning the number newly synthesised

- [ ] **Step 1: Write the failing test**

```python
# tests/test_tts_cache.py
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
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `./venv/bin/pytest tests/test_tts_cache.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'api.services.tts_cache'`

- [ ] **Step 3: Create the cache**

```python
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
```

- [ ] **Step 4: Split `speak` into lookup and synthesis**

In `api/services/interview_service.py`, rename the existing provider call to `synthesise` and add a caching `speak` in front of it:

```python
async def synthesise(text: str, voice_id: str) -> bytes:
    """Call ElevenLabs and return raw audio. No caching - the cache wraps this."""
    # ... the existing body of speak(), using get_tts_client() ...


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
```

Import inside the function to avoid a circular import: `tts_cache` imports `synthesise` from this module.

- [ ] **Step 5: Confirm `data_dir` exists in settings**

Run: `grep -n "data_dir" api/config.py`
If absent, add `data_dir: str = "data"` alongside `database_dir`, and add `DATA_DIR` to `.env.example` with a one-line comment.

- [ ] **Step 6: Add the pre-warm idempotency test**

```python
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
```

- [ ] **Step 7: Run the tests**

Run: `./venv/bin/pytest tests/test_tts_cache.py -v`
Expected: PASS

- [ ] **Step 8: Commit**

```bash
git add api/services/tts_cache.py api/services/interview_service.py tests/test_tts_cache.py api/config.py .env.example
git commit -m "perf(interviews): cache synthesised speech and add a pre-warm entry point

16 scripts hold 300 distinct question texts and every interviewee on a script hears the
same ones, so a 300-person campaign asked ElevenLabs for 300 strings ~5,700 times.

prewarm_script_audio is what sub-project A calls when it releases an invite, so scripted
playback makes no network call at all and synthesis happens at the dispatch rate we
control rather than the clicking rate we do not."
```

---

## Task 5: WAL, a busy timeout, and migrations that run once

`get_connection` opens in `journal_mode=delete`, where writers block readers on one project file - and completions are the heavy writes, clustering at the end of a break. It also runs `init_db` plus 27 `_migrate_*` functions on **every** open, about 4.2 ms, and a single request opens several connections.

**Files:**
- Modify: `api/database.py:1220-1250` (`get_connection`)
- Test: `tests/test_database_connection.py` (create)

**Interfaces:**
- Produces: `get_connection(slug)` unchanged in signature; WAL enabled, migrations memoised per process and slug

- [ ] **Step 1: Write the failing test**

```python
# tests/test_database_connection.py
import pytest
from api.config import get_settings


@pytest.mark.asyncio
async def test_connections_are_wal(tmp_path, monkeypatch):
    """journal_mode=delete makes writers block readers on one project file, and
    completions - the heavy writes - cluster at the end of a break."""
    monkeypatch.setenv("DATABASE_DIR", str(tmp_path))
    get_settings.cache_clear()
    from api.database import get_connection
    async with get_connection("waltest") as conn:
        cur = await conn.execute("PRAGMA journal_mode")
        assert (await cur.fetchone())[0].lower() == "wal"
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_migrations_run_once_per_slug(tmp_path, monkeypatch):
    """28 migration functions on every open, ~4.2ms, and one request opens several."""
    monkeypatch.setenv("DATABASE_DIR", str(tmp_path))
    get_settings.cache_clear()
    import api.database as db
    calls = []
    original = db._migrate_interview_answers

    async def counting(conn):
        calls.append(1)
        await original(conn)

    monkeypatch.setattr(db, "_migrate_interview_answers", counting)
    db._MIGRATED.clear()
    async with db.get_connection("oncetest") as conn:
        await conn.execute("SELECT 1")
    async with db.get_connection("oncetest") as conn:
        await conn.execute("SELECT 1")
    assert len(calls) == 1, f"migrations ran {len(calls)} times for one slug"
    get_settings.cache_clear()
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `./venv/bin/pytest tests/test_database_connection.py -v`
Expected: FAIL - first on `journal_mode` returning `delete`, second on `AttributeError: _MIGRATED`

- [ ] **Step 3: Change `get_connection`**

In `api/database.py`, add above `get_connection`:

```python
# Slugs whose migrations have run in this process. The 27 _migrate_* functions plus
# init_db are idempotent by construction, but they were running on every connection open -
# about 4.2ms, and a single interview request opens several connections.
_MIGRATED: set[str] = set()
```

Then restructure the body:

```python
async def get_connection(slug: str):
    path = get_db_path(slug)
    path.parent.mkdir(parents=True, exist_ok=True)
    async with aiosqlite.connect(path) as conn:
        conn.row_factory = aiosqlite.Row
        await conn.execute("PRAGMA foreign_keys = ON")
        # WAL lets readers proceed while a completion writes. Under journal_mode=delete
        # they block each other, and completions cluster at the end of a break.
        await conn.execute("PRAGMA journal_mode = WAL")
        await conn.execute("PRAGMA busy_timeout = 10000")
        if slug not in _MIGRATED:
            await init_db(conn)
            # ... every existing await _migrate_*(conn) line, unchanged, in order ...
            await _migrate_registry_output_type(conn)
            _MIGRATED.add(slug)
        yield conn
```

Keep all 27 migration calls in their current order. Only the guard and the two pragmas are new.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `./venv/bin/pytest tests/test_database_connection.py -v`
Expected: PASS

- [ ] **Step 5: Run the whole suite twice**

Run: `./venv/bin/pytest -q` then `./venv/bin/pytest -q`
Expected: identical counts both times. Memoisation is process-global, so a test that creates a database, deletes it, and recreates it under the same slug would now skip migrations - if any test fails here, add `_MIGRATED.discard(slug)` to that test's fixture teardown rather than removing the memoisation.

- [ ] **Step 6: Commit**

```bash
git add api/database.py tests/test_database_connection.py
git commit -m "perf(db): WAL, a busy timeout, and migrations that run once per slug

Connections opened in journal_mode=delete, where writers block readers on one project
file - and completions are the heavy writes, clustering at the end of a lunch break.
init_db plus 27 _migrate_* functions also ran on every open, ~4.2ms, several times per
interview request."
```

---

## Task 6: One answer set per session, however many times it is submitted

`interview_answers` has no uniqueness on `(session_id, question_id)`. A second `PATCH /complete` - two tabs, a retry, a flaky connection - writes the entire answer set again, and Casey then synthesises from a corpus with duplicates.

SQLite cannot add a constraint to an existing table, so this is a unique index. No environment currently holds any `interview_answers` rows, but the migration de-duplicates first so it is safe where they exist.

**Files:**
- Modify: `api/database.py` (`_migrate_interview_answers`, `insert_interview_answer`)
- Test: `tests/test_interview_concurrency.py`

**Interfaces:**
- Produces: `insert_interview_answer(conn, **fields) -> int` - unchanged signature, now an upsert

- [ ] **Step 1: Write the failing test**

```python
# tests/test_interview_concurrency.py  (append)
@pytest.mark.asyncio
async def test_completing_twice_writes_one_answer_set(client):
    """Driven through the endpoint twice, not by calling record_answers twice.

    The constraint lives on the table but the guard lives in the endpoint, and CLAUDE.md
    records five occasions where a test verified a property one layer from where it holds.
    """
    pairs = [{"question_id": "q1", "question": "Q one?", "answer": "A one"},
             {"question_id": "q2", "question": "Q two?", "answer": "A two"}]
    for _ in range(2):
        r = await client.patch("/api/interviews/dup-token/complete", json={"qa_pairs": pairs})
        assert r.status_code == 200

    from api.database import get_connection
    async with get_connection("dupproj") as conn:
        cur = await conn.execute(
            "SELECT COUNT(*) FROM interview_answers WHERE session_id="
            "(SELECT id FROM interview_sessions WHERE session_token='dup-token')"
        )
        assert (await cur.fetchone())[0] == 2, "the second completion duplicated the corpus"
```

Seed `dupproj` with a project, a session with token `dup-token`, and a current `interview_scripts` artefact containing `q1` and `q2`, using the same fixture shape as Task 1's `served_project`.

- [ ] **Step 2: Run the test to verify it fails**

Run: `./venv/bin/pytest tests/test_interview_concurrency.py -v`
Expected: FAIL with `assert 4 == 2`

- [ ] **Step 3: Add the unique index**

At the end of `_migrate_interview_answers` in `api/database.py`:

```python
    # One row per question per session. Without this a retried PATCH /complete - two tabs,
    # a flaky connection - appends the whole answer set again, and Casey synthesises from a
    # corpus with silent duplicates.
    #
    # Duplicates are collapsed before the index is created, keeping the lowest id because
    # that is the original write and `id` is the citation token later rows point at.
    await conn.execute("""
        DELETE FROM interview_answers WHERE id NOT IN (
            SELECT MIN(id) FROM interview_answers GROUP BY session_id, question_id
        )
    """)
    await conn.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS idx_interview_answers_session_question
        ON interview_answers(session_id, question_id)
    """)
```

- [ ] **Step 4: Make the insert an upsert**

In `insert_interview_answer`, change the statement to:

```python
    cur = await conn.execute(
        f"INSERT INTO interview_answers ({', '.join(columns)}) VALUES ({placeholders}) "
        f"ON CONFLICT(session_id, question_id) DO UPDATE SET "
        f"{', '.join(f'{c}=excluded.{c}' for c in columns if c not in ('session_id', 'question_id'))}",
        tuple(fields[c] for c in columns),
    )
```

A resubmission updates the existing row rather than adding one, so a corrected answer replaces its predecessor and the citation id survives.

- [ ] **Step 5: Run the tests to verify they pass**

Run: `./venv/bin/pytest tests/test_interview_concurrency.py tests/test_interview_answers.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add api/database.py tests/test_interview_concurrency.py
git commit -m "fix(interviews): one answer set per session however often it is submitted

interview_answers had no uniqueness on (session_id, question_id), so a retried
PATCH /complete appended the entire set again and Casey synthesised from a corpus with
silent duplicates. A unique index, with a de-duplicating migration for any environment
that already has rows, and the insert becomes an upsert so a citation id survives a
resubmission."
```

---

## Task 7: Secure mode uses a local Chroma, per project

Secure mode is a property of a project, not of a deployment: one server runs sensitive and standard projects side by side. `get_chroma_client()` took no arguments and read one global `CHROMA_API_KEY`, so it could not express that rule however it was configured. It has four callers and the rule applies to all of them.

**Files:**
- Modify: `api/services/chroma_client.py`, `api/services/interview_answer_service.py:186`, `api/services/ingest_service.py:115`, `api/services/chat_retrieval_service.py:32`, `agents/tools/chroma_query.py:113`
- Test: `tests/test_secure_mode_routing.py` (create)

**Interfaces:**
- Produces:
  - `project_llm_mode(slug: str) -> str` returning `"standard"` or `"sensitive"` (sync, cached)
  - `get_chroma_client(slug: str)` - **slug is now required**

- [ ] **Step 1: Write the failing test**

```python
# tests/test_secure_mode_routing.py
"""Secure mode is per-project, not per-deployment.

One server runs both kinds. Every test here therefore uses two projects in one process:
a per-deployment implementation passes any single-project test and fails only this shape.
"""
import sqlite3
import pytest
from api.config import get_settings


@pytest.fixture
def two_projects(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_DIR", str(tmp_path))
    monkeypatch.setenv("CHROMA_API_KEY", "cloud-key-is-set")
    get_settings.cache_clear()
    for slug, mode in (("secure-proj", "sensitive"), ("open-proj", "standard")):
        conn = sqlite3.connect(tmp_path / f"{slug}.db")
        conn.execute("CREATE TABLE projects (id INTEGER PRIMARY KEY, slug TEXT, "
                     "llm_mode TEXT, sector TEXT, config_json TEXT)")
        conn.execute("INSERT INTO projects (slug, llm_mode, sector) VALUES (?,?,?)",
                     (slug, mode, "test"))
        conn.commit()
        conn.close()
    from api.services import chroma_client
    chroma_client._MODE_CACHE.clear()
    yield
    get_settings.cache_clear()


def test_a_sensitive_project_never_reaches_cloud_chroma(two_projects, monkeypatch):
    """CHROMA_API_KEY is set, which is exactly the condition that used to force CloudClient."""
    import chromadb
    built = []
    monkeypatch.setattr(chromadb, "CloudClient", lambda **kw: built.append("cloud"))
    monkeypatch.setattr(chromadb, "HttpClient", lambda **kw: built.append("local"))
    from api.services.chroma_client import get_chroma_client
    get_chroma_client("secure-proj")
    assert built == ["local"]


def test_both_modes_are_honoured_in_one_process(two_projects, monkeypatch):
    """The test a per-deployment switch cannot pass."""
    import chromadb
    built = []
    monkeypatch.setattr(chromadb, "CloudClient", lambda **kw: built.append("cloud"))
    monkeypatch.setattr(chromadb, "HttpClient", lambda **kw: built.append("local"))
    from api.services.chroma_client import get_chroma_client
    get_chroma_client("secure-proj")
    get_chroma_client("open-proj")
    assert built == ["local", "cloud"]
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `./venv/bin/pytest tests/test_secure_mode_routing.py -v`
Expected: FAIL - `get_chroma_client()` takes no arguments

- [ ] **Step 3: Rewrite `chroma_client.py`**

```python
# api/services/chroma_client.py
"""Single source of ChromaDB client construction.

Secure mode is a property of a project, not of a deployment: one server runs sensitive and
standard projects side by side, so the choice cannot come from an environment variable
alone. A sensitive project uses a local Chroma even when CHROMA_API_KEY is set.

This is why the slug is required. The previous signature took no arguments and read one
global key, which made the per-project guarantee inexpressible rather than merely unwritten.
"""
import contextlib
import logging
import sqlite3

import chromadb

from api.config import get_settings

_log = logging.getLogger(__name__)

# Resolved once per slug per process. llm_mode changes only when a human edits the project.
_MODE_CACHE: dict[str, str] = {}


def project_llm_mode(slug: str) -> str:
    """The project's llm_mode, read synchronously.

    Sync because every caller is: index_answers, the ingest service and ChromaQueryTool all
    run outside the event loop or in a thread. Defaults to "standard" when the project or
    column cannot be read - a project that does not exist has no secrets to protect, and
    failing closed here would break ingest for every standard project on a bad read.
    """
    if slug in _MODE_CACHE:
        return _MODE_CACHE[slug]
    mode = "standard"
    db_path = get_settings().database_dir + f"/{slug}.db"
    with contextlib.suppress(sqlite3.Error, OSError):
        with contextlib.closing(sqlite3.connect(db_path)) as conn:
            row = conn.execute(
                "SELECT llm_mode FROM projects WHERE slug=?", (slug,)
            ).fetchone()
            if row and row[0]:
                mode = row[0]
    _MODE_CACHE[slug] = mode
    return mode


def get_chroma_client(slug: str):
    """A Chroma client for this project.

    Sensitive projects always get a local HttpClient. Standard projects get CloudClient when
    an API key is set, else the same local client.
    """
    settings = get_settings()
    if project_llm_mode(slug) == "sensitive":
        return chromadb.HttpClient(host=settings.chroma_host, port=settings.chroma_port)
    if settings.chroma_api_key:
        return chromadb.CloudClient(
            tenant=settings.chroma_tenant,
            database=settings.chroma_database,
            api_key=settings.chroma_api_key,
        )
    return chromadb.HttpClient(host=settings.chroma_host, port=settings.chroma_port)
```

- [ ] **Step 4: Pass the slug at all four call sites**

- `api/services/interview_answer_service.py:186` - `get_chroma_client(slug)`
- `api/services/ingest_service.py:115` - `get_chroma_client(slug)`
- `api/services/chat_retrieval_service.py:32` - `get_chroma_client(slug)`
- `agents/tools/chroma_query.py:113` - `get_chroma_client(self.slug)`

Each already has a slug in scope. Verify with `grep -n "get_chroma_client" api/ agents/ -r` - no call may remain argument-less.

- [ ] **Step 5: Run the tests**

Run: `./venv/bin/pytest tests/test_secure_mode_routing.py tests/test_interview_answers.py -q`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add api/services/chroma_client.py api/services/interview_answer_service.py api/services/ingest_service.py api/services/chat_retrieval_service.py agents/tools/chroma_query.py tests/test_secure_mode_routing.py
git commit -m "feat(secure): a sensitive project always uses a local Chroma

Secure mode is per-project, not per-deployment - one server runs both kinds. The client
factory took no arguments and read one global CHROMA_API_KEY, so the guarantee was
inexpressible rather than merely unwritten. It now takes a slug and resolves
projects.llm_mode, covering interviews, ingest, chat retrieval and ChromaQueryTool."
```

---

## Task 8: The elaboration press routes by mode and gives up on time

The press sends the question **and the interviewee's verbatim answer** to Anthropic, hardcoded, with no mode check. In secure mode it must use the local model. And because a local model is slower and serves fewer parallel requests, the press needs a budget: on expiry the endpoint returns no press and the interview moves to the next scripted question. A missed press costs depth on one answer; a ten-second silence costs the interviewee's confidence in the whole conversation.

The budget is configurable in Avery's settings, because the right value depends on the model behind it.

**Files:**
- Modify: `api/services/interview_service.py` (`elaboration_press`), `api/routers/interviews.py` (the session press endpoint)
- Test: `tests/test_secure_mode_routing.py`

**Interfaces:**
- Consumes: `project_llm_mode(slug)` from Task 7
- Produces: `elaboration_press(question_text, response_text, probing_instructions, stakeholder_name="", *, slug="", timeout_seconds=8.0) -> str` - returns `""` when the budget expires
- Config key: `elaboration_press_timeout_seconds` in `projects.config_json`, default `8`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_secure_mode_routing.py  (append)
@pytest.mark.asyncio
async def test_a_sensitive_project_presses_with_the_local_model(two_projects, monkeypatch):
    """Asserts the base URL the request went to, not that a mode helper was called.

    The defect being fixed is precisely that a correct-looking mode helper existed and the
    interview path never consulted it, so asserting the helper would reproduce the bug.
    """
    from api.services import interview_service as svc
    seen = {}

    class FakeMessages:
        async def create(self, **kw):
            seen.update(kw)
            class R:
                content = [type("T", (), {"text": "and then?"})()]
            return R()

    class FakeClient:
        def __init__(self, **kw):
            seen["base_url"] = kw.get("base_url")
            self.messages = FakeMessages()

    monkeypatch.setattr(svc, "AsyncAnthropic", FakeClient)
    await svc.elaboration_press("Q?", "short", "press", slug="secure-proj")
    assert seen["base_url"] == get_settings().llamacpp_base_url


@pytest.mark.asyncio
async def test_the_press_gives_up_on_budget_rather_than_stalling(two_projects, monkeypatch):
    """A local model under load must not hold a live interview open."""
    import asyncio
    from api.services import interview_service as svc

    async def never(*a, **k):
        await asyncio.sleep(5)

    monkeypatch.setattr(svc, "_press_call", never)
    result = await svc.elaboration_press("Q?", "short", "press",
                                         slug="open-proj", timeout_seconds=0.1)
    assert result == "", "an over-budget press must return no press, not raise or stall"
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `./venv/bin/pytest tests/test_secure_mode_routing.py -v`
Expected: FAIL - `elaboration_press()` got an unexpected keyword argument `slug`

- [ ] **Step 3: Rewrite `elaboration_press`**

```python
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

    Skips are logged, so a consistently over-budget model is visible rather than quiet.
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
    try:
        return await asyncio.wait_for(_press_call(prompt, slug), timeout=timeout_seconds)
    except asyncio.TimeoutError:
        _log.warning("elaboration_press[%s]: over budget at %.1fs - skipped", slug, timeout_seconds)
        return ""
```

Add `import asyncio`, `from api.services.chroma_client import project_llm_mode`, and a module `_log` if absent.

- [ ] **Step 4: Pass slug and the configured budget from the endpoint**

In `api/routers/interviews.py`, the session press endpoint resolves the slug from the token and reads the budget from `projects.config_json`:

```python
    db_path = await _find_session_db(session_token)
    if not db_path:
        raise HTTPException(status_code=404, detail="Session not found")
    slug = Path(db_path).stem
    async with get_connection(slug) as conn:
        cur = await conn.execute("SELECT config_json FROM projects WHERE slug=?", (slug,))
        row = await cur.fetchone()
    config = json.loads(row["config_json"]) if row and row["config_json"] else {}
    budget = float(config.get("elaboration_press_timeout_seconds", 8))

    press_text = await elaboration_press(
        body.question_text, body.response_text, body.probing_instructions,
        body.stakeholder_name, slug=slug, timeout_seconds=budget,
    )
    return {"press": press_text}
```

Leave `POST /test/elaboration-press` on the standard path with the default budget - it carries no client data and has no project.

- [ ] **Step 5: Run the tests**

Run: `./venv/bin/pytest tests/test_secure_mode_routing.py tests/test_interviews_router.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add api/services/interview_service.py api/routers/interviews.py tests/test_secure_mode_routing.py
git commit -m "feat(secure): the elaboration press routes by project mode and has a budget

The press sent the question and the interviewee's verbatim answer to Anthropic with no
mode check at all - the interview path contained no reference to llm_mode anywhere. It now
uses the local model for a sensitive project.

A local model is slower and serves fewer parallel requests, and the press is on the
request path with someone waiting, so it gives up at a configurable budget and returns no
press. A missed press costs depth on one answer; a long silence costs the interviewee's
confidence in the conversation."
```

---

## Task 9: The press budget is editable in Avery's settings

Per-agent configuration in this codebase lives in `projects.config_json` beside `interview_method` and the `brand_interviewer_*` keys, edited on the Settings page. The budget follows that pattern rather than introducing an agent-settings table for one value.

CLAUDE.md records "a radio tested as *rendered*; not as *sent*" - the same control on this same page. The test therefore asserts the value is persisted and read back, not that an input appeared.

**Files:**
- Modify: `ui/src/pages/Settings.tsx` (beside Interview Method, around line 270), `ui/src/types.ts`
- Test: `ui/src/__tests__/Settings.test.tsx`

**Interfaces:**
- Consumes: config key `elaboration_press_timeout_seconds`, default `8`, read by Task 8's endpoint

- [ ] **Step 1: Write the failing test**

```tsx
// ui/src/__tests__/Settings.test.tsx
it('sends the press budget when the form is saved', async () => {
  // Rendered is not sent. CLAUDE.md records a radio on this page that was tested as
  // rendered and shipped without ever being transmitted.
  const saved = vi.fn().mockResolvedValue({})
  vi.mocked(projectsApi.updateSettings).mockImplementation(saved)
  render(<Settings />)
  const input = await screen.findByLabelText(/follow-up time limit/i)
  fireEvent.change(input, { target: { value: '15' } })
  fireEvent.click(screen.getByRole('button', { name: /save/i }))
  await waitFor(() =>
    expect(saved).toHaveBeenCalledWith(
      expect.anything(),
      expect.objectContaining({ elaboration_press_timeout_seconds: 15 }),
    ))
})
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd ui && npx vitest run Settings`
Expected: FAIL - unable to find a label matching `/follow-up time limit/i`

- [ ] **Step 3: Add the field**

In `ui/src/types.ts`, add `elaboration_press_timeout_seconds: number` to `ProjectSettings`, and `elaboration_press_timeout_seconds: 8` to the default form state in `Settings.tsx` (near line 27, beside `interview_method: 'none'`).

In `Settings.tsx`, after the Interview Method block:

```tsx
<div className="mt-4">
  <label htmlFor="press-budget" className="text-xs text-gray-600 block mb-2">
    Follow-up time limit (seconds)
  </label>
  <input
    id="press-budget"
    type="number"
    min={1}
    max={60}
    value={form.elaboration_press_timeout_seconds}
    onChange={(e) => setForm({
      ...form,
      elaboration_press_timeout_seconds: Number(e.target.value),
    })}
    className="w-24 rounded border border-gray-300 px-2 py-1 text-sm"
  />
  <p className="text-xs text-muted mt-1">
    How long Avery waits for a follow-up question before moving on. A local model in
    secure mode needs longer than the hosted one.
  </p>
</div>
```

British English, no emoji, `brand`/`surface`/`text-muted` tokens only - no `sky-*` or `blue-*`.

- [ ] **Step 4: Run the frontend tests**

Run: `cd ui && npx vitest run && npx tsc --noEmit`
Expected: PASS, `tsc` clean

- [ ] **Step 5: Commit**

```bash
git add ui/src/pages/Settings.tsx ui/src/types.ts ui/src/__tests__/Settings.test.tsx
git commit -m "feat(ui): the follow-up time limit is editable in Avery's settings

The right budget depends on the model behind it: generous for Haiku, mean for a local
model on modest hardware. Asserted as sent and persisted rather than as rendered - this
page has form controls in its history that rendered correctly and were never transmitted."
```

---

## Task 10: One interview URL, built once

The SPA serves under basename `/dashboard`, but two of three builders omit it and use `frontend_url`, which is unset and defaults to `http://localhost:3000`. Only `campaign_service` builds a link that works. The emailed link is the entire mechanism for sub-project A.

**Files:**
- Modify: `api/services/interview_service.py` (add helper), `api/routers/interviews.py:92`, `agents/tools/interview_session_tool.py:120`, `api/services/campaign_service.py:371`
- Test: `tests/test_interview_url.py` (create)

**Interfaces:**
- Produces: `interview_url(session_token: str) -> str`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_interview_url.py
import pytest
from api.config import get_settings


def test_the_url_carries_the_dashboard_basename(monkeypatch):
    """The SPA is served under /dashboard (vite base, router basename). A link without it
    404s, and the emailed link is the whole mechanism for the dispatch campaign."""
    monkeypatch.setenv("PUBLIC_URL", "https://example.test")
    get_settings.cache_clear()
    from api.services.interview_service import interview_url
    assert interview_url("abc123") == "https://example.test/dashboard/interview/abc123"
    get_settings.cache_clear()


def test_every_builder_uses_the_helper():
    """Three call sites built this string independently and two were wrong."""
    from pathlib import Path
    import re
    offenders = []
    for path in (Path("api"), Path("agents")):
        for f in path.rglob("*.py"):
            for i, line in enumerate(f.read_text().splitlines(), 1):
                if re.search(r'f".*/interview/\{', line):
                    offenders.append(f"{f}:{i}")
    assert not offenders, f"interview URL built by hand at {offenders}"
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `./venv/bin/pytest tests/test_interview_url.py -v`
Expected: FAIL - `ImportError: cannot import name 'interview_url'`, then three offenders

- [ ] **Step 3: Add the helper and use it everywhere**

In `api/services/interview_service.py`:

```python
def interview_url(session_token: str) -> str:
    """The link an interviewee follows.

    public_url, not frontend_url: frontend_url is unset in every deployment and defaults to
    localhost. And /dashboard, because that is the SPA's vite base and router basename - a
    link without it 404s. Two of the three hand-built versions of this string got one or
    both wrong, and only the reminder email produced a working link.
    """
    return f"{get_settings().public_url}/dashboard/interview/{session_token}"
```

Replace the three call sites. `agents/tools/interview_session_tool.py` is synchronous - import the helper at the top of its function to avoid a circular import.

- [ ] **Step 4: Run the tests**

Run: `./venv/bin/pytest tests/test_interview_url.py tests/test_interview_session_tool.py tests/test_campaigns.py -q`
Expected: PASS. `test_campaigns.py` may assert the old string - update the assertion to the helper's output, since the helper is now the definition.

- [ ] **Step 5: Commit**

```bash
git add api/services/interview_service.py api/routers/interviews.py agents/tools/interview_session_tool.py api/services/campaign_service.py tests/test_interview_url.py
git commit -m "fix(interviews): build the interview link in one place

The SPA serves under basename /dashboard, but two of three builders omitted it and used
frontend_url, which is unset and defaults to localhost:3000. Only the reminder email
produced a working link, and the emailed link is the whole mechanism for the dispatch
campaign in sub-project A."
```

---

## Task 11: The session token is a credential, so treat it as one

`GET /api/interviews/sessions/{slug}` has no auth and returns every `session_token` for a project. Tokens are the sole credential for the entire public interview API, so anyone with a slug can read, answer and complete any interviewee's session. Separately, the token is generated by Taylor's prompt - "Generate a UUID4" - and the uniqueness of an access credential should not depend on a language model.

**Files:**
- Modify: `api/routers/interviews.py:46`, `agents/tools/interview_session_tool.py`, `agents/discovery/interview_coordinator.py:82`
- Test: `tests/test_interviews_router.py`, `tests/test_interview_session_tool.py`

**Interfaces:**
- Consumes: `require_any_auth` from `api.auth` (already used by the `/test/*` endpoints in this router)

- [ ] **Step 1: Write the failing test**

```python
# tests/test_interviews_router.py  (append)
@pytest.mark.asyncio
async def test_the_sessions_listing_requires_auth(client):
    """It returns every session_token for a project, and a token is the only credential
    the public interview API has. Anyone knowing a slug could answer anyone's interview."""
    r = await client.get("/api/interviews/sessions/any-slug")
    assert r.status_code in (401, 403), "session tokens are served without authentication"
```

```python
# tests/test_interview_session_tool.py  (append)
def test_the_token_is_generated_in_code(seeded_tool_project):
    """Taylor's prompt asked the model to 'Generate a UUID4'. The uniqueness of the sole
    access credential must not depend on a language model.

    seeded_tool_project is the existing fixture used by test_interview_session_tool_create;
    reuse it rather than building another. It yields (slug, orchestration_run_id) with
    stakeholder assignments already in place.
    """
    import sqlite3
    import uuid
    import contextlib
    from pathlib import Path
    from api.config import get_settings
    from agents.tools.interview_session_tool import InterviewSessionTool

    slug, run_id = seeded_tool_project
    InterviewSessionTool(slug=slug, orchestration_run_id=run_id)._run(operation="create")

    db = Path(get_settings().database_dir) / f"{slug}.db"
    with contextlib.closing(sqlite3.connect(db)) as conn:
        tokens = [r[0] for r in conn.execute(
            "SELECT session_token FROM interview_sessions WHERE orchestration_run_id=?",
            (run_id,),
        )]

    assert tokens, "create wrote no sessions - the fixture seeded no assignments"
    assert len(set(tokens)) == len(tokens), "duplicate session tokens"
    for token in tokens:
        assert uuid.UUID(token).version == 4, f"{token} is not a uuid4"
```

If the existing create test builds its project inline rather than through a fixture, extract
that setup into a `seeded_tool_project` fixture first and have both tests use it. Do not
duplicate the setup.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `./venv/bin/pytest tests/test_interviews_router.py::test_the_sessions_listing_requires_auth -v`
Expected: FAIL with `assert 200 in (401, 403)`

- [ ] **Step 3: Require auth on the listing**

```python
@router.get("/sessions/{slug}")
async def get_sessions_for_project(slug: str, payload: dict = Depends(require_any_auth)):
```

Add `require_any_auth` to the existing `api.auth` import if not already present. The module docstring says "Public interview endpoints - no auth required"; amend it to note that the sessions listing is the exception, and why.

- [ ] **Step 4: Generate the token in code**

In `agents/tools/interview_session_tool.py`, in `_create`, replace any model-supplied token with `session_token = str(uuid.uuid4())` and add `import uuid`. In `agents/discovery/interview_coordinator.py`, remove "Generate a UUID4 session_token" from the task text and state that session tokens are assigned when sessions are created, so Taylor does not invent one.

- [ ] **Step 5: Run the tests**

Run: `./venv/bin/pytest tests/test_interviews_router.py tests/test_interview_session_tool.py tests/test_discovery_interviews_agents.py -q`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add api/routers/interviews.py agents/tools/interview_session_tool.py agents/discovery/interview_coordinator.py tests/test_interviews_router.py tests/test_interview_session_tool.py
git commit -m "fix(interviews): treat the session token as the credential it is

GET /sessions/{slug} had no auth and returned every session_token for a project - and a
token is the sole credential for the whole public interview API, so a slug was enough to
answer anyone's interview. Tokens are now generated with uuid.uuid4() in code rather than
by asking Taylor's model for one."
```

---

## Task 12: Prove it under overlap

Everything above is a unit change. This is the property the sub-project exists for: several interviews running at once, through the real endpoints.

**Files:**
- Modify: `tests/test_interview_concurrency.py`

**Interfaces:**
- Consumes: every change from Tasks 1-11

- [ ] **Step 1: Write the fixture**

```python
# tests/test_interview_concurrency.py  (append)
from dataclasses import dataclass


@dataclass
class Campaign:
    slug: str
    tokens: list[str]


@pytest_asyncio.fixture
async def seeded_campaign(tmp_path, monkeypatch):
    """One project, twenty pending sessions, and a current interview_scripts artefact.

    Every session points at the same script, which is what a real cohort looks like: twenty
    frontline staff on SC-001, all invited on the same day.
    """
    import json
    monkeypatch.setenv("DATABASE_DIR", str(tmp_path))
    monkeypatch.setenv("PROJECTS_DIR", str(tmp_path / "projects"))
    get_settings.cache_clear()
    slug = "peak"
    outputs = tmp_path / "projects" / slug / "outputs"
    outputs.mkdir(parents=True)
    scripts = {"SC-001": {"script_id": "SC-001", "node_id": "1.F",
                          "node_label": "Frontline Interview", "level": "F",
                          "relationship": "internal",
                          "sections": [{"section_id": "s1", "questions": [
                              {"question_id": "q1", "text": "Q?"}]}]}}
    (outputs / "interview_scripts_v1.json").write_text(json.dumps(scripts))

    from api.database import get_connection
    tokens = [f"peak-token-{i:02d}" for i in range(20)]
    async with get_connection(slug) as conn:
        await conn.execute("INSERT INTO projects (slug, sector) VALUES (?,?)", (slug, "test"))
        await conn.commit()
        cur = await conn.execute("SELECT id FROM projects WHERE slug=?", (slug,))
        pid = (await cur.fetchone())[0]
        await conn.execute(
            "INSERT INTO agent_outputs (project_id, run_id, agent_name, output_type, "
            "version, is_current, file_path) VALUES (?,?,?,?,?,?,?)",
            (pid, 0, "interaction_designer", "interview_scripts", 1, 1,
             str(outputs / "interview_scripts_v1.json")),
        )
        for i, token in enumerate(tokens):
            await conn.execute(
                "INSERT INTO interview_sessions (project_id, stakeholder_id, node_label, "
                "session_token, status) VALUES (?,?,?,?,?)",
                (pid, i + 1, "Frontline Interview", token, "pending"),
            )
        await conn.commit()
    yield Campaign(slug=slug, tokens=tokens)
    get_settings.cache_clear()
```

- [ ] **Step 2: Write the test**

```python
# tests/test_interview_concurrency.py  (append)
@pytest.mark.asyncio
async def test_twenty_sessions_complete_concurrently(client, seeded_campaign):
    """Twenty simultaneous completions - the end of a lunch break.

    Asserts three things at once: every completion succeeds, no session sees a locked
    database, and each session's answers are its own. seeded_campaign creates one project
    with 20 sessions and a current interview_scripts artefact.
    """
    import asyncio
    pairs = [{"question_id": "q1", "question": "Q?", "answer": "A"}]

    async def complete(token):
        return await client.patch(f"/api/interviews/{token}/complete",
                                  json={"qa_pairs": pairs})

    results = await asyncio.gather(*[complete(t) for t in seeded_campaign.tokens])
    assert all(r.status_code == 200 for r in results)

    from api.database import get_connection
    async with get_connection(seeded_campaign.slug) as conn:
        cur = await conn.execute(
            "SELECT session_id, COUNT(*) FROM interview_answers GROUP BY session_id")
        counts = dict(await cur.fetchall())
    assert len(counts) == 20, "not every session recorded its answers"
    assert set(counts.values()) == {1}, f"answers leaked between sessions: {counts}"
```

- [ ] **Step 3: Run it**

Run: `./venv/bin/pytest tests/test_interview_concurrency.py -v`
Expected: PASS. A failure mentioning `database is locked` means Task 5's WAL change is not in effect for this connection path; a count above 1 means Task 6's unique index is missing.

- [ ] **Step 4: Run the whole suite twice**

Run: `./venv/bin/pytest -q` then `./venv/bin/pytest -q`
Expected: identical counts, both green.

- [ ] **Step 5: Run the frontend suite**

Run: `cd ui && npx vitest run && npx tsc --noEmit`
Expected: PASS, `tsc` clean

- [ ] **Step 6: Update CLAUDE.md**

Add to Known issues / tech debt:

```markdown
- Deepgram (STT) and ElevenLabs (TTS) are used in secure mode by decision, both being
  streamed with no content retention. Local speech services are future work, not a
  current requirement.
- Avery still blocks on `HumanInputTool` for up to 24 hours during an interview programme,
  and nothing notifies the crew when a session completes. It does not affect interviewee
  experience, which is why sub-project B left it alone.
```

- [ ] **Step 7: Commit**

```bash
git add tests/test_interview_concurrency.py CLAUDE.md
git commit -m "test(interviews): twenty sessions completing at once

The property the sub-project exists for, asserted through the endpoints: every completion
succeeds, none sees a locked database, and no session's answers leak into another's. No
test in the repository had ever run two interview sessions at the same time."
```

---

## Self-review

**Spec coverage**

| Spec requirement | Task |
|---|---|
| index_answers off the event loop | 2 |
| TTS cache keyed `(voice_id, text_hash)` | 4 |
| `prewarm_script_audio` entry point for A | 4 |
| Shared HTTP clients | 3 |
| WAL + busy_timeout | 5 |
| Memoised migrations | 5 |
| `UNIQUE(session_id, question_id)` + upsert | 6 |
| Idempotent `PATCH /complete` | 6 |
| `get_chroma_client(slug)`, per-project | 7 |
| `elaboration_press` routes by mode | 8 |
| Press budget, configurable in Avery's settings | 8, 9 |
| Auth on `GET /sessions/{slug}` | 11 |
| Single `interview_url()` helper | 10 |
| `session_token` generated in code | 11 |
| Concurrency harness | 2, 6, 12 |
| Per-project isolation test | 7 |
| Press setting asserted as sent | 9 |

Task 1 is not in the spec. It was found while writing this plan: `get_session_with_script` reads a bare `interview_scripts.json` that versioning means never exists, and keys the lookup by `node_label` against an artefact keyed by `script_id`. Every session is served `script: None`, so no interview can be conducted at all. It is first because nothing else in this plan matters while that holds.

**Placeholder scan:** none. Every code step carries the code.

**Type consistency:** `cache_key -> str` feeds `cached_audio(key: str)` and `store_audio(key: str, ...)`; `project_llm_mode(slug) -> str` is consumed by `get_chroma_client(slug)` and `_press_call(prompt, slug)`; `elaboration_press(..., slug="", timeout_seconds=8.0) -> str` matches the endpoint call in Task 8; `interview_url(session_token) -> str` matches all three replaced call sites; `synthesise` is defined in Task 4 and referenced by `prewarm_script_audio` in the same task.
