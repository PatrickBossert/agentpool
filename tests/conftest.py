# tests/conftest.py
import os
import shutil
import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from pathlib import Path

from api.config import get_settings

# asyncio_mode = strict (see pytest.ini) — all async tests must use @pytest.mark.asyncio

# Point to a temp directory so tests never touch real project data
os.environ.setdefault("DATABASE_DIR", "/tmp/agentpool_test")
os.environ.setdefault("PROJECTS_DIR", "/tmp/agentpool_test_projects")
# DATA_DIR gets a directory of its own, emptied at the start of every session. It backs the
# TTS cache (api/services/tts_cache.py), which is keyed by voice and text and never expires,
# so pointing it at the persistent /tmp/agentpool_test isolated it from the repo's real
# data/ and not at all from the previous run: the first test to call speak() without its own
# override would store its audio, pass, and then be served a cache hit for ever after -
# passing once and failing on every run afterwards, exactly the trap CLAUDE.md documents.
os.environ.setdefault("DATA_DIR", "/tmp/agentpool_test_data")
os.environ.setdefault("JWT_SECRET", "test-secret")
os.environ.setdefault("ADMIN_PASSWORD", "test-admin-pw")
os.environ.setdefault("ADMIN_USERNAME", "admin")
os.environ.setdefault("ANTHROPIC_API_KEY", "test-key")
os.environ.setdefault("LITELLM_PROXY_URL", "http://localhost:4000")
os.environ.setdefault("CHROMA_HOST", "localhost")
os.environ.setdefault("CHROMA_PORT", "8002")  # pydantic coerces str→int
# Blank all credential-gated settings so unit tests behave identically whether
# or not the developer has real services configured in .env. pydantic-settings
# reads .env directly, so without these a populated .env changes test outcomes:
# a real CHROMA_API_KEY flips ingest_service to CloudClient, a real
# RESEND_API_KEY makes "no key" paths attempt real sends, and so on.
os.environ.setdefault("CHROMA_API_KEY", "")
os.environ.setdefault("RESEND_API_KEY", "")
os.environ.setdefault("TAVILY_API_KEY", "")
os.environ.setdefault("ELEVENLABS_API_KEY", "")
os.environ.setdefault("DEEPGRAM_API_KEY", "")
os.environ.setdefault("N8N_WEBHOOK_URL", "")

Path("/tmp/agentpool_test").mkdir(exist_ok=True)
Path("/tmp/agentpool_test_projects").mkdir(exist_ok=True)

# Recreated rather than merely ensured: an empty DATA_DIR is the whole point of giving it one.
_data_dir = Path(os.environ["DATA_DIR"])
if _data_dir.is_dir() and _data_dir.name == "agentpool_test_data":
    shutil.rmtree(_data_dir, ignore_errors=True)
_data_dir.mkdir(parents=True, exist_ok=True)


@pytest.fixture(autouse=True)
def reset_settings_cache():
    """Rebuild Settings for every test and drop the cache afterwards.

    get_settings() is lru_cached. Tests that monkeypatch env vars and call
    cache_clear() themselves get correct settings — but monkeypatch restores the
    environment at teardown while the cache still holds the Settings object
    built from the patched values. Every later test then reads a stale config;
    test_admin.py pointing DATABASE_DIR at /tmp/test_admin_db was making the
    agent-chat tests 404 because the app looked for projects in the wrong
    directory.

    Clearing on both sides makes each test read the environment as it stands.
    """
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
def seeded_project(tmp_path, monkeypatch):
    """A project whose value_chain_registry already holds 1.2 and 2.7 as active L2 activities.

    So the pre-existing anchor checks (validate_scripts_against_registry, validate_anchor_levels)
    pass on both nodes and a scripts write under test fails - or warns - for its own reason
    rather than an unrelated one.

    Self-contained: points PROJECTS_DIR/DATABASE_DIR at this test's own tmp_path and creates the
    minimal schema SQLiteStateTool's write path needs, so it does not depend on any other
    fixture having run first. Shared by tests/test_sqlite_state_validation.py (the script
    registry succession door) and tests/test_coverage_validation.py (the coverage warner) -
    moved here rather than duplicated once both needed it.

    Plain, not `@pytest_asyncio.fixture`: SQLiteStateTool._run and every helper this fixture
    uses are synchronous.
    """
    import json
    import sqlite3

    from api.config import get_settings
    from api.database import get_connection
    from agents.tools.sqlite_state import SQLiteStateTool

    slug = "seeded-coverage-project"
    monkeypatch.setenv("PROJECTS_DIR", str(tmp_path))
    db_dir = tmp_path / "data"
    db_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("DATABASE_DIR", str(db_dir))
    get_settings.cache_clear()

    conn = sqlite3.connect(str(db_dir / f"{slug}.db"))
    conn.execute("CREATE TABLE projects (id INTEGER PRIMARY KEY, slug TEXT)")
    # Mirrors api/database.py including migration-added columns
    conn.execute(
        "CREATE TABLE agent_outputs ("
        " id INTEGER PRIMARY KEY, project_id INTEGER, agent_name TEXT,"
        " output_type TEXT, file_path TEXT, version INTEGER,"
        " review_status TEXT DEFAULT 'pending', revision_notes TEXT,"
        " is_current INTEGER NOT NULL DEFAULT 1,"
        " created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)"
    )
    # Lineage bookkeeping tables link_output_sync writes to on every successful write.
    conn.execute(
        "CREATE TABLE run_inputs (run_id INTEGER, agent_name TEXT, output_id INTEGER,"
        " PRIMARY KEY (run_id, agent_name, output_id))"
    )
    conn.execute(
        "CREATE TABLE run_documents (run_id INTEGER, agent_name TEXT, doc_id INTEGER,"
        " PRIMARY KEY (run_id, agent_name, doc_id))"
    )
    conn.execute(
        "CREATE TABLE output_lineage (output_id INTEGER, input_output_id INTEGER,"
        " PRIMARY KEY (output_id, input_output_id))"
    )
    conn.execute(
        "CREATE TABLE output_citations (output_id INTEGER, doc_id INTEGER,"
        " PRIMARY KEY (output_id, doc_id))"
    )
    conn.execute("INSERT INTO projects (id, slug) VALUES (1, ?)", (slug,))
    conn.commit()
    conn.close()

    # record_validation_warnings_sync writes straight into validation_warnings with a bare
    # sqlite3 connection - it does not migrate, only get_connection does. Without running the
    # migration once here, the coverage warner's write finds no such table, is swallowed by
    # the write hook's best-effort except, and the surface test fails silently rather than
    # for its own reason.
    import asyncio

    async def _migrate():
        async with get_connection(slug):
            pass

    asyncio.run(_migrate())

    tool = SQLiteStateTool(slug=slug)
    tool._run(
        operation="write", key="value_chain_registry", agent_name="value_chain_mapper",
        value=json.dumps({"schema_version": 2, "activities": [
            {"id": "1.2", "label": "Portfolio", "level": "L2", "active": True},
            {"id": "2.7", "label": "Elsewhere", "level": "L2", "active": True},
        ]}),
    )
    yield slug
    get_settings.cache_clear()


@pytest_asyncio.fixture
async def client():
    from api.main import app
    from api.auth import create_access_token
    # Use a sysadmin token so all project-scoped endpoints pass auth checks
    token = create_access_token("admin", "sysadmin", "test-secret")
    headers = {"Authorization": f"Bearer {token}"}
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test", headers=headers) as ac:
        yield ac
