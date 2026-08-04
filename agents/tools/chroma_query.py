# agents/tools/chroma_query.py
import contextlib
import socket
import sqlite3
from typing import Literal
from pydantic import BaseModel, Field
from crewai.tools import BaseTool
from agents.tools._db import _db_path
from api.config import get_settings
from api.services.chroma_client import get_chroma_client


def _chroma_reachable(host: str, port: int, timeout: float = 3.0) -> bool:
    try:
        socket.create_connection((host, port), timeout=timeout).close()
        return True
    except OSError:
        return False


def _document_names(slug: str) -> dict[int, str]:
    """doc_id -> the name a person would recognise.

    Chroma stores `filename`, which is the hashed name on disk
    (d89a0be7c73442a08cde5080b0797c16.pdf). Citing that is technically a source and useless -
    nobody can open it or recognise it - so the citation resolves through client_documents to
    the name the file was uploaded under.

    Returns an empty map on any failure. A retrieval is still worth having without names, and
    losing the knowledge base because a sidecar lookup failed would be the worse trade.
    """
    try:
        with contextlib.closing(sqlite3.connect(_db_path(slug))) as conn:
            return {
                row[0]: row[1]
                for row in conn.execute(
                    "SELECT id, original_name FROM client_documents"
                )
            }
    except Exception:
        return {}


# Tags worth putting in front of an interview answer: what Casey weights evidence by. Listed
# rather than dumped, so a metadata field added later does not silently widen every citation.
_ANSWER_TAGS = ("node_id", "level", "relationship", "discipline", "elicitation")


def _citation(meta: dict | None, names: dict[int, str]) -> str:
    """The provenance line placed above a retrieved chunk.

    Never raises and never returns empty: an unattributable chunk still says so, because a
    chunk with no line at all reads as belonging to whichever citation precedes it.
    """
    if not meta:
        return "[source unknown]"

    if meta.get("answer_id") is not None:
        tags = " | ".join(str(meta[t]) for t in _ANSWER_TAGS if meta.get(t))
        return f"[answer_id={meta['answer_id']}" + (f" | {tags}]" if tags else "]")

    doc_id = meta.get("doc_id")
    if doc_id is not None:
        # A dangling doc_id is reported rather than hidden - the id is still the thing to
        # chase, and the missing name is itself the finding.
        name = names.get(doc_id, "unknown document")
        chunk = meta.get("chunk")
        suffix = f" | chunk {chunk}" if chunk is not None else ""
        return f"[doc_id={doc_id} | {name}{suffix}]"

    return "[source unknown]"


class ChromaQueryToolInput(BaseModel):
    query: str = Field(description="The search query to run against the document collection.")
    collection: Literal["project", "interviews", "sector"] = Field(
        default="project",
        description=(
            "'project' queries this project's ingested docs; 'interviews' queries interview "
            "answers; 'sector' queries the shared sector knowledge base."
        ),
    )
    top_k: int = Field(default=5, description="Number of results to return.")


class ChromaQueryTool(BaseTool):
    name: str = "ChromaQueryTool"
    description: str = (
        "Retrieve relevant text chunks from ChromaDB. "
        "Use collection='project' for ingested client documents; "
        "use collection='interviews' for interview answers; "
        "use collection='sector' for the shared sector knowledge base. "
        "Every chunk is preceded by its citation in square brackets - [doc_id=3 | "
        "SPUK_2025_Annual_Accounts.pdf | chunk 12] for a document, or [answer_id=812 | node | "
        "level | relationship | discipline | elicitation] for an interview answer. Cite the "
        "doc_id or answer_id when you use a chunk: it is what lets a reader check the claim."
    )
    args_schema: type[BaseModel] = ChromaQueryToolInput
    slug: str
    sector: str

    def _run(
        self,
        query: str,
        collection: str = "project",
        top_k: int = 5,
    ) -> str:
        settings = get_settings()
        if not settings.chroma_api_key and not _chroma_reachable(settings.chroma_host, settings.chroma_port):
            return "ChromaDB is not reachable. Start Docker (docker compose up -d) and retry."
        client = get_chroma_client()

        collection_name = {
            "project": f"{self.slug}_docs",
            "interviews": f"{self.slug}_interviews",
        }.get(collection, f"sector_{self.sector}")

        try:
            col = client.get_collection(collection_name)
        except Exception:
            return f"Collection '{collection_name}' not found. Ingest documents first."

        count = col.count()
        if count == 0:
            return "No documents in collection. Ingest documents first."
        results = col.query(query_texts=[query], n_results=min(top_k, count))
        docs = results.get("documents", [[]])[0]
        if not docs:
            return "No relevant documents found."

        metas = (results.get("metadatas") or [[]])[0] or []
        names = _document_names(self.slug)
        blocks = [
            f"{_citation(metas[i] if i < len(metas) else None, names)}\n{text}"
            for i, text in enumerate(docs)
        ]
        return "\n\n---\n\n".join(blocks)
