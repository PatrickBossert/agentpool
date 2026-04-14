# agents/tools/document_ingestion.py
from pathlib import Path
from typing import Optional
from pydantic import BaseModel, Field
from crewai.tools import BaseTool
import chromadb
from api.config import get_settings


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

        try:
            client = chromadb.HttpClient(host=settings.chroma_host, port=settings.chroma_port)
            collection = client.get_or_create_collection(name=f"{self.slug}_docs")
        except Exception as e:
            return f"Error: ChromaDB unavailable — {e}"

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
            collection.upsert(documents=chunks, ids=ids, metadatas=metadatas)
            ingested.append(path.name)

        return f"Ingested: {', '.join(ingested)}"
