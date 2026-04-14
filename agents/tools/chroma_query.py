# agents/tools/chroma_query.py
from typing import Literal
from pydantic import BaseModel, Field
from crewai.tools import BaseTool
import chromadb
from api.config import get_settings


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
        client = chromadb.HttpClient(host=settings.chroma_host, port=settings.chroma_port)

        collection_name = (
            f"{self.slug}_docs" if collection == "project" else f"sector_{self.sector}"
        )

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
