# tests/test_secure_mode_routing.py
"""Secure mode is per-project, not per-deployment.

One server runs both kinds. Every test here therefore uses two projects in one process:
a per-deployment implementation passes any single-project test and fails only this shape.

The tests below the two-project pair guard a second property: the cache that makes
project_llm_mode cheap must not turn a mode switch, or a transient read fault, into a
standing wrong answer.
"""
import sqlite3
import pytest
import pytest_asyncio
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


@pytest_asyncio.fixture
async def standard_project(tmp_path, monkeypatch):
    """A real project, created through the same schema and migrations production uses -
    not the minimal hand-rolled table the two_projects fixture above uses - because this
    test drives the real write path (update_project_settings) and needs get_connection and
    insert_project to behave exactly as they do in production.
    """
    monkeypatch.setenv("DATABASE_DIR", str(tmp_path))
    monkeypatch.setenv("CHROMA_API_KEY", "cloud-key-is-set")
    get_settings.cache_clear()
    from api.database import get_connection, insert_project
    async with get_connection("switch-proj") as conn:
        await insert_project(
            conn, slug="switch-proj", llm_mode="standard", sector="rail", config_json="{}"
        )
    from api.services import chroma_client
    chroma_client._MODE_CACHE.clear()
    yield
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_switching_to_sensitive_through_settings_invalidates_the_cache(
    standard_project, monkeypatch
):
    """Drives the actual write path an operator uses - PATCH /{slug}/settings ->
    update_project_settings - not the cache dict directly. The finding this guards: an
    already-resolved "standard" project switched to sensitive must stop reaching Chroma
    Cloud in the same process, with no restart required.
    """
    import chromadb
    from api.services.chroma_client import get_chroma_client, project_llm_mode
    from api.services.project_service import update_project_settings
    from api.models import ProjectSettings

    # Stands in for an earlier ingest or interview answer having already resolved (and
    # cached) the project's mode as "standard", before anyone switched it.
    assert project_llm_mode("switch-proj") == "standard"

    result = await update_project_settings(
        "switch-proj", ProjectSettings(llm_mode="sensitive", sector="rail")
    )
    assert result is not None

    built = []
    monkeypatch.setattr(chromadb, "CloudClient", lambda **kw: built.append("cloud"))
    monkeypatch.setattr(chromadb, "HttpClient", lambda **kw: built.append("local"))
    get_chroma_client("switch-proj")
    assert built == ["local"]


def test_a_read_error_against_an_existing_database_fails_closed(tmp_path, monkeypatch):
    """The database file exists but the read fails - here, a projects table that hasn't
    been created yet, standing in for locked, corrupt, or permission-denied. This must not
    default to "standard" the way a genuinely absent project does: a read failure says
    nothing about whether the project is sensitive, and guessing "standard" would silently
    route a possibly-sensitive project's data to Chroma Cloud on a transient fault.
    """
    monkeypatch.setenv("DATABASE_DIR", str(tmp_path))
    get_settings.cache_clear()
    (tmp_path / "broken-proj.db").touch()  # exists as a file; has no projects table
    from api.services import chroma_client
    chroma_client._MODE_CACHE.clear()
    try:
        assert chroma_client.project_llm_mode("broken-proj") == "sensitive"
    finally:
        get_settings.cache_clear()


def test_a_failed_read_is_not_cached(tmp_path, monkeypatch):
    """A transient read failure must not poison the cache: the next, successful read has to
    see the database's real mode, not the fail-closed guess from the failed one - caching a
    guess is what would turn one bad read into a permanent, silent breach.
    """
    monkeypatch.setenv("DATABASE_DIR", str(tmp_path))
    get_settings.cache_clear()
    db_path = tmp_path / "recovers-proj.db"
    db_path.touch()  # exists, but has no projects table yet: the first read fails
    from api.services import chroma_client
    chroma_client._MODE_CACHE.clear()
    try:
        assert chroma_client.project_llm_mode("recovers-proj") == "sensitive"

        conn = sqlite3.connect(db_path)
        conn.execute("CREATE TABLE projects (id INTEGER PRIMARY KEY, slug TEXT, "
                     "llm_mode TEXT, sector TEXT, config_json TEXT)")
        conn.execute("INSERT INTO projects (slug, llm_mode, sector) VALUES (?,?,?)",
                     ("recovers-proj", "standard", "test"))
        conn.commit()
        conn.close()

        assert chroma_client.project_llm_mode("recovers-proj") == "standard"
    finally:
        get_settings.cache_clear()
