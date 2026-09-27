# tests/test_interview_recogniser_provenance.py
"""Which engine produced each answer, recorded on the answer.

Two live interviews were transcribed end to end by the browser's fallback while every surface
this product owns reported success. The only way anybody found out was opening the provider's
console, and what settled it there was the account's usage for the whole day being one second of
an operator's own test tone. Nothing in this system could answer "was this interview transcribed
by the engine we configured?".

These assert the two halves that make the answer durable: the column reaches databases that
already exist, and what lands in it is what the page reported rather than what the door was
handed.
"""
import aiosqlite
import pytest

from api.services.interview_answer_service import RECOGNISERS, _recogniser_of


@pytest.mark.asyncio
async def test_a_database_at_version_22_gains_the_recogniser_column(tmp_path, monkeypatch):
    """The bump, not the migration.

    `_migrate_interview_answers` has been in the block for a long time, so a fresh file gets the
    column from its `CREATE TABLE` whatever the constant says - and every deployment that has
    ever been opened is not a fresh file. `get_connection` re-runs the block only while
    `user_version < _SCHEMA_VERSION`, so without the bump this column appears on nobody's
    existing database, silently and for ever.

    **The literal 22 is the version immediately below the constant and is renumbered with it.**
    An older number would pass under any constant above it and would therefore test nothing
    about this change; `_SCHEMA_VERSION - 1` would pass under a constant that never moved.

    Fails on _SCHEMA_VERSION = 22 and passes on 23.
    """
    monkeypatch.setenv("DATABASE_DIR", str(tmp_path))
    from api.config import get_settings
    get_settings.cache_clear()
    try:
        from api.database import _MIGRATED, get_connection, get_db_path

        slug = "answers-provenance-upgrade"
        async with get_connection(slug) as conn:
            await conn.execute("DROP TABLE IF EXISTS interview_answers")
            await conn.commit()
        # Stand in for the real case: a database migrated before this change existed.
        _MIGRATED.discard(slug)
        async with aiosqlite.connect(get_db_path(slug)) as raw:
            await raw.execute("PRAGMA user_version = 22")
            await raw.commit()

        async with get_connection(slug) as conn:
            cur = await conn.execute("PRAGMA table_info(interview_answers)")
            cols = {r[1] for r in await cur.fetchall()}
        assert "recogniser" in cols, "the migration did not reach an existing database"
    finally:
        get_settings.cache_clear()


@pytest.mark.asyncio
async def test_the_column_is_added_to_a_table_that_already_holds_rows(tmp_path, monkeypatch):
    """An `ALTER` on a populated table, which is every real deployment.

    The rows already there answer `''` - "not recorded" - rather than being guessed at. Every
    answer captured before this change was written by a page that did not know which engine it
    had used, and inventing one for them would put a fact in front of an operator that nobody
    established. This is the direction that matters: the interviews which prompted the work are
    exactly the rows that must **not** claim a recogniser.
    """
    monkeypatch.setenv("DATABASE_DIR", str(tmp_path))
    from api.config import get_settings
    get_settings.cache_clear()
    try:
        from api.database import _MIGRATED, get_connection, get_db_path

        slug = "answers-provenance-populated"
        async with get_connection(slug) as conn:
            await conn.execute("DROP TABLE IF EXISTS interview_answers")
            await conn.execute("""
                CREATE TABLE interview_answers (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id INTEGER NOT NULL, stakeholder_id INTEGER NOT NULL,
                    script_id TEXT NOT NULL, section_id TEXT NOT NULL,
                    question_id TEXT NOT NULL, question_text TEXT NOT NULL,
                    answer_text TEXT NOT NULL DEFAULT '', answered INTEGER NOT NULL DEFAULT 1,
                    follow_up INTEGER NOT NULL DEFAULT 0, node_id TEXT NOT NULL,
                    node_label TEXT NOT NULL DEFAULT '', chain TEXT, level TEXT NOT NULL,
                    relationship TEXT NOT NULL, party_id TEXT, discipline TEXT NOT NULL,
                    question_intent TEXT NOT NULL, elicitation TEXT NOT NULL, rating INTEGER,
                    answered_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            """)
            await conn.execute(
                "INSERT INTO interview_answers (session_id, stakeholder_id, script_id, "
                "section_id, question_id, question_text, answer_text, node_id, level, "
                "relationship, discipline, question_intent, elicitation) VALUES "
                "(1, 1, 'SC-014', 'S1', 'q1', 'What slows connections down?', 'Permits.', "
                "'2.1', 'L2', 'internal', 'ops', 'explore', 'open')")
            await conn.commit()
        _MIGRATED.discard(slug)
        async with aiosqlite.connect(get_db_path(slug)) as raw:
            await raw.execute("PRAGMA user_version = 22")
            await raw.commit()

        async with get_connection(slug) as conn:
            cur = await conn.execute(
                "SELECT answer_text, recogniser FROM interview_answers")
            rows = await cur.fetchall()
        assert [tuple(r) for r in rows] == [("Permits.", "")]
    finally:
        get_settings.cache_clear()


@pytest.mark.parametrize("engine", sorted(RECOGNISERS))
def test_every_engine_the_page_can_report_is_stored(engine):
    """The whole declared vocabulary round-trips.

    Parametrised over the constant rather than over a list written here, so an engine added to
    the vocabulary and not to the sanitiser fails rather than being silently dropped to `''`.
    """
    assert _recogniser_of({"recogniser": engine}) == engine


@pytest.mark.parametrize("claimed", ["", "  ", "whisper", "<script>", "deepgram; DROP", None])
def test_anything_outside_the_vocabulary_is_recorded_as_not_recorded(claimed):
    """Sanitised rather than trusted.

    `PATCH /{token}/complete` is unauthenticated - a session token is the whole of what it
    checks - and this string is read back by an operator deciding whether an interview can be
    relied on. The same rule `SpeechFailureBody.reason` follows one model over.

    **`''` and not a refusal**: the answers matter more than their provenance, and a door that
    422'd an interview's whole completion over an unknown engine name would lose the evidence to
    protect the label on it.
    """
    assert _recogniser_of({"recogniser": claimed}) == ""


def test_an_older_client_that_sends_nothing_is_not_guessed_at():
    """An absent key is "not recorded", never a default engine.

    Defaulting to `browser` would be the more likely guess and it is still a guess - and the
    rows it would mislabel are the ones from before this existed, which is precisely the set an
    operator would be auditing.
    """
    assert _recogniser_of({}) == ""


def test_none_is_a_claim_and_is_kept_apart_from_not_recorded():
    """"Nothing listened" and "nobody wrote it down" are different findings.

    An empty answer under `none` is a transcription failure; an empty answer under `''` is an
    interview this build cannot say anything about. Collapsing them would hide the first inside
    the second, which is the shape of the defect that started this work.
    """
    assert _recogniser_of({"recogniser": "none"}) == "none"
    assert _recogniser_of({"recogniser": ""}) == ""
