# api/database.py
from datetime import date
import aiosqlite
import json as _json
from contextlib import asynccontextmanager
from pathlib import Path
from api.config import get_settings


def _crew_of(agent_name: str) -> str | None:
    """The crew an agent runs in, or None if it runs in none.

    This inverts the graph rather than restating it. The map it replaces listed fifteen of
    the seventeen agents - `visual_illustrator` and `pam` were absent - and it had already
    been wrong once about Morgan, sending a revert of her output to clear reviews on a crew
    she had left. An agent missing from a hand-written inversion is silent in exactly the
    same way: the revert succeeds and the pending review it should have dismissed stays.

    Imported inside the function, and the reason is a real cycle rather than caution:
    `agents/graph.py` imports `api.services.run_service`, which imports this module, and
    `api.services.crew_graph` imports it too. A module-level import here fails at start-up
    in every import order - verified, not assumed.

    `None` is a legitimate answer, not a lookup failure. PAM is in no crew.
    """
    from agents.graph import GRAPH

    for crew in GRAPH.crews.values():
        if agent_name in crew.agent_ids:
            return crew.crew_id
    return None



def get_db_path(slug: str) -> Path:
    return Path(get_settings().database_dir) / f"{slug}.db"


def is_contained_slug(slug: str) -> bool:
    """Whether `get_db_path(slug)` names a file directly inside DATABASE_DIR.

    Every other route that resolves a project takes its slug from a **path** segment, where
    the router has already split on `/` and a traversal needs an encoding trick to survive.
    `GET /auth/users?project=` is the first to take one from a **query string**, where `/`
    and `..` arrive verbatim and nothing upstream objects - so `?project=../../x` builds a
    path outside DATABASE_DIR, and `check_project_access` returns early for a sysadmin
    without ever looking at the string.

    Containment rather than a character class, deliberately. Project creation never validated
    the slug's charset (`create_project` takes `req.client_slug` as given), so a format rule
    invented here could refuse a project that legitimately exists on a live deployment. What
    is actually required is that the path stay put, and that is what is asserted: the
    resolved parent must be DATABASE_DIR itself, which rejects a separator (`a/b` lands in a
    subdirectory), a traversal (`../x` lands above), and an absolute path (`Path.__truediv__`
    *replaces* the left side when the right is absolute, so `/etc/x` yields `/etc/x.db`).
    An empty slug yields a bare `.db` and is refused too.

    Not merged with `_SLUG_RE` in `api/routers/projects.py`, which looks like the same rule
    and is not: that one is a format check on files served out of PROJECTS_DIR, a different
    root with a different guarantee. Two rules that happen to reject some of the same strings
    are not one rule, and unifying them would tie a change in either to the other.
    """
    root = Path(get_settings().database_dir).resolve()
    try:
        candidate = get_db_path(slug).resolve()
    except (OSError, ValueError):  # NUL bytes, over-long names
        return False
    return candidate.parent == root and candidate.name != ".db"


async def init_db(conn: aiosqlite.Connection) -> None:
    await conn.execute("PRAGMA foreign_keys = ON")
    await conn.executescript("""
        CREATE TABLE IF NOT EXISTS projects (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            slug        TEXT UNIQUE NOT NULL,
            llm_mode    TEXT NOT NULL DEFAULT 'standard',
            -- Removes HOSTED_INFERENCE from whatever llm_mode grants; it can never add a
            -- capability. A column beside llm_mode rather than a config_json key, for the
            -- reason _refuse_platform_tier_setting_changes reads projects.llm_mode rather
            -- than its config_json copy: a fact that decides egress is not kept in a copy.
            force_local_inference INTEGER NOT NULL DEFAULT 0,
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

        -- One row per act of committing: what a governing role signed off, and when.
        CREATE TABLE IF NOT EXISTS approval_commits (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            crew_name     TEXT NOT NULL,
            committed_by  TEXT NOT NULL,
            committed_at  TEXT NOT NULL DEFAULT (datetime('now')),
            notes         TEXT NOT NULL DEFAULT ''
        );

        -- One row per act of submitting a crew's work for approval. Parallel to
        -- approval_commits: together they derive the crew's state.
        CREATE TABLE IF NOT EXISTS crew_submissions (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            crew_name     TEXT NOT NULL,
            submitted_by  TEXT NOT NULL,
            submitted_at  TEXT NOT NULL DEFAULT (datetime('now')),
            notes         TEXT NOT NULL DEFAULT ''
        );

        -- Exactly which output versions a commit froze. Later projects diff
        -- consecutive commits through this table.
        CREATE TABLE IF NOT EXISTS approval_commit_outputs (
            commit_id  INTEGER NOT NULL REFERENCES approval_commits(id),
            output_id  INTEGER NOT NULL REFERENCES agent_outputs(id),
            PRIMARY KEY (commit_id, output_id)
        );

        -- Every change asked of an output, however it was asked for.
        CREATE TABLE IF NOT EXISTS output_changes (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            output_id     INTEGER NOT NULL REFERENCES agent_outputs(id),
            requested_by  TEXT NOT NULL,
            source        TEXT NOT NULL,
            request       TEXT NOT NULL,
            summary       TEXT NOT NULL DEFAULT '',
            kind          TEXT NOT NULL DEFAULT 'unclassified',
            status        TEXT NOT NULL DEFAULT 'open',
            applied_run_id INTEGER,
            created_at    TEXT NOT NULL DEFAULT (datetime('now'))
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
            ingest_status TEXT NOT NULL DEFAULT 'pending',
            ingest_error TEXT,
            -- Which knowledge store this document's chunks were written into. Recorded rather
            -- than re-derived, because it is what the delete door has to address: a document
            -- uploaded at the organisation tier whose chunks are removed from `{slug}_docs`
            -- is a delete that removes nothing.
            knowledge_tier TEXT NOT NULL DEFAULT 'project',
            -- The Chroma collection the chunks actually landed in, recorded at the moment
            -- they did. The tier above is only one of three inputs to that name: the other
            -- two - the project's sector and the organisation its slug is registered to -
            -- both move through ordinary, correctly-gated doors, so a delete that re-derived
            -- the name could purge a store the write never used and destroy the only handle
            -- on the chunks it left behind. Empty for a row whose chunks were never written,
            -- and for a row that predates the column; the delete door falls back to
            -- re-deriving for those, which is the best that can be done for an address
            -- nothing recorded.
            knowledge_collection TEXT NOT NULL DEFAULT '',
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
            completed_at   TEXT,
            baseline_date  TEXT,
            created_at     TEXT NOT NULL DEFAULT (datetime('now'))
        );
    """)
    # executescript issues an implicit COMMIT before running; the call below
    # is a safety flush but the schema is already committed.
    await conn.commit()


async def _migrate_projects_force_local_inference(conn: aiosqlite.Connection) -> None:
    """Add the per-project override that forces local inference.

    Every existing project resolves exactly as it did before, because 0 is not a default
    standing in for "unknown": until this branch there was no way to ask for the override, so
    "nobody asked for it" is a statement of fact about every row that predates the column.

    The flag *removes* HOSTED_INFERENCE from what the project's mode grants and can never add
    a capability, so the safe direction and the truthful one are the same here - but they
    would not be for a reversed flag, which is why the design refused one.
    """
    async with conn.execute("PRAGMA table_info(projects)") as cur:
        cols = {row["name"] async for row in cur}
    if "force_local_inference" not in cols:
        await conn.execute(
            "ALTER TABLE projects ADD COLUMN force_local_inference INTEGER NOT NULL DEFAULT 0"
        )
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
            is_project_admin    INTEGER NOT NULL DEFAULT 0,
            is_governor         INTEGER NOT NULL DEFAULT 0,
            is_synthetic        INTEGER NOT NULL DEFAULT 0,
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
        ("is_participant",   "INTEGER NOT NULL DEFAULT 0"),
        ("is_reviewer",      "INTEGER NOT NULL DEFAULT 0"),
        ("is_approver",      "INTEGER NOT NULL DEFAULT 0"),
        ("is_project_admin", "INTEGER NOT NULL DEFAULT 0"),
        ("is_governor",      "INTEGER NOT NULL DEFAULT 0"),
        # Not a person, and never was: a row seeded by scripts/seed_synthetic_stakeholders.py
        # so an assignment surface and a coverage report can be exercised at real scale
        # before any real roster exists. It is a column rather than a naming convention
        # because the rows have to come out again cleanly, and the only removal predicate
        # worth having is one nobody can edit by accident.
        #
        # Deliberately absent from `insert_stakeholder`'s signature and from
        # `_STAKEHOLDER_UPDATABLE_FIELDS`: no API door can set it, and no API door can clear
        # it. A row created through the API is synthetic=0 by column default and stays that
        # way; a seeded row stays 1 however much of it a human edits afterwards. Only the
        # seeder writes it, and only the seeder's --remove reads it.
        ("is_synthetic",     "INTEGER NOT NULL DEFAULT 0"),
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
    """Create stakeholder_assignments table if it doesn't exist.

    An assignment is a fact about the project, not an event inside a run: it is made by
    hand before any orchestration has happened, and it survives every run afterwards.
    That is why the key is `project_id` and not `orchestration_run_id`.

    The node is cited by its value chain **id**, never by its label. Ids are a permanent
    contract (see CLAUDE.md); labels drift on every run Alex makes - one run produced 59
    label changes - so a label-keyed assignment silently detaches from its node.

    Several stakeholders on one activity is the normal case, not a duplicate, and one
    person legitimately speaks for several activities. The uniqueness constraint is
    therefore on the *pair* - the same person filed against the same node twice - and on
    nothing else.
    """
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS stakeholder_assignments (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            project_id      INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
            stakeholder_id  INTEGER NOT NULL REFERENCES stakeholders(id) ON DELETE CASCADE,
            node_id         TEXT NOT NULL,
            created_at      DATETIME DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(project_id, stakeholder_id, node_id)
        )
    """)
    await conn.commit()


async def _migrate_stakeholder_assignments_to_project(conn: aiosqlite.Connection) -> None:
    """Re-key an existing stakeholder_assignments table from a run to the project.

    The old shape was `(id, orchestration_run_id, stakeholder_id, level, node_label,
    created_at)`. Every project database held zero rows in it - the only writer was a
    router endpoint no UI ever called - so this is a free re-key with nothing to backfill
    and no compatibility shim.

    `level` is not carried over. It was the *node's* level, so it belongs to the node and
    is read back from the value chain registry alongside the label; storing a copy on the
    assignment is the same denormalisation as `node_label` and drifts the same way.

    Rows are never dropped on the floor. If a database somewhere does hold assignments,
    the old table is renamed aside rather than deleted - nothing reads the renamed table,
    so this is a safety net, not a shim.
    """
    async with conn.execute("PRAGMA table_info(stakeholder_assignments)") as cur:
        cols = {row[1] for row in await cur.fetchall()}
    if not cols or "project_id" in cols:
        return  # absent (the create above makes the new shape) or already re-keyed

    async with conn.execute("SELECT COUNT(*) FROM stakeholder_assignments") as cur:
        existing = (await cur.fetchone())[0]
    if existing:
        await conn.execute(
            "ALTER TABLE stakeholder_assignments "
            "RENAME TO stakeholder_assignments_pre_project_rekey"
        )
    else:
        await conn.execute("DROP TABLE stakeholder_assignments")
    await conn.commit()
    await _migrate_stakeholder_assignments(conn)


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
            script_id             TEXT,
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


async def _migrate_interview_sessions_script_id(conn: aiosqlite.Connection) -> None:
    """Give a session the id of the script it is for.

    The citation from a stored answer back to its instrument used to be re-derived by
    matching node_template_assignments on node_label. Label matching is what makes
    publish_node_template 404 against an artefact keyed by script_id, and a label is not
    unique - two scripts can normalise to the same one. A session is for exactly one
    script, so it carries it.
    """
    cur = await conn.execute("PRAGMA table_info(interview_sessions)")
    cols = {row[1] for row in await cur.fetchall()}
    if "script_id" not in cols:
        await conn.execute("ALTER TABLE interview_sessions ADD COLUMN script_id TEXT")
    await conn.commit()


async def _migrate_stakeholder_roles(conn: aiosqlite.Connection) -> None:
    """The two roles the stakeholder record was missing.

    is_participant, is_reviewer, and is_approver already lived here; project_admin and
    governor complete the set rather than starting a second one. Authority is then read
    from the row that holds the person's name and address, instead of being inferred by
    matching that address against a separate account.
    """
    cur = await conn.execute("PRAGMA table_info(stakeholders)")
    cols = {row[1] for row in await cur.fetchall()}
    for name in ("is_project_admin", "is_governor"):
        if name not in cols:
            await conn.execute(
                f"ALTER TABLE stakeholders ADD COLUMN {name} INTEGER NOT NULL DEFAULT 0")
    await conn.commit()


async def _migrate_output_changes_kind(conn: aiosqlite.Connection) -> None:
    """Record what kind of feedback a change is, and whether it has been acted upon.

    kind carries the reviewer's intent - a correction and a skill are captured here but
    reach the agent through RAG and the skill library respectively, so only a
    change_request is ever injected. status stops a request being replayed on every run
    thereafter.
    """
    async with conn.execute("PRAGMA table_info(output_changes)") as cur:
        cols = {row["name"] async for row in cur}
    if "kind" not in cols:
        await conn.execute(
            "ALTER TABLE output_changes ADD COLUMN kind TEXT NOT NULL DEFAULT 'unclassified'"
        )
    if "status" not in cols:
        await conn.execute(
            "ALTER TABLE output_changes ADD COLUMN status TEXT NOT NULL DEFAULT 'open'"
        )
    if "applied_run_id" not in cols:
        await conn.execute("ALTER TABLE output_changes ADD COLUMN applied_run_id INTEGER")
    await conn.commit()


async def _migrate_interview_answers(conn: aiosqlite.Connection) -> None:
    """One row per question per session - the system of record for interview evidence.

    Tags are denormalised deliberately. Casey groups by an exact value without a four-way
    join, and every tag is a fact fixed at the moment the answer was given: a later rename of
    a node must not retrospectively change what an interview was about.

    Rows are append-only, which is what makes `id` usable as a citation token.
    """
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS interview_answers (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id      INTEGER NOT NULL REFERENCES interview_sessions(id),
            stakeholder_id  INTEGER NOT NULL REFERENCES stakeholders(id),
            script_id       TEXT    NOT NULL,
            section_id      TEXT    NOT NULL,
            question_id     TEXT    NOT NULL,
            question_text   TEXT    NOT NULL,
            answer_text     TEXT    NOT NULL DEFAULT '',
            answered        INTEGER NOT NULL DEFAULT 1,
            follow_up       INTEGER NOT NULL DEFAULT 0,
            node_id         TEXT    NOT NULL,
            node_label      TEXT    NOT NULL DEFAULT '',
            chain           TEXT,
            level           TEXT    NOT NULL,
            relationship    TEXT    NOT NULL,
            party_id        TEXT,
            discipline      TEXT    NOT NULL,
            question_intent TEXT    NOT NULL,
            elicitation     TEXT    NOT NULL,
            rating          INTEGER,
            answered_at     DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)
    await conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_answers_session ON interview_answers(session_id)")
    await conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_answers_node ON interview_answers(node_id)")
    await conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_answers_discipline ON interview_answers(discipline)")

    # One row per question per session. Without this a retried PATCH /complete - two tabs,
    # a flaky connection - appends the whole answer set again, and Casey synthesises from a
    # corpus with silent duplicates.
    #
    # Duplicates are collapsed before the index is created, keeping the lowest id because
    # that is the original write and `id` is the citation token later rows point at.
    await conn.execute("""
        DELETE FROM interview_answers WHERE id NOT IN (
            SELECT MIN(id) FROM interview_answers GROUP BY session_id, question_id
        )
    """)
    await conn.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS idx_interview_answers_session_question
        ON interview_answers(session_id, question_id)
    """)
    await conn.commit()


_ANSWER_COLUMNS = (
    "session_id", "stakeholder_id", "script_id", "section_id", "question_id",
    "question_text", "answer_text", "answered", "follow_up", "node_id", "node_label",
    "chain", "level", "relationship", "party_id", "discipline", "question_intent",
    "elicitation", "rating",
)


async def insert_interview_answer(conn: aiosqlite.Connection, **fields) -> int:
    """One answer row, upserted on (session_id, question_id).

    A resubmission - two tabs, a retry, a flaky connection - updates the existing row rather
    than adding one, so the answer is replaced but its id, the citation token retrieved
    chunks carry, survives.

    Returns the id via `RETURNING`, not `cur.lastrowid`. `lastrowid` reflects the
    connection's last true INSERT and is left stale by the DO UPDATE branch of an upsert -
    on a connection that has inserted other rows since, a resubmission that hits DO UPDATE
    would otherwise report a different row's id as its own, and record_answers uses this
    return value to decide which rows to re-index, so a stale id would leave the revised
    answer un-indexed while Chroma keeps serving the old text under the real id.
    """
    columns = [c for c in _ANSWER_COLUMNS if c in fields]
    placeholders = ", ".join("?" for _ in columns)
    update_columns = [c for c in columns if c not in ("session_id", "question_id")]
    cur = await conn.execute(
        f"INSERT INTO interview_answers ({', '.join(columns)}) VALUES ({placeholders}) "
        f"ON CONFLICT(session_id, question_id) DO UPDATE SET "
        f"{', '.join(f'{c}=excluded.{c}' for c in update_columns)} "
        f"RETURNING id",
        tuple(fields[c] for c in columns),
    )
    row = await cur.fetchone()
    await conn.commit()
    return row[0]


async def fetch_interview_answers(
    conn: aiosqlite.Connection,
    session_id: int | None = None,
    node_id: str | None = None,
    discipline: str | None = None,
) -> list[dict]:
    """Answers matching whichever filters are given, oldest first."""
    clauses, params = [], []
    for column, value in (("session_id", session_id), ("node_id", node_id),
                          ("discipline", discipline)):
        if value is not None:
            clauses.append(f"{column} = ?")
            params.append(value)
    where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
    async with conn.execute(
        f"SELECT * FROM interview_answers{where} ORDER BY id", tuple(params)
    ) as cur:
        return [dict(row) async for row in cur]


async def fetch_interview_session_by_id(
    conn: aiosqlite.Connection, session_id: int
) -> dict | None:
    """One session by primary key.

    The existing lookups are all by session_token, which the answer service does not hold -
    it runs after completion, from the row's id.
    """
    async with conn.execute(
        "SELECT * FROM interview_sessions WHERE id = ?", (session_id,)
    ) as cur:
        row = await cur.fetchone()
    return dict(row) if row else None


async def _migrate_document_ingest_status(conn: aiosqlite.Connection) -> None:
    """Give existing documents a status derived from the flag they already carry.

    Defaulting every row to 'pending' would have reported already-indexed documents as
    waiting, which is the same lie in the other direction.
    """
    async with conn.execute("PRAGMA table_info(client_documents)") as cur:
        cols = {row["name"] async for row in cur}
    if "ingest_status" not in cols:
        await conn.execute(
            "ALTER TABLE client_documents ADD COLUMN ingest_status TEXT NOT NULL "
            "DEFAULT 'pending'"
        )
        await conn.execute(
            "UPDATE client_documents SET ingest_status='ingested' WHERE ingested=1"
        )
    if "ingest_error" not in cols:
        await conn.execute("ALTER TABLE client_documents ADD COLUMN ingest_error TEXT")
    await conn.commit()


async def _migrate_document_knowledge_tier(conn: aiosqlite.Connection) -> None:
    """Record which knowledge store each document's chunks went into.

    Every existing row is 'project' and that is not a default standing in for "unknown": until
    this branch there was no other store anything could be written to, so the column's default
    is a statement of fact about every document that predates it. The delete door reads it to
    decide which collection to purge, and a wrong answer there leaves chunks retrievable after
    an operator believes the document gone.
    """
    async with conn.execute("PRAGMA table_info(client_documents)") as cur:
        cols = {row["name"] async for row in cur}
    if "knowledge_tier" not in cols:
        await conn.execute(
            "ALTER TABLE client_documents ADD COLUMN knowledge_tier TEXT NOT NULL "
            "DEFAULT 'project'"
        )
    await conn.commit()


async def _migrate_document_knowledge_collection(conn: aiosqlite.Connection) -> None:
    """Record the *store* each document's chunks went into, not only the tier.

    `knowledge_tier` made the tier durable so a later operation could not re-decide it, but
    the tier is one of three inputs to a collection name. The other two are read fresh on
    every call and both move through ordinary, correctly-gated doors: `sector` is deliberately
    outside `_PLATFORM_TIER_SETTINGS`, so a project_admin may change it through
    `PATCH /{slug}/settings`, and `insert_project_registry` is an upsert whose whole purpose
    is reassigning an engagement to another organisation. Change either between upload and
    delete and the delete purges a store the write never touched, answers 204, and removes
    the row and the file - leaving the text retrievable in a shared store with nothing left
    that could name it, because the row was the handle.

    **The backfill, and what it can and cannot promise:**

    - `project` - **exact.** The collection has always been `{slug}_docs`, the slug is the
      database's own identity and cannot move, and until the tiers existed there was nowhere
      else to be.
    - `sector` and `organisation` - **a freeze, not a recovery.** The true address is whatever
      the sector or the organisation was when the chunks were written, and nothing recorded
      it, so this can only write what re-derivation would say today - which is precisely the
      value that may already have moved. What it buys is that the answer stops moving from
      here: the drift window closes at the migration instead of staying open for ever. No row
      is *worse* off, since a blank column falls back to the same re-derivation.
    - A project naming no sector is left blank rather than filled with `sector_`, which would
      be a store silently shared by every project that names none - the fallback defect this
      branch exists to remove, in a second costume.

    Only rows that actually reached a store are touched (`ingested = 1`). A pending or failed
    row has no address to record, and inventing one would make a later reingest write
    somewhere it was never told to.
    """
    async with conn.execute("PRAGMA table_info(client_documents)") as cur:
        cols = {row["name"] async for row in cur}
    if "knowledge_collection" not in cols:
        await conn.execute(
            "ALTER TABLE client_documents ADD COLUMN knowledge_collection TEXT NOT NULL "
            "DEFAULT ''"
        )

    # What the backfill can read at all, asked rather than assumed. SQLite parses a
    # correlated subquery when the statement is prepared, not when a row matches, so
    # `SELECT p.sector ...` raises on any database whose `projects` table lacks the column -
    # and several test fixtures build that table by hand. A migration that raises on a shape
    # it did not expect takes every later migration in the block down with it, so each half
    # of the backfill asks for its own column and skips itself rather than the rest.
    async with conn.execute("PRAGMA table_info(projects)") as cur:
        project_cols = {row["name"] async for row in cur}

    _UNADDRESSED = (
        " WHERE knowledge_collection = '' AND ingested = 1 AND knowledge_tier = ?"
        " AND EXISTS (SELECT 1 FROM projects p WHERE p.id = client_documents.project_id"
    )
    if "slug" in project_cols:
        await conn.execute(
            "UPDATE client_documents SET knowledge_collection ="
            " (SELECT p.slug || '_docs' FROM projects p"
            "  WHERE p.id = client_documents.project_id)"
            + _UNADDRESSED + ")",
            ("project",),
        )
    if "sector" in project_cols:
        await conn.execute(
            "UPDATE client_documents SET knowledge_collection ="
            " (SELECT 'sector_' || p.sector FROM projects p"
            "  WHERE p.id = client_documents.project_id)"
            + _UNADDRESSED + " AND COALESCE(TRIM(p.sector), '') <> '')",
            ("sector",),
        )

    # The organisation tier alone needs the *system* database, so it is guarded by the
    # question "is there anything to do" - on every deployment the answer is no, because the
    # tier only became writable on the branch that added this column, and a cross-database
    # read on every project's first open at this version would be a cost paid by everyone for
    # a case belonging to nobody.
    slugs: list[str] = []
    if "slug" in project_cols:
        async with conn.execute(
            "SELECT DISTINCT p.slug FROM client_documents d"
            " JOIN projects p ON p.id = d.project_id"
            " WHERE d.knowledge_collection = '' AND d.ingested = 1"
            " AND d.knowledge_tier = 'organisation'"
        ) as cur:
            slugs = [row["slug"] async for row in cur]
    if slugs:
        async with get_system_connection() as sys_conn:
            for slug in slugs:
                async with sys_conn.execute(
                    "SELECT o.slug FROM project_registry p"
                    " JOIN organisations o ON o.id = p.org_id WHERE p.slug=?",
                    (slug,),
                ) as org_cur:
                    row = await org_cur.fetchone()
                if not row or not (row["slug"] or "").strip():
                    continue
                await conn.execute(
                    "UPDATE client_documents SET knowledge_collection = ?"
                    " WHERE knowledge_collection = '' AND ingested = 1"
                    " AND knowledge_tier = 'organisation' AND project_id IN"
                    " (SELECT id FROM projects WHERE slug = ?)",
                    (f"org_{row['slug']}", slug),
                )
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
            completed_at   TEXT,
            baseline_date  TEXT,
            created_at     TEXT NOT NULL DEFAULT (datetime('now'))
        )
    """)
    # When a milestone was actually reached, as distinct from when it was due. Null while
    # it is outstanding: slippage is the difference between the two, so an actual date on
    # something incomplete would report a completion that has not happened.
    async with conn.execute("PRAGMA table_info(project_milestones)") as cur:
        cols = {row["name"] async for row in cur}
    if "completed_at" not in cols:
        await conn.execute("ALTER TABLE project_milestones ADD COLUMN completed_at TEXT")
    # What the milestone was promised, as distinct from due_date, which is what is
    # currently expected. due_date is editable, so without this a re-plan after a slip
    # overwrites the commitment and every later comparison measures actual against the
    # revised plan - a project re-planned as often as it slips looks perfectly on track.
    if "baseline_date" not in cols:
        await conn.execute("ALTER TABLE project_milestones ADD COLUMN baseline_date TEXT")
    await conn.commit()


# Crews renamed when the pipeline was re-sequenced: `architecture` compiles as-is
# capabilities and derives uplift initiatives, and `discovery` - which ran before the
# interviews it depends on - enumerates requirements against those initiatives and now runs
# seventh. The stored names move with the code: a row naming a crew that no longer exists
# does not read as history, it disappears from the board, and a commit gate keyed to one can
# never be satisfied.
_CREW_RENAMES: dict[str, str] = {
    "architecture": "capabilities",
    "discovery": "requirements",
}


async def rename_crew_in_stored_rows(conn: aiosqlite.Connection) -> int:
    """Bring stored crew names into line with the code. Returns rows changed.

    Runs on every connection open, so it must be a no-op once applied - the WHERE clause
    makes it one, and a run that legitimately arrives under the new name is never touched.
    """
    changed = 0
    for table in ("crew_runs", "approval_commits", "crew_submissions"):
        async with conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table,)
        ) as cur:
            if await cur.fetchone() is None:
                continue
        for old, new in _CREW_RENAMES.items():
            cur = await conn.execute(
                f"UPDATE {table} SET crew_name=? WHERE crew_name=?", (new, old)
            )
            changed += cur.rowcount
    await conn.commit()
    return changed


async def _migrate_milestone_baselines(conn: aiosqlite.Connection) -> None:
    """Every baseline a milestone has ever carried, so re-planning never erases a promise.

    A baseline that can be quietly overwritten is not a baseline: the whole value of one is
    that the original commitment survives the change request that moved it.
    """
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS milestone_baselines (
            id             INTEGER PRIMARY KEY AUTOINCREMENT,
            milestone_id   INTEGER NOT NULL,
            baseline_date  TEXT NOT NULL,
            superseded_at  TEXT NOT NULL DEFAULT (datetime('now')),
            reason         TEXT NOT NULL,
            set_by         TEXT NOT NULL DEFAULT ''
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


async def _migrate_drop_stakeholder_node_assignments(conn: aiosqlite.Connection) -> None:
    """Drop stakeholder_node_assignments - the second, unread assignment table.

    There were two. This one was project-keyed and written by the assignment page, keyed on
    `node_key`: a level and a label glued together ('L0:Governance', 'L2:Strategic
    Planning'), with no node id anywhere. Nothing on the backend ever read it. The other,
    `stakeholder_assignments`, is what run_service hands the Interview Coordinator, and it
    had no reachable writer. So a human could save the mapping into a table no agent
    consults, while the table agents consult stayed empty - which is the defect this branch
    exists to fix.

    Both were empty on every database on this deployment, verified before the drop, so
    nothing is migrated across: Jordan's Setup tab writes `stakeholder_assignments` by node
    id now. Dropping rather than leaving it empty is the point - an unread table with a
    plausible name is how the duplication happened, and a second one is how it would happen
    again.
    """
    await conn.execute("DROP TABLE IF EXISTS stakeholder_node_assignments")
    await conn.commit()


async def _migrate_agent_chat_history(conn: aiosqlite.Connection) -> None:
    """Create agent_chat_history table for server-side chat persistence."""
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS agent_chat_history (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            project_id  INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
            username    TEXT NOT NULL,
            crew_key    TEXT NOT NULL,
            role        TEXT NOT NULL CHECK(role IN ('user', 'assistant')),
            content     TEXT NOT NULL,
            created_at  TEXT NOT NULL DEFAULT (datetime('now'))
        )
    """)
    await conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_chat_history_lookup "
        "ON agent_chat_history(project_id, username, crew_key, created_at)"
    )
    await conn.commit()


async def _migrate_interview_script_ledger(conn: aiosqlite.Connection) -> None:
    """Create the interview script ledger if it does not exist.

    One row per script id, and script_id is the PRIMARY KEY rather than an indexed
    column: "one id means one node for the life of the project" becomes a constraint
    the database enforces instead of a rule an agent must honour. Rows are retired
    with active = 0 and never deleted - a deleted row is an id free to be handed to a
    different script, and every stored answer citing it then resolves to the wrong
    instrument.
    """
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS interview_script_ledger (
            script_id           TEXT PRIMARY KEY,
            project_id          INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
            node_id             TEXT NOT NULL,
            node_label          TEXT NOT NULL DEFAULT '',
            active              INTEGER NOT NULL DEFAULT 1,
            review_status       TEXT NOT NULL DEFAULT 'pending',
            reviewed_at_version INTEGER,
            review_return_to    TEXT,
            last_version        INTEGER,
            last_author         TEXT NOT NULL DEFAULT '',
            created_at          DATETIME DEFAULT CURRENT_TIMESTAMP,
            updated_at          DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)
    await conn.commit()


async def _migrate_script_reviews(conn: aiosqlite.Connection) -> None:
    """One row per review event on one script.

    Separate from the ledger because "reviewed many times by different people, approved
    once" is a history plus a current state, and collapsing them loses who said what.
    Nothing here is ever updated or deleted.
    """
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS script_reviews (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            project_id  INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
            script_id   TEXT    NOT NULL,
            reviewer    TEXT    NOT NULL DEFAULT '',
            decision    TEXT    NOT NULL,
            notes       TEXT    NOT NULL DEFAULT '',
            at_version  INTEGER,
            return_to   TEXT,
            forced      INTEGER NOT NULL DEFAULT 0,
            created_at  DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)
    async with conn.execute("PRAGMA table_info(script_reviews)") as cur:
        cols = {row["name"] async for row in cur}
    if "forced" not in cols:
        await conn.execute(
            "ALTER TABLE script_reviews ADD COLUMN forced INTEGER NOT NULL DEFAULT 0"
        )
    await conn.commit()


async def _migrate_blocked_writes(conn: aiosqlite.Connection) -> None:
    """Writes an agent attempted and was not permitted to make.

    The attempted payload is deliberately not stored - it can be large, and the useful fact
    is that the reach happened, by whom, and for what.
    """
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS blocked_writes (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            project_id   INTEGER NOT NULL REFERENCES projects(id),
            run_id       INTEGER,
            agent_name   TEXT NOT NULL,
            key          TEXT NOT NULL,
            owner        TEXT,
            reason       TEXT NOT NULL,
            attempted_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)
    await conn.commit()


async def _migrate_validation_warnings(conn: aiosqlite.Connection) -> None:
    """Structural findings a validator raised but did not refuse.

    Deliberately not blocked_writes. That table means "an agent reached for something it
    does not own"; this one means "what an agent wrote is structurally suspect". Overloading
    one with the other would blur a distinction the ownership work paid to establish.

    `measure` is not in the design's DDL. It is here because the dismissal rule - re-raise
    when the L3 proportion moves more than ten percentage points - cannot compare against a
    number nobody stored. Null for codes that carry no measure.

    The unique index is what makes a warning idempotent: a re-run refreshes the occurrence
    rather than appending a duplicate, so a reviewer's disposition outlives the run that
    triggered it.
    """
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS validation_warnings (
            id               INTEGER PRIMARY KEY AUTOINCREMENT,
            project_id       INTEGER NOT NULL REFERENCES projects(id),
            run_id           INTEGER,
            source           TEXT NOT NULL,
            subject          TEXT,
            code             TEXT NOT NULL,
            detail           TEXT NOT NULL,
            measure          REAL,
            disposition      TEXT NOT NULL DEFAULT 'open',
            disposition_note TEXT,
            disposed_by      TEXT,
            disposed_at      DATETIME,
            created_at       DATETIME DEFAULT CURRENT_TIMESTAMP,
            updated_at       DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)
    await conn.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS idx_validation_warnings_occurrence
        ON validation_warnings (project_id, source, IFNULL(subject, ''), code)
    """)
    await conn.commit()


async def _migrate_registry_output_type(conn: aiosqlite.Connection) -> None:
    """Re-type the registry rows DeriveRegistryTool wrote as 'state'.

    Matched on file_path, not on agent or version: the fault was always that the row's type
    disagreed with the family its file belongs to, and the file is the only witness to that.
    A 'state' row naming anything else is left alone - state is a real output type with real
    rows.

    One filename family answering to two output types is what let the clean-baseline prune
    demote value_chain_summary v12 to v4 and value_chain_tree v13 to v9, and it is the
    invariant current_output_path depends on.
    """
    await conn.execute(
        "UPDATE agent_outputs SET output_type='value_chain_registry'"
        " WHERE output_type='state'"
        "   AND file_path LIKE '%value_chain_registry%'"
    )
    await conn.commit()


async def _migrate_inbound_replies(conn: aiosqlite.Connection) -> None:
    """What a participant wrote back, kept where the engagement keeps its facts.

    It lands in the **project's** database rather than in `system.db`, beside the
    stakeholder it is about, for the reason `[[durable-keyed-artefacts-and-rag]]` gives:
    a reply is a fact about the engagement, not an event inside a run and not a row about
    the platform. `stakeholder_id` only means anything inside one project file - ids
    restart at 1 in every one of them - so a reply stored anywhere else would be keyed on
    a number that names a different person depending on which database you read it beside.

    `provider_event_id` is the webhook message id, and it is UNIQUE because a webhook is
    redelivered on any failure to answer. Without it, a reply that arrived while the API
    was restarting would be stored once per retry and a reviewer would read the same
    sentence four times. It comes out of the *signed* headers, so it is the provider's
    word and not the payload's.

    `body` is plain text and never HTML. Storing markup that a browser later renders is
    how an unauthenticated endpoint becomes a way of running script in an operator's
    session; the surface shows text, so text is what is kept.

    **Nothing here reaches a RAG store**, and that is the point of it being a table. The
    knowledge-tier work makes writing to a project's Chroma collections a deliberate act
    with authority for the destination tier, and a webhook holds none - it has no user, no
    role, and its content came from outside. A human reads the reply here and decides.
    """
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS inbound_replies (
            id                INTEGER PRIMARY KEY AUTOINCREMENT,
            project_id        INTEGER NOT NULL REFERENCES projects(id),
            stakeholder_id    INTEGER NOT NULL REFERENCES stakeholders(id),
            provider_event_id TEXT    NOT NULL UNIQUE,
            event_type        TEXT    NOT NULL DEFAULT '',
            from_address      TEXT    NOT NULL DEFAULT '',
            subject           TEXT    NOT NULL DEFAULT '',
            body              TEXT    NOT NULL DEFAULT '',
            truncated         INTEGER NOT NULL DEFAULT 0,
            attachment_count  INTEGER NOT NULL DEFAULT 0,
            in_reply_to       TEXT    NOT NULL DEFAULT '',
            received_at       DATETIME DEFAULT CURRENT_TIMESTAMP,
            read_at           DATETIME,
            read_by           TEXT
        )
    """)
    await conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_inbound_replies_project
        ON inbound_replies (project_id, received_at DESC)
    """)
    await conn.commit()


async def insert_inbound_reply(
    conn: aiosqlite.Connection,
    *,
    project_id: int,
    stakeholder_id: int,
    provider_event_id: str,
    event_type: str,
    from_address: str,
    subject: str,
    body: str,
    truncated: bool,
    attachment_count: int,
    in_reply_to: str,
) -> int | None:
    """Store one reply. Returns its id, or None when this delivery was already stored.

    `INSERT ... ON CONFLICT DO NOTHING` rather than a check-then-insert: the webhook is
    retried concurrently by the provider on a slow answer, and two requests that both
    looked first would both find nothing.
    """
    cur = await conn.execute(
        "INSERT INTO inbound_replies (project_id, stakeholder_id, provider_event_id,"
        " event_type, from_address, subject, body, truncated, attachment_count,"
        " in_reply_to) VALUES (?,?,?,?,?,?,?,?,?,?)"
        " ON CONFLICT(provider_event_id) DO NOTHING",
        (
            project_id, stakeholder_id, provider_event_id, event_type, from_address,
            subject, body, int(truncated), attachment_count, in_reply_to,
        ),
    )
    await conn.commit()
    return cur.lastrowid if cur.rowcount else None


async def fetch_inbound_replies(
    conn: aiosqlite.Connection, *, project_id: int, limit: int = 200
) -> list[dict]:
    """Replies on this project, newest first, each carrying the person who sent it.

    The stakeholder's name is joined here rather than resolved by the caller, because the
    caller is a surface: a list of ids is a list nobody can triage.
    """
    async with conn.execute(
        "SELECT r.*, s.name AS stakeholder_name, s.email AS stakeholder_email"
        " FROM inbound_replies r"
        " LEFT JOIN stakeholders s ON s.id = r.stakeholder_id"
        " WHERE r.project_id = ?"
        " ORDER BY r.received_at DESC, r.id DESC LIMIT ?",
        (project_id, limit),
    ) as cur:
        return [dict(r) for r in await cur.fetchall()]


async def mark_inbound_reply_read(
    conn: aiosqlite.Connection, *, project_id: int, reply_id: int, by: str
) -> bool:
    """Mark one reply as read. False when it is not this project's, or was already read.

    `project_id` is in the WHERE clause as defence in depth and **not** as the thing that
    keeps one engagement's replies out of another's - said plainly because power-checking
    proved it cannot be: there is one database file per project, so within this connection
    `project_id` is a constant and removing it from the clause changes no outcome. What
    actually isolates the engagements is `get_connection(slug)` opening a different file.
    The clause is here for the day a table like this is asked to hold two projects, which
    is the day it stops being free.
    """
    cur = await conn.execute(
        "UPDATE inbound_replies SET read_at=CURRENT_TIMESTAMP, read_by=?"
        " WHERE id=? AND project_id=? AND read_at IS NULL",
        (by, reply_id, project_id),
    )
    await conn.commit()
    return (cur.rowcount or 0) > 0


async def fetch_validation_warnings(
    conn: aiosqlite.Connection,
    *,
    project_id: int,
    sources: list[str] | None = None,
    dispositions: list[str] | None = None,
) -> list[dict]:
    """Warnings for a project, most recent occurrence first."""
    where = ["project_id = ?"]
    params: list = [project_id]
    if sources:
        where.append(f"source IN ({','.join('?' * len(sources))})")
        params.extend(sources)
    if dispositions:
        where.append(f"disposition IN ({','.join('?' * len(dispositions))})")
        params.extend(dispositions)
    sql = (
        "SELECT * FROM validation_warnings WHERE "
        + " AND ".join(where)
        + " ORDER BY updated_at DESC, id DESC"
    )
    async with conn.execute(sql, params) as cur:
        return [dict(r) for r in await cur.fetchall()]


async def dispose_validation_warning(
    conn: aiosqlite.Connection,
    *,
    warning_id: int,
    disposition: str,
    note: str,
    by: str,
) -> bool:
    """Record a reviewer's judgement. False when the id does not exist."""
    cur = await conn.execute(
        "UPDATE validation_warnings SET disposition=?, disposition_note=?, disposed_by=?,"
        " disposed_at=CURRENT_TIMESTAMP WHERE id=?",
        (disposition, note, by, warning_id),
    )
    await conn.commit()
    return cur.rowcount > 0


async def _migrate_lineage(conn: aiosqlite.Connection) -> None:
    """What a run read, and what each output was built from.

    run_inputs and run_documents accumulate during a run; output_lineage and
    output_citations are the durable edges, written when an output is created. Keeping both
    means a run's reads survive a process restart mid-run, and the edges do not depend on
    anything being held in memory.
    """
    # run_id alone used to be the key on run_inputs/run_documents. A crew run spans several
    # agents (discovery_mapping runs value_chain_mapper and value_lever_analyst), so that key
    # let a read made by one agent attach to an output a different agent wrote later in the
    # same run. agent_name is part of the key here so a fresh database gets the right shape
    # directly; _migrate_run_inputs_agent_scope below rebuilds any database that already has
    # these tables under the old, run-only key - CREATE TABLE IF NOT EXISTS does nothing there.
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS run_inputs (
            run_id     INTEGER NOT NULL,
            agent_name TEXT NOT NULL DEFAULT '',
            output_id  INTEGER NOT NULL REFERENCES agent_outputs(id),
            PRIMARY KEY (run_id, agent_name, output_id)
        )
    """)
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS run_documents (
            run_id     INTEGER NOT NULL,
            agent_name TEXT NOT NULL DEFAULT '',
            doc_id     INTEGER NOT NULL REFERENCES client_documents(id),
            PRIMARY KEY (run_id, agent_name, doc_id)
        )
    """)
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS output_lineage (
            output_id       INTEGER NOT NULL REFERENCES agent_outputs(id),
            input_output_id INTEGER NOT NULL REFERENCES agent_outputs(id),
            PRIMARY KEY (output_id, input_output_id)
        )
    """)
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS output_citations (
            output_id INTEGER NOT NULL REFERENCES agent_outputs(id),
            doc_id    INTEGER NOT NULL REFERENCES client_documents(id),
            PRIMARY KEY (output_id, doc_id)
        )
    """)
    await conn.commit()


async def _migrate_run_inputs_agent_scope(conn: aiosqlite.Connection) -> None:
    """Rebuild run_inputs/run_documents onto (run_id, agent_name, *) if they predate it.

    CREATE TABLE IF NOT EXISTS in _migrate_lineage does nothing to a database where the
    table already exists under the old two-column key - SQLite cannot change a primary key
    via ALTER TABLE. Detect the old shape by the absence of the agent_name column and rebuild,
    the same way _migrate_human_reviews rebuilds to drop a NOT NULL constraint. Existing rows
    are carried over with agent_name='' rather than dropped: both tables were empty in every
    database this shipped against, but a rebuild must not assume that of every database.
    """
    async with conn.execute("PRAGMA table_info(run_inputs)") as cur:
        cols = {row["name"] async for row in cur}
    if cols and "agent_name" not in cols:
        await conn.executescript("""
            DROP TABLE IF EXISTS run_inputs_new;
            CREATE TABLE run_inputs_new (
                run_id     INTEGER NOT NULL,
                agent_name TEXT NOT NULL DEFAULT '',
                output_id  INTEGER NOT NULL REFERENCES agent_outputs(id),
                PRIMARY KEY (run_id, agent_name, output_id)
            );
            INSERT INTO run_inputs_new (run_id, agent_name, output_id)
                SELECT run_id, '', output_id FROM run_inputs;
            DROP TABLE run_inputs;
            ALTER TABLE run_inputs_new RENAME TO run_inputs;
        """)

    async with conn.execute("PRAGMA table_info(run_documents)") as cur:
        cols = {row["name"] async for row in cur}
    if cols and "agent_name" not in cols:
        await conn.executescript("""
            DROP TABLE IF EXISTS run_documents_new;
            CREATE TABLE run_documents_new (
                run_id     INTEGER NOT NULL,
                agent_name TEXT NOT NULL DEFAULT '',
                doc_id     INTEGER NOT NULL REFERENCES client_documents(id),
                PRIMARY KEY (run_id, agent_name, doc_id)
            );
            INSERT INTO run_documents_new (run_id, agent_name, doc_id)
                SELECT run_id, '', doc_id FROM run_documents;
            DROP TABLE run_documents;
            ALTER TABLE run_documents_new RENAME TO run_documents;
        """)

    await conn.commit()


async def fetch_blocked_writes(
    conn: aiosqlite.Connection, *, run_id: int | None = None
) -> list[dict]:
    where = " WHERE run_id = ?" if run_id is not None else ""
    params = (run_id,) if run_id is not None else ()
    async with conn.execute(
        f"SELECT * FROM blocked_writes{where} ORDER BY id DESC", params
    ) as cur:
        return [dict(row) async for row in cur]


# get_stakeholder_node_assignments / upsert_stakeholder_node_assignments retired with the
# table they read - see _migrate_drop_stakeholder_node_assignments. The mapping is
# fetch_stakeholder_assignments / replace_stakeholder_assignments, keyed on node id.


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
    completed_at: str | None = None, completed_at_given: bool = False,
) -> bool:
    """Update a milestone. `completed_at_given` distinguishes "set it to null" from "leave
    it alone" - absent from a payload has to mean unchanged, or renaming a milestone would
    silently discard the date it was actually reached."""
    fields, vals = [], []

    # Ticking a milestone records when, unticking clears it. An explicit date always wins:
    # milestones are ticked off retrospectively far more often than on the day.
    if completed_at_given:
        fields.append("completed_at=?")
        vals.append(completed_at or None)
    elif status == "complete":
        fields.append("completed_at=?")
        vals.append(date.today().isoformat())
    elif status is not None and status != "complete":
        fields.append("completed_at=?")
        vals.append(None)

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


async def baseline_milestones(conn: aiosqlite.Connection, *, slug: str) -> int:
    """Record each dated milestone's current plan as what was promised. Returns the count.

    Only where no baseline exists: re-activating an in-flight project must not adopt its
    slipped plan as the promise, which would be the very failure the baseline prevents
    arriving through the mechanism meant to prevent it.

    Only where a due date exists: an undated milestone was never promised anything, and
    inventing a baseline for it would manufacture a commitment nobody made.
    """
    cur = await conn.execute(
        "UPDATE project_milestones SET baseline_date = due_date "
        "WHERE slug = ? AND baseline_date IS NULL AND due_date IS NOT NULL",
        (slug,),
    )
    await conn.commit()
    return cur.rowcount


async def rebaseline_milestone(
    conn: aiosqlite.Connection, *, milestone_id: int, slug: str,
    baseline_date: str, reason: str, set_by: str,
) -> bool:
    """Move a milestone's promise, keeping the one it replaces. False if there is none.

    The history row is written BEFORE the baseline is overwritten. If the update then
    fails, history holds a superseded date that is still current - visibly odd and
    recoverable. The other order loses the original permanently, which is unrecoverable.
    """
    async with conn.execute(
        "SELECT baseline_date FROM project_milestones WHERE id=? AND slug=?",
        (milestone_id, slug),
    ) as cur:
        row = await cur.fetchone()
    if row is None or row["baseline_date"] is None:
        return False

    await conn.execute(
        "INSERT INTO milestone_baselines (milestone_id, baseline_date, reason, set_by) "
        "VALUES (?,?,?,?)",
        (milestone_id, row["baseline_date"], reason, set_by),
    )
    await conn.execute(
        "UPDATE project_milestones SET baseline_date=? WHERE id=? AND slug=?",
        (baseline_date, milestone_id, slug),
    )
    await conn.commit()
    return True


async def fetch_milestone_baselines(
    conn: aiosqlite.Connection, *, milestone_id: int
) -> list[dict]:
    """Superseded baselines, oldest first - the order the plan actually moved in."""
    async with conn.execute(
        "SELECT id, milestone_id, baseline_date, superseded_at, reason, set_by "
        "FROM milestone_baselines WHERE milestone_id=? ORDER BY id",
        (milestone_id,),
    ) as cur:
        return [dict(r) for r in await cur.fetchall()]


async def delete_milestone(conn: aiosqlite.Connection, *, milestone_id: int, slug: str) -> bool:
    cur = await conn.execute(
        "DELETE FROM project_milestones WHERE id=? AND slug=?", (milestone_id, slug)
    )
    await conn.commit()
    return cur.rowcount > 0


# Bumped whenever a _migrate_* function is added to (or removed from) the block below -
# and equally whenever an existing one starts doing something new, such as adding a column.
# The gate is `user_version < _SCHEMA_VERSION`, so an unbumped change to a migration that
# has already run is exactly as invisible as an unbumped new migration.
# Written to the database file itself as PRAGMA user_version once the block has run, so
# forgetting to bump this after adding a migration means the new migration silently never
# runs again after a database's first post-upgrade open in a process. No test can catch a
# missed bump *in general* - it is a fact about this constant, not about behaviour - but a
# migration can be made to catch its own: build a database in the pre-migration shape,
# stamp it with the PREVIOUS version, open it, and assert the migration reached it. See
# tests/test_stakeholder_synthetic_migration.py, which fails on 8 and passes on 9;
# tests/test_stakeholder_node_assignments_retired.py, which fails on 9 and passes on 10;
# tests/test_inbound_replies.py::test_a_database_already_at_the_previous_version_gets_
# the_inbound_replies_table, which fails on 10 and passes on 11; and
# tests/test_knowledge_tier_ingestion.py::test_a_database_at_the_previous_version_gains_the_
# knowledge_tier_column, which fails on 11 and passes on 12; and
# tests/test_knowledge_collection_is_recorded.py::test_a_database_at_the_previous_version_
# gains_the_collection_column, which fails on 12 and passes on 13; and
# tests/test_local_inference_override.py::test_a_database_at_the_previous_version_gains_the_
# force_local_inference_column, which fails on 13 and passes on 14.
_SCHEMA_VERSION = 14

# Slugs this process has opened and found (or brought) up to _SCHEMA_VERSION. Record-
# keeping only, not a gate: get_connection reads PRAGMA user_version - part of the
# database file's own header - unconditionally on every open, including for a slug
# already in this set, and that read is what actually decides whether migrations run.
# Slug alone is not a reliable proxy for "this exact file has already been migrated": a
# test (or an out-of-band `rm` and restart, or restoring a backup over a live path) can
# delete and recreate - or in-place overwrite - a project's .db file under the same slug,
# and the new file needs migrating even though its slug looks familiar. A pragma read
# costs microseconds against the 4.2 ms it guards, and three pragmas are already issued
# per open, so there is no reason to skip it based on this set. It exists so
# _forget_migrations and tests have a slug-keyed record to clear or discard from.
_MIGRATED: set[str] = set()

# busy_timeout is per-connection (unlike journal_mode, which is a persistent file
# property), so it must be reapplied on every open. Centralised here so get_connection and
# interview_db_connection cannot drift apart on the value - the concurrency work this
# constant serves is worthless if only one of the two paths that open project databases
# honours it.
_BUSY_TIMEOUT_MS = 10000


async def _apply_connection_pragmas(conn: aiosqlite.Connection, *, wal: bool = True) -> None:
    """Apply the durability pragmas every project-database connection needs.

    Shared by get_connection and interview_db_connection so the pragma list is defined in
    exactly one place - the defect this task fixes was these two paths quietly disagreeing,
    and factoring out a second copy would only reintroduce that risk under a different name.

    wal defaults to on. _find_session_db opts out: it scans every candidate database file
    looking for a session token, and PRAGMA journal_mode=WAL is a write - it briefly takes an
    exclusive lock and creates -wal/-shm files - so applying it there would write to every
    database in the directory on every interview request, not just the one holding the
    session. busy_timeout is cheap and per-connection either way, so it is always applied.
    """
    conn.row_factory = aiosqlite.Row
    await conn.execute("PRAGMA foreign_keys = ON")
    if wal:
        # WAL lets readers proceed while a completion writes. Under journal_mode=delete
        # they block each other, and completions - the heavy writes - cluster at the end
        # of a break. WAL is a persistent property of the database file, so this only
        # needs to take effect once, but re-asserting it each open is cheap and safe.
        await conn.execute("PRAGMA journal_mode = WAL")
    # busy_timeout lets a connection wait for a lock instead of failing immediately with
    # "database is locked" under the brief contention WAL doesn't eliminate.
    await conn.execute(f"PRAGMA busy_timeout = {_BUSY_TIMEOUT_MS}")


async def _forget_migrations(slug: str) -> None:
    """Reset the on-disk migration marker for slug, forcing the next open to re-run every
    _migrate_* function against it.

    Not used by application code - once a slug is migrated, nothing the app does writes
    non-migrated rows into that file again, since every write goes through current-schema-
    aware code. It exists for tests that reproduce a pre-migration database by writing
    legacy-shaped rows directly via raw SQL against an already-migrated file and then
    reopening to assert the migration fixes them: PRAGMA user_version on that file already
    reads as current, so the reopen needs an explicit reason to re-run, standing in for the
    real scenario the migration exists for - a legacy file opened for the first time.
    """
    _MIGRATED.discard(slug)
    path = get_db_path(slug)
    async with aiosqlite.connect(path) as conn:
        await conn.execute("PRAGMA user_version = 0")
        await conn.commit()


@asynccontextmanager
async def get_connection(slug: str):
    path = get_db_path(slug)
    path.parent.mkdir(parents=True, exist_ok=True)
    async with aiosqlite.connect(path) as conn:
        await _apply_connection_pragmas(conn)
        # The file is the authority on whether it has been migrated, not the slug or the
        # inode: PRAGMA user_version is part of the database file's own header, so it
        # survives across processes and is correct even if the file was deleted and
        # recreated, or overwritten in place (e.g. a backup restored over the live path),
        # under the same slug and possibly the same inode.
        cur = await conn.execute("PRAGMA user_version")
        current_version = (await cur.fetchone())[0]
        if current_version < _SCHEMA_VERSION:
            await init_db(conn)
            await _migrate_projects_force_local_inference(conn)
            await _migrate_orchestration_runs_error(conn)
            await _migrate_agent_outputs_is_current(conn)
            await _migrate_agent_outputs_revision_notes(conn)
            await _migrate_human_reviews(conn)
            await _migrate_crew_runs(conn)
            await _migrate_stakeholders(conn)
            await _migrate_campaigns(conn)
            await _migrate_stakeholder_assignments(conn)
            await _migrate_stakeholder_assignments_to_project(conn)
            await _migrate_interview_sessions(conn)
            await _migrate_interview_sessions_ratings(conn)
            await _migrate_interview_sessions_checkpoint(conn)
            await _migrate_interview_answers(conn)
            await _migrate_document_ingest_status(conn)
            await _migrate_document_knowledge_tier(conn)
            await _migrate_document_knowledge_collection(conn)
            await _migrate_project_milestones(conn)
            await _migrate_milestone_baselines(conn)
            await rename_crew_in_stored_rows(conn)
            await _migrate_nonworking_ranges(conn)
            await _migrate_drop_stakeholder_node_assignments(conn)
            await _migrate_agent_chat_history(conn)
            await _migrate_interview_script_ledger(conn)
            await _migrate_script_reviews(conn)
            await _migrate_interview_sessions_script_id(conn)
            await _migrate_stakeholder_roles(conn)
            await _migrate_blocked_writes(conn)
            await _migrate_lineage(conn)
            await _migrate_run_inputs_agent_scope(conn)
            await _migrate_output_changes_kind(conn)
            await _migrate_validation_warnings(conn)
            await _migrate_registry_output_type(conn)
            await _migrate_inbound_replies(conn)
            # PRAGMA does not accept bound parameters; _SCHEMA_VERSION is a hardcoded
            # module constant, never user input, so formatting it in is safe.
            await conn.execute(f"PRAGMA user_version = {_SCHEMA_VERSION}")
        _MIGRATED.add(slug)
        yield conn


@asynccontextmanager
async def interview_db_connection(db_path: str, *, wal: bool = True):
    """A connection to a project database opened by path rather than slug.

    The interview endpoints resolve a session by scanning for its token (see
    _find_session_db in api/services/interview_service.py), so they hold a path and not a
    slug, and they must not run migrations - a public interview request is not the place to
    discover a schema change. They still need the same durability settings get_connection
    applies, which is what this exists for: WAL so a completion does not block the readers
    around it, and the same busy_timeout rather than aiosqlite's own 5s default.

    wal=False is for the scan itself, not for serving or writing a session - see
    _apply_connection_pragmas for why the scan opts out.
    """
    async with aiosqlite.connect(db_path) as conn:
        await _apply_connection_pragmas(conn, wal=wal)
        yield conn


async def insert_project(conn: aiosqlite.Connection, *, slug: str, llm_mode: str, sector: str, config_json: str) -> bool:
    """Insert a project. Returns True if inserted, False if slug already exists.

    The second writer of llm_mode, and so the second place the mode cache has to be dropped.
    project_llm_mode caches "standard" both when the database file is absent and when the row
    is absent - which is precisely the state during creation, including the window inside
    create_project where get_connection(slug) has made the file but this insert has not yet
    written the row. Anything resolving a mode in that window pins "standard" for the life of
    the process, and creation never calls update_project_config, so nothing later clears it:
    a project created as sensitive would ship its documents to Chroma Cloud with no
    operator-visible signal.
    """
    try:
        await conn.execute(
            "INSERT INTO projects (slug, llm_mode, sector, config_json) VALUES (?,?,?,?)",
            (slug, llm_mode, sector, config_json),
        )
        await conn.commit()
    except aiosqlite.IntegrityError:
        return False
    from api.services.chroma_client import forget_project_mode
    forget_project_mode(slug)
    return True


async def fetch_project(conn: aiosqlite.Connection, *, slug: str) -> dict | None:
    async with conn.execute("SELECT * FROM projects WHERE slug=?", (slug,)) as cur:
        row = await cur.fetchone()
        return dict(row) if row else None


async def list_projects(conn: aiosqlite.Connection) -> list[dict]:
    async with conn.execute("SELECT * FROM projects ORDER BY created_at DESC") as cur:
        return [dict(r) async for r in cur]


async def set_project_status(
    conn: aiosqlite.Connection, *, slug: str, status: str
) -> None:
    """Set a project's lifecycle status. Idempotent."""
    await conn.execute("UPDATE projects SET status=? WHERE slug=?", (status, slug))
    await conn.commit()


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


async def insert_crew_run_if_not_running(
    conn: aiosqlite.Connection,
    *,
    project_id: int,
    crew_name: str,
    orchestration_run_id: int | None = None,
) -> int | None:
    """Insert a running crew_run row, unless this crew already has one.

    Returns the new run's id, or None when a running row already existed and nothing
    was inserted.

    The condition is inside the INSERT rather than in a read before it. Auto-start
    classifies a downstream crew as ready and then inserts, with several awaits in
    between; two approvers committing the same upstream inside that window would both
    see "not running" and both insert, leaving two concurrent runs of one crew writing
    versioned outputs. A single statement is evaluated under SQLite's write lock, so
    only one of them can win.
    """
    cur = await conn.execute(
        "INSERT INTO crew_runs (project_id, crew_name, status, started_at, orchestration_run_id) "
        "SELECT ?, ?, 'running', CURRENT_TIMESTAMP, ? "
        "WHERE NOT EXISTS ("
        "  SELECT 1 FROM crew_runs WHERE crew_name=? AND status='running'"
        ")",
        (project_id, crew_name, orchestration_run_id, crew_name),
    )
    await conn.commit()
    return cur.lastrowid if cur.rowcount else None


async def fetch_crew_runs(conn: aiosqlite.Connection, *, project_id: int) -> list[dict]:
    async with conn.execute(
        "SELECT * FROM crew_runs WHERE project_id=? ORDER BY created_at DESC", (project_id,)
    ) as cur:
        return [dict(r) async for r in cur]


async def crew_is_running(conn: aiosqlite.Connection, *, crew_name: str) -> bool:
    """Whether this crew has a run currently in flight.

    Committing mid-run freezes whichever output versions happen to be current at
    that moment - a mix of this run's and the last's - so commit_crew checks this
    before it writes.
    """
    async with conn.execute(
        "SELECT 1 FROM crew_runs WHERE crew_name=? AND status='running' LIMIT 1",
        (crew_name,),
    ) as cur:
        return await cur.fetchone() is not None


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


async def set_current_output(conn: aiosqlite.Connection, *, project_id: int,
                              output_type: str, output_id: int) -> None:
    """Mark one output as the current version of its type, superseding the rest.

    Used when a new version is saved for an output type that keeps a single "current"
    row per project (e.g. the value chain model) - the new row becomes current and every
    other version of the same type falls out of currency in the same commit.
    """
    await conn.execute(
        "UPDATE agent_outputs SET is_current=0 "
        "WHERE project_id=? AND output_type=? AND id<>?",
        (project_id, output_type, output_id),
    )
    await conn.execute(
        "UPDATE agent_outputs SET is_current=1 WHERE id=?", (output_id,),
    )
    await conn.commit()


async def output_exists(conn: aiosqlite.Connection, *, output_id: int) -> bool:
    async with conn.execute(
        "SELECT 1 FROM agent_outputs WHERE id=?", (output_id,)
    ) as cur:
        return await cur.fetchone() is not None


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
    knowledge_tier: str = "project",
) -> int:
    """Record an uploaded document.

    `knowledge_tier` defaults to the narrowest store, so a caller that has not thought about
    tiers files the document where it can only be read by this project. It is recorded here
    rather than derived later because the delete door has to purge the store the write
    actually used.
    """
    cur = await conn.execute(
        """INSERT INTO client_documents
           (project_id, filename, original_name, file_path, content_type, size_bytes,
            knowledge_tier)
           VALUES (?,?,?,?,?,?,?)""",
        (project_id, filename, original_name, file_path, content_type, size_bytes,
         knowledge_tier),
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
    # Delete output_citations and run_documents rows referencing this document first to
    # satisfy the FK constraint, then hard-delete the client_documents row itself. Both
    # tables reference client_documents(id): output_citations is the durable edge written
    # when an output cites this document, run_documents is the per-run record of a retrieval
    # that returned a chunk from it.
    await conn.execute("DELETE FROM output_citations WHERE doc_id=?", (doc_id,))
    await conn.execute("DELETE FROM run_documents WHERE doc_id=?", (doc_id,))
    cur = await conn.execute("DELETE FROM client_documents WHERE id=?", (doc_id,))
    await conn.commit()
    return cur.rowcount > 0


async def fetch_document_names(conn: aiosqlite.Connection, *, project_id: int) -> dict[str, str]:
    """Map doc id to original_name, not the stored filename - that's a hash, unreadable in a citation."""
    async with conn.execute(
        "SELECT id, original_name FROM client_documents WHERE project_id=?",
        (project_id,),
    ) as cur:
        return {str(row[0]): row[1] async for row in cur}


async def update_project_config(
    conn: aiosqlite.Connection,
    *,
    slug: str,
    project_id: int,
    llm_mode: str,
    force_local_inference: bool,
    sector: str,
    config_json: str,
) -> None:
    """The one write path for a project's egress inputs - every caller that can change
    `llm_mode` or `force_local_inference` goes through here, which is why the cache
    invalidation lives here rather than at any one of them. Called with an unchanged
    llm_mode (e.g. a config-key merge through `merge_project_config` below) still clears
    the cache; that costs one extra read on the next resolution and is cheaper than a
    caller forgetting to invalidate on the one call that actually flips the mode.

    **This is the wide writer, and it has exactly one production caller** -
    `update_project_settings`, behind `PATCH /{slug}/settings`, the door whose job *is*
    changing these columns. Anything that only wants to merge a config key calls
    `merge_project_config`, which reads the three columns off the row rather than restating
    them. That is not tidiness: the three arguments below are mandatory, so a door that
    cares about none of them still has to get all three right, and a wrong `llm_mode` there
    flips a sensitive project to `standard` immediately - `forget_project_mode` drops the
    cache on the way out - which permits `CLOUD_VECTOR_STORE` and sends the corpus to Chroma
    Cloud with no error and no warning. `tests/test_local_inference_override.py::
    test_the_wide_project_config_writer_has_exactly_one_production_caller` holds the caller
    set to what this paragraph claims.

    `force_local_inference` is **required and not defaulted**. A default here would be
    fail-open in the widening direction: a caller that lost the value would quietly clear an
    override an administrator set and put the engagement's prompts back on hosted inference
    with nothing said. The same argument the LLM and mail seams make for never defaulting a
    slug - a caller that lost the value is not a value of `False`."""
    await conn.execute(
        "UPDATE projects SET llm_mode=?, force_local_inference=?, sector=?, config_json=? "
        "WHERE id=?",
        (llm_mode, 1 if force_local_inference else 0, sector, config_json, project_id),
    )
    await conn.commit()
    from api.services.chroma_client import forget_project_mode
    forget_project_mode(slug)


async def merge_project_config(
    conn: aiosqlite.Connection, *, project: dict, key: str, value
) -> None:
    """Merge one key into a project's `config_json`, disturbing nothing else.

    The seam for every door that wants a config key and nothing more - the branding header
    upload, and Agent Chat's document and link doors. It exists because `update_project_config`
    writes `llm_mode`, `force_local_inference` and `sector` on every call, so before this each
    such door had to restate three columns it did not care about. Six carry-throughs across
    two files, all correct, and five of the six could be mutated with the whole backend suite
    green - so the shape was one edit away from a silent egress change reachable by a
    `project_admin` uploading a logo or an approver adding a link, both of whom are 403'd from
    changing `llm_mode` through the front door.

    The seam takes the **row**, not the values. There is nothing for a caller to get wrong,
    and nothing for two callers to spell differently - which had already begun, the two sites
    reading `sector` as `project["sector"]` and `project.get("sector") or ""`. That is the
    established answer on this codebase to a positive obligation over a closed set: a seam,
    as `collection_for`, `chunk_filter_for`, `deliver_reset`, `outbound_mail` and
    `project_completion` are, rather than a source walk that can only ever see a *new* caller.

    All three columns are read as `project[...]`, subscript and unnormalised, deliberately.
    A carry-through writes back what it read; `or ""` is a normalisation, and a door merging
    a config key has no business collapsing a NULL sector into an empty string - only
    `PATCH /{slug}/settings`, which owns the column, may decide that. `.get` bought no safety
    either: the `UPDATE` below names all three columns, so a row that genuinely lacked one
    could not be written at all, and the default would only have substituted a value for a
    column that *does* exist. That is the fail-open direction the required keyword arguments
    above were introduced to close.
    """
    config = _json.loads(project.get("config_json") or "{}")
    config[key] = value
    await update_project_config(
        conn,
        slug=project["slug"],
        project_id=project["id"],
        llm_mode=project["llm_mode"],
        force_local_inference=bool(project["force_local_inference"]),
        sector=project["sector"],
        config_json=_json.dumps(config),
    )


async def _set_document_ingest_state(
    conn: aiosqlite.Connection, *, doc_id: int, status: str, error: str | None
) -> None:
    """The only writer of ingest state.

    `ingested` and `ingest_status` describe one fact, and two columns describing one fact
    drift the moment either gains its own writer. Both are set here, together, always.
    """
    await conn.execute(
        "UPDATE client_documents SET ingested=?, ingest_status=?, ingest_error=? WHERE id=?",
        (1 if status == "ingested" else 0, status, error, doc_id),
    )
    await conn.commit()


async def update_document_ingested(
    conn: aiosqlite.Connection, *, doc_id: int, collection: str | None = None
) -> None:
    """Indexed successfully. Clears any earlier failure: a stale reason beside a green
    status is worse than none, because a reader trusts the older, louder signal.

    `collection` is the store the chunks actually landed in, recorded here because this is
    the moment it becomes a fact rather than a calculation - the delete and reingest doors
    read it instead of working the name out again from values that may have moved since. It
    is optional so a caller that has not been given one leaves the column as it found it;
    the doors fall back to re-deriving, which is the best that can be done for an address
    nothing recorded.
    """
    if collection:
        await conn.execute(
            "UPDATE client_documents SET knowledge_collection=? WHERE id=?",
            (collection, doc_id),
        )
    await _set_document_ingest_state(conn, doc_id=doc_id, status="ingested", error=None)


async def update_document_ingest_failed(
    conn: aiosqlite.Connection, *, doc_id: int, error: str
) -> None:
    """Failed, with the reason a person can act on.

    Without this the row could only say `ingested = 0`, which the UI renders as "pending" -
    indistinguishable from not yet started, and unchanged after three permanent failures.
    """
    await _set_document_ingest_state(conn, doc_id=doc_id, status="failed", error=error[:1000])


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
    """Hard-delete all versions newer than output_id for the same output_type.

    Scoped by (project_id, output_type) only, not agent_name - version numbering and
    is_current supersession are per output_type project-wide (see insert_agent_output_sync
    and set_current_output), because the filename that anchors a version carries no agent.
    Scoping this delete by agent_name as well would leave another agent's rows for the same
    output_type undeleted and, worse, leave their is_current row untouched by the sweep
    below, re-creating the two-current-rows state this scoping fix exists to prevent.

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
           WHERE project_id=? AND output_type=? AND version > ?""",
        (project_id, output_type, target_version),
    ) as cur:
        deleted_paths = [r["file_path"] for r in await cur.fetchall()]
    # Delete human_reviews, run_inputs, output_lineage and output_citations rows referencing
    # the newer outputs first to satisfy the FK constraint, then hard-delete the agent_outputs
    # rows themselves. Every subquery below is scoped identically to the main delete so it
    # selects the same row set. output_lineage is scoped on both output_id and
    # input_output_id, since a doomed output can be the thing built (output_id) or a thing
    # something else was built from (input_output_id).
    await conn.execute(
        """DELETE FROM human_reviews WHERE output_id IN (
               SELECT id FROM agent_outputs
               WHERE project_id=? AND output_type=? AND version > ?
           )""",
        (project_id, output_type, target_version),
    )
    await conn.execute(
        """DELETE FROM run_inputs WHERE output_id IN (
               SELECT id FROM agent_outputs
               WHERE project_id=? AND output_type=? AND version > ?
           )""",
        (project_id, output_type, target_version),
    )
    await conn.execute(
        """DELETE FROM output_lineage WHERE output_id IN (
               SELECT id FROM agent_outputs
               WHERE project_id=? AND output_type=? AND version > ?
           )""",
        (project_id, output_type, target_version),
    )
    await conn.execute(
        """DELETE FROM output_lineage WHERE input_output_id IN (
               SELECT id FROM agent_outputs
               WHERE project_id=? AND output_type=? AND version > ?
           )""",
        (project_id, output_type, target_version),
    )
    await conn.execute(
        """DELETE FROM output_citations WHERE output_id IN (
               SELECT id FROM agent_outputs
               WHERE project_id=? AND output_type=? AND version > ?
           )""",
        (project_id, output_type, target_version),
    )
    await conn.execute(
        """DELETE FROM agent_outputs
           WHERE project_id=? AND output_type=? AND version > ?""",
        (project_id, output_type, target_version),
    )
    # Set the target as the sole current version
    await conn.execute(
        """UPDATE agent_outputs SET is_current=0
           WHERE project_id=? AND output_type=?""",
        (project_id, output_type),
    )
    await conn.execute(
        "UPDATE agent_outputs SET is_current=1 WHERE id=?",
        (output_id,),
    )
    # Auto-dismiss any pending HITL reviews for this crew so the waiting state clears.
    # HITL reviews link via crew_run_id (not output_id), so they survive output deletion
    # unless explicitly cleared here.
    crew_name = _crew_of(agent_name)
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


async def fetch_review(conn: aiosqlite.Connection, *, review_id: int) -> dict | None:
    """A single human_reviews row by id, including its output_id - callers that need to
    attach a change to the output a review was made against use this."""
    async with conn.execute(
        "SELECT * FROM human_reviews WHERE id=?", (review_id,)
    ) as cur:
        row = await cur.fetchone()
    return dict(row) if row else None


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


async def insert_approval_commit(
    conn: aiosqlite.Connection, *, crew_name: str, committed_by: str, notes: str = ""
) -> int:
    """Record that a crew's outputs were committed. Never undone - a later commit
    supersedes it, and the history is the audit trail."""
    cur = await conn.execute(
        "INSERT INTO approval_commits (crew_name, committed_by, notes) VALUES (?,?,?)",
        (crew_name, committed_by, notes),
    )
    await conn.commit()
    return cur.lastrowid


async def link_commit_outputs(
    conn: aiosqlite.Connection, *, commit_id: int, output_ids: list[int]
) -> None:
    """Freeze these output versions against a commit. An empty list is valid - some
    crews produce no artefact."""
    for output_id in output_ids:
        await conn.execute(
            "INSERT OR IGNORE INTO approval_commit_outputs (commit_id, output_id) VALUES (?,?)",
            (commit_id, output_id),
        )
    await conn.commit()


async def fetch_approval_commits(
    conn: aiosqlite.Connection, *, crew_name: str | None = None
) -> list[dict]:
    """Commit history, newest first. Filtered to one crew when named."""
    if crew_name is None:
        sql, params = "SELECT * FROM approval_commits ORDER BY id DESC", ()
    else:
        sql, params = (
            "SELECT * FROM approval_commits WHERE crew_name=? ORDER BY id DESC",
            (crew_name,),
        )
    async with conn.execute(sql, params) as cur:
        return [dict(row) for row in await cur.fetchall()]


async def crew_has_commit(conn: aiosqlite.Connection, *, crew_name: str) -> bool:
    """Whether this crew has ever been committed - the unit readiness is computed from."""
    async with conn.execute(
        "SELECT 1 FROM approval_commits WHERE crew_name=? LIMIT 1", (crew_name,)
    ) as cur:
        return await cur.fetchone() is not None


async def insert_crew_submission(
    conn: aiosqlite.Connection, *, crew_name: str, submitted_by: str, notes: str = ""
) -> int:
    """Record that a contributor marked this crew's work ready for approval."""
    cur = await conn.execute(
        "INSERT INTO crew_submissions (crew_name, submitted_by, notes) VALUES (?,?,?)",
        (crew_name, submitted_by, notes),
    )
    await conn.commit()
    return cur.lastrowid


async def latest_submission_at(
    conn: aiosqlite.Connection, *, crew_name: str
) -> str | None:
    """When this crew was last submitted, or None if it never has been."""
    async with conn.execute(
        "SELECT MAX(submitted_at) AS at FROM crew_submissions WHERE crew_name=?",
        (crew_name,),
    ) as cur:
        row = await cur.fetchone()
    return row["at"] if row else None


async def latest_commit_at(conn: aiosqlite.Connection, *, crew_name: str) -> str | None:
    """committed_at of this crew's most recent commit, or None if never committed.

    changes_for_crew uses this to scope the change log to what happened since - the
    change count must be able to reach zero, which it cannot if every change ever
    recorded is counted forever.
    """
    async with conn.execute(
        "SELECT committed_at FROM approval_commits WHERE crew_name=? "
        "ORDER BY committed_at DESC, id DESC LIMIT 1",
        (crew_name,),
    ) as cur:
        row = await cur.fetchone()
    return row["committed_at"] if row else None


async def insert_output_change(
    conn: aiosqlite.Connection,
    *,
    output_id: int,
    requested_by: str,
    source: str,
    request: str,
    summary: str = "",
    kind: str = "unclassified",
) -> int:
    """Record a change asked of an output: who asked, through which door, for what."""
    cur = await conn.execute(
        "INSERT INTO output_changes (output_id, requested_by, source, request, summary, kind) "
        "VALUES (?,?,?,?,?,?)",
        (output_id, requested_by, source, request, summary, kind),
    )
    await conn.commit()
    return cur.lastrowid


async def fetch_output_changes(
    conn: aiosqlite.Connection, *, output_ids: list[int], since: str | None = None
) -> list[dict]:
    """Changes against these outputs, newest first.

    An empty id list returns nothing rather than everything - the alternative is an
    unfiltered query that silently reports the whole project's history.

    `since`, when given, excludes changes recorded at or before that timestamp (an
    approval_commits.committed_at value) - the crew's change log resets at each
    commit, since a commit is what a change count of zero is meant to reflect.
    """
    if not output_ids:
        return []
    placeholders = ",".join("?" for _ in output_ids)
    sql = f"SELECT * FROM output_changes WHERE output_id IN ({placeholders})"
    params: list = list(output_ids)
    if since is not None:
        sql += " AND created_at > ?"
        params.append(since)
    sql += " ORDER BY id DESC"
    async with conn.execute(sql, tuple(params)) as cur:
        return [dict(row) for row in await cur.fetchall()]


async def fetch_open_change_requests(
    conn: aiosqlite.Connection, *, output_ids: list[int]
) -> list[dict]:
    """Open change requests for these outputs, oldest first.

    Only kind='change_request'. A correction reaches the agent through RAG and a skill
    through the prompt library; injecting them here too would say the same thing twice.
    """
    if not output_ids:
        return []
    marks = ",".join("?" * len(output_ids))
    async with conn.execute(
        f"SELECT * FROM output_changes"
        f" WHERE output_id IN ({marks}) AND kind='change_request' AND status='open'"
        f" ORDER BY id ASC",
        tuple(output_ids),
    ) as cur:
        return [dict(row) async for row in cur]


async def mark_change_requests_applied(
    conn: aiosqlite.Connection, *, change_ids: list[int], run_id: int | None
) -> int:
    """Close the requests a run consumed. Returns rows changed.

    An empty list is the ordinary case on a first run and must not build an IN () clause.
    """
    if not change_ids:
        return 0
    marks = ",".join("?" * len(change_ids))
    cur = await conn.execute(
        f"UPDATE output_changes SET status='applied', applied_run_id=?"
        f" WHERE id IN ({marks}) AND status='open'",
        (run_id, *change_ids),
    )
    await conn.commit()
    return cur.rowcount


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


async def count_outputs_by_type(
    conn: aiosqlite.Connection, *, project_id: int, output_types: list[str]
) -> dict:
    """Read-only counterpart to prune_output_types - reports what a prune would touch.

    Returns {"counts": {output_type: row_count, ...}, "file_paths": [...]}, deleting
    nothing. This is the per-type breakdown a prune's audit trail needs: a caller that
    only prints a single total cannot tell, from the transcript alone, which types
    were actually hit.
    """
    if not output_types:
        return {"counts": {}, "file_paths": []}

    marks = ",".join("?" * len(output_types))
    params = (project_id, *output_types)

    async with conn.execute(
        f"SELECT output_type, COUNT(*) FROM agent_outputs"
        f" WHERE project_id=? AND output_type IN ({marks})"
        f" GROUP BY output_type",
        params,
    ) as cur:
        counts = {row[0]: row[1] async for row in cur}

    async with conn.execute(
        f"SELECT DISTINCT file_path FROM agent_outputs"
        f" WHERE project_id=? AND output_type IN ({marks})",
        params,
    ) as cur:
        file_paths = [row[0] async for row in cur]

    return {"counts": counts, "file_paths": file_paths}


async def prune_output_types(
    conn: aiosqlite.Connection, *, project_id: int, output_types: list[str]
) -> dict:
    """Delete every agent_outputs row of the given types, with its dependent rows.

    Returns {"deleted": int, "file_paths": [...]}. The paths are collected before the
    delete, because afterwards there is nothing left to ask - the caller archives them.

    Dependents must go first. agent_outputs is referenced by human_reviews,
    approval_commit_outputs, output_changes, run_inputs, output_lineage on BOTH of its
    columns, and output_citations, and get_connection enables foreign key enforcement, so
    a bare delete raises. Missing input_output_id would leave the commoner case broken:
    a doomed row is more often something else was built from than something that built.
    """
    if not output_types:
        return {"deleted": 0, "file_paths": []}

    marks = ",".join("?" * len(output_types))
    params = (project_id, *output_types)

    async with conn.execute(
        f"SELECT DISTINCT file_path FROM agent_outputs"
        f" WHERE project_id=? AND output_type IN ({marks})",
        params,
    ) as cur:
        file_paths = [row[0] async for row in cur]

    doomed = (
        f"SELECT id FROM agent_outputs WHERE project_id=? AND output_type IN ({marks})"
    )
    for table, column in (
        ("human_reviews", "output_id"),
        ("approval_commit_outputs", "output_id"),
        ("output_changes", "output_id"),
        ("run_inputs", "output_id"),
        ("output_lineage", "output_id"),
        ("output_lineage", "input_output_id"),
        ("output_citations", "output_id"),
    ):
        await conn.execute(f"DELETE FROM {table} WHERE {column} IN ({doomed})", params)

    async with conn.execute(
        f"DELETE FROM agent_outputs WHERE project_id=? AND output_type IN ({marks})",
        params,
    ) as cur:
        deleted = cur.rowcount
    await conn.commit()
    return {"deleted": deleted, "file_paths": file_paths}


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
    is_project_admin: bool = False,
    is_governor: bool = False,
) -> int:
    """Insert a stakeholder row. Returns new id."""
    cur = await conn.execute(
        """INSERT INTO stakeholders
           (project_id, name, job_title, organisation, email, slack_handle,
            stakeholder_groups, project_role, value_streams, value_chain_stage,
            activity, disposition, location, country_code, timezone,
            preferred_language, currency,
            level, entity, mobile, comms_channel,
            is_participant, is_reviewer, is_approver, is_project_admin, is_governor)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            project_id, name, job_title, organisation, email, slack_handle,
            _json.dumps(stakeholder_groups or []),
            project_role,
            _json.dumps(value_streams or []),
            value_chain_stage, activity, disposition,
            location, country_code, timezone, preferred_language, currency,
            level, entity, mobile, comms_channel,
            int(is_participant), int(is_reviewer), int(is_approver),
            int(is_project_admin), int(is_governor),
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
    row["is_project_admin"] = bool(row.get("is_project_admin", 0))
    row["is_governor"] = bool(row.get("is_governor", 0))
    # SELECT * carries this to every reader whatever we do here, so the choice is between a
    # 0/1 int and a bool. A reader that can see a seeded row should be told it is one.
    row["is_synthetic"] = bool(row.get("is_synthetic", 0))
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


async def fetch_stakeholder_identities(
    conn: aiosqlite.Connection, *, stakeholder_ids: list[int]
) -> dict[int, dict]:
    """The name and entity of the named stakeholder rows, keyed by id.

    Two columns and no others, and that is the point rather than an optimisation: this is
    read by `api/services/user_identity.py` on behalf of an administrator looking at a list
    of *logins*, and the only fields that screen shows are name and entity. Selecting the
    row wholesale would put job title, mobile, disposition and every role flag on a code
    path whose caller has no business with them.

    Not scoped by project_id, because the caller has already opened this project's database
    by slug - the slug *is* the scope, and it is decided in user_identity.py against the
    projects the caller may administer. A project_id here would be a second, weaker copy of
    a check made where it can actually be answered.
    """
    out: dict[int, dict] = {}
    ids = sorted(set(stakeholder_ids))
    # Chunked under SQLITE_MAX_VARIABLE_NUMBER. Small in practice, free to keep correct.
    for start in range(0, len(ids), 400):
        chunk = ids[start:start + 400]
        placeholders = ",".join("?" * len(chunk))
        async with conn.execute(
            f"SELECT id, name, entity FROM stakeholders WHERE id IN ({placeholders})",
            chunk,
        ) as cur:
            async for row in cur:
                out[row["id"]] = {"name": row["name"], "entity": row["entity"]}
    return out


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
    "is_participant", "is_reviewer", "is_approver", "is_project_admin", "is_governor",
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
    for key in ("is_participant", "is_reviewer", "is_approver",
                "is_project_admin", "is_governor"):
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
            is_sys_admin INTEGER NOT NULL DEFAULT 0,
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
            stakeholder_id INTEGER,
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

        CREATE TABLE IF NOT EXISTS skills (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            name            TEXT NOT NULL,
            description     TEXT NOT NULL,
            source          TEXT NOT NULL DEFAULT 'manual',
            source_project  TEXT,
            status          TEXT NOT NULL DEFAULT 'pending'
                                CHECK(status IN ('pending', 'approved', 'rejected')),
            flag_reason     TEXT,
            flag_suggestion TEXT,
            created_at      DATETIME DEFAULT CURRENT_TIMESTAMP,
            reviewed_at     DATETIME,
            reviewed_by     TEXT
        );

        CREATE TABLE IF NOT EXISTS agent_skill_assignments (
            skill_id    INTEGER NOT NULL,
            agent_name  TEXT NOT NULL,
            PRIMARY KEY (skill_id, agent_name)
        );

        CREATE TABLE IF NOT EXISTS scheduled_jobs (
            job_name     TEXT NOT NULL,
            slug         TEXT NOT NULL,
            next_due_at  TEXT NOT NULL,
            last_run_at  TEXT,
            status       TEXT NOT NULL DEFAULT 'idle',
            last_error   TEXT NOT NULL DEFAULT '',
            PRIMARY KEY (job_name, slug)
        );

        CREATE TABLE IF NOT EXISTS scheduler_heartbeat (
            id           INTEGER PRIMARY KEY CHECK (id = 1),
            last_tick_at TEXT NOT NULL
        );

        -- The address this deployment answers on, settable by a sysadmin rather than
        -- only by editing .env and restarting. Singleton, like scheduler_heartbeat
        -- above: CHECK (id = 1) makes a second row impossible rather than merely
        -- unwritten. A blank public_url is the unset state, not a chosen empty string -
        -- api.services.platform_settings.platform_public_url() falls back to the
        -- PUBLIC_URL environment variable whenever this is blank or the row is absent.
        CREATE TABLE IF NOT EXISTS platform_settings (
            id         INTEGER PRIMARY KEY CHECK (id = 1),
            public_url TEXT NOT NULL DEFAULT '',
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS auth_tokens (
            id             INTEGER PRIMARY KEY AUTOINCREMENT,
            token_hash     TEXT    NOT NULL UNIQUE,
            email          TEXT    NOT NULL,
            project_slug   TEXT,
            stakeholder_id INTEGER,
            purpose        TEXT    NOT NULL,
            expires_at     DATETIME NOT NULL,
            used_at        DATETIME,
            created_at     DATETIME DEFAULT CURRENT_TIMESTAMP
        );

        -- issue_invite/reissue_invite/issue_reset all look up "the live row for this
        -- (email, purpose)" before writing. Without this index that lookup is a full table
        -- scan, and it is on the unauthenticated /auth/reset-request path - growing linearly
        -- with table size is exactly the property token_hash's own index was added to close
        -- on the accept path.
        CREATE INDEX IF NOT EXISTS idx_auth_tokens_email_purpose ON auth_tokens(email, purpose);

        -- One reply address per person per engagement, and deliberately NOT a new
        -- `purpose` on auth_tokens. Every purpose that table holds is single-use and
        -- expiring: `_find_live_token` filters `used_at IS NULL AND expires_at > now`,
        -- `accept_token` stamps `used_at` on redemption, and `expires_at` is NOT NULL.
        -- A reply token is the opposite of all three - it is long-lived, it is reused on
        -- every message, and `used_at` has no meaning for something that is never used
        -- up. Sharing the table would mean a NOT NULL expiry filled with a sentinel, a
        -- `used_at` column that must never be stamped, and a row that
        -- `accept_token(raw, password)` - which takes `purpose=None` and accepts any live
        -- row - would happily redeem as a login.
        --
        -- `issue` is what makes revocation stick. Re-minting after a revocation bumps it,
        -- which derives a different token and overwrites `token_hash`, so the revoked
        -- address is not merely refused - its digest is no longer in the table at all.
        -- Nothing deletes from here, so `issue` only ever climbs.
        CREATE TABLE IF NOT EXISTS reply_tokens (
            project_slug   TEXT    NOT NULL,
            stakeholder_id INTEGER NOT NULL,
            token_hash     TEXT    NOT NULL UNIQUE,
            issue          INTEGER NOT NULL DEFAULT 1,
            created_at     DATETIME DEFAULT CURRENT_TIMESTAMP,
            revoked_at     DATETIME,
            PRIMARY KEY (project_slug, stakeholder_id)
        );

        -- The provider's id for a message that was actually sent to a named person.
        -- Recorded from the first send rather than when it is needed, because it cannot
        -- be recovered afterwards: if inbound routing turns out to strip the `+tag` from
        -- the recipient address, `In-Reply-To` matched against this table is the only
        -- fallback, and it only exists for messages sent after it started being kept.
        CREATE TABLE IF NOT EXISTS sent_messages (
            provider_message_id TEXT PRIMARY KEY,
            project_slug        TEXT    NOT NULL,
            stakeholder_id      INTEGER NOT NULL,
            sent_at             DATETIME DEFAULT CURRENT_TIMESTAMP
        );
    """)
    await conn.commit()

    # Migrate old agent_skills table (pre-relational schema) if it still exists
    async with conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='agent_skills'"
    ) as cur:
        has_old = await cur.fetchone() is not None
    if has_old:
        await conn.execute(
            """INSERT OR IGNORE INTO skills
               (id, name, description, source, source_project, status,
                flag_reason, flag_suggestion, created_at, reviewed_at, reviewed_by)
               SELECT id, name, description, source, source_project, status,
                      flag_reason, flag_suggestion, created_at, reviewed_at, reviewed_by
               FROM agent_skills"""
        )
        await conn.execute(
            """INSERT OR IGNORE INTO agent_skill_assignments (skill_id, agent_name)
               SELECT id, agent_name FROM agent_skills"""
        )
        await conn.execute("DROP TABLE agent_skills")
        await conn.commit()

    # Idempotent migrations on existing DBs
    async with conn.execute("PRAGMA table_info(users)") as cur:
        user_cols = {row["name"] async for row in cur}
    if "email" not in user_cols:
        await conn.execute("ALTER TABLE users ADD COLUMN email TEXT NOT NULL DEFAULT ''")
    # Migrate legacy 'consultant' role to 'sysadmin'
    await conn.execute("UPDATE users SET role='sysadmin' WHERE role='consultant'")
    await conn.commit()

    # Column upgrades for existing system databases: CREATE TABLE IF NOT EXISTS above does
    # nothing once the table already exists, so new columns need an explicit ALTER TABLE.
    for table, column, decl in (
        ("users", "is_sys_admin", "INTEGER NOT NULL DEFAULT 0"),
        ("project_memberships", "stakeholder_id", "INTEGER"),
    ):
        cur = await conn.execute(f"PRAGMA table_info({table})")
        if column not in {row[1] for row in await cur.fetchall()}:
            await conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {decl}")
    await conn.commit()

    # The home organisation, seeded here rather than left to an operator step.
    #
    # check_project_access resolves a non-sysadmin org_admin by comparing the JWT's org_id to
    # the project_registry row for the slug, and falls through to 403 when there is no row. On
    # the live deployment both organisations and project_registry held zero rows, which was
    # harmless only because the sole account was a sysadmin and returns before the registry is
    # consulted at all - the first org_admin ever appointed would have been locked out of every
    # project in the system, with project_memberships looking perfectly correct throughout.
    #
    # This belongs here, and not in the backfill script or an operator runbook step, because
    # the defect was self-reinforcing: nothing created the data and nothing ever would. A fix
    # that depends on somebody remembering to run something re-creates that same hole on the
    # next fresh deployment. init_system_db is idempotent, has no version gate, and runs on
    # every system connection, so seeding here makes "there is an organisation to register
    # against" total rather than conditional - and INSERT OR IGNORE keys on the slug, so an
    # operator renaming the organisation through PATCH /auth/orgs/{id} is not overwritten on
    # the next connection.
    settings = get_settings()
    await conn.execute(
        "INSERT OR IGNORE INTO organisations (slug, name) VALUES (?,?)",
        (settings.home_org_slug, settings.home_org_name),
    )
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


# ── skills library ─────────────────────────────────────────────────────────────

async def insert_skill(
    conn: aiosqlite.Connection,
    *,
    name: str,
    description: str,
    source: str = "manual",
    source_project: str | None = None,
    agents: list[str] | None = None,
    flag_reason: str | None = None,
    flag_suggestion: str | None = None,
) -> int:
    cur = await conn.execute(
        """INSERT INTO skills (name, description, source, source_project, flag_reason, flag_suggestion)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (name, description, source, source_project, flag_reason, flag_suggestion),
    )
    skill_id = cur.lastrowid
    if agents:
        await conn.executemany(
            "INSERT OR IGNORE INTO agent_skill_assignments (skill_id, agent_name) VALUES (?, ?)",
            [(skill_id, a) for a in agents],
        )
    await conn.commit()
    return skill_id


async def fetch_skills(
    conn: aiosqlite.Connection,
    *,
    agent_name: str | None = None,
    status: str | None = None,
) -> list[dict]:
    where: list[str] = []
    params: list = []
    if status is not None:
        where.append("s.status = ?")
        params.append(status)
    if agent_name is not None:
        where.append("s.id IN (SELECT skill_id FROM agent_skill_assignments WHERE agent_name = ?)")
        params.append(agent_name)
    where_sql = ("WHERE " + " AND ".join(where)) if where else ""
    query = f"""
        SELECT s.*, GROUP_CONCAT(asa.agent_name, '|') AS agents_csv
        FROM skills s
        LEFT JOIN agent_skill_assignments asa ON asa.skill_id = s.id
        {where_sql}
        GROUP BY s.id
        ORDER BY s.created_at DESC
    """
    rows: list[dict] = []
    async with conn.execute(query, params) as cur:
        async for row in cur:
            d = dict(row)
            csv = d.pop("agents_csv", None) or ""
            d["agents"] = [a for a in csv.split("|") if a]
            rows.append(d)
    return rows


async def update_skill(
    conn: aiosqlite.Connection,
    *,
    skill_id: int,
    status: str | None = None,
    name: str | None = None,
    description: str | None = None,
    reviewed_by: str | None = None,
    agents: list[str] | None = None,
) -> bool:
    updates: list[str] = []
    params: list = []
    if name is not None:
        updates.append("name = ?"); params.append(name)
    if description is not None:
        updates.append("description = ?"); params.append(description)
    if status is not None:
        updates.append("status = ?"); params.append(status)
        updates.append("reviewed_at = CURRENT_TIMESTAMP")
    if reviewed_by is not None:
        updates.append("reviewed_by = ?"); params.append(reviewed_by)
    changed = False
    if updates:
        params.append(skill_id)
        cur = await conn.execute(f"UPDATE skills SET {', '.join(updates)} WHERE id = ?", params)
        changed = cur.rowcount > 0
    if agents is not None:
        await conn.execute("DELETE FROM agent_skill_assignments WHERE skill_id = ?", (skill_id,))
        if agents:
            await conn.executemany(
                "INSERT OR IGNORE INTO agent_skill_assignments (skill_id, agent_name) VALUES (?, ?)",
                [(skill_id, a) for a in agents],
            )
        changed = True
    await conn.commit()
    return changed


async def delete_skill(conn: aiosqlite.Connection, *, skill_id: int) -> bool:
    await conn.execute("DELETE FROM agent_skill_assignments WHERE skill_id = ?", (skill_id,))
    cur = await conn.execute("DELETE FROM skills WHERE id = ?", (skill_id,))
    await conn.commit()
    return cur.rowcount > 0


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
    """Returns True if inserted, False if username already exists.

    is_sys_admin is derived from the role rather than passed in, because it is not
    independent of it and nothing was setting it: every account created through
    POST /admin/users got role='sysadmin' with is_sys_admin=0, and behaved differently
    under caller_roles - which reads only the column - from one set up by hand. Two
    sysadmins, same role string, different authority, nothing on either row to say why.
    """
    try:
        await conn.execute(
            "INSERT INTO users (username, email, role, hashed_pw, project_slug, is_sys_admin)"
            " VALUES (?,?,?,?,?,?)",
            (username, email, role, hashed_pw, project_slug, 1 if role == "sysadmin" else 0),
        )
        await conn.commit()
        return True
    except aiosqlite.IntegrityError:
        return False


# ── Stakeholder Assignments ───────────────────────────────────────────────────

async def fetch_stakeholder_assignments(
    conn: aiosqlite.Connection, *, project_id: int
) -> list[dict]:
    """Return every assignment held by the project, ordered by id.

    Keyed on the project, so this answers before the first orchestration run and still
    answers after the tenth.
    """
    async with conn.execute(
        "SELECT * FROM stakeholder_assignments WHERE project_id=? ORDER BY id",
        (project_id,),
    ) as cur:
        return [dict(r) async for r in cur]


async def replace_stakeholder_assignments(
    conn: aiosqlite.Connection,
    *,
    project_id: int,
    assignments: list[dict],
) -> int:
    """Replace the project's whole mapping. Returns the number of rows stored.

    Each item needs `stakeholder_id` and `node_id`. An empty list is accepted and clears
    the mapping - removing the last assignment is a legitimate edit of a durable fact,
    not a malformed request.

    Repeated pairs in one payload collapse to one row; different stakeholders on one node,
    and one stakeholder across several nodes, are both kept, because many-to-many is the
    whole point.
    """
    await conn.execute(
        "DELETE FROM stakeholder_assignments WHERE project_id=?", (project_id,)
    )
    seen: set[tuple[int, str]] = set()
    for a in assignments:
        pair = (a["stakeholder_id"], a["node_id"])
        if pair in seen:
            continue
        seen.add(pair)
        await conn.execute(
            "INSERT INTO stakeholder_assignments (project_id, stakeholder_id, node_id)"
            " VALUES (?,?,?)",
            (project_id, pair[0], pair[1]),
        )
    await conn.commit()
    return len(seen)


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
    script_id: str | None = None,
) -> int:
    cur = await conn.execute(
        "INSERT INTO interview_sessions "
        "(project_id, orchestration_run_id, stakeholder_id, node_label, session_token,"
        " voice_config, script_id) "
        "VALUES (?,?,?,?,?,?,?)",
        (project_id, orchestration_run_id, stakeholder_id, node_label, session_token,
         voice_config, script_id),
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


async def fetch_interview_sessions_status_for_project(
    conn: aiosqlite.Connection, *, project_id: int
) -> dict:
    """Return counts of sessions by status across every orchestration run for a project.

    `fetch_interview_sessions_status` scopes to a single orchestration run, but
    `orchestration_run_id` is nullable on `interview_sessions` and a project can have run more
    than one campaign. A caller asking "does this project have live interviews right now?" - the
    standalone Synthesis Analyst guard - needs the project-wide answer, not one run's slice of it.
    """
    counts = {"pending": 0, "active": 0, "completed": 0, "abandoned": 0}
    async with conn.execute(
        "SELECT status, COUNT(*) as n FROM interview_sessions "
        "WHERE project_id=? GROUP BY status",
        (project_id,),
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


async def fetch_organisation_by_slug(
    conn: aiosqlite.Connection, *, slug: str
) -> dict | None:
    async with conn.execute("SELECT * FROM organisations WHERE slug=?", (slug,)) as cur:
        row = await cur.fetchone()
        return dict(row) if row else None


async def resolve_home_org_id(conn: aiosqlite.Connection) -> int | None:
    """The organisation this installation's engagements belong to, or None.

    Resolved by `home_org_slug` and by nothing else. Deliberately *not* "the only row", and
    deliberately not the lowest id: both would silently change answer the moment a second
    organisation is created through POST /auth/orgs, and the wrong answer here hands an
    unrelated organisation's admin a real engagement rather than merely failing.

    None is reachable only if the row has been deleted through DELETE /auth/orgs/{id} on a
    connection that was opened before the delete - init_system_db re-seeds it on the next one -
    so callers treat it as "cannot register yet", never as "pick something else".
    """
    org = await fetch_organisation_by_slug(conn, slug=get_settings().home_org_slug)
    return org["id"] if org else None


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


async def fetch_user_org_ids(conn: aiosqlite.Connection, *, user_id: int) -> list[int]:
    """Every organisation this login belongs to.

    `fetch_user_org` below answers with the *first* row, on the stated convention that a user
    belongs to one organisation - which is true by convention and not by constraint: nothing
    stops a second `org_memberships` row, and `POST /auth/orgs/{org_id}/members` is a door
    that adds one. That makes "the first row" an arbitrary choice among several, which is
    fine for embedding an org_id in a session and not fine for an authority decision: an
    account with two memberships would be administrable by whichever organisation's row
    happened to sort first. `_assert_may_administer` asks this instead, and requires the
    caller's organisation to be the *only* one.
    """
    async with conn.execute(
        "SELECT org_id FROM org_memberships WHERE user_id=? ORDER BY org_id", (user_id,)
    ) as cur:
        return [row["org_id"] async for row in cur]


async def fetch_user_org(conn: aiosqlite.Connection, *, user_id: int) -> dict | None:
    """Return the first org_membership row for this user (users belong to one org).

    For session issuance, not for authority - see fetch_user_org_ids above."""
    async with conn.execute(
        "SELECT * FROM org_memberships WHERE user_id=? LIMIT 1", (user_id,)
    ) as cur:
        row = await cur.fetchone()
        return dict(row) if row else None


# ── Project registry helpers ──────────────────────────────────────────────────

async def insert_project_registry(
    conn: aiosqlite.Connection, *, slug: str, org_id: int, display_name: str
) -> None:
    """Assign a slug to an organisation, replacing any assignment it already had.

    An upsert, not `INSERT OR IGNORE`. This is what `POST /auth/projects` calls, and that door
    exists so an operator can say which organisation owns an engagement. Now that project
    creation registers *every* project rather than only an org_admin's, on-conflict-ignore
    would have made that door a permanent no-op: every slug already has a row, so the operator's
    correction would return 201 and change nothing - the silent kind of failure, and on the
    table that decides who reaches which engagement.

    Registration at creation deliberately does not come through here; it uses
    `register_project_if_unregistered`, so re-POSTing an existing slug cannot drag an
    engagement back out of the organisation an operator moved it to.

    An empty `display_name` leaves the stored one alone rather than blanking it. The door's
    request model defaults `display_name` to `""`, so reassigning a project to another
    organisation - which is the whole point of the door - would otherwise wipe a curated name
    as a side effect, and `OrgDetail.tsx` would start showing the slug. Empty means "not
    specified" here, not "set it to empty"; clearing a name is not something this door offers.
    """
    await conn.execute(
        "INSERT INTO project_registry (slug, org_id, display_name) VALUES (?,?,?)"
        " ON CONFLICT(slug) DO UPDATE SET org_id=excluded.org_id,"
        " display_name=CASE WHEN excluded.display_name = '' THEN project_registry.display_name"
        "                   ELSE excluded.display_name END",
        (slug, org_id, display_name),
    )
    await conn.commit()


async def register_project_if_unregistered(
    conn: aiosqlite.Connection, *, slug: str, org_id: int, display_name: str
) -> bool:
    """Give a slug an organisation only if it has none. Returns True if a row was written.

    The creation path's verb. `POST /projects` answers 200 rather than 409 on an existing
    slug, so it is also the repair path for a project that predates registration - and it must
    not double as a way to reassign one.
    """
    cur = await conn.execute(
        "INSERT OR IGNORE INTO project_registry (slug, org_id, display_name) VALUES (?,?,?)",
        (slug, org_id, display_name),
    )
    await conn.commit()
    return cur.rowcount > 0


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


async def link_membership(
    conn: aiosqlite.Connection, *, user_id: int, project_slug: str, stakeholder_id: int
) -> None:
    """Point a login at the person record it is on this project.

    Upserts on the existing UNIQUE(user_id, project_slug): a person has one membership per
    engagement, and re-linking corrects it rather than creating a second.
    """
    await conn.execute(
        "INSERT INTO project_memberships (user_id, project_slug, stakeholder_id)"
        " VALUES (?,?,?)"
        " ON CONFLICT(user_id, project_slug) DO UPDATE SET stakeholder_id=excluded.stakeholder_id",
        (user_id, project_slug, stakeholder_id),
    )
    await conn.commit()


async def delete_project_membership(
    conn: aiosqlite.Connection, *, user_id: int, project_slug: str
) -> None:
    await conn.execute(
        "DELETE FROM project_memberships WHERE user_id=? AND project_slug=?",
        (user_id, project_slug),
    )
    await conn.commit()


async def delete_project_membership_by_stakeholder(
    conn: aiosqlite.Connection, *, project_slug: str, stakeholder_id: int
) -> int:
    """Unlink whatever login this project's stakeholder row is reached through.

    The exact inverse of link_membership, and keyed the same way. Deliberately not
    expressed as "look the email up in users, then delete_project_membership": the
    stakeholder's email may have been edited since the invite was accepted, in which case
    it no longer matches the users row that membership actually points at, and the
    revocation would find nothing and report success. stakeholder_id is the link
    caller_roles walks, so it is the link revocation has to cut.

    A membership granted by an administrator through /admin (insert_project_membership)
    carries a NULL stakeholder_id and is untouched by this - it was never a consequence
    of a stakeholder's role flags, so clearing those flags must not withdraw it.

    Returns the number of memberships removed, so a caller can tell "revoked" from
    "there was nothing to revoke".
    """
    cur = await conn.execute(
        "DELETE FROM project_memberships WHERE project_slug=? AND stakeholder_id=?",
        (project_slug, stakeholder_id),
    )
    await conn.commit()
    return cur.rowcount or 0


async def fetch_user_project_memberships(
    conn: aiosqlite.Connection, *, user_id: int
) -> list[dict]:
    async with conn.execute(
        "SELECT * FROM project_memberships WHERE user_id=? ORDER BY project_slug",
        (user_id,),
    ) as cur:
        return [dict(r) async for r in cur]


async def fetch_project_memberships(
    conn: aiosqlite.Connection, *, project_slug: str
) -> list[dict]:
    """Every login on this project, with the stakeholder row it is that person through.

    `stakeholder_id` is kept even when NULL, and that is the point rather than an oversight:
    a NULL is a membership `insert_project_membership` wrote - the /admin access grant - and
    the account is genuinely on the project, so it belongs in a project-scoped user list. It
    simply has no person record behind it (see `delete_project_membership_by_stakeholder`
    for the other consequence of that distinction). Filtering NULLs here would drop the
    account from the list rather than drop its name, which is a different and wrong answer.

    One query for the whole project rather than one per user: the caller is rendering a
    table, and a per-row read here becomes a per-row database open in `user_identity.py`.
    """
    async with conn.execute(
        "SELECT user_id, stakeholder_id FROM project_memberships WHERE project_slug=?",
        (project_slug,),
    ) as cur:
        return [dict(r) async for r in cur]


async def fetch_project_login_emails(
    conn: aiosqlite.Connection, *, project_slug: str
) -> set[str]:
    """Every login username that reaches THIS project through a membership.

    The set form of the question `has_project_membership` answers one user at a time, for
    the read model that has to answer it for a whole stakeholder list at once - one join
    rather than two queries per row.

    Scoped to the slug, and that scoping is the security property rather than an
    optimisation: "does this address have a login anywhere" would turn any project
    administrator's stakeholder list into an account-existence oracle over arbitrary
    addresses, which is what `/auth/reset-request`'s always-204 contract exists to prevent.
    Per-project linkage is something the caller already knows by other means.

    Usernames are returned verbatim. `users.username` is TEXT UNIQUE under SQLite's binary
    collation, so `fetch_user` distinguishes casings - a caller comparing case-insensitively
    here would report a login the write doors would not find.
    """
    async with conn.execute(
        "SELECT u.username FROM project_memberships m"
        " JOIN users u ON u.id = m.user_id"
        " WHERE m.project_slug=?",
        (project_slug,),
    ) as cur:
        return {row[0] async for row in cur}


async def fetch_open_invite_emails(
    conn: aiosqlite.Connection, *, project_slug: str
) -> set[str]:
    """Every address holding an unredeemed invite to this project.

    Unredeemed, not unexpired: `reissue_invite` selects on `used_at IS NULL` alone and
    refreshes the expiry as it mints the new token, so an invite that has timed out is
    still one a resend can revive. Matching its WHERE clause is what keeps "shown as
    invited" and "a resend would succeed" the same set - a state read that excluded expired
    rows would hide the action from exactly the people who need it most.
    """
    async with conn.execute(
        "SELECT email FROM auth_tokens"
        " WHERE project_slug=? AND purpose='invite' AND used_at IS NULL",
        (project_slug,),
    ) as cur:
        return {row[0] async for row in cur}


# ── Reply tokens: the routing key in a participant's reply address ────────────
#
# Raw tokens never appear here. `api/services/outbound_mail.py` derives one and hands
# down its digest; these helpers know nothing but the digest, which is the whole point -
# a copy of this table, a backup of it, or a stray SELECT into a log yields no working
# address.

async def fetch_reply_token(
    conn: aiosqlite.Connection, *, project_slug: str, stakeholder_id: int
) -> dict | None:
    """The reply-token row for this person on this project, live or revoked.

    Revoked rows are returned rather than filtered, because the caller minting a
    replacement needs the `issue` it must climb past. Resolution uses
    `fetch_reply_token_by_hash`, which does filter.
    """
    async with conn.execute(
        "SELECT * FROM reply_tokens WHERE project_slug=? AND stakeholder_id=?",
        (project_slug, stakeholder_id),
    ) as cur:
        row = await cur.fetchone()
    return dict(row) if row else None


async def fetch_reply_token_by_hash(
    conn: aiosqlite.Connection, *, token_hash: str
) -> dict | None:
    """The live row carrying this digest, or None.

    A single indexed equality lookup - `token_hash` is UNIQUE, so the constraint's index
    serves it - for the same reason `invite_service` hashes with sha256 rather than
    bcrypt: this runs on an unauthenticated inbound path, and a scan there is a denial of
    service wearing a lookup's clothes.

    Costs the same whether or not the digest is present, which is what keeps an unknown
    token from being distinguishable from a known one by how long the answer took.
    """
    async with conn.execute(
        "SELECT * FROM reply_tokens WHERE token_hash=? AND revoked_at IS NULL",
        (token_hash,),
    ) as cur:
        row = await cur.fetchone()
    return dict(row) if row else None


async def upsert_reply_token(
    conn: aiosqlite.Connection,
    *,
    project_slug: str,
    stakeholder_id: int,
    token_hash: str,
    issue: int,
) -> None:
    """Write the live digest for this person on this project.

    On conflict the row is *replaced*, not left alone: the conflicting row is the revoked
    predecessor being rotated past, and overwriting its `token_hash` is what takes the
    revoked address out of the table entirely rather than leaving a refused row behind
    that a later change could accidentally start honouring again.
    """
    await conn.execute(
        "INSERT INTO reply_tokens (project_slug, stakeholder_id, token_hash, issue)"
        " VALUES (?,?,?,?)"
        " ON CONFLICT(project_slug, stakeholder_id) DO UPDATE SET"
        " token_hash=excluded.token_hash, issue=excluded.issue,"
        " revoked_at=NULL, created_at=CURRENT_TIMESTAMP",
        (project_slug, stakeholder_id, token_hash, issue),
    )
    await conn.commit()


async def mark_reply_token_revoked(
    conn: aiosqlite.Connection, *, project_slug: str, stakeholder_id: int
) -> bool:
    """Stop this person's reply address routing. Returns whether a live row was revoked."""
    cur = await conn.execute(
        "UPDATE reply_tokens SET revoked_at=CURRENT_TIMESTAMP"
        " WHERE project_slug=? AND stakeholder_id=? AND revoked_at IS NULL",
        (project_slug, stakeholder_id),
    )
    await conn.commit()
    return (cur.rowcount or 0) > 0


async def record_sent_message(
    conn: aiosqlite.Connection,
    *,
    provider_message_id: str,
    project_slug: str,
    stakeholder_id: int,
) -> None:
    """Remember which person a sent message was about, by the provider's id for it.

    `INSERT OR REPLACE` rather than a plain insert: the id comes from outside, and a
    provider that ever repeated one must not turn a successful send into an exception
    after the message has already gone.
    """
    await conn.execute(
        "INSERT OR REPLACE INTO sent_messages"
        " (provider_message_id, project_slug, stakeholder_id) VALUES (?,?,?)",
        (provider_message_id, project_slug, stakeholder_id),
    )
    await conn.commit()


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
    """is_sys_admin moves with the role for the same reason insert_user derives it: it is
    a projection of the role, not a second fact about the account. Setting it only at
    creation would fix the divergence for new accounts and leave it wide open on the one
    edit that can introduce it - promoting somebody to sysadmin through PUT /admin/users."""
    is_sys_admin = 1 if role == "sysadmin" else 0
    if hashed_pw:
        await conn.execute(
            "UPDATE users SET email=?, role=?, hashed_pw=?, is_sys_admin=? WHERE id=?",
            (email, role, hashed_pw, is_sys_admin, user_id),
        )
    else:
        await conn.execute(
            "UPDATE users SET email=?, role=?, is_sys_admin=? WHERE id=?",
            (email, role, is_sys_admin, user_id),
        )
    await conn.commit()


async def delete_user(conn: aiosqlite.Connection, *, user_id: int) -> None:
    await conn.execute("DELETE FROM users WHERE id=?", (user_id,))
    await conn.commit()


# ── Scheduled jobs ────────────────────────────────────────────────────────────

async def upsert_scheduled_job(
    conn: aiosqlite.Connection, *, job_name: str, slug: str, next_due_at: str
) -> None:
    """Register a job, leaving an existing row's schedule untouched.

    Called on every boot, so it must not reset the next due time of a job that is
    already scheduled - otherwise a restart would postpone every job.
    """
    await conn.execute(
        "INSERT INTO scheduled_jobs (job_name, slug, next_due_at) VALUES (?,?,?) "
        "ON CONFLICT(job_name, slug) DO NOTHING",
        (job_name, slug, next_due_at),
    )
    await conn.commit()


async def fetch_due_jobs(conn: aiosqlite.Connection, *, now_iso: str) -> list[dict]:
    """Jobs whose next_due_at has passed and which are not already running."""
    async with conn.execute(
        "SELECT * FROM scheduled_jobs WHERE next_due_at <= ? AND status != 'running' "
        "ORDER BY next_due_at",
        (now_iso,),
    ) as cur:
        return [dict(row) for row in await cur.fetchall()]


async def fetch_platform_public_url(conn: aiosqlite.Connection) -> str:
    """The stored public_url, raw - `''` when nothing has been saved through the door yet.

    Deliberately *not* the resolved value: the fallback to the PUBLIC_URL environment
    variable is stated once, in api.services.platform_settings.platform_public_url(), and a
    second helper that folded it in here would be a second place for the precedence rule to
    drift. This one answers only "what is in the table".
    """
    async with conn.execute(
        "SELECT public_url FROM platform_settings WHERE id = 1"
    ) as cur:
        row = await cur.fetchone()
    return row["public_url"] if row else ""


async def store_platform_public_url(conn: aiosqlite.Connection, public_url: str) -> None:
    """Save the platform's public_url. Singleton upsert, like the heartbeat below.

    Takes the value already normalised - api.services.platform_settings.normalise_public_url
    owns the rules about what a public URL may be, and this helper must not become a second
    opinion on them.
    """
    await conn.execute(
        "INSERT INTO platform_settings (id, public_url, updated_at) "
        "VALUES (1, ?, CURRENT_TIMESTAMP) "
        "ON CONFLICT(id) DO UPDATE SET public_url=excluded.public_url, "
        "updated_at=excluded.updated_at",
        (public_url,),
    )
    await conn.commit()


async def record_scheduler_heartbeat(conn: aiosqlite.Connection, *, now_iso: str) -> None:
    """Stamp the scheduler's liveness.

    The heartbeat means "the loop is cycling", not "the last job succeeded" - the
    caller stamps it even on a pass where a job raised.
    """
    await conn.execute(
        "INSERT INTO scheduler_heartbeat (id, last_tick_at) VALUES (1, ?) "
        "ON CONFLICT(id) DO UPDATE SET last_tick_at=excluded.last_tick_at",
        (now_iso,),
    )
    await conn.commit()


async def fetch_scheduler_heartbeat(conn: aiosqlite.Connection) -> str | None:
    """The last tick timestamp, or None when the scheduler has never ticked."""
    async with conn.execute(
        "SELECT last_tick_at FROM scheduler_heartbeat WHERE id = 1"
    ) as cur:
        row = await cur.fetchone()
    return row["last_tick_at"] if row else None


async def mark_job_running(
    conn: aiosqlite.Connection, *, job_name: str, slug: str, now_iso: str
) -> bool:
    """Claim a job. Returns False when another claim already holds it.

    The status guard in the WHERE clause is what makes the claim atomic.
    """
    cur = await conn.execute(
        "UPDATE scheduled_jobs SET status='running', last_run_at=? "
        "WHERE job_name=? AND slug=? AND status != 'running'",
        (now_iso, job_name, slug),
    )
    await conn.commit()
    return cur.rowcount > 0


async def mark_job_finished(
    conn: aiosqlite.Connection, *, job_name: str, slug: str, status: str,
    next_due_at: str, last_error: str = "",
) -> None:
    await conn.execute(
        "UPDATE scheduled_jobs SET status=?, next_due_at=?, last_error=? "
        "WHERE job_name=? AND slug=?",
        (status, next_due_at, last_error, job_name, slug),
    )
    await conn.commit()


async def reset_stale_running_jobs(conn: aiosqlite.Connection) -> int:
    """On startup, reset any scheduled_jobs rows left in 'running'.

    A row stuck in 'running' is orphaned by a previous process death - power
    cut, SIGKILL, operator restart, or mark_job_finished itself raising. Since
    fetch_due_jobs excludes 'running' rows and nothing else ever clears the
    status, that project's job would otherwise never run again.

    next_due_at is left untouched so an overdue job runs on the next tick
    rather than being postponed a day. Mirrors _mark_stale_runs_failed's
    treatment of crew_runs.
    """
    cur = await conn.execute(
        "UPDATE scheduled_jobs SET status='idle', last_error=? "
        "WHERE status='running'",
        ("interrupted by a restart",),
    )
    await conn.commit()
    return cur.rowcount
