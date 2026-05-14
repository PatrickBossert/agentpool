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


async def _migrate_campaigns(conn: aiosqlite.Connection) -> None:
    """Create campaigns, interview_responses, reminder_emails tables;
    add interview_status/interview_invited_at/interview_completed_at to stakeholders."""

    await conn.executescript("""
        CREATE TABLE IF NOT EXISTS campaigns (
            id                      INTEGER PRIMARY KEY AUTOINCREMENT,
            project_id              INTEGER NOT NULL REFERENCES projects(id),
            value_stream_name       TEXT NOT NULL DEFAULT '',
            listenlabs_campaign_id  TEXT NOT NULL DEFAULT '',
            campaign_name           TEXT NOT NULL DEFAULT '',
            interview_start         TEXT,
            interview_close         TEXT,
            findings_summary        TEXT NOT NULL DEFAULT '',
            created_at              DATETIME DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS interview_responses (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            stakeholder_id  INTEGER NOT NULL REFERENCES stakeholders(id),
            campaign_id     INTEGER NOT NULL REFERENCES campaigns(id),
            raw_data        TEXT NOT NULL,
            imported_at     DATETIME DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS reminder_emails (
            id                  INTEGER PRIMARY KEY AUTOINCREMENT,
            project_id          INTEGER NOT NULL REFERENCES projects(id),
            campaign_id         INTEGER NOT NULL REFERENCES campaigns(id),
            stakeholder_id      INTEGER NOT NULL REFERENCES stakeholders(id),
            subject             TEXT NOT NULL DEFAULT '',
            body                TEXT NOT NULL DEFAULT '',
            escalation_level    TEXT NOT NULL DEFAULT 'gentle',
            status              TEXT NOT NULL DEFAULT 'pending',
            created_at          DATETIME DEFAULT CURRENT_TIMESTAMP
        );
    """)
    await conn.commit()

    # Add interview columns to stakeholders if missing
    async with conn.execute("PRAGMA table_info(stakeholders)") as cur:
        cols = {row["name"] async for row in cur}

    for col, defn in [
        ("interview_status",       "TEXT"),
        ("interview_invited_at",   "DATETIME"),
        ("interview_completed_at", "DATETIME"),
    ]:
        if col not in cols:
            await conn.execute(f"ALTER TABLE stakeholders ADD COLUMN {col} {defn}")

    await conn.commit()


async def _migrate_stakeholder_assignments(conn: aiosqlite.Connection) -> None:
    """Create stakeholder_assignments table if it doesn't exist."""
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS stakeholder_assignments (
            id                    INTEGER PRIMARY KEY AUTOINCREMENT,
            orchestration_run_id  INTEGER NOT NULL REFERENCES orchestration_runs(id),
            stakeholder_id        INTEGER NOT NULL REFERENCES stakeholders(id),
            level                 TEXT NOT NULL,
            node_label            TEXT NOT NULL,
            created_at            DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)
    await conn.commit()


async def _migrate_interview_sessions(conn: aiosqlite.Connection) -> None:
    """Create interview_sessions table if it doesn't exist."""
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS interview_sessions (
            id                    INTEGER PRIMARY KEY AUTOINCREMENT,
            project_id            INTEGER NOT NULL REFERENCES projects(id),
            orchestration_run_id  INTEGER REFERENCES orchestration_runs(id),
            stakeholder_id        INTEGER NOT NULL REFERENCES stakeholders(id),
            node_label            TEXT NOT NULL,
            session_token         TEXT NOT NULL UNIQUE,
            status                TEXT NOT NULL DEFAULT 'pending',
            transcript_json       TEXT,
            started_at            TEXT,
            completed_at          TEXT,
            created_at            DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)
    await conn.commit()


async def _migrate_interview_sessions_ratings(conn: aiosqlite.Connection) -> None:
    """Add ratings_json column to interview_sessions if missing."""
    async with conn.execute("PRAGMA table_info(interview_sessions)") as cur:
        cols = {row["name"] async for row in cur}
    if "ratings_json" not in cols:
        await conn.execute("ALTER TABLE interview_sessions ADD COLUMN ratings_json TEXT")
        await conn.commit()


async def _migrate_node_template_assignments(conn: aiosqlite.Connection) -> None:
    """Create node_template_assignments table if it doesn't exist."""
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS node_template_assignments (
            id                        INTEGER PRIMARY KEY AUTOINCREMENT,
            project_id                INTEGER NOT NULL REFERENCES projects(id),
            node_label                TEXT    NOT NULL,
            interview_template_id     INTEGER,
            questionnaire_template_id INTEGER,
            created_at                TEXT NOT NULL DEFAULT (datetime('now')),
            updated_at                TEXT NOT NULL DEFAULT (datetime('now')),
            UNIQUE(project_id, node_label)
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
        await _migrate_campaigns(conn)
        await _migrate_stakeholder_assignments(conn)
        await _migrate_interview_sessions(conn)
        await _migrate_node_template_assignments(conn)
        await _migrate_interview_sessions_ratings(conn)
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


# ── Campaigns ─────────────────────────────────────────────────────────────────

async def insert_campaign(
    conn: aiosqlite.Connection,
    *,
    project_id: int,
    value_stream_name: str = '',
    listenlabs_campaign_id: str = '',
    campaign_name: str = '',
    interview_start: str | None = None,
    interview_close: str | None = None,
) -> int:
    cur = await conn.execute(
        """INSERT INTO campaigns
           (project_id, value_stream_name, listenlabs_campaign_id, campaign_name,
            interview_start, interview_close)
           VALUES (?,?,?,?,?,?)""",
        (project_id, value_stream_name, listenlabs_campaign_id, campaign_name,
         interview_start, interview_close),
    )
    await conn.commit()
    return cur.lastrowid


async def fetch_campaigns(conn: aiosqlite.Connection, *, project_id: int) -> list[dict]:
    async with conn.execute(
        "SELECT * FROM campaigns WHERE project_id=? ORDER BY created_at ASC",
        (project_id,),
    ) as cur:
        return [dict(r) async for r in cur]


async def fetch_campaign(
    conn: aiosqlite.Connection, *, campaign_id: int, project_id: int
) -> dict | None:
    async with conn.execute(
        "SELECT * FROM campaigns WHERE id=? AND project_id=?",
        (campaign_id, project_id),
    ) as cur:
        row = await cur.fetchone()
    return dict(row) if row else None


_CAMPAIGN_UPDATABLE = frozenset({
    'value_stream_name', 'listenlabs_campaign_id', 'campaign_name',
    'interview_start', 'interview_close', 'findings_summary',
})


async def update_campaign(
    conn: aiosqlite.Connection, *, campaign_id: int, **fields
) -> bool:
    invalid = set(fields) - _CAMPAIGN_UPDATABLE
    if invalid:
        raise ValueError(f"Unknown campaign fields: {invalid}")
    if not fields:
        return False
    set_clause = ", ".join(f"{k}=?" for k in fields)
    values = list(fields.values()) + [campaign_id]
    cur = await conn.execute(
        f"UPDATE campaigns SET {set_clause} WHERE id=?", values
    )
    await conn.commit()
    return cur.rowcount > 0


async def delete_campaign(conn: aiosqlite.Connection, *, campaign_id: int) -> bool:
    cur = await conn.execute("DELETE FROM campaigns WHERE id=?", (campaign_id,))
    await conn.commit()
    return cur.rowcount > 0


async def fetch_stakeholders_for_value_stream(
    conn: aiosqlite.Connection,
    *,
    project_id: int,
    value_stream_name: str,
    exclude_completed: bool = False,
) -> list[dict]:
    """Return stakeholders whose value_streams JSON array contains value_stream_name."""
    clause = "WHERE project_id=? AND value_streams LIKE ?"
    params: list = [project_id, f'%"{value_stream_name}"%']
    if exclude_completed:
        clause += " AND (interview_status IS NULL OR interview_status != 'completed')"
    async with conn.execute(
        f"SELECT * FROM stakeholders {clause} ORDER BY name ASC", params
    ) as cur:
        return [_deserialize_stakeholder(dict(r)) async for r in cur]


async def update_stakeholder_interview_status(
    conn: aiosqlite.Connection,
    *,
    stakeholder_id: int,
    status: str,
    completed_at: str | None = None,
    invited_at: str | None = None,
) -> bool:
    parts = ["interview_status=?"]
    vals: list = [status]
    if completed_at is not None:
        parts.append("interview_completed_at=?")
        vals.append(completed_at)
    if invited_at is not None:
        parts.append("interview_invited_at=?")
        vals.append(invited_at)
    vals.append(stakeholder_id)
    cur = await conn.execute(
        f"UPDATE stakeholders SET {', '.join(parts)} WHERE id=?", vals
    )
    await conn.commit()
    return cur.rowcount > 0


async def insert_interview_response(
    conn: aiosqlite.Connection,
    *,
    stakeholder_id: int,
    campaign_id: int,
    raw_data: str,
) -> int:
    cur = await conn.execute(
        "INSERT INTO interview_responses (stakeholder_id, campaign_id, raw_data) VALUES (?,?,?)",
        (stakeholder_id, campaign_id, raw_data),
    )
    await conn.commit()
    return cur.lastrowid


async def fetch_interview_responses(
    conn: aiosqlite.Connection, *, campaign_id: int
) -> list[dict]:
    async with conn.execute(
        "SELECT * FROM interview_responses WHERE campaign_id=? ORDER BY imported_at ASC",
        (campaign_id,),
    ) as cur:
        return [dict(r) async for r in cur]


async def insert_reminder_email(
    conn: aiosqlite.Connection,
    *,
    project_id: int,
    campaign_id: int,
    stakeholder_id: int,
    subject: str,
    body: str,
    escalation_level: str,
) -> int:
    cur = await conn.execute(
        """INSERT INTO reminder_emails
           (project_id, campaign_id, stakeholder_id, subject, body, escalation_level)
           VALUES (?,?,?,?,?,?)""",
        (project_id, campaign_id, stakeholder_id, subject, body, escalation_level),
    )
    await conn.commit()
    return cur.lastrowid


async def fetch_reminder_emails(
    conn: aiosqlite.Connection, *, project_id: int, status: str = 'pending'
) -> list[dict]:
    async with conn.execute(
        "SELECT * FROM reminder_emails WHERE project_id=? AND status=? ORDER BY created_at DESC",
        (project_id, status),
    ) as cur:
        return [dict(r) async for r in cur]


async def update_reminder_email(
    conn: aiosqlite.Connection,
    *,
    email_id: int,
    project_id: int,
    status: str,
    subject: str | None = None,
    body: str | None = None,
) -> bool:
    parts = ["status=?"]
    vals: list = [status]
    if subject is not None:
        parts.append("subject=?")
        vals.append(subject)
    if body is not None:
        parts.append("body=?")
        vals.append(body)
    vals += [email_id, project_id]
    cur = await conn.execute(
        f"UPDATE reminder_emails SET {', '.join(parts)} WHERE id=? AND project_id=?", vals
    )
    await conn.commit()
    return cur.rowcount > 0


# ── System DB (users + templates) ────────────────────────────────────────────

def get_system_db_path() -> Path:
    return Path(get_settings().database_dir) / "system.db"


async def init_system_db(conn: aiosqlite.Connection) -> None:
    """Initialise all system.db tables (idempotent)."""
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

        CREATE TABLE IF NOT EXISTS interview_templates (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            name        TEXT    NOT NULL,
            description TEXT    NOT NULL DEFAULT '',
            type        TEXT    NOT NULL CHECK(type IN ('interview', 'questionnaire')),
            schema_json TEXT    NOT NULL,
            created_at  TEXT    NOT NULL DEFAULT (datetime('now')),
            updated_at  TEXT    NOT NULL DEFAULT (datetime('now'))
        );
    """)
    await conn.commit()


@asynccontextmanager
async def get_system_connection():
    path = get_system_db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    async with aiosqlite.connect(path) as conn:
        conn.row_factory = aiosqlite.Row
        await init_system_db(conn)
        yield conn


async def get_system_db():
    """FastAPI dependency: yields an aiosqlite connection to system.db."""
    path = get_system_db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    async with aiosqlite.connect(str(path)) as conn:
        conn.row_factory = aiosqlite.Row
        await init_system_db(conn)
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


# ── Stakeholder Assignments ───────────────────────────────────────────────────

async def fetch_stakeholder_assignments(
    conn: aiosqlite.Connection, *, orchestration_run_id: int
) -> list[dict]:
    """Return all assignments for an orchestration run, ordered by id."""
    async with conn.execute(
        "SELECT * FROM stakeholder_assignments WHERE orchestration_run_id=? ORDER BY id",
        (orchestration_run_id,),
    ) as cur:
        return [dict(r) async for r in cur]


async def replace_stakeholder_assignments(
    conn: aiosqlite.Connection,
    *,
    orchestration_run_id: int,
    assignments: list[dict],
) -> int:
    """Replace all assignments for this run. Returns count saved."""
    await conn.execute(
        "DELETE FROM stakeholder_assignments WHERE orchestration_run_id=?",
        (orchestration_run_id,),
    )
    for a in assignments:
        await conn.execute(
            "INSERT INTO stakeholder_assignments "
            "(orchestration_run_id, stakeholder_id, level, node_label) VALUES (?,?,?,?)",
            (orchestration_run_id, a["stakeholder_id"], a["level"], a["node_label"]),
        )
    await conn.commit()
    return len(assignments)


# ── Interview Sessions ────────────────────────────────────────────────────────

async def insert_interview_session(
    conn: aiosqlite.Connection,
    *,
    project_id: int,
    orchestration_run_id: int | None,
    stakeholder_id: int,
    node_label: str,
    session_token: str,
) -> int:
    cur = await conn.execute(
        "INSERT INTO interview_sessions "
        "(project_id, orchestration_run_id, stakeholder_id, node_label, session_token) "
        "VALUES (?,?,?,?,?)",
        (project_id, orchestration_run_id, stakeholder_id, node_label, session_token),
    )
    await conn.commit()
    return cur.lastrowid


async def fetch_interview_session(
    conn: aiosqlite.Connection, session_token: str
) -> dict | None:
    async with conn.execute(
        "SELECT * FROM interview_sessions WHERE session_token=?", (session_token,)
    ) as cur:
        row = await cur.fetchone()
    return dict(row) if row else None


async def fetch_interview_sessions_status(
    conn: aiosqlite.Connection, *, orchestration_run_id: int
) -> dict:
    """Return counts of sessions by status for a given orchestration run."""
    counts = {"pending": 0, "active": 0, "completed": 0, "abandoned": 0}
    async with conn.execute(
        "SELECT status, COUNT(*) as n FROM interview_sessions "
        "WHERE orchestration_run_id=? GROUP BY status",
        (orchestration_run_id,),
    ) as cur:
        async for row in cur:
            status = row["status"]
            if status in counts:
                counts[status] = row["n"]
    return counts


async def fetch_interview_transcripts(
    conn: aiosqlite.Connection, *, orchestration_run_id: int
) -> list[dict]:
    """Return completed sessions with stakeholder name for transcript assembly."""
    async with conn.execute(
        "SELECT s.name, is_.stakeholder_id, is_.node_label, is_.transcript_json "
        "FROM interview_sessions is_ "
        "JOIN stakeholders s ON s.id = is_.stakeholder_id "
        "WHERE is_.orchestration_run_id=? AND is_.status='completed'",
        (orchestration_run_id,),
    ) as cur:
        return [dict(row) async for row in cur]


async def update_interview_session_status(
    conn: aiosqlite.Connection, session_token: str, status: str
) -> None:
    await conn.execute(
        "UPDATE interview_sessions SET status=? WHERE session_token=?",
        (status, session_token),
    )
    await conn.commit()


async def complete_interview_session(
    conn, session_token: str, transcript_json: str, ratings_json: str | None = None
) -> None:
    await conn.execute(
        """UPDATE interview_sessions
           SET status='completed', transcript_json=?, ratings_json=?,
               completed_at=datetime('now')
           WHERE session_token=?""",
        (transcript_json, ratings_json, session_token),
    )
    await conn.commit()


# ── Interview Templates ───────────────────────────────────────────────────────

async def fetch_all_templates(conn, type_filter=None) -> list:
    """List all templates; optionally filter by type ('interview'|'questionnaire')."""
    if type_filter:
        async with conn.execute(
            "SELECT id, name, description, type, created_at, updated_at "
            "FROM interview_templates WHERE type=? ORDER BY name",
            (type_filter,),
        ) as cur:
            return [dict(r) async for r in cur]
    async with conn.execute(
        "SELECT id, name, description, type, created_at, updated_at "
        "FROM interview_templates ORDER BY name"
    ) as cur:
        return [dict(r) async for r in cur]


async def fetch_template(conn, template_id: int):
    """Fetch one template including schema_json. Returns dict or None."""
    async with conn.execute(
        "SELECT * FROM interview_templates WHERE id=?", (template_id,)
    ) as cur:
        row = await cur.fetchone()
    return dict(row) if row else None


async def insert_template(conn, name: str, description: str, type_: str, schema_json: str) -> int:
    cur = await conn.execute(
        "INSERT INTO interview_templates (name, description, type, schema_json) VALUES (?,?,?,?)",
        (name, description, type_, schema_json),
    )
    await conn.commit()
    return cur.lastrowid


async def update_template(conn, template_id: int, name: str, description: str, schema_json: str) -> None:
    await conn.execute(
        """UPDATE interview_templates
           SET name=?, description=?, schema_json=?, updated_at=datetime('now')
           WHERE id=?""",
        (name, description, schema_json, template_id),
    )
    await conn.commit()


async def delete_template(conn, template_id: int) -> bool:
    cur = await conn.execute(
        "DELETE FROM interview_templates WHERE id=?", (template_id,)
    )
    await conn.commit()
    return cur.rowcount > 0


# ── Node Template Assignments ─────────────────────────────────────────────────

async def fetch_node_template_assignments(conn, project_id: int) -> list:
    async with conn.execute(
        "SELECT node_label, interview_template_id, questionnaire_template_id "
        "FROM node_template_assignments WHERE project_id=? ORDER BY node_label",
        (project_id,),
    ) as cur:
        return [dict(r) async for r in cur]


async def upsert_node_template_assignment(
    conn, project_id: int, node_label: str,
    interview_template_id, questionnaire_template_id,
) -> None:
    await conn.execute("""
        INSERT INTO node_template_assignments
            (project_id, node_label, interview_template_id, questionnaire_template_id)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(project_id, node_label) DO UPDATE SET
            interview_template_id=excluded.interview_template_id,
            questionnaire_template_id=excluded.questionnaire_template_id,
            updated_at=datetime('now')
    """, (project_id, node_label, interview_template_id, questionnaire_template_id))
    await conn.commit()


async def fetch_interview_sessions_for_run(
    conn: aiosqlite.Connection, orchestration_run_id: int
) -> list[aiosqlite.Row]:
    """Return all interview_sessions rows for an orchestration run, joined with stakeholder name."""
    cur = await conn.execute(
        """
        SELECT
            is_.id,
            is_.stakeholder_id,
            s.name,
            is_.node_label,
            is_.session_token,
            is_.status,
            is_.started_at,
            is_.completed_at,
            is_.created_at
        FROM interview_sessions is_
        LEFT JOIN stakeholders s ON s.id = is_.stakeholder_id
        WHERE is_.orchestration_run_id = ?
        ORDER BY is_.created_at ASC
        """,
        (orchestration_run_id,),
    )
    return await cur.fetchall()
