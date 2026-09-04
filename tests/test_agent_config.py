# tests/test_agent_config.py
"""Per-project agent configuration, and the defaults that win when it is absent.

The first completed interview on this system used the wrong voice, and the third of the three
broken links was a default declared inside a React component: `DEFAULT_VOICE_CONFIG` in
`ui/src/pages/VoiceInterview.tsx`, holding `21m00Tcm4TlvDq8ikWAM` - ElevenLabs' stock *Rachel*,
a female voice - for an interviewer described as male everywhere he is described at all. The
voice heard was not a fallback for Avery's; it was a hardcoded stranger.

**The control comes first, and it is the reason this file is ordered the way it is.** An
implementation that resolved nothing at all - that returned the row and no defaults - would pass
every override test below by returning the override, and would fail silently on every project
that had not been configured, which is all of them. Testing the override arm without the default
arm asserts the half that cannot break.

The two arms are asserted separately throughout, and per field: resolution is per field, so
"a project may set a voice without setting a name" is a property to drive rather than a sentence
to trust.
"""
import sqlite3

import httpx
import pytest

from agents.identity import AGENT_IDENTITY, AVERY_VOICE_ID, DEFAULT_TTS_MODEL_ID
from api.config import get_settings
from api.database import (
    get_connection,
    fetch_agent_config,
    insert_project,
    upsert_agent_config,
)
from api.services.agent_config_service import (
    CONFIG_FIELDS,
    UnknownAgent,
    agent_defaults,
    resolve_agent_config,
)

# ElevenLabs' stock Rachel. Named here so the tests below can say "not this" without reading it
# back out of the source they are checking, which would make the assertion unfalsifiable.
RACHEL = "21m00Tcm4TlvDq8ikWAM"

# ElevenLabs' stock George, and the *fifth* declaration - the one `TestInterviewDialog.tsx`
# passed explicitly on every rehearsal call, so the server's corrected default was unreachable
# and Avery rehearsed in a voice no configuration named.
GEORGE = "JBFqnCBsd6RMkjVDRZzb"

AVERY = "stakeholder_interviewer"


def _code_lines(text: str) -> str:
    """The source with `//` comment lines removed.

    Prose naming a wrong id is the record of the defect and is why these comments are worth
    reading; code naming it is the defect. The guards below assert about the second.
    """
    return "\n".join(line for line in text.splitlines() if not line.lstrip().startswith("//"))


def _capture_tts(monkeypatch) -> list[dict]:
    """Point `synthesise`'s HTTP client at an `httpx.MockTransport` and record every request.

    Reading the real request rather than swapping the client class, following the rule
    CLAUDE.md records for the LLM seam: a test that mocks at the function boundary cannot see
    what actually goes on the wire, and "the value reached the call" is a weaker claim than
    "the value reached the request". No ElevenLabs call is made.
    """
    import json as _json

    seen: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append({"url": str(request.url), "json": _json.loads(request.content)})
        return httpx.Response(200, content=b"AUDIO-BYTES")

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    monkeypatch.setattr("api.services.interview_service.get_tts_client", lambda: client)

    settings = get_settings()
    monkeypatch.setattr(settings, "elevenlabs_api_key", "test-key", raising=False)
    monkeypatch.setattr(
        "api.services.interview_service.get_settings", lambda: settings
    )
    return seen


@pytest.fixture
def project_dir(tmp_path, monkeypatch):
    """An isolated DATABASE_DIR, per CLAUDE.md's poisoned-database rule.

    `get_settings.cache_clear()` on both sides: the settings object is cached, so a test that
    sets DATABASE_DIR without clearing reads the previous test's directory, and one that does
    not clear on the way out leaves tmp_path pointed at by a directory that no longer exists.
    """
    get_settings.cache_clear()
    monkeypatch.setenv("DATABASE_DIR", str(tmp_path))
    yield tmp_path
    get_settings.cache_clear()


def _only(**overrides) -> dict:
    """The six config fields, with everything not named explicitly set to None.

    `upsert_agent_config` requires all six precisely so a partial call cannot look like a
    no-op while clearing the rest, and this helper restates that rather than dodging it: the
    fields it fills with None are being cleared, which is what the tests using it mean.
    """
    fields = dict.fromkeys(CONFIG_FIELDS, None)
    unknown = set(overrides) - set(fields)
    assert not unknown, f"not config fields: {sorted(unknown)}"
    fields.update(overrides)
    return fields


async def _make_project(slug: str) -> int:
    """Create a real project database through the real path, and answer its project_id."""
    async with get_connection(slug) as conn:
        await insert_project(
            conn, slug=slug, llm_mode="standard", sector="test", config_json="{}"
        )
        async with conn.execute("SELECT id FROM projects WHERE slug=?", (slug,)) as cur:
            return (await cur.fetchone())["id"]


# --- The control ----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_project_with_no_configuration_resolves_every_default(project_dir):
    """The control. Every field, not only the one the defect was about.

    Asserting `display_name` alone would pass for an implementation that resolved the name and
    dropped the voice - which is the exact shape of the bug this task exists to fix, one field
    over.
    """
    slug = "control-project"
    await _make_project(slug)

    cfg = await resolve_agent_config(slug, AVERY)

    assert cfg["display_name"] == "Avery Singh"
    assert cfg["image_url"] == "/agents/avery-singh.jpg"
    assert cfg["voice_id"] == AVERY_VOICE_ID
    assert cfg["language"] == "en"
    assert cfg["country_code"] == "GB"
    assert set(cfg) == set(CONFIG_FIELDS)


@pytest.mark.asyncio
async def test_every_agent_resolves_a_default_name_and_locale(project_dir):
    """Not only Avery - the resolver answers for the whole roll.

    `AGENT_IDENTITY` is the roll of seventeen. A resolver that special-cased the interviewer
    would pass the control above and answer nothing for the other sixteen, which is precisely
    the special case the design refuses ("every agent gets the settings because the shape is the
    same and the alternative is a special case").
    """
    slug = "roll-project"
    await _make_project(slug)

    for agent_id, identity in AGENT_IDENTITY.items():
        cfg = await resolve_agent_config(slug, agent_id)
        assert cfg["display_name"] == identity.display_name, agent_id
        assert cfg["image_url"] == identity.image, agent_id
        assert cfg["language"] == "en", agent_id
        assert cfg["country_code"] == "GB", agent_id


@pytest.mark.asyncio
async def test_a_slug_with_no_database_resolves_the_defaults_and_creates_no_file(project_dir):
    """Probing a slug must not materialise one database file per guess.

    The rule `caller_roles` and `_stakeholder_matches_invite` already follow, and it reaches
    here because the resolved voice is read on the public interview path.
    """
    cfg = await resolve_agent_config("no-such-engagement", AVERY)

    assert cfg["display_name"] == "Avery Singh"
    assert not (project_dir / "no-such-engagement.db").exists()


@pytest.mark.asyncio
async def test_an_unknown_agent_id_is_refused_rather_than_resolved(project_dir):
    """A typo must not reach an interview as a nameless, voiceless interviewer."""
    slug = "unknown-agent-project"
    await _make_project(slug)

    with pytest.raises(UnknownAgent):
        await resolve_agent_config(slug, "stakeholder_interviewr")


@pytest.mark.parametrize("slug", ["", "   ", "\t"])
@pytest.mark.asyncio
async def test_a_blank_slug_is_refused_rather_than_answered(project_dir, slug):
    """A blank slug is a caller that *lost* one, not a project that does not exist.

    This seam answers it exactly as `project_llm_mode` does, and after being caught pointing
    the other way. There the same silent answer sent a sensitive engagement's interview answers
    to a hosted model, because the test dialog held the slug in its props and discarded it -
    which is the dialog this very task has just wired to send it. **Two seams disagreeing about
    what a blank slug means is worse than either rule**, so they agree.

    The unrecognised-slug arm is deliberately the opposite and is asserted separately above: a
    project that genuinely does not exist has no configuration and no secrets, and answering
    the defaults for it is what avoids materialising a database file per guess.
    """
    with pytest.raises(ValueError):
        await resolve_agent_config(slug, AVERY)


@pytest.mark.asyncio
async def test_the_synthesis_model_resolves_like_every_other_field(project_dir):
    """`model_id` is a configured field, carried ahead of need.

    Voice and language are separate axes - a voice's `verified_languages` names a model per
    language - so a project that picks a French voice and keeps an English model has configured
    half of what it meant. Every project is English today and the resolved answer never varies,
    which is the point: the column costs one field now rather than a second migration later.
    """
    slug = "model-project"
    project_id = await _make_project(slug)

    assert (await resolve_agent_config(slug, AVERY))["model_id"] == DEFAULT_TTS_MODEL_ID

    async with get_connection(slug) as conn:
        await upsert_agent_config(
            conn, project_id=project_id, agent_id=AVERY, **_only(model_id="eleven_multilingual_v2")
        )

    cfg = await resolve_agent_config(slug, AVERY)
    assert cfg["model_id"] == "eleven_multilingual_v2"
    # And it is still resolved per field: the voice was not touched.
    assert cfg["voice_id"] == AVERY_VOICE_ID


# --- The override arm -----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_configured_field_overrides_its_default(project_dir):
    slug = "override-project"
    project_id = await _make_project(slug)
    async with get_connection(slug) as conn:
        await upsert_agent_config(
            conn,
            project_id=project_id,
            agent_id=AVERY,
            display_name="Ade Okonkwo",
            image_url="/agents/ade-okonkwo.jpg",
            voice_id="VOICE-FROM-THE-PROJECT",
            language="fr",
            country_code="FR",
            model_id="MODEL-FROM-THE-PROJECT",
        )

    cfg = await resolve_agent_config(slug, AVERY)

    assert cfg["display_name"] == "Ade Okonkwo"
    assert cfg["image_url"] == "/agents/ade-okonkwo.jpg"
    assert cfg["voice_id"] == "VOICE-FROM-THE-PROJECT"
    assert cfg["language"] == "fr"
    assert cfg["country_code"] == "FR"


@pytest.mark.asyncio
async def test_a_project_may_set_a_voice_without_setting_a_name(project_dir):
    """Resolution is per field, and this is the assertion that says so.

    A resolver that took the row wholesale the moment one existed would answer `None` for the
    name here - so choosing a voice would silently erase a name nobody touched.
    """
    slug = "voice-only-project"
    project_id = await _make_project(slug)
    async with get_connection(slug) as conn:
        await upsert_agent_config(
            conn,
            project_id=project_id,
            agent_id=AVERY,
            display_name=None,
            image_url=None,
            voice_id="JUST-THE-VOICE",
            language=None,
            country_code=None,
            model_id=None,
        )

    cfg = await resolve_agent_config(slug, AVERY)

    assert cfg["voice_id"] == "JUST-THE-VOICE"
    assert cfg["display_name"] == "Avery Singh"
    assert cfg["image_url"] == "/agents/avery-singh.jpg"
    assert cfg["language"] == "en"
    assert cfg["country_code"] == "GB"


@pytest.mark.asyncio
async def test_configuring_one_agent_does_not_configure_another(project_dir):
    """The key is `(project_id, agent_id)`, and a resolver that read the first row of the
    table would pass every test above."""
    slug = "two-agent-project"
    project_id = await _make_project(slug)
    async with get_connection(slug) as conn:
        await upsert_agent_config(
            conn, project_id=project_id, agent_id=AVERY, **_only(display_name="Ade Okonkwo")
        )

    assert (await resolve_agent_config(slug, AVERY))["display_name"] == "Ade Okonkwo"
    assert (await resolve_agent_config(slug, "pam"))["display_name"] == "Pamela Reid"


@pytest.mark.asyncio
async def test_configuring_one_project_does_not_configure_another(project_dir):
    slug_a, slug_b = "engagement-a", "engagement-b"
    project_id = await _make_project(slug_a)
    await _make_project(slug_b)
    async with get_connection(slug_a) as conn:
        await upsert_agent_config(
            conn, project_id=project_id, agent_id=AVERY, **_only(display_name="Ade Okonkwo")
        )

    assert (await resolve_agent_config(slug_a, AVERY))["display_name"] == "Ade Okonkwo"
    assert (await resolve_agent_config(slug_b, AVERY))["display_name"] == "Avery Singh"


# --- NULL is not an empty string ------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_deliberately_cleared_name_resolves_as_cleared_and_not_as_the_default(
    project_dir,
):
    """NULL means "use the default"; an empty string does not, and they are different states.

    A project that has deliberately cleared a display name has said something. A truthiness
    test - `row.get(field) or default` - collapses that into "never configured" and quietly
    reinstates the default over a decision somebody made.
    """
    slug = "cleared-name-project"
    project_id = await _make_project(slug)
    async with get_connection(slug) as conn:
        await upsert_agent_config(
            conn,
            project_id=project_id,
            agent_id=AVERY,
            **_only(display_name="", image_url=""),
        )

    cfg = await resolve_agent_config(slug, AVERY)

    assert cfg["display_name"] == ""
    assert cfg["image_url"] == ""
    # The columns left alone are NULL, which *is* "use the default".
    assert cfg["voice_id"] == AVERY_VOICE_ID


@pytest.mark.asyncio
async def test_a_row_of_nulls_resolves_exactly_as_no_row_does(project_dir):
    """The other half of the same rule, and the one an over-eager resolver breaks."""
    slug = "null-row-project"
    project_id = await _make_project(slug)
    async with get_connection(slug) as conn:
        await upsert_agent_config(conn, project_id=project_id, agent_id=AVERY, **_only())

    assert await resolve_agent_config(slug, AVERY) == agent_defaults(AVERY)


@pytest.mark.asyncio
async def test_writing_none_clears_an_override_rather_than_leaving_it_alone(project_dir):
    """`upsert_agent_config` writes every field, so omitting one restores its default.

    Documented on the function, and asserted here because a settings form that posts its whole
    state depends on it: the alternative - merge semantics - makes clearing a field impossible
    through the only door there is.
    """
    slug = "clearing-project"
    project_id = await _make_project(slug)
    async with get_connection(slug) as conn:
        await upsert_agent_config(
            conn, project_id=project_id, agent_id=AVERY, **_only(display_name="Ade Okonkwo")
        )
        await upsert_agent_config(
            conn, project_id=project_id, agent_id=AVERY, **_only(voice_id="ONLY-A-VOICE")
        )
        row = await fetch_agent_config(conn, project_id=project_id, agent_id=AVERY)

    assert row is not None and row["display_name"] is None
    cfg = await resolve_agent_config(slug, AVERY)
    assert cfg["display_name"] == "Avery Singh"
    assert cfg["voice_id"] == "ONLY-A-VOICE"


@pytest.mark.asyncio
async def test_no_row_and_a_row_of_nulls_are_distinguishable_at_the_helper(project_dir):
    """`resolve_agent_config` collapses the two; `fetch_agent_config` must not.

    The settings door needs to know whether this project has ever been configured, and that
    question has no answer once the two are the same.
    """
    slug = "distinguish-project"
    project_id = await _make_project(slug)
    async with get_connection(slug) as conn:
        assert await fetch_agent_config(conn, project_id=project_id, agent_id=AVERY) is None
        await upsert_agent_config(conn, project_id=project_id, agent_id=AVERY, **_only())
        assert await fetch_agent_config(conn, project_id=project_id, agent_id=AVERY) is not None


# --- The defaults themselves ----------------------------------------------------------------


def test_averys_default_voice_is_not_the_female_stock_voice_the_first_interview_used():
    """The defect, stated as an assertion so it cannot come back unnoticed."""
    assert AGENT_IDENTITY[AVERY].voice_id is not None
    assert AGENT_IDENTITY[AVERY].voice_id != RACHEL
    assert AVERY_VOICE_ID != RACHEL


def test_the_interview_portals_fallback_is_averys_default_voice():
    """The front-end constant is a mirror, not a second decision.

    `DEFAULT_VOICE_CONFIG` in `VoiceInterview.tsx` still exists - until sessions are stamped at
    creation there is something for it to be a fallback *for* - but it may no longer disagree
    with the server. This is what a default living in a component costs: the only way to hold
    the two in step is to read one language's source from the other's test suite.

    Comment lines are stripped before the "Rachel is absent" half, and the distinction is real
    rather than a convenience: prose naming the wrong id is the *record* of the defect and is
    why the comment above the constant is worth reading, while code naming it is the defect.
    """
    from pathlib import Path

    source = Path(__file__).resolve().parents[1] / "ui/src/pages/VoiceInterview.tsx"
    text = source.read_text()
    code = "\n".join(
        line for line in text.splitlines() if not line.lstrip().startswith("//")
    )

    assert RACHEL not in code, "the stock female voice is back in the interview portal"
    assert f"elevenlabs_voice_id: '{AVERY_VOICE_ID}'" in code
    # And that the constant is what the fallback *is*, not merely what it is declared as. The
    # first version of this guard asserted only the two lines above, so repointing the use -
    # `?? { ...DEFAULT_VOICE_CONFIG, elevenlabs_voice_id: 'JBFqnCBsd6RMkjVDRZzb' }` - left the
    # backend suite, the frontend suite and tsc all green while the portal spoke as George.
    # The behavioural half of this is asserted in
    # ui/src/__tests__/VoiceInterviewDefaultVoice.test.tsx, which reads the voice off the
    # request; this half is what ties that id to the server's.
    assert "session.voice_config ?? DEFAULT_VOICE_CONFIG" in code
    assert GEORGE not in code


def test_the_rehearsal_door_lets_no_caller_name_a_voice():
    """The door a consultant rehearses through must not take a voice from its client.

    It used to, with a default corrected from Rachel to Avery's - and the correction reached
    nobody, because the only caller passed `voice_id` explicitly from a *second* constant also
    called `AVERY_VOICE_ID`, in `TestInterviewDialog.tsx`, holding George. A field the client
    fills is a field the client decides.
    """
    from api.routers.interviews import TestSpeakRequest

    assert "voice_id" not in TestSpeakRequest.model_fields
    assert "model_id" not in TestSpeakRequest.model_fields
    assert TestSpeakRequest.model_fields["slug"].is_required()


def test_the_rehearsal_dialog_declares_no_voice_of_its_own():
    """The fifth declaration, asserted absent.

    `TestInterviewDialog.tsx` held `const AVERY_VOICE_ID = 'JBFqnCBsd6RMkjVDRZzb'` - George -
    and passed it on all three `/speak` calls, so Avery rehearsed as one man and interviewed as
    another under one variable name in two files, with every gate green. Comment lines are
    stripped for the same reason as in the portal guard below: prose recording the defect is
    why the comment is worth reading, code declaring it is the defect.
    """
    from pathlib import Path

    source = (
        Path(__file__).resolve().parents[1]
        / "ui/src/components/tabs/TestInterviewDialog.tsx"
    )
    code = _code_lines(source.read_text())

    assert GEORGE not in code, "the rehearsal dialog has grown its own voice id again"
    assert "voice_id" not in code, "the rehearsal dialog is naming a voice to the server again"
    assert "slug }" in code, "the rehearsal dialog must send the slug for the server to resolve"


@pytest.mark.asyncio
async def test_the_rehearsal_door_speaks_in_the_projects_configured_voice_and_model(
    project_dir, client, monkeypatch
):
    """The whole chain, asserted at the wire.

    **The voice and the model that reach the ElevenLabs request**, not the values in the table
    and not the arguments to `speak`. A configured field that reaches nothing is this codebase's
    most frequently repeated defect, and the review that sent this round back found exactly that
    shape in the guard it replaced.
    """
    slug = "rehearsal-project"
    project_id = await _make_project(slug)
    async with get_connection(slug) as conn:
        await upsert_agent_config(
            conn,
            project_id=project_id,
            agent_id=AVERY,
            **_only(voice_id="CONFIGURED-VOICE", model_id="CONFIGURED-MODEL"),
        )

    seen = _capture_tts(monkeypatch)
    res = await client.post(
        "/api/interviews/test/speak", json={"text": "Shall we begin?", "slug": slug}
    )

    assert res.status_code == 200
    assert len(seen) == 1
    assert seen[0]["url"].endswith("/text-to-speech/CONFIGURED-VOICE")
    assert seen[0]["json"]["model_id"] == "CONFIGURED-MODEL"


@pytest.mark.asyncio
async def test_an_unconfigured_project_rehearses_in_averys_default_voice_and_model(
    project_dir, client, monkeypatch
):
    """The control, at the wire. Without it, the test above passes for a door that resolves
    only overrides and speaks in nothing at all when a project has none."""
    slug = "rehearsal-default-project"
    await _make_project(slug)

    seen = _capture_tts(monkeypatch)
    res = await client.post(
        "/api/interviews/test/speak", json={"text": "Shall we begin?", "slug": slug}
    )

    assert res.status_code == 200
    assert seen[0]["url"].endswith(f"/text-to-speech/{AVERY_VOICE_ID}")
    assert seen[0]["json"]["model_id"] == DEFAULT_TTS_MODEL_ID
    assert GEORGE not in seen[0]["url"]


@pytest.mark.asyncio
async def test_the_rehearsal_door_refuses_a_request_with_no_slug(project_dir, client):
    """422, not a default. The sibling elaboration-press door already carries this rule, and
    for the sharper reason: a slug that goes missing there sends a sensitive engagement's
    answers to a hosted model."""
    res = await client.post("/api/interviews/test/speak", json={"text": "hello"})
    assert res.status_code == 422

    res = await client.post("/api/interviews/test/speak", json={"text": "hello", "slug": ""})
    assert res.status_code == 422


# --- The migration --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_the_table_has_the_columns_the_resolver_reads(project_dir):
    slug = "schema-project"
    await _make_project(slug)
    async with get_connection(slug) as conn:
        async with conn.execute("PRAGMA table_info(project_agent_config)") as cur:
            columns = {row["name"]: dict(row) async for row in cur}

    assert set(columns) == {"project_id", "agent_id", "updated_at", *CONFIG_FIELDS}
    # Every column but the key is nullable, because NULL is how "use the default" is spelled.
    for field in CONFIG_FIELDS:
        assert columns[field]["notnull"] == 0, field
    assert columns["project_id"]["notnull"] == 1
    assert columns["agent_id"]["notnull"] == 1


@pytest.mark.asyncio
async def test_one_row_per_project_and_agent(project_dir):
    slug = "primary-key-project"
    project_id = await _make_project(slug)
    async with get_connection(slug) as conn:
        await upsert_agent_config(
            conn, project_id=project_id, agent_id=AVERY, **_only(display_name="First")
        )
        await upsert_agent_config(
            conn, project_id=project_id, agent_id=AVERY, **_only(display_name="Second")
        )
        async with conn.execute(
            "SELECT COUNT(*) AS n FROM project_agent_config WHERE project_id=? AND agent_id=?",
            (project_id, AVERY),
        ) as cur:
            assert (await cur.fetchone())["n"] == 1

    assert (await resolve_agent_config(slug, AVERY))["display_name"] == "Second"


@pytest.mark.asyncio
async def test_a_database_at_the_previous_version_gains_the_project_agent_config_table(
    project_dir,
):
    """Fails on _SCHEMA_VERSION 14 and passes on 15.

    A migration added without the bump silently never runs on any database already opened at
    the current version - no error, no warning. The miss would look like configuration simply
    not saving, on exactly the deployments that already exist.
    """
    import api.database as db

    slug = "legacy-agent-config-db"
    async with db.get_connection(slug):
        pass
    con = sqlite3.connect(str(project_dir / f"{slug}.db"))
    con.execute("DROP TABLE project_agent_config")
    con.execute("PRAGMA user_version = 14")
    con.commit()
    con.close()
    db._MIGRATED.discard(slug)

    async with db.get_connection(slug) as conn:
        async with conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='project_agent_config'"
        ) as cur:
            assert await cur.fetchone() is not None


@pytest.mark.asyncio
async def test_a_database_at_version_15_gains_the_model_id_column(project_dir):
    """Fails on _SCHEMA_VERSION 15 and passes on 16.

    The easier bump to forget than a new migration: `_migrate_project_agent_config` is already
    in the block and already runs on a fresh database, so a fresh deployment would look
    perfectly correct while every database opened at 15 silently never gained the column.
    """
    import api.database as db

    slug = "legacy-model-id-db"
    async with db.get_connection(slug):
        pass
    con = sqlite3.connect(str(project_dir / f"{slug}.db"))
    con.execute("ALTER TABLE project_agent_config DROP COLUMN model_id")
    con.execute("PRAGMA user_version = 15")
    con.commit()
    con.close()
    db._MIGRATED.discard(slug)

    async with db.get_connection(slug) as conn:
        async with conn.execute("PRAGMA table_info(project_agent_config)") as cur:
            cols = {row["name"] async for row in cur}
    assert "model_id" in cols


@pytest.mark.asyncio
async def test_the_migration_repairs_a_table_missing_a_column_rather_than_raising(project_dir):
    """It is guarded with `PRAGMA table_info` so it skips *itself*.

    A migration that raises takes every later migration in the block down with it, and the
    later ones are the ones nobody is looking at. Driven against a real half-shaped table
    rather than asserted from the source.
    """
    import api.database as db

    slug = "half-shaped-agent-config"
    async with db.get_connection(slug):
        pass
    con = sqlite3.connect(str(project_dir / f"{slug}.db"))
    con.execute("DROP TABLE project_agent_config")
    # Missing `updated_at` as well as five of the six config columns. `updated_at` was left
    # out of the repair loop's first version, so a table in exactly this shape was reported
    # repaired and still broke every upsert - which is why it is the column omitted here.
    con.execute(
        "CREATE TABLE project_agent_config ("
        " project_id INTEGER NOT NULL, agent_id TEXT NOT NULL, display_name TEXT,"
        " PRIMARY KEY (project_id, agent_id))"
    )
    con.execute("PRAGMA user_version = 14")
    con.commit()
    con.close()
    db._MIGRATED.discard(slug)

    project_id = await _make_project(slug)
    async with db.get_connection(slug) as conn:
        async with conn.execute("PRAGMA table_info(project_agent_config)") as cur:
            columns = {row["name"] async for row in cur}
        # Repaired in the sense that matters: the writer works against it afterwards.
        await upsert_agent_config(
            conn, project_id=project_id, agent_id=AVERY, **_only(voice_id="AFTER-REPAIR")
        )
    assert set(CONFIG_FIELDS) <= columns
    assert "updated_at" in columns
    assert (await resolve_agent_config(slug, AVERY))["voice_id"] == "AFTER-REPAIR"
