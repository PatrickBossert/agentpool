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
    # Cleared on the way out as well as in: the cache is process-global and keyed by slug,
    # so clearing only on entry leaves this fixture's slugs resolved for the rest of the
    # session, pointing at a tmp_path that no longer exists.
    chroma_client._MODE_CACHE.clear()
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
    chroma_client._MODE_CACHE.clear()
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


@pytest.mark.asyncio
async def test_creating_a_project_as_sensitive_is_not_pinned_to_standard(tmp_path, monkeypatch):
    """The second writer of llm_mode - and the one nothing invalidated.

    project_llm_mode caches "standard" when the database file is absent, and again when the
    row is absent. Both describe the moments around creation, including the window inside
    create_project where get_connection(slug) has made the file and insert_project has not
    yet written the row. Whatever resolves a mode in that window pins "standard" for the life
    of the process, and creation never calls update_project_config, so the invalidation wired
    into that path never fires.

    The pre-creation resolution below stands in for that window: it is the state the cache
    would be left in, reached deterministically. The assertion is on the client actually
    constructed, because the mode helper returning the right string is only half of it.
    """
    import chromadb
    from api.services import chroma_client
    from api.models import ProjectCreate
    from api.services.project_service import create_project

    monkeypatch.setenv("DATABASE_DIR", str(tmp_path))
    monkeypatch.setenv("PROJECTS_DIR", str(tmp_path / "projects"))
    monkeypatch.setenv("CHROMA_API_KEY", "cloud-key-is-set")
    get_settings.cache_clear()
    chroma_client._MODE_CACHE.clear()
    try:
        assert chroma_client.project_llm_mode("fresh-proj") == "standard"

        await create_project(
            ProjectCreate(client_slug="fresh-proj", llm_mode="sensitive", sector="rail")
        )

        assert chroma_client.project_llm_mode("fresh-proj") == "sensitive"

        built = []
        monkeypatch.setattr(chromadb, "CloudClient", lambda **kw: built.append("cloud"))
        monkeypatch.setattr(chromadb, "HttpClient", lambda **kw: built.append("local"))
        chroma_client.get_chroma_client("fresh-proj")
        assert built == ["local"], (
            "a project created as sensitive is still routed to Chroma Cloud"
        )
    finally:
        chroma_client._MODE_CACHE.clear()
        get_settings.cache_clear()


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
        chroma_client._MODE_CACHE.clear()
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
        chroma_client._MODE_CACHE.clear()
        get_settings.cache_clear()


@pytest.mark.asyncio
async def test_the_press_uses_the_project_s_fast_local_model(two_projects, monkeypatch):
    """Agents and the live follow-up must resolve from the same place.

    Asserted on the base URL the request actually reached, not on which setting was read -
    the defect this whole plan exists to fix was a correct-looking mode helper that a code
    path never consulted.
    """
    import json
    import sqlite3
    from pathlib import Path
    from api.services import interview_service as svc

    db = Path(get_settings().database_dir) / "secure-proj.db"
    with sqlite3.connect(db) as conn:
        conn.execute("UPDATE projects SET config_json=? WHERE slug=?",
                     (json.dumps({"local_fast_model": "gemma4:fast",
                                  "local_fast_url": "http://localhost:11999/v1"}), "secure-proj"))
        conn.commit()

    seen = {}

    class FakeMessages:
        async def create(self, **kw):
            seen.update(kw)
            class R:
                content = [type("T", (), {"text": "and then?"})()]
            return R()

    class FakeClient:
        def __init__(self, **kw):
            seen["base_url"] = kw.get("base_url")
            self.messages = FakeMessages()

    monkeypatch.setattr(svc, "AsyncAnthropic", FakeClient)
    await svc.elaboration_press("Q?", "short", "press", slug="secure-proj")
    assert seen["base_url"] == "http://localhost:11999/v1"
    assert seen["model"] == "gemma4:fast"


@pytest.mark.asyncio
async def test_the_press_skips_rather_than_errors_when_the_fast_tier_is_unconfigured(
    two_projects, monkeypatch
):
    """A sensitive project with no fast-tier model configured must degrade to a skipped
    follow-up, the same as an over-budget call - not raise into the endpoint and surface an
    error page to a waiting interviewee.
    """
    import json
    import sqlite3
    from pathlib import Path
    from api.services import interview_service as svc

    db = Path(get_settings().database_dir) / "secure-proj.db"
    with sqlite3.connect(db) as conn:
        conn.execute("UPDATE projects SET config_json=? WHERE slug=?",
                     (json.dumps({"local_fast_model": "", "local_fast_url": ""}), "secure-proj"))
        conn.commit()

    result = await svc.elaboration_press("Q?", "short", "press", slug="secure-proj")
    assert result == "", "an unconfigured fast tier must return no press, not raise"


@pytest.mark.asyncio
async def test_the_press_gives_up_on_budget_rather_than_stalling(two_projects, monkeypatch):
    """A local model under load must not hold a live interview open."""
    import asyncio
    from api.services import interview_service as svc

    async def never(*a, **k):
        await asyncio.sleep(5)

    monkeypatch.setattr(svc, "_press_call", never)
    result = await svc.elaboration_press("Q?", "short", "press",
                                         slug="open-proj", timeout_seconds=0.1)
    assert result == "", "an over-budget press must return no press, not raise or stall"
