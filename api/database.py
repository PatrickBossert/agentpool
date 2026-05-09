# api/database.py
import aiosqlite
import json as _json
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


async def _migrate_crew_runs(conn: aiosqlite.Connection) -> None:
    """Add orchestration_run_id FK column to crew_runs on existing DBs."""
    async with conn.execute("PRAGMA table_info(crew_runs)") as cur:
        cols = [row["name"] async for row in cur]
    if "orchestration_run_id" not in cols:
        await conn.execute(
            "ALTER TABLE crew_runs ADD COLUMN orchestration_run_id INTEGER REFERENCES orchestration_runs(id)"
        )
        await conn.commit()


async def _migrate_stakeholders(conn: aiosqlite.Connection) -> None:
    """Create stakeholders table if it doesn't exist."""
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS stakeholders (
            id                  INTEGER PRIMARY KEY AUTOINCREMENT,
            project_id          INTEGER NOT NULL REFERENCES projects(id),
            name                TEXT NOT NULL,
            job_title           TEXT NOT NULL DEFAULT '',
            organisation        TEXT NOT NULL DEFAULT '',
            email               TEXT NOT NULL DEFAULT '',
            slack_handle        TEXT NOT NULL DEFAULT '',
            stakeholder_groups  TEXT NOT NULL DEFAULT '[]',
            project_role        TEXT NOT NULL DEFAULT 'recipient',
            value_streams       TEXT NOT NULL DEFAULT '[]',
            value_chain_stage   TEXT NOT NULL DEFAULT '',
            activity            TEXT NOT NULL DEFAULT '',
            disposition         TEXT NOT NULL DEFAULT 'neutral',
            location            TEXT NOT NULL DEFAULT '',
            country_code        TEXT NOT NULL DEFAULT '',
            timezone            TEXT NOT NULL DEFAULT '',
            preferred_language  TEXT NOT NULL DEFAULT '',
            currency            TEXT NOT NULL DEFAULT '',
            created_at          DATETIME DEFAULT CURRENT_TIMESTAMP
        )
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
        await _migrate_crew_runs(conn)
        await _migrate_stakeholders(conn)
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


async def insert_crew_run(
    conn: aiosqlite.Connection,
    *,
    project_id: int,
    crew_name: str,
    status: str,
    orchestration_run_id: int | None = None,
) -> int:
    cur = await conn.execute(
        "INSERT INTO crew_runs (project_id, crew_name, status, started_at, orchestration_run_id) "
        "VALUES (?,?,?, CURRENT_TIMESTAMP, ?)",
        (project_id, crew_name, status, orchestration_run_id),
    )
    await conn.commit()
    return cur.lastrowid


async def fetch_crew_runs(conn: aiosqlite.Connection, *, project_id: int) -> list[dict]:
    async with conn.execute(
        "SELECT * FROM crew_runs WHERE project_id=? ORDER BY created_at DESC", (project_id,)
    ) as cur:
        return [dict(r) async for r in cur]


async def fetch_latest_orchestration_run(
    conn: aiosqlite.Connection, *, project_id: int
) -> dict | None:
    async with conn.execute(
        "SELECT id, status, started_at, completed_at "
        "FROM orchestration_runs WHERE project_id=? "
        "ORDER BY started_at DESC LIMIT 1",
        (project_id,),
    ) as cur:
        row = await cur.fetchone()
    return dict(row) if row else None


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


async def update_project_config(
    conn: aiosqlite.Connection,
    *,
    project_id: int,
    llm_mode: str,
    sector: str,
    config_json: str,
) -> None:
    await conn.execute(
        "UPDATE projects SET llm_mode=?, sector=?, config_json=? WHERE id=?",
        (llm_mode, sector, config_json, project_id),
    )
    await conn.commit()


async def update_document_ingested(
    conn: aiosqlite.Connection, *, doc_id: int
) -> None:
    await conn.execute(
        "UPDATE client_documents SET ingested=1 WHERE id=?",
        (doc_id,),
    )
    await conn.commit()


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


async def fetch_pending_reviews(
    conn: aiosqlite.Connection, *, project_id: int
) -> list[dict]:
    """Return pending HITL human_reviews rows for a project, by insertion order (id DESC).

    Joins through crew_runs because human_reviews has no direct project_id.
    Rows with crew_run_id IS NULL (legacy output reviews) are excluded by the JOIN.
    """
    async with conn.execute(
        """
        SELECT hr.id, hr.prompt, hr.crew_run_id, hr.decision, hr.reviewed_at
        FROM human_reviews hr
        JOIN crew_runs cr ON cr.id = hr.crew_run_id
        WHERE cr.project_id = ? AND hr.decision = 'pending'
        ORDER BY hr.id DESC
        """,
        (project_id,),
    ) as cur:
        rows = await cur.fetchall()
    return [dict(r) for r in rows]


async def fetch_outputs_by_type(
    conn: aiosqlite.Connection, *, project_id: int, output_type: str
) -> list[dict]:
    async with conn.execute(
        "SELECT * FROM agent_outputs WHERE project_id=? AND output_type=? ORDER BY created_at DESC",
        (project_id, output_type),
    ) as cur:
        return [dict(r) async for r in cur]


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


async def fetch_all_orchestration_runs(
    conn: aiosqlite.Connection, *, project_id: int
) -> list[dict]:
    """Return all orchestration_runs for a project (newest first) with crew summaries.

    Uses LEFT JOIN so orch runs with no linked crew_runs still appear (crew_runs=[]).
    Crew runs with orchestration_run_id IS NULL are excluded by the JOIN condition.
    """
    async with conn.execute(
        """
        SELECT
            o.id,
            o.status,
            o.started_at,
            o.completed_at,
            cr.crew_name,
            cr.status AS crew_status
        FROM orchestration_runs o
        LEFT JOIN crew_runs cr ON cr.orchestration_run_id = o.id
        WHERE o.project_id = ?
        ORDER BY o.started_at DESC, cr.id ASC
        """,
        (project_id,),
    ) as cur:
        rows = await cur.fetchall()

    # Group crew_runs per orchestration run, preserving DESC order of orch runs
    runs: dict[int, dict] = {}
    for row in rows:
        r = dict(row)
        oid = r["id"]
        if oid not in runs:
            runs[oid] = {
                "id": oid,
                "status": r["status"],
                "started_at": r["started_at"],
                "completed_at": r["completed_at"],
                "crew_runs": [],
            }
        if r["crew_name"] is not None:
            runs[oid]["crew_runs"].append(
                {"crew_name": r["crew_name"], "status": r["crew_status"]}
            )
    return list(runs.values())


async def insert_stakeholder(
    conn: aiosqlite.Connection,
    *,
    project_id: int,
    name: str,
    job_title: str = '',
    organisation: str = '',
    email: str = '',
    slack_handle: str = '',
    stakeholder_groups: list = None,
    project_role: str = 'recipient',
    value_streams: list = None,
    value_chain_stage: str = '',
    activity: str = '',
    disposition: str = 'neutral',
    location: str = '',
    country_code: str = '',
    timezone: str = '',
    preferred_language: str = '',
    currency: str = '',
) -> int:
    """Insert a stakeholder row. Returns new id."""
    cur = await conn.execute(
        """INSERT INTO stakeholders
           (project_id, name, job_title, organisation, email, slack_handle,
            stakeholder_groups, project_role, value_streams, value_chain_stage,
            activity, disposition, location, country_code, timezone,
            preferred_language, currency)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            project_id, name, job_title, organisation, email, slack_handle,
            _json.dumps(stakeholder_groups or []),
            project_role,
            _json.dumps(value_streams or []),
            value_chain_stage, activity, disposition,
            location, country_code, timezone, preferred_language, currency,
        ),
    )
    await conn.commit()
    return cur.lastrowid


def _deserialize_stakeholder(row: dict) -> dict:
    """Convert JSON text columns back to Python lists."""
    row["stakeholder_groups"] = _json.loads(row.get("stakeholder_groups") or "[]")
    row["value_streams"] = _json.loads(row.get("value_streams") or "[]")
    return row


async def fetch_stakeholders(
    conn: aiosqlite.Connection, *, project_id: int
) -> list[dict]:
    """Return all stakeholders for a project, ordered by name ASC."""
    async with conn.execute(
        "SELECT * FROM stakeholders WHERE project_id=? ORDER BY name ASC",
        (project_id,),
    ) as cur:
        return [_deserialize_stakeholder(dict(r)) async for r in cur]


async def fetch_stakeholder(
    conn: aiosqlite.Connection, *, stakeholder_id: int, project_id: int
) -> dict | None:
    """Return one stakeholder; None if not found or belongs to different project."""
    async with conn.execute(
        "SELECT * FROM stakeholders WHERE id=? AND project_id=?",
        (stakeholder_id, project_id),
    ) as cur:
        row = await cur.fetchone()
    return _deserialize_stakeholder(dict(row)) if row else None


_STAKEHOLDER_UPDATABLE_FIELDS = frozenset({
    "name", "job_title", "organisation", "email", "slack_handle",
    "stakeholder_groups", "project_role", "value_streams", "value_chain_stage",
    "activity", "disposition", "location", "country_code", "timezone",
    "preferred_language", "currency",
})


async def update_stakeholder(
    conn: aiosqlite.Connection, *, stakeholder_id: int, **fields
) -> bool:
    """Update stakeholder fields by id. Returns False if not found.

    JSON-serializes list fields automatically.
    Only allows updates to known columns (prevents SQL injection via key names).
    """
    invalid = set(fields) - _STAKEHOLDER_UPDATABLE_FIELDS
    if invalid:
        raise ValueError(f"Unknown stakeholder fields: {invalid}")

    for key in ("stakeholder_groups", "value_streams"):
        if key in fields and isinstance(fields[key], list):
            fields[key] = _json.dumps(fields[key])

    if not fields:
        return False
    set_clause = ", ".join(f"{k}=?" for k in fields)
    values = list(fields.values()) + [stakeholder_id]
    cur = await conn.execute(
        f"UPDATE stakeholders SET {set_clause} WHERE id=?", values
    )
    await conn.commit()
    return cur.rowcount > 0


async def delete_stakeholder(
    conn: aiosqlite.Connection, *, stakeholder_id: int
) -> bool:
    """Hard delete. Returns False if not found."""
    cur = await conn.execute(
        "DELETE FROM stakeholders WHERE id=?", (stakeholder_id,)
    )
    await conn.commit()
    return cur.rowcount > 0


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
