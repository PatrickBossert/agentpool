# tests/test_secure_mode_routing.py
"""Secure mode is per-project, not per-deployment.

One server runs both kinds. Every test here therefore uses two projects in one process:
a per-deployment implementation passes any single-project test and fails only this shape.
"""
import sqlite3
import pytest
from api.config import get_settings


@pytest.fixture
def two_projects(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_DIR", str(tmp_path))
    monkeypatch.setenv("CHROMA_API_KEY", "cloud-key-is-set")
    get_settings.cache_clear()
    for slug, mode in (("secure-proj", "sensitive"), ("open-proj", "standard")):
        conn = sqlite3.connect(tmp_path / f"{slug}.db")
        conn.execute("CREATE TABLE projects (id INTEGER PRIMARY KEY, slug TEXT, "
                     "llm_mode TEXT, sector TEXT, config_json TEXT)")
        conn.execute("INSERT INTO projects (slug, llm_mode, sector) VALUES (?,?,?)",
                     (slug, mode, "test"))
        conn.commit()
        conn.close()
    from api.services import chroma_client
    chroma_client._MODE_CACHE.clear()
    yield
    get_settings.cache_clear()


def test_a_sensitive_project_never_reaches_cloud_chroma(two_projects, monkeypatch):
    """CHROMA_API_KEY is set, which is exactly the condition that used to force CloudClient."""
    import chromadb
    built = []
    monkeypatch.setattr(chromadb, "CloudClient", lambda **kw: built.append("cloud"))
    monkeypatch.setattr(chromadb, "HttpClient", lambda **kw: built.append("local"))
    from api.services.chroma_client import get_chroma_client
    get_chroma_client("secure-proj")
    assert built == ["local"]


def test_both_modes_are_honoured_in_one_process(two_projects, monkeypatch):
    """The test a per-deployment switch cannot pass."""
    import chromadb
    built = []
    monkeypatch.setattr(chromadb, "CloudClient", lambda **kw: built.append("cloud"))
    monkeypatch.setattr(chromadb, "HttpClient", lambda **kw: built.append("local"))
    from api.services.chroma_client import get_chroma_client
    get_chroma_client("secure-proj")
    get_chroma_client("open-proj")
    assert built == ["local", "cloud"]
