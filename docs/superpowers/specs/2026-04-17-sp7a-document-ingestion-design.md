# SP7a — Document Ingestion Pipeline
## Design Specification
**Date:** 2026-04-17
**Status:** Approved for implementation planning
**Branch base:** `master` (post SP6a)
**Working directory:** `/Users/pboagents/Documents/agentpool1`

---

## 1. Scope

Wire automatic ChromaDB ingestion into the existing document upload flow. When a user uploads a file via `POST /projects/{slug}/documents/upload`, the document is saved to disk and recorded in SQLite (already working). The missing step — chunking the text and upserting into the `{slug}_docs` ChromaDB collection — will now happen automatically as a FastAPI background task, and the `ingested` flag in SQLite will be flipped to `1` on completion.

**In scope:**
- `api/services/ingest_service.py` — new standalone `ingest_document` function
- `api/database.py` — new `update_document_ingested` helper
- `api/routers/documents.py` — add `BackgroundTasks` to upload endpoint
- `.docx` file support (in addition to existing `.txt`, `.md`, `.pdf`)
- Unit tests for all new code

**Out of scope:**
- UI changes (Documents page already shows `ingested` boolean)
- Refactoring `DocumentIngestionTool` (left as-is for agent use)
- Re-ingestion / re-index on update
- Manual "Ingest" trigger endpoint
- Ingestion progress streaming

---

## 2. Architecture

```
POST /projects/{slug}/documents/upload
  │
  ├─ Save file to disk                    (existing)
  ├─ INSERT into client_documents         (existing, ingested=0)
  ├─ Return 201 with document record      (existing)
  │
  └─ BackgroundTasks.add_task(ingest_document, slug, doc_id, file_path)
       │
       ├─ extract text  (.txt/.md → read_text, .pdf → pypdf, .docx → python-docx)
       ├─ chunk text    (1000 chars / 200 overlap)
       ├─ upsert chunks → ChromaDB collection "{slug}_docs"
       └─ UPDATE client_documents SET ingested=1 WHERE id=doc_id
            └─ on any error: log, leave ingested=0 (silent failure)
```

---

## 3. Backend Changes

### 3.1 `api/database.py`

New helper (follows existing pattern — keyword-only `doc_id`):

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

### 3.2 `api/services/ingest_service.py` (new file)

```python
# api/services/ingest_service.py
import logging
from pathlib import Path

import chromadb

from api.config import get_settings
from api.database import get_connection, update_document_ingested

logger = logging.getLogger(__name__)


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


SUPPORTED_SUFFIXES = {".txt", ".md", ".pdf", ".docx"}


async def ingest_document(slug: str, doc_id: int, file_path: str) -> None:
    """
    Background task: extract text, chunk, upsert to ChromaDB, mark ingested.
    Logs and returns silently on any error — ingested flag stays 0.
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

### 3.3 `api/routers/documents.py`

Change only the upload endpoint. Add `BackgroundTasks` parameter and enqueue the task after the document is inserted:

```python
from fastapi import APIRouter, BackgroundTasks, HTTPException, UploadFile, File
from api.services.ingest_service import ingest_document

@router.post("/{slug}/documents/upload", status_code=201)
async def upload_document(
    slug: str,
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
):
    # ... existing save-to-disk + insert_document logic unchanged ...

    background_tasks.add_task(ingest_document, slug, doc_id, str(dest))
    return _coerce_doc(next(d for d in docs if d["id"] == doc_id))
```

---

## 4. File Type Support

| Extension | Parser | Already in requirements? |
|---|---|---|
| `.txt` / `.md` | `Path.read_text()` | Yes |
| `.pdf` | `pypdf` | Yes |
| `.docx` | `python-docx` (`docx`) | Yes (used by `word_output.py`) |

No new dependencies required.

---

## 5. Testing

### `tests/test_database.py`
One new test:
```python
@pytest.mark.asyncio
async def test_update_document_ingested(db):
    from api.database import insert_project, insert_document, update_document_ingested
    await insert_project(db, slug="ingest-flag", llm_mode="standard", sector="rail", config_json="{}")
    async with db.execute("SELECT id FROM projects WHERE slug='ingest-flag'") as cur:
        project_id = (await cur.fetchone())["id"]
    doc_id = await insert_document(
        db, project_id=project_id,
        filename="test.txt", original_name="test.txt",
        file_path="/tmp/test.txt", content_type="text/plain", size_bytes=10,
    )
    await update_document_ingested(db, doc_id=doc_id)
    async with db.execute("SELECT ingested FROM client_documents WHERE id=?", (doc_id,)) as cur:
        row = await cur.fetchone()
    assert row["ingested"] == 1
```

### `tests/test_ingest_service.py` (new)

Five tests, all patching `chromadb.HttpClient` and file I/O:

1. **Unsupported extension** (`.zip`) — function returns without calling ChromaDB or DB
2. **Text extraction failure** — `_extract_text` raises → function returns, `ingested` stays 0
3. **ChromaDB unavailable** — `HttpClient` raises → function returns, `ingested` stays 0
4. **Happy path `.txt`** — chunks upserted, `update_document_ingested` called, DB flag set to 1
5. **Happy path `.docx`** — `python-docx` path exercised, same assertions as above

### `tests/test_documents_api.py`

One new test — verify background task is enqueued on upload:
```python
@pytest.mark.asyncio
async def test_upload_document_enqueues_ingest(client, tmp_path, monkeypatch):
    # Create project first, then upload a .txt file
    # Assert response is 201 and ingested=False (task hasn't run yet)
    # Assert that the background task ran (TestClient runs background tasks synchronously)
    # and ingested=True after fetching the document list
```

---

## 6. Run Command

```bash
pytest tests/test_database.py tests/test_ingest_service.py tests/test_documents_api.py -v
```

---

## 7. Notes

- `ingest_document` is `async` so it can `await get_connection(slug)` for the DB update. FastAPI's `BackgroundTasks` supports both sync and async callables.
- The `{slug}_docs` ChromaDB collection name matches what `DocumentIngestionTool` and `ChromaQueryTool` already use — no collection name change needed.
- `DocumentIngestionTool` is not modified. It remains available for agents to trigger manual re-ingestion if needed (e.g. after a document is replaced).
- If ChromaDB is not running when a document is uploaded, ingestion silently fails and `ingested` stays `0`. The user can see this in the Documents page. No retry mechanism is in scope.
