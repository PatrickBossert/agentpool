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
