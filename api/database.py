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
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            output_id    INTEGER REFERENCES agent_outputs(id),
            crew_run_id  INTEGER REFERENCES crew_runs(id),
            reviewer     TEXT,
            decision     TEXT NOT NULL DEFAULT 'pending',
            prompt       TEXT,
            notes        TEXT,
            reviewed_at  DATETIME DEFAULT CURRENT_TIMESTAMP
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

        CREATE TABLE IF NOT EXISTS orchestration_runs (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            project_id   INTEGER NOT NULL REFERENCES projects(id),
            status       TEXT NOT NULL DEFAULT 'running',
            started_at   DATETIME DEFAULT CURRENT_TIMESTAMP,
            completed_at DATETIME
        );
    """)
    # executescript issues an implicit COMMIT before running; the call below
    # is a safety flush but the schema is already committed.
    await conn.commit()


async def _migrate_human_reviews(conn: aiosqlite.Connection) -> None:
    """Add prompt/crew_run_id columns and make output_id nullable on existing DBs."""
    async with conn.execute("PRAGMA table_info(human_reviews)") as cur:
        cols = {row["name"]: row async for row in cur}

    if "prompt" not in cols:
        await conn.execute("ALTER TABLE human_reviews ADD COLUMN prompt TEXT")
    if "crew_run_id" not in cols:
        await conn.execute(
            "ALTER TABLE human_reviews ADD COLUMN crew_run_id INTEGER REFERENCES crew_runs(id)"
        )

    output_id_col = cols.get("output_id")
    if output_id_col and output_id_col["notnull"]:
        # SQLite can't drop NOT NULL via ALTER — rebuild the table.
        await conn.executescript("""
            DROP TABLE IF EXISTS human_reviews_new;
            CREATE TABLE human_reviews_new (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                output_id    INTEGER REFERENCES agent_outputs(id),
                crew_run_id  INTEGER REFERENCES crew_runs(id),
                reviewer     TEXT,
                decision     TEXT NOT NULL DEFAULT 'pending',
                prompt       TEXT,
                notes        TEXT,
                reviewed_at  DATETIME DEFAULT CURRENT_TIMESTAMP
            );
            INSERT INTO human_reviews_new
                (id, output_id, reviewer, decision, notes, reviewed_at)
                SELECT id, output_id, reviewer, decision, notes, reviewed_at
                FROM human_reviews;
            DROP TABLE human_reviews;
            ALTER TABLE human_reviews_new RENAME TO human_reviews;
        """)

    await conn.commit()


@asynccontextmanager
async def get_connection(slug: str):
    path = get_db_path(slug)
    path.parent.mkdir(parents=True, exist_ok=True)
    async with aiosqlite.connect(path) as conn:
        conn.row_factory = aiosqlite.Row
        await conn.execute("PRAGMA foreign_keys = ON")
        await init_db(conn)
        await _migrate_human_reviews(conn)
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


async def insert_review(
    conn: aiosqlite.Connection, *,
    output_id: int,
    reviewer: str,
    decision: str,
    notes: str,
) -> int:
    cur = await conn.execute(
        "INSERT INTO human_reviews (output_id, reviewer, decision, notes) VALUES (?,?,?,?)",
        (output_id, reviewer, decision, notes),
    )
    await conn.commit()
    return cur.lastrowid


async def update_review(
    conn: aiosqlite.Connection, *, review_id: int, decision: str, notes: str
) -> bool:
    """Update an existing review record. Returns True if the record was found."""
    cur = await conn.execute(
        "UPDATE human_reviews SET decision=?, notes=?, reviewed_at=CURRENT_TIMESTAMP WHERE id=?",
        (decision, notes, review_id),
    )
    await conn.commit()
    return cur.rowcount > 0


async def fetch_outputs_by_type(
    conn: aiosqlite.Connection, *, project_id: int, output_type: str
) -> list[dict]:
    async with conn.execute(
        "SELECT * FROM agent_outputs WHERE project_id=? AND output_type=? ORDER BY created_at DESC",
        (project_id, output_type),
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


async def update_crew_run_status(
    conn: aiosqlite.Connection,
    *,
    run_id: int,
    status: str,
    result_json: str = "{}",
) -> None:
    await conn.execute(
        "UPDATE crew_runs SET status=?, result_json=?, finished_at=CURRENT_TIMESTAMP WHERE id=?",
        (status, result_json, run_id),
    )
    await conn.commit()


async def insert_orchestration_run(conn: aiosqlite.Connection, *, project_id: int) -> int:
    cur = await conn.execute(
        "INSERT INTO orchestration_runs (project_id, status) VALUES (?, 'running')",
        (project_id,),
    )
    await conn.commit()
    return cur.lastrowid


async def update_orchestration_run_status(
    conn: aiosqlite.Connection, *, run_id: int, status: str
) -> None:
    if status in ("completed", "failed"):
        await conn.execute(
            "UPDATE orchestration_runs SET status=?, completed_at=CURRENT_TIMESTAMP WHERE id=?",
            (status, run_id),
        )
    else:
        await conn.execute(
            "UPDATE orchestration_runs SET status=? WHERE id=?",
            (status, run_id),
        )
    await conn.commit()


async def fetch_orchestration_run(conn: aiosqlite.Connection, *, run_id: int) -> dict | None:
    async with conn.execute(
        "SELECT * FROM orchestration_runs WHERE id=?", (run_id,)
    ) as cur:
        row = await cur.fetchone()
        return dict(row) if row else None
