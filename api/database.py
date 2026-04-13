# api/database.py
import aiosqlite
from contextlib import asynccontextmanager
from pathlib import Path
from api.config import get_settings


def get_db_path(slug: str) -> Path:
    return Path(get_settings().database_dir) / f"{slug}.db"


async def init_db(conn: aiosqlite.Connection) -> None:
    await conn.execute("PRAGMA foreign_keys = ON")
    await conn.executescript("""
        CREATE TABLE IF NOT EXISTS projects (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            slug        TEXT UNIQUE NOT NULL,
            llm_mode    TEXT NOT NULL DEFAULT 'standard',
            sector      TEXT,
            config_json TEXT,
            status      TEXT NOT NULL DEFAULT 'created',
            created_at  DATETIME DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS crew_runs (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            project_id  INTEGER NOT NULL REFERENCES projects(id),
            crew_name   TEXT NOT NULL,
            status      TEXT NOT NULL DEFAULT 'pending',
            result_json TEXT,
            started_at  DATETIME,
            finished_at DATETIME,
            created_at  DATETIME DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS agent_outputs (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            project_id  INTEGER NOT NULL REFERENCES projects(id),
            agent_name  TEXT NOT NULL,
            output_type TEXT NOT NULL,
            file_path   TEXT NOT NULL,
            version     INTEGER NOT NULL DEFAULT 1,
            review_status TEXT NOT NULL DEFAULT 'pending',
            created_at  DATETIME DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS human_reviews (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            output_id   INTEGER NOT NULL REFERENCES agent_outputs(id),
            reviewer    TEXT,
            decision    TEXT NOT NULL,
            notes       TEXT,
            reviewed_at DATETIME DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS client_documents (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            project_id   INTEGER NOT NULL REFERENCES projects(id),
            filename     TEXT NOT NULL,
            original_name TEXT NOT NULL,
            file_path    TEXT NOT NULL,
            content_type TEXT,
            size_bytes   INTEGER,
            ingested     INTEGER NOT NULL DEFAULT 0,
            uploaded_at  DATETIME DEFAULT CURRENT_TIMESTAMP
        );
    """)
    # executescript issues an implicit COMMIT before running; the call below
    # is a safety flush but the schema is already committed.
    await conn.commit()


@asynccontextmanager
async def get_connection(slug: str):
    path = get_db_path(slug)
    path.parent.mkdir(parents=True, exist_ok=True)
    async with aiosqlite.connect(path) as conn:
        conn.row_factory = aiosqlite.Row
        await conn.execute("PRAGMA foreign_keys = ON")
        await init_db(conn)
        yield conn


async def insert_project(conn: aiosqlite.Connection, *, slug: str, llm_mode: str, sector: str, config_json: str) -> bool:
    """Insert a project. Returns True if inserted, False if slug already exists."""
    try:
        await conn.execute(
            "INSERT INTO projects (slug, llm_mode, sector, config_json) VALUES (?,?,?,?)",
            (slug, llm_mode, sector, config_json),
        )
        await conn.commit()
        return True
    except aiosqlite.IntegrityError:
        return False


async def fetch_project(conn: aiosqlite.Connection, *, slug: str) -> dict | None:
    async with conn.execute("SELECT * FROM projects WHERE slug=?", (slug,)) as cur:
        row = await cur.fetchone()
        return dict(row) if row else None


async def list_projects(conn: aiosqlite.Connection) -> list[dict]:
    async with conn.execute("SELECT * FROM projects ORDER BY created_at DESC") as cur:
        return [dict(r) async for r in cur]


async def insert_crew_run(conn: aiosqlite.Connection, *, project_id: int, crew_name: str, status: str) -> int:
    cur = await conn.execute(
        "INSERT INTO crew_runs (project_id, crew_name, status, started_at) VALUES (?,?,?, CURRENT_TIMESTAMP)",
        (project_id, crew_name, status),
    )
    await conn.commit()
    return cur.lastrowid


async def fetch_crew_runs(conn: aiosqlite.Connection, *, project_id: int) -> list[dict]:
    async with conn.execute(
        "SELECT * FROM crew_runs WHERE project_id=? ORDER BY created_at DESC", (project_id,)
    ) as cur:
        return [dict(r) async for r in cur]


async def insert_agent_output(conn: aiosqlite.Connection, *, project_id: int, agent_name: str,
                               output_type: str, file_path: str, version: int) -> int:
    cur = await conn.execute(
        "INSERT INTO agent_outputs (project_id, agent_name, output_type, file_path, version) VALUES (?,?,?,?,?)",
        (project_id, agent_name, output_type, file_path, version),
    )
    await conn.commit()
    return cur.lastrowid


async def fetch_agent_outputs(conn: aiosqlite.Connection, *, project_id: int) -> list[dict]:
    async with conn.execute(
        "SELECT * FROM agent_outputs WHERE project_id=? ORDER BY created_at DESC", (project_id,)
    ) as cur:
        return [dict(r) async for r in cur]


async def insert_document(
    conn: aiosqlite.Connection, *,
    project_id: int,
    filename: str,
    original_name: str,
    file_path: str,
    content_type: str,
    size_bytes: int,
) -> int:
    cur = await conn.execute(
        """INSERT INTO client_documents
           (project_id, filename, original_name, file_path, content_type, size_bytes)
           VALUES (?,?,?,?,?,?)""",
        (project_id, filename, original_name, file_path, content_type, size_bytes),
    )
    await conn.commit()
    return cur.lastrowid


async def fetch_documents(conn: aiosqlite.Connection, *, project_id: int) -> list[dict]:
    async with conn.execute(
        "SELECT * FROM client_documents WHERE project_id=? ORDER BY uploaded_at DESC",
        (project_id,),
    ) as cur:
        return [dict(r) async for r in cur]


# ── System DB (users) ────────────────────────────────────────────────────────

def get_system_db_path() -> Path:
    return Path(get_settings().database_dir) / "system.db"


@asynccontextmanager
async def get_system_connection():
    path = get_system_db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    async with aiosqlite.connect(path) as conn:
        conn.row_factory = aiosqlite.Row
        await conn.execute("PRAGMA foreign_keys = ON")
        await conn.executescript("""
            CREATE TABLE IF NOT EXISTS users (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                username    TEXT UNIQUE NOT NULL,
                role        TEXT NOT NULL DEFAULT 'consultant',
                hashed_pw   TEXT NOT NULL,
                project_slug TEXT,
                created_at  DATETIME DEFAULT CURRENT_TIMESTAMP
            );
        """)
        await conn.commit()
        yield conn


async def fetch_user(conn: aiosqlite.Connection, *, username: str) -> dict | None:
    async with conn.execute("SELECT * FROM users WHERE username=?", (username,)) as cur:
        row = await cur.fetchone()
        return dict(row) if row else None


async def insert_user(conn: aiosqlite.Connection, *, username: str, role: str,
                      hashed_pw: str, project_slug: str | None = None) -> bool:
    """Returns True if inserted, False if username already exists."""
    try:
        await conn.execute(
            "INSERT INTO users (username, role, hashed_pw, project_slug) VALUES (?,?,?,?)",
            (username, role, hashed_pw, project_slug),
        )
        await conn.commit()
        return True
    except aiosqlite.IntegrityError:
        return False
