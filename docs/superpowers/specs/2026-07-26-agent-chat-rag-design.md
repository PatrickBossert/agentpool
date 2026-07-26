# Agent Chat RAG + Project Document Library - Design Spec

**Date:** 2026-07-26
**Sprint:** SP18a (proposed)

---

## Goal

Give agent chat real retrieval over the project's document library, replacing the fixed 3,000-character preview that is injected into the system prompt today. Agents should be able to answer from any document in the project, not just the first two pages of whatever was attached to the current conversation.

Images shared in chat become vision inputs to Claude rather than a placeholder line.

---

## Problem

Documents uploaded through agent chat are already chunked, embedded, and stored in the project's ChromaDB collection by `ingest_document`. **Agent chat never queries that store.** `api/services/agent_chat_service.py` contains no reference to Chroma, embeddings, or retrieval.

Instead, `chat_upload` truncates extracted text to `_PREVIEW_CHARS = 3_000` and the chat service appends that verbatim to the system prompt. A 40-page report is therefore visible to the agent as roughly its first two pages. The remaining content is indexed and unreachable.

Retrieval already exists for crews via `ChromaQueryTool`, but only 6 of the 18 agent roles in `agents/tools/registry.py` hold it, and `pam` is not among them.

**Library membership is already correct.** Both `POST /{slug}/documents/upload` and `POST /{slug}/agent-chat/upload` write to `projects/{slug}/docs`, insert into `client_documents` against the same `project_id`, and are returned unfiltered by `GET /{slug}/documents`. No change is needed to make chat uploads part of the project library; this spec adds a test to lock that behaviour in.

---

## Architecture

Three changes, plus one extraction.

1. **`api/services/chat_retrieval_service.py`** (new) - `search(slug, query, k)` returns ranked chunks from the project collection. Knows nothing about prompts, agents, or HTTP. Its only dependency is the Chroma client helper.
2. **`api/services/agent_chat_service.py`** - calls `search()` and injects labelled chunks into the system prompt; builds multimodal content blocks when images are attached.
3. **`api/routers/agent_chat.py`** - `chat_upload` awaits ingestion instead of queueing it, stops returning `preview_text` for text documents, and rejects oversized images.

**Extraction:** client selection (`CloudClient` when `chroma_api_key` is set, otherwise `HttpClient`) is currently duplicated in `api/services/ingest_service.py` and `agents/tools/chroma_query.py`. Move it to a single helper and have all three call sites use it, rather than writing a third copy.

---

## Data flow

**Upload**

```
POST /{slug}/agent-chat/upload
  -> save file to projects/{slug}/docs/
  -> insert_document()            (client_documents row)
  -> append to discovery_document_ids
  -> await ingest_document()      (was: background_tasks.add_task)
  -> return {doc_id, filename, original_name, is_image}
```

`preview_text` is no longer returned for text documents. Images carry no extracted text and are handled at chat time.

**Chat turn**

```
POST /{slug}/agent-chat
  -> chat_retrieval_service.search(slug, message, k=6)
  -> system_prompt += labelled chunks (filename + text per chunk)
  -> for each attached image: read file, base64-encode, add image block
  -> messages.create(system=system_prompt, messages=[... , {role: user, content: blocks}])
```

---

## Components

### chat_retrieval_service.search

```python
def search(slug: str, query: str, k: int = 6) -> list[Chunk]
```

Queries collection `{slug}_docs` with `collection.query(query_texts=[query], n_results=k)`. Returns chunk text plus the `filename` and `doc_id` metadata that `ingest_document` already writes, so retrieved content can be attributed in the prompt.

Returns `[]` when the collection is missing or Chroma is unreachable. Callers must treat an empty result as "no context", never as an error.

**Retrieval runs on every chat turn**, using the user's message verbatim as the query, with no relevance threshold. Chroma returns nearest neighbours regardless of how well they match, so a message like "hi" will still pull six chunks. This is accepted deliberately: a distance threshold would need tuning against real embeddings and query patterns we do not have yet, and a wrong threshold silently suppresses good results. Revisit once there is usage data.

### Prompt injection

Retrieved chunks are appended to the system prompt under a single heading, each labelled with its source filename:

```
--- Retrieved from project documents ---
[discovery-notes.pdf] <chunk text>
[org-chart.docx] <chunk text>
```

Attribution matters: without it the agent cannot tell the user which document an answer came from.

### Image blocks

Images bypass retrieval entirely. For each attached image the service reads the file, base64-encodes it, and emits an Anthropic image block with the media type derived from the suffix. The five accepted suffixes (`.png .jpg .jpeg .webp .gif`) map exactly onto Claude's supported media types, and the chat already runs on `claude-haiku-4-5-20251001`, which is vision-capable.

---

## Parameters

| Setting | Value | Reasoning |
|---------|-------|-----------|
| `k` | 6 chunks | ~6,000 characters at the existing 1000-char chunk size. Comparable in volume to today's 3,000-char preview, but selected by relevance rather than position. |
| Corpus | `{slug}_docs` only | The `sector_{sector}` knowledge base is a separate shared corpus. Mixing it in would surprise a user asking about "my documents". |
| Image cap | 4 MB raw | Anthropic's limit is ~5 MB base64. Encoding inflates by roughly a third, so the raw-file guard sits below it. |

The image cap is not hypothetical: `ui/public/agents/crewpic.png` is 5.9 MB and would exceed the API limit.

---

## Error handling

The two Chroma failure modes get deliberately opposite treatment.

| Failure | Behaviour | Reasoning |
|---------|-----------|-----------|
| Chroma unreachable during **chat** | Log, return no chunks, answer without them | A degraded answer beats a broken chat. Retrieval is an enhancement to the turn, not a precondition. |
| Chroma unreachable during **upload** | Fail the request with 502 | Ingestion is now the only path to a document being usable. A silent failure would leave a document that looks uploaded but is permanently invisible. |

The upload case also fixes an existing defect: `ingest_service.py` currently catches upsert failures with `logger.warning` and returns, so a Chroma outage today produces a successful-looking upload and an unindexed document.

Other cases:

- Image over 4 MB - reject at upload with 422 and a message naming the limit.
- Unsupported suffix - unchanged, already rejected with 422.
- Text extraction yields nothing (e.g. a scanned PDF with no text layer) - the upload succeeds, no chunks are stored, and retrieval simply never returns that document. Surfacing this properly needs OCR and is out of scope.

---

## Testing

Unit tests, Chroma mocked throughout - no live service required.

**chat_retrieval_service**
- Returns ranked chunks with filename and doc_id attribution
- Returns `[]` when the collection does not exist
- Returns `[]` when the client raises, and does not propagate

**agent_chat_service**
- Retrieved chunks appear in the system prompt, labelled with their filename
- An empty retrieval result produces a prompt with no retrieval section
- An attached image produces a correctly shaped base64 image block
- A text document does not produce an image block

**chat_upload**
- Ingestion failure fails the request rather than returning 201
- Image over 4 MB rejected with 422
- Response no longer carries `preview_text` for text documents

**Library membership (regression lock)**
- A document uploaded via `POST /{slug}/agent-chat/upload` is returned by `GET /{slug}/documents`

Existing tests that assert on `preview_text` will need updating.

---

## Scope

**Included:** everything above, plus removal of `PINECONE_API_KEY` from `.env.example`. Pinecone is referenced in no plan, spec, code path, or dependency; it was introduced incidentally in `6dab668` and `api/config.py` has no field for it, so the key is discarded by `extra="ignore"`. Documenting it implies a capability that does not exist.

**Explicitly excluded:**

- The 12 crew agent roles without `ChromaQueryTool`, including `pam`. Granting retrieval to those is a separate change to `agents/tools/registry.py` with its own prompt implications.
- Any change to how `ingest_document` chunks (1000 chars, 200 overlap) or which embedding function is used. No `embedding_function` is specified anywhere today, so Chroma's default applies; changing it would invalidate existing collections.
- OCR for image-only PDFs.

---

## Known consequences

**Uploads become slower.** Synchronous ingestion means the request waits for extraction, chunking, and embedding. A large PDF could take several seconds with no progress indicator. This is the direct cost of guaranteeing a document is searchable before the user's next message, which is required because the preview no longer exists as a fallback.

**Images may be re-sent per turn.** The frontend controls `injected_docs` per request and this spec does not change that contract. If the UI re-attaches a document on every subsequent turn, image tokens are paid repeatedly. The frontend's behaviour should be checked before this ships.
