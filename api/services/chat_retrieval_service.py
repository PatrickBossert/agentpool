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
    try:
        if not query.strip():
            return []

        client = get_chroma_client(slug)
        collection = client.get_collection(f"{slug}_docs")
        count = collection.count()
        if not count:
            return []
        results = collection.query(query_texts=[query], n_results=min(k, count))

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
    except Exception as exc:
        logger.warning("chat retrieval failed for project %s: %s", slug, exc)
        return []
