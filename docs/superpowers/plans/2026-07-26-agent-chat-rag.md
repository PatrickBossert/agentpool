# Agent Chat RAG + Project Document Library Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace agent chat's fixed 3,000-character document preview with retrieval over the whole project document library, and send shared images to Claude as vision inputs.

**Architecture:** A new `chat_retrieval_service.search()` queries the project's ChromaDB collection and returns attributed chunks. `agent_chat_service` injects those chunks into the system prompt and builds image content blocks. `chat_upload` ingests synchronously so a document is searchable before the user's next message. Chroma client construction is extracted from two duplicated call sites into one helper.

**Tech Stack:** FastAPI, ChromaDB (`CloudClient` or `HttpClient`), Anthropic SDK (`claude-haiku-4-5-20251001`, vision-capable), pytest + pytest-asyncio, `unittest.mock`.

**Spec:** `docs/superpowers/specs/2026-07-26-agent-chat-rag-design.md`

## Global Constraints

- Retrieval returns `k = 6` chunks by default. Chunks are 1000 chars with 200 overlap (existing `_chunk_text` defaults, unchanged).
- Retrieval queries collection `{slug}_docs` only. Never `sector_{sector}`.
- Retrieval runs on every chat turn, using the user's message verbatim, with no relevance threshold.
- Image upload cap is **4 MB raw** (Anthropic's limit is ~5 MB base64; encoding inflates by ~33%).
- Accepted image suffixes are exactly `.png .jpg .jpeg .webp .gif`.
- Chroma unreachable during **chat** must degrade silently (log, no chunks, answer anyway). Chroma unreachable during **upload** must fail the request with 502.
- Blocking Chroma and file-parsing calls must run via `asyncio.to_thread` - they run inside the FastAPI event loop.
- British English throughout (`-ise`, `-our`). Use ` - ` (spaced hyphen), never `—`, in any user-facing string or comment.
- Do not change `_chunk_text` parameters or introduce an `embedding_function`; that would invalidate existing collections.

## File Structure

| File | Responsibility |
|------|----------------|
| `api/services/chroma_client.py` (create) | Single source of Chroma client construction |
| `api/services/chat_retrieval_service.py` (create) | `search(slug, query, k)` → attributed chunks |
| `api/services/ingest_service.py` (modify) | Use shared client; raise on failure when asked; offload blocking work |
| `agents/tools/chroma_query.py` (modify) | Use shared client |
| `api/services/agent_chat_service.py` (modify) | Inject retrieved chunks; build image blocks |
| `api/routers/agent_chat.py` (modify) | Synchronous ingest, image size guard, drop preview |
| `.env.example` (modify) | Remove `PINECONE_API_KEY` |
| `tests/test_chroma_client.py` (create) | Client selection |
| `tests/test_chat_retrieval_service.py` (create) | Retrieval behaviour and failure modes |
| `tests/test_agent_chat_rag.py` (create) | Prompt injection and image blocks |
| `tests/test_chat_upload.py` (create) | Upload behaviour and library membership |

---

### Task 1: Shared Chroma client helper

**Files:**
- Create: `api/services/chroma_client.py`
- Modify: `api/services/ingest_service.py:60-68`
- Modify: `agents/tools/chroma_query.py:47-54`
- Test: `tests/test_chroma_client.py`

**Interfaces:**
- Consumes: `api.config.get_settings`
- Produces: `get_chroma_client() -> chromadb.ClientAPI`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_chroma_client.py
from unittest.mock import patch, MagicMock


def test_uses_cloud_client_when_api_key_set():
    with patch("api.services.chroma_client.chromadb") as m_chroma, \
         patch("api.services.chroma_client.get_settings") as m_settings:
        m_settings.return_value.chroma_api_key = "ck-test"
        m_settings.return_value.chroma_tenant = "tenant-1"
        m_settings.return_value.chroma_database = "db-1"
        from api.services.chroma_client import get_chroma_client
        get_chroma_client()
    m_chroma.CloudClient.assert_called_once_with(
        tenant="tenant-1", database="db-1", api_key="ck-test"
    )
    m_chroma.HttpClient.assert_not_called()


def test_uses_http_client_when_no_api_key():
    with patch("api.services.chroma_client.chromadb") as m_chroma, \
         patch("api.services.chroma_client.get_settings") as m_settings:
        m_settings.return_value.chroma_api_key = ""
        m_settings.return_value.chroma_host = "localhost"
        m_settings.return_value.chroma_port = 8002
        from api.services.chroma_client import get_chroma_client
        get_chroma_client()
    m_chroma.HttpClient.assert_called_once_with(host="localhost", port=8002)
    m_chroma.CloudClient.assert_not_called()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `./venv/bin/pytest tests/test_chroma_client.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'api.services.chroma_client'`

- [ ] **Step 3: Write minimal implementation**

```python
# api/services/chroma_client.py
"""Single source of ChromaDB client construction.

Cloud and local selection was duplicated in ingest_service and chroma_query.
Keeping it in one place means a change to how we connect cannot leave one
call site behind.
"""
import chromadb

from api.config import get_settings


def get_chroma_client():
    """Return a Chroma client: CloudClient when an API key is set, else HttpClient."""
    settings = get_settings()
    if settings.chroma_api_key:
        return chromadb.CloudClient(
            tenant=settings.chroma_tenant,
            database=settings.chroma_database,
            api_key=settings.chroma_api_key,
        )
    return chromadb.HttpClient(host=settings.chroma_host, port=settings.chroma_port)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `./venv/bin/pytest tests/test_chroma_client.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Replace the duplicated block in ingest_service**

In `api/services/ingest_service.py`, replace lines 60-69 (the `try:` block opening through `collection = client.get_or_create_collection(...)`) so the client comes from the helper:

```python
    try:
        client = get_chroma_client()
        collection = client.get_or_create_collection(f"{slug}_docs")
```

Add the import near the top, after `from api.config import get_settings`:

```python
from api.services.chroma_client import get_chroma_client
```

`import chromadb` is now unused in this file - remove it.

- [ ] **Step 6: Replace the duplicated block in chroma_query**

In `agents/tools/chroma_query.py`, replace lines 47-54 with:

```python
        client = get_chroma_client()
```

Add the import after `from api.config import get_settings`:

```python
from api.services.chroma_client import get_chroma_client
```

`import chromadb` is now unused in this file - remove it. Leave `_chroma_reachable` and its guard on line 45 exactly as they are.

- [ ] **Step 7: Run the affected suites**

Run: `./venv/bin/pytest tests/test_chroma_client.py tests/test_ingest_service.py -v`
Expected: PASS, no regressions

Note: `tests/test_ingest_service.py` patches `chromadb` inside `ingest_service`. After this change it must patch the helper instead. Update its patch targets from `api.services.ingest_service.chromadb` to `api.services.ingest_service.get_chroma_client`, adjusting each mock so `get_chroma_client.return_value` is the client object those tests previously built via `mock_chroma.HttpClient.return_value`. Assertions such as `mock_chroma.HttpClient.assert_not_called()` become assertions on `get_chroma_client` call counts.

- [ ] **Step 8: Commit**

```bash
git add api/services/chroma_client.py tests/test_chroma_client.py \
        api/services/ingest_service.py agents/tools/chroma_query.py \
        tests/test_ingest_service.py
git commit -m "refactor: single source of ChromaDB client construction"
```

---

### Task 2: Retrieval service

**Files:**
- Create: `api/services/chat_retrieval_service.py`
- Test: `tests/test_chat_retrieval_service.py`

**Interfaces:**
- Consumes: `api.services.chroma_client.get_chroma_client`
- Produces: `RETRIEVAL_TOP_K: int = 6`; `search(slug: str, query: str, k: int = RETRIEVAL_TOP_K) -> list[dict]` where each dict is `{"text": str, "filename": str, "doc_id": int | None}`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_chat_retrieval_service.py
from unittest.mock import patch, MagicMock


def _client_returning(documents, metadatas, count=10):
    col = MagicMock()
    col.count.return_value = count
    col.query.return_value = {"documents": [documents], "metadatas": [metadatas]}
    client = MagicMock()
    client.get_collection.return_value = col
    return client, col


def test_returns_attributed_chunks():
    client, col = _client_returning(
        ["chunk one", "chunk two"],
        [{"filename": "a.pdf", "doc_id": 1}, {"filename": "b.docx", "doc_id": 2}],
    )
    with patch("api.services.chat_retrieval_service.get_chroma_client", return_value=client):
        from api.services.chat_retrieval_service import search
        result = search("acme", "what is the process?", k=2)

    assert result == [
        {"text": "chunk one", "filename": "a.pdf", "doc_id": 1},
        {"text": "chunk two", "filename": "b.docx", "doc_id": 2},
    ]
    client.get_collection.assert_called_once_with("acme_docs")
    col.query.assert_called_once_with(query_texts=["what is the process?"], n_results=2)


def test_returns_empty_when_collection_missing():
    client = MagicMock()
    client.get_collection.side_effect = Exception("not found")
    with patch("api.services.chat_retrieval_service.get_chroma_client", return_value=client):
        from api.services.chat_retrieval_service import search
        assert search("acme", "anything") == []


def test_returns_empty_when_client_unreachable():
    with patch("api.services.chat_retrieval_service.get_chroma_client",
               side_effect=Exception("connection refused")):
        from api.services.chat_retrieval_service import search
        assert search("acme", "anything") == []


def test_returns_empty_for_empty_collection():
    client, _ = _client_returning([], [], count=0)
    with patch("api.services.chat_retrieval_service.get_chroma_client", return_value=client):
        from api.services.chat_retrieval_service import search
        assert search("acme", "anything") == []


def test_caps_n_results_at_collection_count():
    client, col = _client_returning(["only chunk"], [{"filename": "a.pdf", "doc_id": 1}], count=1)
    with patch("api.services.chat_retrieval_service.get_chroma_client", return_value=client):
        from api.services.chat_retrieval_service import search
        search("acme", "q", k=6)
    col.query.assert_called_once_with(query_texts=["q"], n_results=1)


def test_tolerates_missing_metadata():
    client, _ = _client_returning(["chunk"], [None])
    with patch("api.services.chat_retrieval_service.get_chroma_client", return_value=client):
        from api.services.chat_retrieval_service import search
        assert search("acme", "q") == [
            {"text": "chunk", "filename": "unknown", "doc_id": None}
        ]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `./venv/bin/pytest tests/test_chat_retrieval_service.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'api.services.chat_retrieval_service'`

- [ ] **Step 3: Write minimal implementation**

```python
# api/services/chat_retrieval_service.py
"""Semantic retrieval over a project's ingested documents, for agent chat.

Agent chat previously injected a fixed 3,000-character slice of an attached
document into the system prompt, so a long document was visible only as its
opening pages. This searches the whole project collection instead.

Every failure returns an empty list. Retrieval enhances a chat turn; it must
never break one.
"""
import logging

from api.services.chroma_client import get_chroma_client

logger = logging.getLogger(__name__)

RETRIEVAL_TOP_K = 6


def search(slug: str, query: str, k: int = RETRIEVAL_TOP_K) -> list[dict]:
    """Return up to k relevant chunks from the project's document collection.

    Each chunk is {"text", "filename", "doc_id"}. filename and doc_id come from
    the metadata ingest_document writes, and let the caller tell the agent which
    document a passage came from.

    Returns [] when the collection is missing, empty, or Chroma is unreachable.
    """
    if not query.strip():
        return []

    try:
        client = get_chroma_client()
        collection = client.get_collection(f"{slug}_docs")
        count = collection.count()
        if not count:
            return []
        results = collection.query(query_texts=[query], n_results=min(k, count))
    except Exception as exc:
        logger.warning("chat retrieval failed for project %s: %s", slug, exc)
        return []

    documents = (results.get("documents") or [[]])[0]
    metadatas = (results.get("metadatas") or [[]])[0]

    chunks: list[dict] = []
    for i, text in enumerate(documents):
        meta = metadatas[i] if i < len(metadatas) and metadatas[i] else {}
        chunks.append({
            "text": text,
            "filename": meta.get("filename", "unknown"),
            "doc_id": meta.get("doc_id"),
        })
    return chunks
```

- [ ] **Step 4: Run test to verify it passes**

Run: `./venv/bin/pytest tests/test_chat_retrieval_service.py -v`
Expected: PASS (6 passed)

- [ ] **Step 5: Commit**

```bash
git add api/services/chat_retrieval_service.py tests/test_chat_retrieval_service.py
git commit -m "feat: add semantic retrieval service for agent chat"
```

---

### Task 3: Inject retrieved chunks into the chat prompt

**Files:**
- Modify: `api/services/agent_chat_service.py` (imports; `run_agent_chat` at line 395)
- Test: `tests/test_agent_chat_rag.py`

**Interfaces:**
- Consumes: `api.services.chat_retrieval_service.search`, `RETRIEVAL_TOP_K`
- Produces: `_format_retrieved(chunks: list[dict]) -> str`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_agent_chat_rag.py
import pytest
from unittest.mock import patch, AsyncMock, MagicMock


def test_format_retrieved_labels_each_chunk_with_its_source():
    from api.services.agent_chat_service import _format_retrieved
    out = _format_retrieved([
        {"text": "alpha text", "filename": "a.pdf", "doc_id": 1},
        {"text": "beta text", "filename": "b.docx", "doc_id": 2},
    ])
    assert "Retrieved from project documents" in out
    assert "[a.pdf] alpha text" in out
    assert "[b.docx] beta text" in out


def test_format_retrieved_empty_returns_empty_string():
    from api.services.agent_chat_service import _format_retrieved
    assert _format_retrieved([]) == ""
```

- [ ] **Step 2: Run test to verify it fails**

Run: `./venv/bin/pytest tests/test_agent_chat_rag.py -v`
Expected: FAIL with `ImportError: cannot import name '_format_retrieved'`

- [ ] **Step 3: Write minimal implementation**

Add to `api/services/agent_chat_service.py`, above `run_agent_chat`:

```python
def _format_retrieved(chunks: list[dict]) -> str:
    """Render retrieved chunks as a prompt block, each labelled with its source.

    Attribution matters: without the filename the agent cannot tell the user
    which document an answer came from.
    """
    if not chunks:
        return ""
    lines = ["--- Retrieved from project documents ---"]
    for chunk in chunks:
        lines.append(f"[{chunk['filename']}] {chunk['text']}")
    return "\n".join(lines)
```

Add the import near the other service imports at the top of the file:

```python
from api.services.chat_retrieval_service import search as retrieve_chunks
```

- [ ] **Step 4: Run test to verify it passes**

Run: `./venv/bin/pytest tests/test_agent_chat_rag.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Write the failing integration-level test**

Append to `tests/test_agent_chat_rag.py`:

```python
@pytest.mark.asyncio
async def test_retrieved_chunks_reach_the_system_prompt(client):
    """The user's message is used as the query and results land in the prompt."""
    await client.post("/projects", json={
        "client_slug": "rag-test", "llm_mode": "standard", "sector": "rail",
    })

    captured = {}

    async def fake_create(**kwargs):
        captured["system"] = kwargs.get("system", "")
        r = MagicMock()
        r.content = [MagicMock(text="ok")]
        return r

    with patch("api.services.agent_chat_service.AsyncAnthropic") as mock_cls, \
         patch("api.services.agent_chat_service.retrieve_chunks") as mock_search:
        mock_search.return_value = [
            {"text": "the warehouse runs two shifts", "filename": "ops.pdf", "doc_id": 1},
        ]
        inst = AsyncMock()
        inst.messages.create = fake_create
        mock_cls.return_value = inst

        resp = await client.post("/projects/rag-test/agent-chat", json={
            "agent_name": "Interview Coordinator",
            "message": "how many shifts?",
            "history": [],
        })

    assert resp.status_code == 200
    mock_search.assert_called_once()
    assert mock_search.call_args.args[0] == "rag-test"
    assert mock_search.call_args.args[1] == "how many shifts?"
    assert "the warehouse runs two shifts" in captured["system"]
    assert "[ops.pdf]" in captured["system"]


@pytest.mark.asyncio
async def test_no_retrieval_results_produces_no_retrieval_section(client):
    await client.post("/projects", json={
        "client_slug": "rag-empty", "llm_mode": "standard", "sector": "rail",
    })
    captured = {}

    async def fake_create(**kwargs):
        captured["system"] = kwargs.get("system", "")
        r = MagicMock()
        r.content = [MagicMock(text="ok")]
        return r

    with patch("api.services.agent_chat_service.AsyncAnthropic") as mock_cls, \
         patch("api.services.agent_chat_service.retrieve_chunks", return_value=[]):
        inst = AsyncMock()
        inst.messages.create = fake_create
        mock_cls.return_value = inst
        await client.post("/projects/rag-empty/agent-chat", json={
            "agent_name": "Interview Coordinator", "message": "hello", "history": [],
        })

    assert "Retrieved from project documents" not in captured["system"]
```

- [ ] **Step 6: Run test to verify it fails**

Run: `./venv/bin/pytest tests/test_agent_chat_rag.py -v`
Expected: FAIL - `mock_search.assert_called_once()` fails because nothing calls it yet

- [ ] **Step 7: Wire retrieval into run_agent_chat**

In `api/services/agent_chat_service.py`, inside `run_agent_chat`, immediately after the `async with get_connection(slug) as conn:` block closes (after the `else:` branch that builds `system_prompt`, currently ending line 442) and **before** the existing `if injected_docs:` block, insert:

```python
    # Retrieval runs on every turn - see the design spec for why there is no
    # relevance threshold. Chroma's client is synchronous, so keep it off the
    # event loop.
    retrieved = await asyncio.to_thread(retrieve_chunks, slug, message, RETRIEVAL_TOP_K)
    retrieved_block = _format_retrieved(retrieved)
    if retrieved_block:
        system_prompt += f"\n\n{retrieved_block}"
```

Add `RETRIEVAL_TOP_K` to the existing retrieval import:

```python
from api.services.chat_retrieval_service import RETRIEVAL_TOP_K, search as retrieve_chunks
```

Add `import asyncio` to the file's imports if it is not already present.

- [ ] **Step 8: Run test to verify it passes**

Run: `./venv/bin/pytest tests/test_agent_chat_rag.py -v`
Expected: PASS (4 passed)

- [ ] **Step 9: Commit**

```bash
git add api/services/agent_chat_service.py tests/test_agent_chat_rag.py
git commit -m "feat: retrieve project documents on every agent chat turn"
```

---

### Task 4: Images as Claude vision inputs

**Files:**
- Modify: `api/services/agent_chat_service.py` (`run_agent_chat`, lines 444-465)
- Test: `tests/test_agent_chat_rag.py` (append)

**Interfaces:**
- Consumes: `injected_docs` entries shaped `{"doc_id": int, "original_name": str, "is_image": bool}`; `api.database.fetch_documents`
- Produces: `IMAGE_MEDIA_TYPES: dict[str, str]`; `_build_image_blocks(conn, project_id: int, docs: list[dict]) -> list[dict]`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_agent_chat_rag.py`:

```python
import base64
from pathlib import Path


def test_image_media_types_cover_every_accepted_suffix():
    from api.routers.agent_chat import _IMAGE_SUFFIXES
    from api.services.agent_chat_service import IMAGE_MEDIA_TYPES
    assert set(IMAGE_MEDIA_TYPES) == _IMAGE_SUFFIXES


@pytest.mark.asyncio
async def test_image_becomes_a_base64_content_block(client, tmp_path):
    """An attached image is sent to Claude as an image block, not as text."""
    await client.post("/projects", json={
        "client_slug": "vision-test", "llm_mode": "standard", "sector": "rail",
    })

    png_bytes = b"\x89PNG\r\n\x1a\nFAKEIMAGEDATA"
    img = tmp_path / "chart.png"
    img.write_bytes(png_bytes)

    from api.database import get_connection, fetch_project, insert_document
    async with get_connection("vision-test") as conn:
        project = await fetch_project(conn, slug="vision-test")
        doc_id = await insert_document(
            conn, project_id=project["id"], filename="chart.png",
            original_name="chart.png", file_path=str(img),
            content_type="image/png", size_bytes=len(png_bytes),
        )

    captured = {}

    async def fake_create(**kwargs):
        captured["messages"] = kwargs.get("messages", [])
        r = MagicMock()
        r.content = [MagicMock(text="ok")]
        return r

    with patch("api.services.agent_chat_service.AsyncAnthropic") as mock_cls, \
         patch("api.services.agent_chat_service.retrieve_chunks", return_value=[]):
        inst = AsyncMock()
        inst.messages.create = fake_create
        mock_cls.return_value = inst
        resp = await client.post("/projects/vision-test/agent-chat", json={
            "agent_name": "Interview Coordinator",
            "message": "what does this show?",
            "history": [],
            "injected_docs": [
                {"doc_id": doc_id, "original_name": "chart.png", "is_image": True}
            ],
        })

    assert resp.status_code == 200
    final = captured["messages"][-1]
    blocks = final["content"]
    assert isinstance(blocks, list)
    image_blocks = [b for b in blocks if b["type"] == "image"]
    assert len(image_blocks) == 1
    assert image_blocks[0]["source"]["media_type"] == "image/png"
    assert image_blocks[0]["source"]["data"] == base64.b64encode(png_bytes).decode()
    text_blocks = [b for b in blocks if b["type"] == "text"]
    assert text_blocks[0]["text"] == "what does this show?"


@pytest.mark.asyncio
async def test_text_only_turn_sends_a_plain_string(client):
    """With no images the message stays a plain string - no needless block wrapping."""
    await client.post("/projects", json={
        "client_slug": "vision-none", "llm_mode": "standard", "sector": "rail",
    })
    captured = {}

    async def fake_create(**kwargs):
        captured["messages"] = kwargs.get("messages", [])
        r = MagicMock()
        r.content = [MagicMock(text="ok")]
        return r

    with patch("api.services.agent_chat_service.AsyncAnthropic") as mock_cls, \
         patch("api.services.agent_chat_service.retrieve_chunks", return_value=[]):
        inst = AsyncMock()
        inst.messages.create = fake_create
        mock_cls.return_value = inst
        await client.post("/projects/vision-none/agent-chat", json={
            "agent_name": "Interview Coordinator", "message": "hi", "history": [],
        })

    assert captured["messages"][-1]["content"] == "hi"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `./venv/bin/pytest tests/test_agent_chat_rag.py -v`
Expected: FAIL with `ImportError: cannot import name 'IMAGE_MEDIA_TYPES'`

- [ ] **Step 3: Write minimal implementation**

Add to `api/services/agent_chat_service.py`, next to `_format_retrieved`:

```python
IMAGE_MEDIA_TYPES = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".gif": "image/gif",
}


async def _build_image_blocks(conn, project_id: int, docs: list[dict]) -> list[dict]:
    """Turn attached image documents into Anthropic image content blocks.

    Paths are resolved from client_documents by doc_id rather than taken from the
    request, so a caller cannot point this at an arbitrary file on disk.
    Unreadable or unrecognised files are skipped rather than failing the turn.
    """
    wanted = {d["doc_id"] for d in docs if d.get("is_image") and d.get("doc_id") is not None}
    if not wanted:
        return []

    rows = await fetch_documents(conn, project_id=project_id)
    blocks: list[dict] = []
    for row in rows:
        if row["id"] not in wanted:
            continue
        path = Path(row["file_path"])
        media_type = IMAGE_MEDIA_TYPES.get(path.suffix.lower())
        if media_type is None:
            continue
        try:
            data = await asyncio.to_thread(path.read_bytes)
        except OSError as exc:
            logger.warning("agent chat: could not read image %s: %s", path, exc)
            continue
        blocks.append({
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": media_type,
                "data": base64.b64encode(data).decode(),
            },
        })
    return blocks
```

Add these imports to the top of the file if not already present:

```python
import base64
import logging
from pathlib import Path

from api.database import fetch_documents

logger = logging.getLogger(__name__)
```

- [ ] **Step 4: Replace the injected_docs block and message assembly**

In `run_agent_chat`, replace the whole existing `if injected_docs:` block (lines 444-451, which appends `preview_text` to the system prompt) with nothing - retrieval has replaced it. Leave the `if injected_links:` block untouched.

Then move image resolution inside the database block. Immediately before the `async with get_connection(slug) as conn:` block ends, add:

```python
        image_blocks = await _build_image_blocks(conn, project["id"], injected_docs or [])
```

Finally, replace the user-message append (currently `api_messages.append({"role": "user", "content": message})`) with:

```python
    if image_blocks:
        api_messages.append({
            "role": "user",
            "content": [*image_blocks, {"type": "text", "text": message}],
        })
    else:
        api_messages.append({"role": "user", "content": message})
```

- [ ] **Step 5: Run test to verify it passes**

Run: `./venv/bin/pytest tests/test_agent_chat_rag.py -v`
Expected: PASS (8 passed)

- [ ] **Step 6: Commit**

```bash
git add api/services/agent_chat_service.py tests/test_agent_chat_rag.py
git commit -m "feat: send chat-shared images to Claude as vision inputs"
```

---

### Task 5: Synchronous ingestion, loud failure, image size guard

**Files:**
- Modify: `api/services/ingest_service.py` (`ingest_document`)
- Modify: `api/routers/agent_chat.py:38-41` (`InjectedDoc`), `:209-288` (`chat_upload`)
- Test: `tests/test_chat_upload.py`

**Interfaces:**
- Consumes: `api.services.ingest_service.ingest_document`
- Produces: `IngestError(Exception)`; `ingest_document(slug, doc_id, file_path, *, raise_on_error: bool = False)`; `MAX_IMAGE_BYTES: int = 4 * 1024 * 1024`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_chat_upload.py
import pytest
from unittest.mock import patch, AsyncMock

SLUG = "upload-test"


async def _make_project(client):
    await client.post("/projects", json={
        "client_slug": SLUG, "llm_mode": "standard", "sector": "rail",
    })


@pytest.mark.asyncio
async def test_upload_ingests_before_responding(client):
    """Ingestion is awaited, not queued - the document is searchable on return."""
    await _make_project(client)
    with patch("api.routers.agent_chat.ingest_document", new_callable=AsyncMock) as m_ingest:
        resp = await client.post(
            f"/projects/{SLUG}/agent-chat/upload",
            data={"agent_name": "Interview Coordinator"},
            files={"file": ("notes.txt", b"warehouse runs two shifts", "text/plain")},
        )
    assert resp.status_code == 201
    m_ingest.assert_awaited_once()
    assert m_ingest.await_args.kwargs["raise_on_error"] is True


@pytest.mark.asyncio
async def test_upload_fails_loudly_when_ingestion_fails(client):
    """A Chroma outage must not produce a document that looks uploaded but is invisible."""
    await _make_project(client)
    from api.services.ingest_service import IngestError
    with patch("api.routers.agent_chat.ingest_document",
               new_callable=AsyncMock, side_effect=IngestError("chroma down")):
        resp = await client.post(
            f"/projects/{SLUG}/agent-chat/upload",
            data={"agent_name": "Interview Coordinator"},
            files={"file": ("notes.txt", b"some text", "text/plain")},
        )
    assert resp.status_code == 502
    assert "index" in resp.json()["detail"].lower()


@pytest.mark.asyncio
async def test_response_no_longer_carries_preview_text(client):
    await _make_project(client)
    with patch("api.routers.agent_chat.ingest_document", new_callable=AsyncMock):
        resp = await client.post(
            f"/projects/{SLUG}/agent-chat/upload",
            data={"agent_name": "Interview Coordinator"},
            files={"file": ("notes.txt", b"some text", "text/plain")},
        )
    assert resp.status_code == 201
    assert "preview_text" not in resp.json()


@pytest.mark.asyncio
async def test_oversized_image_rejected(client):
    await _make_project(client)
    from api.routers.agent_chat import MAX_IMAGE_BYTES
    oversized = b"\x89PNG\r\n\x1a\n" + b"x" * MAX_IMAGE_BYTES
    resp = await client.post(
        f"/projects/{SLUG}/agent-chat/upload",
        data={"agent_name": "Interview Coordinator"},
        files={"file": ("big.png", oversized, "image/png")},
    )
    assert resp.status_code == 422
    assert "4 MB" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_image_upload_skips_ingestion(client):
    """Images cannot be embedded by a text pipeline - do not try."""
    await _make_project(client)
    with patch("api.routers.agent_chat.ingest_document", new_callable=AsyncMock) as m_ingest:
        resp = await client.post(
            f"/projects/{SLUG}/agent-chat/upload",
            data={"agent_name": "Interview Coordinator"},
            files={"file": ("chart.png", b"\x89PNG\r\n\x1a\ndata", "image/png")},
        )
    assert resp.status_code == 201
    assert resp.json()["is_image"] is True
    m_ingest.assert_not_awaited()


@pytest.mark.asyncio
async def test_document_with_no_extractable_text_still_uploads(client):
    """A scanned PDF yields no chunks. That is not an error - see the spec.

    raise_on_error=True must not turn 'nothing to index' into a failed upload,
    or every image-only PDF becomes an unexplained 502.
    """
    await _make_project(client)
    with patch("api.services.ingest_service._extract_text", return_value="   "):
        resp = await client.post(
            f"/projects/{SLUG}/agent-chat/upload",
            data={"agent_name": "Interview Coordinator"},
            files={"file": ("scanned.pdf", b"%PDF-1.4 fake", "application/pdf")},
        )
    assert resp.status_code == 201


@pytest.mark.asyncio
async def test_chat_upload_appears_in_project_documents(client):
    """Regression lock: chat uploads are project documents, not a separate store."""
    await _make_project(client)
    with patch("api.routers.agent_chat.ingest_document", new_callable=AsyncMock):
        upload = await client.post(
            f"/projects/{SLUG}/agent-chat/upload",
            data={"agent_name": "Interview Coordinator"},
            files={"file": ("shared.txt", b"content", "text/plain")},
        )
    doc_id = upload.json()["doc_id"]

    listing = await client.get(f"/projects/{SLUG}/documents")
    assert listing.status_code == 200
    assert doc_id in [d["id"] for d in listing.json()]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `./venv/bin/pytest tests/test_chat_upload.py -v`
Expected: FAIL - `ImportError: cannot import name 'IngestError'` and `MAX_IMAGE_BYTES`

- [ ] **Step 3: Make ingest_document able to fail loudly and stay off the event loop**

In `api/services/ingest_service.py`, add above `_extract_text`:

```python
class IngestError(Exception):
    """Raised when ingestion fails and the caller asked to be told."""
```

Replace the `ingest_document` signature and body with:

```python
async def ingest_document(
    slug: str, doc_id: int, file_path: str, *, raise_on_error: bool = False
) -> None:
    """Extract text, chunk, upsert to ChromaDB, then mark ingested=1 in SQLite.

    raise_on_error=True makes every failure raise IngestError. Callers that await
    this in a request path need that: if indexing is the only route to a document
    being usable, a silent failure leaves a document that looks uploaded and is
    permanently invisible. Background callers keep the default and only log.
    """
    path = Path(file_path)

    def _fail(message: str, exc: Exception | None = None) -> None:
        logger.warning("ingest_document: %s", message)
        if raise_on_error:
            raise IngestError(message) from exc

    if path.suffix.lower() not in SUPPORTED_SUFFIXES:
        logger.info("ingest_document: unsupported type %s, skipping", path.suffix)
        return

    try:
        text = await asyncio.to_thread(_extract_text, path)
    except Exception as exc:
        return _fail(f"text extraction failed for {path.name}: {exc}", exc)

    chunks = _chunk_text(text)
    if not chunks:
        logger.info("ingest_document: no text extracted from %s", path.name)
        return

    def _upsert() -> None:
        client = get_chroma_client()
        collection = client.get_or_create_collection(f"{slug}_docs")
        ids = [f"{path.name}::{i}" for i in range(len(chunks))]
        metadatas = [
            {"filename": path.name, "chunk": i, "doc_id": doc_id} for i in range(len(chunks))
        ]
        collection.upsert(documents=chunks, ids=ids, metadatas=metadatas)

    try:
        await asyncio.to_thread(_upsert)
    except Exception as exc:
        return _fail(f"ChromaDB upsert failed for {path.name}: {exc}", exc)

    try:
        async with get_connection(slug) as conn:
            await update_document_ingested(conn, doc_id=doc_id)
    except Exception as exc:
        return _fail(f"DB update failed for doc_id={doc_id}: {exc}", exc)
```

Add `import asyncio` to the top of the file.

- [ ] **Step 4: Update chat_upload**

In `api/routers/agent_chat.py`:

Give `InjectedDoc.preview_text` a default so existing clients that still send it keep working and new ones can omit it:

```python
class InjectedDoc(BaseModel):
    doc_id: int
    original_name: str
    preview_text: str = ""
    is_image: bool = False
```

Replace the `_PREVIEW_CHARS = 3_000` constant with:

```python
MAX_IMAGE_BYTES = 4 * 1024 * 1024  # Anthropic's limit is ~5 MB base64; encoding adds ~33%
```

`_PREVIEW_CHARS` is still used by the link-preview path at line 316 - keep the constant if that line still references it, otherwise remove it.

Add the size guard immediately after the existing suffix check in `chat_upload`:

```python
    content = await file.read()
    if suffix in _IMAGE_SUFFIXES and len(content) > MAX_IMAGE_BYTES:
        raise HTTPException(
            status_code=422,
            detail="Image is too large - the maximum is 4 MB.",
        )
```

Then remove the later `content = await file.read()` so the file is read once.

Replace the preview-and-queue block with an awaited ingest:

```python
    is_image = suffix in _IMAGE_SUFFIXES

    if not is_image:
        try:
            await ingest_document(slug, doc_id, str(dest), raise_on_error=True)
        except IngestError:
            raise HTTPException(
                status_code=502,
                detail="Document saved but could not be indexed for search - try again.",
            )

    return {
        "doc_id": doc_id,
        "filename": unique_name,
        "original_name": file.filename or unique_name,
        "is_image": is_image,
    }
```

Update the import to bring in the exception, and drop `_extract_text` if nothing else uses it:

```python
from api.services.ingest_service import SUPPORTED_SUFFIXES, IngestError, ingest_document
```

`BackgroundTasks` may now be unused in `chat_upload` - leave the parameter in place only if another route in this file uses it.

- [ ] **Step 5: Run test to verify it passes**

Run: `./venv/bin/pytest tests/test_chat_upload.py -v`
Expected: PASS (6 passed)

- [ ] **Step 6: Run the full unit suite for regressions**

Run: `./venv/bin/pytest -q --ignore=tests/integration`
Expected: PASS, no failures

- [ ] **Step 7: Commit**

```bash
git add api/services/ingest_service.py api/routers/agent_chat.py tests/test_chat_upload.py
git commit -m "feat: ingest chat uploads synchronously and fail loudly"
```

---

### Task 6: Remove Pinecone from .env.example

**Files:**
- Modify: `.env.example:47-48`

**Interfaces:**
- Consumes: nothing
- Produces: nothing

- [ ] **Step 1: Confirm nothing reads the variable**

Run:
```bash
grep -rn "PINECONE" --include='*.py' . | grep -v './venv'
grep -rn "pinecone" requirements.txt api/config.py
```
Expected: no output from either. `api/config.py` has no field, so `extra="ignore"` discards the key.

- [ ] **Step 2: Remove the section**

Delete these two lines and the blank line above them from `.env.example`:

```
# ── Pinecone (vector database) ───────────────────────────────────
PINECONE_API_KEY=pcsk_...
```

- [ ] **Step 3: Verify**

Run: `grep -c -i pinecone .env.example`
Expected: `0`

- [ ] **Step 4: Commit**

```bash
git add .env.example
git commit -m "chore: remove PINECONE_API_KEY from .env.example"
```

---

## Manual verification

Automated tests mock Chroma throughout. Before considering this done, verify against the real service - Chroma Cloud is configured and reachable:

1. Start the API: `./venv/bin/uvicorn api.main:app --reload`
2. Upload a multi-page PDF through an agent chat. Confirm the request takes noticeably longer than before (synchronous ingestion) and returns 201.
3. Confirm the document appears on the project's Documents page.
4. Ask the agent a question whose answer appears **only past the first 3,000 characters** of that PDF. Before this change the agent could not answer it. Confirm it now does, and cites the filename.
5. Share a PNG chart and ask what it shows. Confirm the agent describes the image.
6. Check the frontend: if it re-sends `injected_docs` on every turn, an image is re-encoded and re-billed each turn. If so, raise it as a follow-up.
