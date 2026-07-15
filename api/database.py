# api/database.py
import aiosqlite
import json as _json
from contextlib import asynccontextmanager
from pathlib import Path
from api.config import get_settings

# Maps snake_case agent_name → crew_name so revert can clear pending HITL reviews
_AGENT_TO_CREW: dict[str, str] = {
    "value_chain_mapper":          "discovery_mapping",
    "interaction_designer":        "assessment_design",
    "requirements_capture":        "discovery",
    "requirements_analyst":        "discovery",
    "value_lever_analyst":         "discovery",
    "stakeholder_manager":         "stakeholder_management",
    "interview_coordinator":       "discovery_interviews",
    "stakeholder_interviewer":     "discovery_interviews",
    "synthesis_analyst":           "discovery_interviews",
    "value_proposition_generator": "value_design",
    "portfolio_manager":           "value_design",
    "enterprise_architect":        "architecture",
    "initiative_identifier":       "architecture",
    "roadmap_generator":           "delivery",
    "business_plan_generator":     "business_plan",
}


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
            id             INTEGER PRIMARY KEY AUTOINCREMENT,
            project_id     INTEGER NOT NULL REFERENCES projects(id),
            agent_name     TEXT NOT NULL,
            output_type    TEXT NOT NULL,
            file_path      TEXT NOT NULL,
            version        INTEGER NOT NULL DEFAULT 1,
            review_status  TEXT NOT NULL DEFAULT 'pending',
            revision_notes TEXT,
            created_at     DATETIME DEFAULT CURRENT_TIMESTAMP
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
            completed_at DATETIME,
            error_detail TEXT
        );

        CREATE TABLE IF NOT EXISTS project_milestones (
            id             INTEGER PRIMARY KEY AUTOINCREMENT,
            slug           TEXT NOT NULL,
            milestone_key  TEXT NOT NULL,
            title          TEXT NOT NULL,
            description    TEXT NOT NULL DEFAULT '',
            due_date       TEXT,
            status         TEXT NOT NULL DEFAULT 'pending',
            notes          TEXT NOT NULL DEFAULT '',
            sort_order     INTEGER NOT NULL DEFAULT 0,
            created_at     TEXT NOT NULL DEFAULT (datetime('now'))
        );
    """)
    # executescript issues an implicit COMMIT before running; the call below
    # is a safety flush but the schema is already committed.
    await conn.commit()


async def _migrate_orchestration_runs_error(conn: aiosqlite.Connection) -> None:
    """Add error_detail column to orchestration_runs if missing."""
    async with conn.execute("PRAGMA table_info(orchestration_runs)") as cur:
        cols = {row["name"] async for row in cur}
    if "error_detail" not in cols:
        await conn.execute("ALTER TABLE orchestration_runs ADD COLUMN error_detail TEXT")
        await conn.commit()


async def _migrate_agent_outputs_is_current(conn: aiosqlite.Connection) -> None:
    """Add is_current column to agent_outputs; back-fill so only the highest
    version per (project_id, agent_name, output_type) tuple is current."""
    async with conn.execute("PRAGMA table_info(agent_outputs)") as cur:
        cols = {row["name"] async for row in cur}
    if "is_current" in cols:
        return
    await conn.execute("ALTER TABLE agent_outputs ADD COLUMN is_current INTEGER NOT NULL DEFAULT 1")
    # Mark older versions as not current (keep only the max version per group)
    await conn.execute("""
        UPDATE agent_outputs SET is_current=0
        WHERE version < (
            SELECT MAX(ao2.version) FROM agent_outputs ao2
            WHERE ao2.project_id = agent_outputs.project_id
              AND ao2.agent_name = agent_outputs.agent_name
              AND ao2.output_type = agent_outputs.output_type
        )
    """)
    await conn.commit()


async def _migrate_agent_outputs_revision_notes(conn: aiosqlite.Connection) -> None:
    """Add revision_notes column to agent_outputs if missing."""
    async with conn.execute("PRAGMA table_info(agent_outputs)") as cur:
        cols = {row["name"] async for row in cur}
    if "revision_notes" not in cols:
        await conn.execute("ALTER TABLE agent_outputs ADD COLUMN revision_notes TEXT")
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
    """Create stakeholders table if it doesn't exist, and add new columns on existing DBs."""
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
            level               TEXT NOT NULL DEFAULT '',
            entity              TEXT NOT NULL DEFAULT '',
            mobile              TEXT NOT NULL DEFAULT '',
            comms_channel       TEXT NOT NULL DEFAULT 'email',
            is_participant      INTEGER NOT NULL DEFAULT 0,
            is_reviewer         INTEGER NOT NULL DEFAULT 0,
            is_approver         INTEGER NOT NULL DEFAULT 0,
            created_at          DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)
    await conn.commit()

    # Add new columns to existing DBs that were created before this migration
    async with conn.execute("PRAGMA table_info(stakeholders)") as cur:
        cols = {row["name"] async for row in cur}

    for col, defn in [
        ("level",          "TEXT NOT NULL DEFAULT ''"),
        ("entity",         "TEXT NOT NULL DEFAULT ''"),
        ("mobile",         "TEXT NOT NULL DEFAULT ''"),
        ("comms_channel",  "TEXT NOT NULL DEFAULT 'email'"),
        ("is_participant", "INTEGER NOT NULL DEFAULT 0"),
        ("is_reviewer",    "INTEGER NOT NULL DEFAULT 0"),
        ("is_approver",    "INTEGER NOT NULL DEFAULT 0"),
    ]:
        if col not in cols:
            await conn.execute(f"ALTER TABLE stakeholders ADD COLUMN {col} {defn}")

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
            voice_config          TEXT,
            transcript_json       TEXT,
            ratings_json          TEXT,
            checkpoint_json       TEXT,
            started_at            TEXT,
            completed_at          TEXT,
            created_at            DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)
    await conn.commit()


async def _migrate_interview_sessions_ratings(conn: aiosqlite.Connection) -> None:
    """Add ratings_json and voice_config columns to interview_sessions if missing."""
    async with conn.execute("PRAGMA table_info(interview_sessions)") as cur:
        cols = {row["name"] async for row in cur}
    if "ratings_json" not in cols:
        await conn.execute("ALTER TABLE interview_sessions ADD COLUMN ratings_json TEXT")
    if "voice_config" not in cols:
        await conn.execute("ALTER TABLE interview_sessions ADD COLUMN voice_config TEXT")
    await conn.commit()


async def _migrate_interview_sessions_checkpoint(conn: aiosqlite.Connection) -> None:
    """Add checkpoint_json column to interview_sessions if missing."""
    async with conn.execute("PRAGMA table_info(interview_sessions)") as cur:
        cols = {row["name"] async for row in cur}
    if "checkpoint_json" not in cols:
        await conn.execute("ALTER TABLE interview_sessions ADD COLUMN checkpoint_json TEXT")
    await conn.commit()


async def _migrate_node_template_assignments(conn: aiosqlite.Connection) -> None:
    """Create node_template_assignments table if it doesn't exist."""
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS node_template_assignments (
            id                        INTEGER PRIMARY KEY AUTOINCREMENT,
            project_id                INTEGER NOT NULL REFERENCES projects(id),
            node_label                TEXT    NOT NULL,
            activity_id               TEXT,
            level                     TEXT    DEFAULT 'L2',
            interview_template_id     INTEGER,
            questionnaire_template_id INTEGER,
            created_at                TEXT NOT NULL DEFAULT (datetime('now')),
            updated_at                TEXT NOT NULL DEFAULT (datetime('now')),
            UNIQUE(project_id, node_label)
        )
    """)
    async with conn.execute("PRAGMA table_info(node_template_assignments)") as cur:
        cols = {row["name"] async for row in cur}
    if "activity_id" not in cols:
        await conn.execute("ALTER TABLE node_template_assignments ADD COLUMN activity_id TEXT")
    if "level" not in cols:
        await conn.execute("ALTER TABLE node_template_assignments ADD COLUMN level TEXT DEFAULT 'L2'")
    await conn.commit()


async def _migrate_project_milestones(conn: aiosqlite.Connection) -> None:
    """Create project_milestones table if missing (handles existing DBs pre-schema update)."""
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS project_milestones (
            id             INTEGER PRIMARY KEY AUTOINCREMENT,
            slug           TEXT NOT NULL,
            milestone_key  TEXT NOT NULL,
            title          TEXT NOT NULL,
            description    TEXT NOT NULL DEFAULT '',
            due_date       TEXT,
            status         TEXT NOT NULL DEFAULT 'pending',
            notes          TEXT NOT NULL DEFAULT '',
            sort_order     INTEGER NOT NULL DEFAULT 0,
            created_at     TEXT NOT NULL DEFAULT (datetime('now'))
        )
    """)
    await conn.commit()


async def _migrate_nonworking_ranges(conn: aiosqlite.Connection) -> None:
    """Create nonworking_ranges table for custom non-working date ranges."""
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS nonworking_ranges (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            slug        TEXT NOT NULL,
            label       TEXT NOT NULL,
            start_date  TEXT NOT NULL,
            end_date    TEXT NOT NULL,
            created_at  TEXT NOT NULL DEFAULT (datetime('now'))
        )
    """)
    await conn.commit()


async def _migrate_stakeholder_node_assignments(conn: aiosqlite.Connection) -> None:
    """Create stakeholder_node_assignments table if it doesn't exist.

    Each row maps a stakeholder to a value chain node for a project.
    node_key is a string such as 'L0:Governance' or 'L2:Strategic Planning'.
    """
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS stakeholder_node_assignments (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            project_id      INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
            stakeholder_id  INTEGER NOT NULL REFERENCES stakeholders(id) ON DELETE CASCADE,
            node_key        TEXT NOT NULL,
            UNIQUE(project_id, stakeholder_id, node_key)
        )
    """)
    await conn.commit()


async def get_stakeholder_node_assignments(
    conn: aiosqlite.Connection, project_id: int
) -> list[dict]:
    """Return all stakeholder-node assignments for a project."""
    async with conn.execute(
        "SELECT id, stakeholder_id, node_key FROM stakeholder_node_assignments WHERE project_id=? ORDER BY id ASC",
        (project_id,),
    ) as cur:
        return [dict(r) async for r in cur]


async def upsert_stakeholder_node_assignments(
    conn: aiosqlite.Connection, project_id: int, assignments: list[dict]
) -> None:
    """Replace all stakeholder-node assignments for a project with the given list.

    Each dict must contain: stakeholder_id (int), node_key (str).
    Deletes all existing assignments for the project, then inserts the new ones.
    """
    await conn.execute(
        "DELETE FROM stakeholder_node_assignments WHERE project_id=?", (project_id,)
    )
    for a in assignments:
        await conn.execute(
            "INSERT INTO stakeholder_node_assignments (project_id, stakeholder_id, node_key) VALUES (?,?,?)",
            (project_id, a["stakeholder_id"], a["node_key"]),
        )
    await conn.commit()


async def list_nonworking_ranges(conn: aiosqlite.Connection, slug: str) -> list[dict]:
    async with conn.execute(
        "SELECT * FROM nonworking_ranges WHERE slug=? ORDER BY start_date", (slug,)
    ) as cur:
        return [dict(r) async for r in cur]


async def insert_nonworking_range(
    conn: aiosqlite.Connection, *, slug: str, label: str, start_date: str, end_date: str,
) -> int:
    cur = await conn.execute(
        "INSERT INTO nonworking_ranges (slug, label, start_date, end_date) VALUES (?,?,?,?)",
        (slug, label, start_date, end_date),
    )
    await conn.commit()
    return cur.lastrowid  # type: ignore[return-value]


async def update_nonworking_range(
    conn: aiosqlite.Connection, *, slug: str, range_id: int,
    label: str, start_date: str, end_date: str,
) -> bool:
    cur = await conn.execute(
        "UPDATE nonworking_ranges SET label=?, start_date=?, end_date=? WHERE id=? AND slug=?",
        (label, start_date, end_date, range_id, slug),
    )
    await conn.commit()
    return cur.rowcount > 0


async def delete_nonworking_range(
    conn: aiosqlite.Connection, *, slug: str, range_id: int,
) -> bool:
    cur = await conn.execute(
        "DELETE FROM nonworking_ranges WHERE id=? AND slug=?", (range_id, slug)
    )
    await conn.commit()
    return cur.rowcount > 0


_DEFAULT_MILESTONES = [
    ("project_initiation",      "Project initiation",                           "Engagement formally kicked off. Project charter signed, team onboarding complete, and tooling access confirmed.",                                       0),
    ("discovery_docs",          "Discovery documents uploaded",                 "Source documents, strategy papers, and reference materials uploaded and indexed for the Value Chain Mapper (Alex Chen).",                              1),
    ("value_chain_approved",    "Value chain mapping approved",                 "L1, L2, and L3 value chain structure reviewed and signed off by the project team before assessment instrument design begins.",                         2),
    ("stakeholders_assigned",   "Stakeholders configured and assigned",         "All stakeholder contacts entered and assigned to value chain nodes. Coverage reviewed across L1 and L2 before interview scheduling.",                  3),
    ("scripts_approved",        "Interview scripts and questionnaires approved","Assessment instruments designed by Maya Patel, reviewed, and signed off by the project team before deployment to stakeholders.",                        4),
    ("interviews_launched",     "Interview campaign launched",                  "Interview links generated and sent to all assigned stakeholders. Sessions are active and accessible.",                                                  5),
    ("interviews_complete",     "Interview responses complete",                 "All assigned stakeholders have completed their interview session. Track daily until this milestone closes.",                                            6),
    ("propositions_approved",   "Value propositions approved",                  "Portfolio of value propositions reviewed, refined, and approved by the project team before architecture and delivery planning.",                        7),
    ("portfolio_approved",      "Portfolio scoring approved",                   "Initiative register scored and prioritised using the IIRC Six Capitals framework. Signed off before roadmap sequencing.",                              8),
    ("roadmap_approved",        "Delivery roadmap approved",                    "Phased delivery roadmap reviewed and confirmed by the project team before business case compilation.",                                                 9),
    ("business_case_draft",     "Draft business case prepared",                 "Draft business case, financial model, and executive slide deck prepared and shared with the project team for review. Allow at least one week before final delivery.", 10),
    ("business_plan_delivered", "Business case delivered",                      "Final business case, financial model, and executive slide deck approved and delivered to the client.",                                                 11),
    ("project_closeout",        "Project closeout",                             "Engagement formally closed. Final deliverables accepted, lessons learnt captured, and project archived.",                                              12),
]


async def seed_default_milestones(conn: aiosqlite.Connection, slug: str) -> int:
    """Insert default milestones for a project. Skips keys that already exist. Returns count inserted."""
    async with conn.execute(
        "SELECT milestone_key FROM project_milestones WHERE slug=?", (slug,)
    ) as cur:
        existing = {row["milestone_key"] async for row in cur}
    inserted = 0
    for key, title, description, order in _DEFAULT_MILESTONES:
        if key not in existing:
            await conn.execute(
                "INSERT INTO project_milestones (slug, milestone_key, title, description, sort_order) VALUES (?,?,?,?,?)",
                (slug, key, title, description, order),
            )
            inserted += 1
    # Rename milestones whose terminology has been updated
    await conn.execute(
        "UPDATE project_milestones SET title='Business case delivered', "
        "description='Final business case, financial model, and executive slide deck approved and delivered to the client.' "
        "WHERE slug=? AND milestone_key='business_plan_delivered' AND title='Business plan delivered'",
        (slug,),
    )
    await conn.execute(
        "UPDATE project_milestones SET description='Phased delivery roadmap reviewed and confirmed by the project team before business case compilation.' "
        "WHERE slug=? AND milestone_key='roadmap_approved' AND description LIKE '%business plan compilation%'",
        (slug,),
    )
    await conn.commit()
    return inserted


async def list_milestones(conn: aiosqlite.Connection, slug: str) -> list[dict]:
    # Auto-migrate renamed milestone titles on every list call (no-op once done)
    await conn.execute(
        "UPDATE project_milestones SET title='Business case delivered' "
        "WHERE slug=? AND milestone_key='business_plan_delivered' AND title='Business plan delivered'",
        (slug,),
    )
    # Fix sort_order for milestones whose position changed when new milestones were inserted
    await conn.execute(
        "UPDATE project_milestones SET sort_order=10 WHERE slug=? AND milestone_key='business_case_draft' AND sort_order!=10",
        (slug,),
    )
    await conn.execute(
        "UPDATE project_milestones SET sort_order=11 WHERE slug=? AND milestone_key='business_plan_delivered' AND sort_order<11",
        (slug,),
    )
    await conn.commit()
    async with conn.execute(
        "SELECT * FROM project_milestones WHERE slug=? ORDER BY sort_order, id", (slug,)
    ) as cur:
        return [dict(r) async for r in cur]


async def insert_milestone(
    conn: aiosqlite.Connection, *, slug: str, milestone_key: str, title: str,
    description: str, due_date: str | None, notes: str, sort_order: int,
) -> int:
    cur = await conn.execute(
        "INSERT INTO project_milestones (slug, milestone_key, title, description, due_date, notes, sort_order) VALUES (?,?,?,?,?,?,?)",
        (slug, milestone_key, title, description, due_date, notes, sort_order),
    )
    await conn.commit()
    return cur.lastrowid


async def update_milestone(
    conn: aiosqlite.Connection, *, milestone_id: int, slug: str,
    title: str | None, description: str | None, due_date: str | None,
    status: str | None, notes: str | None, sort_order: int | None,
) -> bool:
    fields, vals = [], []
    if title       is not None: fields.append("title=?");       vals.append(title)
    if description is not None: fields.append("description=?"); vals.append(description)
    if due_date    is not None: fields.append("due_date=?");    vals.append(due_date if due_date != "" else None)
    if status      is not None: fields.append("status=?");      vals.append(status)
    if notes       is not None: fields.append("notes=?");       vals.append(notes)
    if sort_order  is not None: fields.append("sort_order=?");  vals.append(sort_order)
    if not fields:
        return False
    vals.extend([milestone_id, slug])
    await conn.execute(
        f"UPDATE project_milestones SET {', '.join(fields)} WHERE id=? AND slug=?", vals
    )
    await conn.commit()
    return True


async def delete_milestone(conn: aiosqlite.Connection, *, milestone_id: int, slug: str) -> bool:
    cur = await conn.execute(
        "DELETE FROM project_milestones WHERE id=? AND slug=?", (milestone_id, slug)
    )
    await conn.commit()
    return cur.rowcount > 0


@asynccontextmanager
async def get_connection(slug: str):
    path = get_db_path(slug)
    path.parent.mkdir(parents=True, exist_ok=True)
    async with aiosqlite.connect(path) as conn:
        conn.row_factory = aiosqlite.Row
        await conn.execute("PRAGMA foreign_keys = ON")
        await init_db(conn)
        await _migrate_orchestration_runs_error(conn)
        await _migrate_agent_outputs_is_current(conn)
        await _migrate_agent_outputs_revision_notes(conn)
        await _migrate_human_reviews(conn)
        await _migrate_crew_runs(conn)
        await _migrate_stakeholders(conn)
        await _migrate_campaigns(conn)
        await _migrate_stakeholder_assignments(conn)
        await _migrate_interview_sessions(conn)
        await _migrate_node_template_assignments(conn)
        await _migrate_interview_sessions_ratings(conn)
        await _migrate_interview_sessions_checkpoint(conn)
        await _migrate_project_milestones(conn)
        await _migrate_nonworking_ranges(conn)
        await _migrate_stakeholder_node_assignments(conn)
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
        """
        SELECT ao.*,
               -- Latest reviewer notes on THIS version (for revision dialog pre-population)
               (SELECT hr.notes FROM human_reviews hr
                WHERE hr.output_id = ao.id
                ORDER BY hr.reviewed_at DESC LIMIT 1) AS reviewer_notes
        FROM agent_outputs ao
        WHERE ao.project_id=?
        ORDER BY ao.created_at DESC
        """,
        (project_id,),
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


async def fetch_document(conn: aiosqlite.Connection, *, doc_id: int) -> dict | None:
    async with conn.execute(
        "SELECT * FROM client_documents WHERE id=?", (doc_id,)
    ) as cur:
        row = await cur.fetchone()
    return dict(row) if row else None


async def delete_document(conn: aiosqlite.Connection, *, doc_id: int) -> bool:
    cur = await conn.execute("DELETE FROM client_documents WHERE id=?", (doc_id,))
    await conn.commit()
    return cur.rowcount > 0


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
    await conn.execute(
        "UPDATE agent_outputs SET review_status=? WHERE id=?",
        (decision, output_id),
    )
    await conn.commit()
    return cur.lastrowid


async def revert_to_version(
    conn: aiosqlite.Connection, *, project_id: int, output_id: int
) -> tuple[dict | None, list[str]]:
    """Hard-delete all versions newer than output_id for the same (agent_name, output_type).
    Sets the target version as is_current=1.
    Returns (target_row, list_of_file_paths_that_were_deleted).
    The caller is responsible for deleting the returned files from disk."""
    async with conn.execute(
        "SELECT agent_name, output_type, version FROM agent_outputs WHERE id=? AND project_id=?",
        (output_id, project_id),
    ) as cur:
        row = await cur.fetchone()
    if not row:
        return None, []
    agent_name = row["agent_name"]
    output_type = row["output_type"]
    target_version = row["version"]
    # Collect file paths of newer versions so the caller can delete them from disk
    async with conn.execute(
        """SELECT file_path FROM agent_outputs
           WHERE project_id=? AND agent_name=? AND output_type=? AND version > ?""",
        (project_id, agent_name, output_type, target_version),
    ) as cur:
        deleted_paths = [r["file_path"] for r in await cur.fetchall()]
    # Delete human_reviews referencing the newer outputs first to satisfy the FK constraint,
    # then hard-delete the agent_outputs rows themselves.
    await conn.execute(
        """DELETE FROM human_reviews WHERE output_id IN (
               SELECT id FROM agent_outputs
               WHERE project_id=? AND agent_name=? AND output_type=? AND version > ?
           )""",
        (project_id, agent_name, output_type, target_version),
    )
    await conn.execute(
        """DELETE FROM agent_outputs
           WHERE project_id=? AND agent_name=? AND output_type=? AND version > ?""",
        (project_id, agent_name, output_type, target_version),
    )
    # Set the target as the sole current version
    await conn.execute(
        """UPDATE agent_outputs SET is_current=0
           WHERE project_id=? AND agent_name=? AND output_type=?""",
        (project_id, agent_name, output_type),
    )
    await conn.execute(
        "UPDATE agent_outputs SET is_current=1 WHERE id=?",
        (output_id,),
    )
    # Auto-dismiss any pending HITL reviews for this crew so the waiting state clears.
    # HITL reviews link via crew_run_id (not output_id), so they survive output deletion
    # unless explicitly cleared here.
    crew_name = _AGENT_TO_CREW.get(agent_name)
    if crew_name:
        await conn.execute(
            """UPDATE human_reviews
               SET decision='dismissed', reviewed_at=CURRENT_TIMESTAMP
               WHERE decision='pending' AND crew_run_id IN (
                   SELECT id FROM crew_runs WHERE project_id=? AND crew_name=?
               )""",
            (project_id, crew_name),
        )
    await conn.commit()
    async with conn.execute("SELECT * FROM agent_outputs WHERE id=?", (output_id,)) as cur:
        r = await cur.fetchone()
    return (dict(r) if r else None), deleted_paths


async def update_review(
    conn: aiosqlite.Connection, *, review_id: int, decision: str, notes: str
) -> bool:
    """Update an existing review record. Returns True if the record was found."""
    cur = await conn.execute(
        "UPDATE human_reviews SET decision=?, notes=?, reviewed_at=CURRENT_TIMESTAMP WHERE id=?",
        (decision, notes, review_id),
    )
    await conn.execute(
        "UPDATE agent_outputs SET review_status=? WHERE id=(SELECT output_id FROM human_reviews WHERE id=?)",
        (decision, review_id),
    )
    await conn.commit()
    return cur.rowcount > 0


async def delete_hitl_review(
    conn: aiosqlite.Connection, *, review_id: int
) -> bool:
    """Hard-delete a human_review row. Returns True if the record existed."""
    await conn.execute(
        "UPDATE agent_outputs SET review_status='pending' WHERE id=(SELECT output_id FROM human_reviews WHERE id=?)",
        (review_id,),
    )
    cur = await conn.execute("DELETE FROM human_reviews WHERE id=?", (review_id,))
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
        SELECT hr.id, hr.prompt, hr.crew_run_id, hr.decision, hr.reviewed_at, cr.crew_name
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
    conn: aiosqlite.Connection, *, run_id: int, status: str, error_detail: str | None = None
) -> None:
    if status in ("completed", "failed"):
        await conn.execute(
            "UPDATE orchestration_runs SET status=?, completed_at=CURRENT_TIMESTAMP, error_detail=? WHERE id=?",
            (status, error_detail, run_id),
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
    level: str = '',
    entity: str = '',
    mobile: str = '',
    comms_channel: str = 'email',
    is_participant: bool = False,
    is_reviewer: bool = False,
    is_approver: bool = False,
) -> int:
    """Insert a stakeholder row. Returns new id."""
    cur = await conn.execute(
        """INSERT INTO stakeholders
           (project_id, name, job_title, organisation, email, slack_handle,
            stakeholder_groups, project_role, value_streams, value_chain_stage,
            activity, disposition, location, country_code, timezone,
            preferred_language, currency,
            level, entity, mobile, comms_channel,
            is_participant, is_reviewer, is_approver)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            project_id, name, job_title, organisation, email, slack_handle,
            _json.dumps(stakeholder_groups or []),
            project_role,
            _json.dumps(value_streams or []),
            value_chain_stage, activity, disposition,
            location, country_code, timezone, preferred_language, currency,
            level, entity, mobile, comms_channel,
            int(is_participant), int(is_reviewer), int(is_approver),
        ),
    )
    await conn.commit()
    return cur.lastrowid


def _deserialize_stakeholder(row: dict) -> dict:
    """Convert JSON text columns to Python types and cast integer booleans."""
    row["stakeholder_groups"] = _json.loads(row.get("stakeholder_groups") or "[]")
    row["value_streams"] = _json.loads(row.get("value_streams") or "[]")
    row["is_participant"] = bool(row.get("is_participant", 0))
    row["is_reviewer"] = bool(row.get("is_reviewer", 0))
    row["is_approver"] = bool(row.get("is_approver", 0))
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
    "level", "entity", "mobile", "comms_channel",
    "is_participant", "is_reviewer", "is_approver",
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
    for key in ("is_participant", "is_reviewer", "is_approver"):
        if key in fields:
            fields[key] = int(bool(fields[key]))

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


async def fetch_approved_reminder_emails(
    conn: aiosqlite.Connection, *, project_id: int
) -> list[dict]:
    """Return all approved (ready-to-send) reminder emails with stakeholder email address."""
    async with conn.execute(
        """SELECT re.*, s.email AS stakeholder_email, s.name AS stakeholder_name
           FROM reminder_emails re
           JOIN stakeholders s ON s.id = re.stakeholder_id
           WHERE re.project_id = ? AND re.status = 'approved'
           ORDER BY re.created_at""",
        (project_id,),
    ) as cur:
        return [dict(r) async for r in cur]


async def mark_reminder_email_sent(
    conn: aiosqlite.Connection, *, email_id: int, status: str
) -> None:
    """Set status to 'sent' or 'failed' — no project_id check needed (internal)."""
    await conn.execute(
        "UPDATE reminder_emails SET status=? WHERE id=?", (status, email_id)
    )
    await conn.commit()


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
            email       TEXT NOT NULL DEFAULT '',
            role        TEXT NOT NULL DEFAULT 'sysadmin',
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

        CREATE TABLE IF NOT EXISTS organisations (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            slug       TEXT    UNIQUE NOT NULL,
            name       TEXT    NOT NULL,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS org_memberships (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            org_id     INTEGER NOT NULL REFERENCES organisations(id) ON DELETE CASCADE,
            role       TEXT    NOT NULL CHECK(role IN ('org_admin', 'member')),
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(user_id, org_id)
        );

        CREATE TABLE IF NOT EXISTS project_registry (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            slug         TEXT    UNIQUE NOT NULL,
            org_id       INTEGER NOT NULL REFERENCES organisations(id) ON DELETE CASCADE,
            display_name TEXT    NOT NULL DEFAULT '',
            created_at   DATETIME DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS project_memberships (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id      INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            project_slug TEXT    NOT NULL,
            created_at   DATETIME DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(user_id, project_slug)
        );

        CREATE TABLE IF NOT EXISTS agent_skill_notes (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            agent_name TEXT NOT NULL,
            note       TEXT NOT NULL,
            raw_input  TEXT,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        );
    """)
    await conn.commit()

    # Idempotent migrations on existing DBs
    async with conn.execute("PRAGMA table_info(users)") as cur:
        user_cols = {row["name"] async for row in cur}
    if "email" not in user_cols:
        await conn.execute("ALTER TABLE users ADD COLUMN email TEXT NOT NULL DEFAULT ''")
    # Migrate legacy 'consultant' role to 'sysadmin'
    await conn.execute("UPDATE users SET role='sysadmin' WHERE role='consultant'")
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


async def insert_skill_note(conn: aiosqlite.Connection, *, agent_name: str, note: str, raw_input: str) -> int:
    cur = await conn.execute(
        "INSERT INTO agent_skill_notes (agent_name, note, raw_input) VALUES (?,?,?)",
        (agent_name, note, raw_input),
    )
    await conn.commit()
    return cur.lastrowid


async def fetch_skill_notes(conn: aiosqlite.Connection, *, agent_name: str | None = None) -> list[dict]:
    if agent_name:
        async with conn.execute(
            "SELECT * FROM agent_skill_notes WHERE agent_name=? ORDER BY created_at DESC",
            (agent_name,),
        ) as cur:
            return [dict(r) async for r in cur]
    async with conn.execute(
        "SELECT * FROM agent_skill_notes ORDER BY agent_name, created_at DESC"
    ) as cur:
        return [dict(r) async for r in cur]


async def fetch_user(conn: aiosqlite.Connection, *, username: str) -> dict | None:
    async with conn.execute("SELECT * FROM users WHERE username=?", (username,)) as cur:
        row = await cur.fetchone()
        return dict(row) if row else None


async def insert_user(
    conn: aiosqlite.Connection,
    *,
    username: str,
    email: str = "",
    role: str,
    hashed_pw: str,
    project_slug: str | None = None,
) -> bool:
    """Returns True if inserted, False if username already exists."""
    try:
        await conn.execute(
            "INSERT INTO users (username, email, role, hashed_pw, project_slug) VALUES (?,?,?,?,?)",
            (username, email, role, hashed_pw, project_slug),
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
    voice_config: str | None = None,
) -> int:
    cur = await conn.execute(
        "INSERT INTO interview_sessions "
        "(project_id, orchestration_run_id, stakeholder_id, node_label, session_token, voice_config) "
        "VALUES (?,?,?,?,?,?)",
        (project_id, orchestration_run_id, stakeholder_id, node_label, session_token, voice_config),
    )
    await conn.commit()
    return cur.lastrowid


async def fetch_session_token_for_stakeholder(
    conn: aiosqlite.Connection, stakeholder_id: int
) -> str | None:
    """Return the most recent active/pending session token for a stakeholder, or None."""
    async with conn.execute(
        "SELECT session_token FROM interview_sessions "
        "WHERE stakeholder_id=? AND status != 'abandoned' "
        "ORDER BY id DESC LIMIT 1",
        (stakeholder_id,),
    ) as cur:
        row = await cur.fetchone()
    return row["session_token"] if row else None


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
    if status == "active":
        await conn.execute(
            "UPDATE interview_sessions SET status=?, started_at=datetime('now') WHERE session_token=?",
            (status, session_token),
        )
    else:
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


async def save_interview_checkpoint(
    conn: aiosqlite.Connection, session_token: str, checkpoint: dict | None
) -> None:
    """Persist a mid-session checkpoint. Pass None to clear (e.g. on completion)."""
    import json
    value = json.dumps(checkpoint) if checkpoint is not None else None
    await conn.execute(
        "UPDATE interview_sessions SET checkpoint_json=? WHERE session_token=?",
        (value, session_token),
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
        "SELECT node_label, activity_id, level, interview_template_id, questionnaire_template_id "
        "FROM node_template_assignments WHERE project_id=? ORDER BY node_label",
        (project_id,),
    ) as cur:
        return [dict(r) async for r in cur]


async def upsert_node_template_assignment(
    conn, project_id: int, node_label: str,
    interview_template_id, questionnaire_template_id,
    activity_id: str | None = None,
    level: str | None = None,
) -> None:
    await conn.execute("""
        INSERT INTO node_template_assignments
            (project_id, node_label, activity_id, level, interview_template_id, questionnaire_template_id)
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(project_id, node_label) DO UPDATE SET
            activity_id=COALESCE(excluded.activity_id, activity_id),
            level=COALESCE(excluded.level, level),
            interview_template_id=excluded.interview_template_id,
            questionnaire_template_id=excluded.questionnaire_template_id,
            updated_at=datetime('now')
    """, (project_id, node_label, activity_id, level or "L2", interview_template_id, questionnaire_template_id))
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


# ── Organisation helpers ──────────────────────────────────────────────────────

async def insert_organisation(conn: aiosqlite.Connection, *, slug: str, name: str) -> int:
    cur = await conn.execute(
        "INSERT INTO organisations (slug, name) VALUES (?,?)", (slug, name)
    )
    await conn.commit()
    return cur.lastrowid


async def fetch_all_organisations(conn: aiosqlite.Connection) -> list[dict]:
    async with conn.execute("SELECT * FROM organisations ORDER BY name") as cur:
        return [dict(r) async for r in cur]


async def fetch_organisation(conn: aiosqlite.Connection, *, org_id: int) -> dict | None:
    async with conn.execute("SELECT * FROM organisations WHERE id=?", (org_id,)) as cur:
        row = await cur.fetchone()
        return dict(row) if row else None


async def update_organisation(conn: aiosqlite.Connection, *, org_id: int, name: str) -> None:
    await conn.execute("UPDATE organisations SET name=? WHERE id=?", (name, org_id))
    await conn.commit()


async def delete_organisation(conn: aiosqlite.Connection, *, org_id: int) -> None:
    await conn.execute("DELETE FROM organisations WHERE id=?", (org_id,))
    await conn.commit()


# ── Org membership helpers ────────────────────────────────────────────────────

async def insert_org_membership(
    conn: aiosqlite.Connection, *, user_id: int, org_id: int, role: str
) -> bool:
    try:
        await conn.execute(
            "INSERT INTO org_memberships (user_id, org_id, role) VALUES (?,?,?)",
            (user_id, org_id, role),
        )
        await conn.commit()
        return True
    except aiosqlite.IntegrityError:
        return False


async def fetch_org_members(conn: aiosqlite.Connection, *, org_id: int) -> list[dict]:
    async with conn.execute(
        """SELECT u.id, u.username, u.email, u.role AS user_role, om.role, u.created_at
           FROM org_memberships om
           JOIN users u ON u.id = om.user_id
           WHERE om.org_id=? ORDER BY u.username""",
        (org_id,),
    ) as cur:
        return [dict(r) async for r in cur]


async def update_org_membership_role(
    conn: aiosqlite.Connection, *, user_id: int, org_id: int, role: str
) -> None:
    await conn.execute(
        "UPDATE org_memberships SET role=? WHERE user_id=? AND org_id=?",
        (role, user_id, org_id),
    )
    await conn.commit()


async def delete_org_membership(
    conn: aiosqlite.Connection, *, user_id: int, org_id: int
) -> None:
    await conn.execute(
        "DELETE FROM org_memberships WHERE user_id=? AND org_id=?", (user_id, org_id)
    )
    await conn.commit()


async def fetch_user_org(conn: aiosqlite.Connection, *, user_id: int) -> dict | None:
    """Return the first org_membership row for this user (users belong to one org)."""
    async with conn.execute(
        "SELECT * FROM org_memberships WHERE user_id=? LIMIT 1", (user_id,)
    ) as cur:
        row = await cur.fetchone()
        return dict(row) if row else None


# ── Project registry helpers ──────────────────────────────────────────────────

async def insert_project_registry(
    conn: aiosqlite.Connection, *, slug: str, org_id: int, display_name: str
) -> None:
    await conn.execute(
        "INSERT OR IGNORE INTO project_registry (slug, org_id, display_name) VALUES (?,?,?)",
        (slug, org_id, display_name),
    )
    await conn.commit()


async def fetch_project_registry(
    conn: aiosqlite.Connection, *, slug: str
) -> dict | None:
    async with conn.execute(
        "SELECT * FROM project_registry WHERE slug=?", (slug,)
    ) as cur:
        row = await cur.fetchone()
        return dict(row) if row else None


async def fetch_org_projects(conn: aiosqlite.Connection, *, org_id: int) -> list[dict]:
    async with conn.execute(
        "SELECT * FROM project_registry WHERE org_id=? ORDER BY display_name", (org_id,)
    ) as cur:
        return [dict(r) async for r in cur]


async def fetch_all_registry(conn: aiosqlite.Connection) -> list[dict]:
    async with conn.execute(
        "SELECT pr.*, o.name AS org_name FROM project_registry pr "
        "JOIN organisations o ON o.id = pr.org_id ORDER BY pr.slug"
    ) as cur:
        return [dict(r) async for r in cur]


async def delete_project_registry(conn: aiosqlite.Connection, *, slug: str) -> None:
    await conn.execute("DELETE FROM project_registry WHERE slug=?", (slug,))
    await conn.commit()


# ── Project membership helpers ────────────────────────────────────────────────

async def insert_project_membership(
    conn: aiosqlite.Connection, *, user_id: int, project_slug: str
) -> bool:
    try:
        await conn.execute(
            "INSERT INTO project_memberships (user_id, project_slug) VALUES (?,?)",
            (user_id, project_slug),
        )
        await conn.commit()
        return True
    except aiosqlite.IntegrityError:
        return False


async def delete_project_membership(
    conn: aiosqlite.Connection, *, user_id: int, project_slug: str
) -> None:
    await conn.execute(
        "DELETE FROM project_memberships WHERE user_id=? AND project_slug=?",
        (user_id, project_slug),
    )
    await conn.commit()


async def fetch_user_project_memberships(
    conn: aiosqlite.Connection, *, user_id: int
) -> list[dict]:
    async with conn.execute(
        "SELECT * FROM project_memberships WHERE user_id=? ORDER BY project_slug",
        (user_id,),
    ) as cur:
        return [dict(r) async for r in cur]


async def has_project_membership(
    conn: aiosqlite.Connection, *, user_id: int, project_slug: str
) -> bool:
    async with conn.execute(
        "SELECT 1 FROM project_memberships WHERE user_id=? AND project_slug=?",
        (user_id, project_slug),
    ) as cur:
        return await cur.fetchone() is not None


# ── Extended user helpers ─────────────────────────────────────────────────────

async def fetch_user_by_id(conn: aiosqlite.Connection, *, user_id: int) -> dict | None:
    async with conn.execute("SELECT * FROM users WHERE id=?", (user_id,)) as cur:
        row = await cur.fetchone()
        return dict(row) if row else None


async def fetch_all_users(conn: aiosqlite.Connection) -> list[dict]:
    async with conn.execute("SELECT * FROM users ORDER BY username") as cur:
        return [dict(r) async for r in cur]


async def fetch_users_by_org(conn: aiosqlite.Connection, *, org_id: int) -> list[dict]:
    async with conn.execute(
        """SELECT u.* FROM users u
           JOIN org_memberships om ON om.user_id = u.id
           WHERE om.org_id=? ORDER BY u.username""",
        (org_id,),
    ) as cur:
        return [dict(r) async for r in cur]


async def update_user(
    conn: aiosqlite.Connection,
    *,
    user_id: int,
    email: str,
    role: str,
    hashed_pw: str | None = None,
) -> None:
    if hashed_pw:
        await conn.execute(
            "UPDATE users SET email=?, role=?, hashed_pw=? WHERE id=?",
            (email, role, hashed_pw, user_id),
        )
    else:
        await conn.execute(
            "UPDATE users SET email=?, role=? WHERE id=?",
            (email, role, user_id),
        )
    await conn.commit()


async def delete_user(conn: aiosqlite.Connection, *, user_id: int) -> None:
    await conn.execute("DELETE FROM users WHERE id=?", (user_id,))
    await conn.commit()
