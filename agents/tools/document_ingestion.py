# agents/tools/document_ingestion.py
import socket
from pathlib import Path
from typing import Optional
from pydantic import BaseModel, Field
from crewai.tools import BaseTool
from api.config import get_settings
from api.services.chroma_client import get_chroma_client
from api.services.ingest_service import UPSERT_BATCH, ingest_collection


def _chroma_reachable(host: str, port: int, timeout: float = 3.0) -> bool:
    try:
        socket.create_connection((host, port), timeout=timeout).close()
        return True
    except OSError:
        return False


def _chunk_text(text: str, chunk_size: int = 1000, overlap: int = 200) -> list[str]:
    """Split text into overlapping chunks."""
    chunks = []
    start = 0
    while start < len(text):
        end = start + chunk_size
        chunks.append(text[start:end])
        start += chunk_size - overlap
    return [c for c in chunks if c.strip()]


def _read_file(path: Path) -> str:
    """Extract text from .txt, .md, or .pdf files."""
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        from pypdf import PdfReader
        reader = PdfReader(str(path))
        return "\n".join(page.extract_text() or "" for page in reader.pages)
    return path.read_text(errors="replace")


class DocumentIngestionToolInput(BaseModel):
    filename: Optional[str] = Field(
        default=None,
        description="Specific filename to ingest. If None, ingests all files in docs/.",
    )


class DocumentIngestionTool(BaseTool):
    name: str = "DocumentIngestionTool"
    description: str = (
        "Ingest client documents from the project docs/ directory into ChromaDB. "
        "Call with filename=None to ingest all documents, or specify a single filename. "
        "Returns a list of ingested document names."
    )
    args_schema: type[BaseModel] = DocumentIngestionToolInput
    slug: str

    def _run(self, filename: str | None = None) -> str:
        settings = get_settings()
        docs_dir = Path(settings.projects_dir) / self.slug / "docs"
        if not docs_dir.exists():
            return f"Error: docs directory not found at {docs_dir}"

        paths = (
            [docs_dir / filename]
            if filename
            else list(docs_dir.iterdir())
        )
        paths = [p for p in paths if p.is_file() and p.suffix.lower() in {".txt", ".md", ".pdf"}]
        if not paths:
            return "No supported documents found (.txt, .md, .pdf)"

        # Routed through the shared factory rather than constructing a client here, because
        # this tool is held by value_chain_mapper and requirements_analyst and ingests the
        # client's own corporate documents. Building CloudClient off CHROMA_API_KEY alone sent
        # a sensitive project's documents to Chroma Cloud, and left the sensitive path broken
        # as well as leaking: ChromaQueryTool reads local for that project while this wrote
        # cloud, so nothing Alex ingested could be retrieved.
        # Always the project tier, and there is no argument that could make it anything else -
        # `DocumentIngestionToolInput` offers a filename and nothing more. An agent reading
        # the client's own documents must not be able to publish them into a store shared with
        # the organisation's other engagements, or with other clients in the sector; promotion
        # is a human act with authority for the destination, never something a crew can reach.
        # Resolved through `ingest_collection` rather than built by hand here - this was one of
        # the five sites spelling out `f"{slug}_docs"`, and the delete door that disagreed with
        # them was silently deleting nothing.
        try:
            collection_name = ingest_collection(self.slug, "project")
            client = get_chroma_client(self.slug)
            collection = client.get_or_create_collection(name=collection_name)
        except Exception as e:
            # The probe runs only once construction has already failed: it costs a socket
            # connection, and its one job is to tell "Docker is not running" apart from every
            # other reason Chroma might be unavailable. Which client the factory chose is not
            # re-derived here - duplicating the routing rule is how the two drift apart.
            if not _chroma_reachable(settings.chroma_host, settings.chroma_port):
                return "ChromaDB is not reachable. Start Docker (docker compose up -d) and retry."
            return f"Error: ChromaDB unavailable - {e}"

        ingested = []
        for path in paths:
            try:
                text = _read_file(path)
            except Exception as e:
                ingested.append(f"{path.name} (skipped: {e})")
                continue
            if not text.strip():
                continue
            chunks = _chunk_text(text)
            ids = [f"{path.name}::{i}" for i in range(len(chunks))]
            metadatas = [{"filename": path.name, "chunk": i} for i in range(len(chunks))]
            # Batched for the same reason as the upload path: Chroma caps records per Upsert
            # action, and one call carrying every chunk of a large document is rejected
            # whole. Unbatched, Alex could never ingest a document over ~300KB of text.
            try:
                for start in range(0, len(chunks), UPSERT_BATCH):
                    end = start + UPSERT_BATCH
                    collection.upsert(
                        documents=chunks[start:end],
                        ids=ids[start:end],
                        metadatas=metadatas[start:end],
                    )
            except Exception as e:
                # Named in the returned string rather than swallowed: this text is what the
                # agent reads, and a document silently missing from the index is a gap it
                # cannot see and will not mention.
                ingested.append(f"{path.name} (FAILED: {e})")
                continue
            ingested.append(path.name)

        return f"Ingested: {', '.join(ingested)}"
