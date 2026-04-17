# SP7a — Document Ingestion Pipeline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Auto-ingest uploaded documents into ChromaDB (with `.txt`, `.md`, `.pdf`, `.docx` support) as a FastAPI background task, flipping `ingested=1` in SQLite on completion.

**Architecture:** A new `api/services/ingest_service.py` module owns all ingestion logic (text extraction, chunking, ChromaDB upsert, DB flag update). The upload endpoint in `api/routers/documents.py` enqueues `ingest_document` as a `BackgroundTask` after saving the file. `DocumentIngestionTool` (agent-side) is left unchanged.

**Tech Stack:** FastAPI BackgroundTasks, aiosqlite, chromadb, pypdf (existing), python-docx (existing, imported as `docx`)

---

## File Map

| File | Change |
|---|---|
| `api/database.py` | Add `update_document_ingested` helper |
| `api/services/ingest_service.py` | Create — `_extract_text`, `_chunk_text`, `ingest_document` |
| `api/routers/documents.py` | Add `BackgroundTasks` to upload endpoint |
| `tests/test_database.py` | One new test for `update_document_ingested` |
| `tests/test_ingest_service.py` | New file — 5 unit tests |
| `tests/test_documents.py` | One new integration test — ingested=True after upload |

---

### Task 1: DB helper — `update_document_ingested`

**Files:**
- Modify: `api/database.py` (after `fetch_documents`, around line 228)
- Test: `tests/test_database.py`

---

- [ ] **Step 1: Write the failing test**

Append to `tests/test_database.py`:

```python
@pytest.mark.asyncio
async def test_update_document_ingested(db):
    from api.database import insert_project, insert_document, update_document_ingested
    await insert_project(db, slug="ingest-flag", llm_mode="standard", sector="rail", config_json="{}")
    async with db.execute("SELECT id FROM projects WHERE slug='ingest-flag'") as cur:
        project_id = (await cur.fetchone())["id"]
    doc_id = await insert_document(
        db,
        project_id=project_id,
        filename="test.txt",
        original_name="test.txt",
        file_path="/tmp/test.txt",
        content_type="text/plain",
        size_bytes=10,
    )
    await update_document_ingested(db, doc_id=doc_id)
    async with db.execute("SELECT ingested FROM client_documents WHERE id=?", (doc_id,)) as cur:
        row = await cur.fetchone()
    assert row["ingested"] == 1
```

- [ ] **Step 2: Run to verify it fails**

```bash
python3.13 -m pytest tests/test_database.py::test_update_document_ingested -v
```

Expected: `FAILED` — `ImportError: cannot import name 'update_document_ingested'`

- [ ] **Step 3: Add `update_document_ingested` to `api/database.py`**

Read `api/database.py` to find `fetch_documents` (around line 222). Add the new function immediately after it:

```python
async def update_document_ingested(
    conn: aiosqlite.Connection, *, doc_id: int
) -> None:
    await conn.execute(
        "UPDATE client_documents SET ingested=1 WHERE id=?",
        (doc_id,),
    )
    await conn.commit()
```

- [ ] **Step 4: Run to verify it passes**

```bash
python3.13 -m pytest tests/test_database.py::test_update_document_ingested -v
```

Expected: `1 passed`

- [ ] **Step 5: Commit**

```bash
git add api/database.py tests/test_database.py
git commit -m "feat(db): add update_document_ingested helper"
```

---

### Task 2: Ingest service

**Files:**
- Create: `api/services/ingest_service.py`
- Create: `tests/test_ingest_service.py`

---

- [ ] **Step 1: Write the failing tests**

Create `tests/test_ingest_service.py`:

```python
# tests/test_ingest_service.py
"""Unit tests for api.services.ingest_service."""
import io
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_chroma_mock():
    """Return a mock chromadb.HttpClient whose get_or_create_collection works."""
    collection = MagicMock()
    collection.upsert = MagicMock()
    client = MagicMock()
    client.get_or_create_collection = MagicMock(return_value=collection)
    return client, collection


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_unsupported_extension_skips(tmp_path):
    """A .zip file should be silently skipped — no ChromaDB call, ingested stays 0."""
    zip_file = tmp_path / "archive.zip"
    zip_file.write_bytes(b"PK...")

    with patch("api.services.ingest_service.chromadb") as mock_chroma, \
         patch("api.services.ingest_service.update_document_ingested", new_callable=AsyncMock) as mock_db:
        from api.services.ingest_service import ingest_document
        await ingest_document("test-slug", doc_id=1, file_path=str(zip_file))

    mock_chroma.HttpClient.assert_not_called()
    mock_db.assert_not_called()


@pytest.mark.asyncio
async def test_text_extraction_failure_leaves_ingested_false(tmp_path):
    """If _extract_text raises, function returns without touching ChromaDB or DB."""
    bad_pdf = tmp_path / "broken.pdf"
    bad_pdf.write_bytes(b"not a real pdf")

    chroma_client, _ = _make_chroma_mock()
    with patch("api.services.ingest_service.chromadb") as mock_chroma, \
         patch("api.services.ingest_service.update_document_ingested", new_callable=AsyncMock) as mock_db, \
         patch("api.services.ingest_service._extract_text", side_effect=Exception("parse error")):
        mock_chroma.HttpClient.return_value = chroma_client
        from api.services.ingest_service import ingest_document
        await ingest_document("test-slug", doc_id=2, file_path=str(bad_pdf))

    mock_db.assert_not_called()


@pytest.mark.asyncio
async def test_chroma_unavailable_leaves_ingested_false(tmp_path):
    """If ChromaDB raises on connect, function returns without updating DB."""
    txt_file = tmp_path / "report.txt"
    txt_file.write_text("Some important content here.")

    with patch("api.services.ingest_service.chromadb") as mock_chroma, \
         patch("api.services.ingest_service.update_document_ingested", new_callable=AsyncMock) as mock_db:
        mock_chroma.HttpClient.side_effect = Exception("connection refused")
        mock_chroma.CloudClient.side_effect = Exception("connection refused")
        from api.services.ingest_service import ingest_document
        await ingest_document("test-slug", doc_id=3, file_path=str(txt_file))

    mock_db.assert_not_called()


@pytest.mark.asyncio
async def test_happy_path_txt(tmp_path):
    """.txt file: chunks upserted and ingested flag set to 1."""
    txt_file = tmp_path / "brief.txt"
    txt_file.write_text("Client briefing document. " * 50)  # >200 chars to get 1+ chunks

    chroma_client, collection = _make_chroma_mock()
    mock_conn = MagicMock()
    mock_conn.__aenter__ = AsyncMock(return_value=mock_conn)
    mock_conn.__aexit__ = AsyncMock(return_value=False)

    with patch("api.services.ingest_service.chromadb") as mock_chroma, \
         patch("api.services.ingest_service.update_document_ingested", new_callable=AsyncMock) as mock_db, \
         patch("api.services.ingest_service.get_connection", return_value=mock_conn):
        mock_chroma.HttpClient.return_value = chroma_client
        from api.services.ingest_service import ingest_document
        await ingest_document("test-slug", doc_id=4, file_path=str(txt_file))

    collection.upsert.assert_called_once()
    call_kwargs = collection.upsert.call_args
    assert len(call_kwargs.kwargs["documents"]) >= 1
    assert call_kwargs.kwargs["ids"][0].startswith("brief.txt::")
    mock_db.assert_awaited_once_with(mock_conn, doc_id=4)


@pytest.mark.asyncio
async def test_happy_path_docx(tmp_path):
    """.docx file: python-docx path exercised, chunks upserted, flag set."""
    from docx import Document as DocxDocument
    docx_path = tmp_path / "proposal.docx"
    doc = DocxDocument()
    for _ in range(10):
        doc.add_paragraph("This is a paragraph about digital transformation strategy.")
    doc.save(str(docx_path))

    chroma_client, collection = _make_chroma_mock()
    mock_conn = MagicMock()
    mock_conn.__aenter__ = AsyncMock(return_value=mock_conn)
    mock_conn.__aexit__ = AsyncMock(return_value=False)

    with patch("api.services.ingest_service.chromadb") as mock_chroma, \
         patch("api.services.ingest_service.update_document_ingested", new_callable=AsyncMock) as mock_db, \
         patch("api.services.ingest_service.get_connection", return_value=mock_conn):
        mock_chroma.HttpClient.return_value = chroma_client
        from api.services.ingest_service import ingest_document
        await ingest_document("test-slug", doc_id=5, file_path=str(docx_path))

    collection.upsert.assert_called_once()
    mock_db.assert_awaited_once_with(mock_conn, doc_id=5)
```

- [ ] **Step 2: Run to verify they fail**

```bash
python3.13 -m pytest tests/test_ingest_service.py -v
```

Expected: `FAILED` on all 5 — `ModuleNotFoundError: No module named 'api.services.ingest_service'`

- [ ] **Step 3: Create `api/services/ingest_service.py`**

First check that `api/services/__init__.py` exists:

```bash
ls api/services/
```

If `__init__.py` is missing, create it as an empty file. Then create `api/services/ingest_service.py`:

```python
# api/services/ingest_service.py
import logging
from pathlib import Path

import chromadb

from api.config import get_settings
from api.database import get_connection, update_document_ingested

logger = logging.getLogger(__name__)

SUPPORTED_SUFFIXES = {".txt", ".md", ".pdf", ".docx"}


def _extract_text(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        from pypdf import PdfReader
        reader = PdfReader(str(path))
        return "\n".join(page.extract_text() or "" for page in reader.pages)
    if suffix == ".docx":
        from docx import Document
        doc = Document(str(path))
        return "\n".join(p.text for p in doc.paragraphs)
    return path.read_text(errors="replace")


def _chunk_text(text: str, chunk_size: int = 1000, overlap: int = 200) -> list[str]:
    chunks, start = [], 0
    while start < len(text):
        chunks.append(text[start : start + chunk_size])
        start += chunk_size - overlap
    return [c for c in chunks if c.strip()]


async def ingest_document(slug: str, doc_id: int, file_path: str) -> None:
    """
    Background task: extract text from file, chunk, upsert to ChromaDB,
    then mark ingested=1 in SQLite. Logs and returns on any error.
    """
    path = Path(file_path)
    if path.suffix.lower() not in SUPPORTED_SUFFIXES:
        logger.info("ingest_document: unsupported type %s, skipping", path.suffix)
        return

    settings = get_settings()
    try:
        text = _extract_text(path)
    except Exception as exc:
        logger.warning("ingest_document: text extraction failed for %s: %s", path.name, exc)
        return

    chunks = _chunk_text(text)
    if not chunks:
        logger.info("ingest_document: no text extracted from %s", path.name)
        return

    try:
        if settings.chroma_api_key:
            client = chromadb.CloudClient(
                tenant=settings.chroma_tenant,
                database=settings.chroma_database,
                api_key=settings.chroma_api_key,
            )
        else:
            client = chromadb.HttpClient(host=settings.chroma_host, port=settings.chroma_port)
        collection = client.get_or_create_collection(f"{slug}_docs")
        ids = [f"{path.name}::{i}" for i in range(len(chunks))]
        metadatas = [{"filename": path.name, "chunk": i} for i in range(len(chunks))]
        collection.upsert(documents=chunks, ids=ids, metadatas=metadatas)
    except Exception as exc:
        logger.warning("ingest_document: ChromaDB upsert failed for %s: %s", path.name, exc)
        return

    try:
        async with get_connection(slug) as conn:
            await update_document_ingested(conn, doc_id=doc_id)
    except Exception as exc:
        logger.warning("ingest_document: DB update failed for doc_id=%s: %s", doc_id, exc)
```

- [ ] **Step 4: Run to verify tests pass**

```bash
python3.13 -m pytest tests/test_ingest_service.py -v
```

Expected: `5 passed`

- [ ] **Step 5: Commit**

```bash
git add api/services/ingest_service.py tests/test_ingest_service.py
git commit -m "feat(ingest): add document ingestion service with ChromaDB upsert"
```

---

### Task 3: Wire BackgroundTasks into upload endpoint

**Files:**
- Modify: `api/routers/documents.py`
- Modify: `tests/test_documents.py`

---

- [ ] **Step 1: Write the failing integration test**

Read `tests/test_documents.py` to understand its existing structure (slug `"doc-test"`, `PROJECT` payload, `clean` fixture). Then append:

```python
@pytest.mark.asyncio
async def test_upload_triggers_ingest_background_task(client, tmp_path):
    """After upload, background task runs and sets ingested=True (AsyncClient runs tasks inline)."""
    from unittest.mock import AsyncMock, patch

    await client.post("/projects", json=PROJECT)

    mock_ingest = AsyncMock()
    with patch("api.routers.documents.ingest_document", mock_ingest):
        file_content = b"Quarterly review document with strategy details."
        resp = await client.post(
            "/projects/doc-test/documents/upload",
            files={"file": ("strategy.txt", io.BytesIO(file_content), "text/plain")},
        )

    assert resp.status_code == 201
    data = resp.json()
    assert data["original_name"] == "strategy.txt"
    # Background task ran (AsyncClient + ASGITransport executes tasks inline)
    mock_ingest.assert_awaited_once()
    call_args = mock_ingest.call_args
    assert call_args.args[0] == "doc-test"          # slug
    assert isinstance(call_args.args[1], int)        # doc_id
    assert call_args.args[2].endswith(".txt")        # file_path ends with .txt extension
```

- [ ] **Step 2: Run to verify it fails**

```bash
python3.13 -m pytest tests/test_documents.py::test_upload_triggers_ingest_background_task -v
```

Expected: `FAILED` — `AssertionError: Expected 'ingest_document' to have been awaited once. Awaited 0 times.`

- [ ] **Step 3: Update `api/routers/documents.py`**

Read the current file first, then make two targeted changes:

**Change 1** — update the import line at the top. Find:
```python
from fastapi import APIRouter, HTTPException, UploadFile, File
```
Replace with:
```python
from fastapi import APIRouter, BackgroundTasks, HTTPException, UploadFile, File
from api.services.ingest_service import ingest_document
```

**Change 2** — update the upload endpoint signature and add the background task. Find:
```python
@router.post("/{slug}/documents/upload", status_code=201)
async def upload_document(slug: str, file: UploadFile = File(...)):
```
Replace with:
```python
@router.post("/{slug}/documents/upload", status_code=201)
async def upload_document(
    slug: str,
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
):
```

Then find the return statement at the end of the function:
```python
        return _coerce_doc(next(d for d in docs if d["id"] == doc_id))
```
Replace with:
```python
        background_tasks.add_task(ingest_document, slug, doc_id, str(dest))
        return _coerce_doc(next(d for d in docs if d["id"] == doc_id))
```

- [ ] **Step 4: Run to verify the new test passes**

```bash
python3.13 -m pytest tests/test_documents.py::test_upload_triggers_ingest_background_task -v
```

Expected: `1 passed`

- [ ] **Step 5: Run the full test suite to check for regressions**

```bash
python3.13 -m pytest --ignore=tests/integration -q
```

Expected: 179+ passed, same 6 pre-existing failures, zero new failures.

- [ ] **Step 6: Commit**

```bash
git add api/routers/documents.py tests/test_documents.py
git commit -m "feat(api): auto-ingest uploaded documents via BackgroundTasks"
```
