# agents/tools/chroma_query.py
import socket
from typing import Literal
from pydantic import BaseModel, Field
from crewai.tools import BaseTool
from api.config import get_settings
from api.services.chroma_client import get_chroma_client


def _chroma_reachable(host: str, port: int, timeout: float = 3.0) -> bool:
    try:
        socket.create_connection((host, port), timeout=timeout).close()
        return True
    except OSError:
        return False


class ChromaQueryToolInput(BaseModel):
    query: str = Field(description="The search query to run against the document collection.")
    collection: Literal["project", "sector"] = Field(
        default="project",
        description="'project' queries this project's ingested docs; 'sector' queries the shared sector knowledge base.",
    )
    top_k: int = Field(default=5, description="Number of results to return.")


class ChromaQueryTool(BaseTool):
    name: str = "ChromaQueryTool"
    description: str = (
        "Retrieve relevant text chunks from ChromaDB. "
        "Use collection='project' for ingested client documents; "
        "use collection='interviews' for interview answers - one document per question, "
        "each carrying its node, level, relationship, discipline, and elicitation as "
        "metadata; "
        "use collection='sector' for the shared sector knowledge base."
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
        return "\n\n---\n\n".join(docs)
