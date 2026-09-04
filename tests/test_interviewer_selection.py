# tests/test_interviewer_selection.py
"""Which interviewer takes a stakeholder, and why the answer is written down.

Two interviewers exist as of Task 2 and a project chooses between them with
`interviewer_selection`: `always_male`, `always_female`, or `random`. The choice is resolved
**once, at session creation**, and stamped on the row together with the resolved voice and
synthesis model.

**The stamp is the whole design, not an optimisation.** A project's configuration can change
between an invite going out and the participant clicking it, and under `random` a lookup would
answer a different person every time the same link is opened - so somebody who paused halfway
would come back to a stranger, and the transcript could never say who conducted the interview.
sp57 settled the identical question for `client_documents.knowledge_collection`: an address
that is re-derived is an address that can move underneath the thing it points at.

**Sex is asked of ElevenLabs, never declared here.** `always_female` is answered from the
resolved voice's own `labels.gender`, so a project that gives Avery a female voice gets Avery -
which is what `test_the_sex_follows_the_configured_voice_and_not_the_agent` drives. A table in
this repository mapping agents to sexes would be the sixth declaration of voice facts on a
branch that exists to end the first five, and it would be wrong the first time a project
exercised the configuration the branch added.

No test here makes a real ElevenLabs call. Both the metadata lookup and the synthesis call are
driven through `httpx.MockTransport` and asserted on the **request**, following the rule this
branch learned twice: a test that mocks at the function boundary cannot see what went on the
wire, and "the value reached the call" is a weaker claim than "the value reached the request".
"""
from __future__ import annotations

import asyncio
import json
import random
import sqlite3

import httpx
import pytest
from httpx import ASGITransport, AsyncClient

from agents.identity import AGENT_IDENTITY, AVERY_VOICE_ID, DEFAULT_TTS_MODEL_ID, LAURA_VOICE_ID
from agents.tools.interview_session_tool import InterviewSessionTool
from api.config import get_settings
from api.database import get_connection, insert_project
from api.services.interviewer_selection import (
    NoInterviewerAvailable,
    interviewer_agent_ids,
    resolve_interviewer_selection,
)
from api.services.voice_metadata import forget_voice_metadata

AVERY = "stakeholder_interviewer"
LAURA = "second_interviewer"

# ElevenLabs' stock Rachel - the female voice the first completed interview was conducted in,
# and the value Taylor's `VOICE_LOCALE_TABLE` still hands out in his prompt. Named here so the
# tests can say "not this" without reading it from the source they are checking.
RACHEL = "21m00Tcm4TlvDq8ikWAM"


@pytest.fixture
def project_dir(tmp_path, monkeypatch):
    """An isolated DATABASE_DIR, per CLAUDE.md's poisoned-database rule.

    `get_settings.cache_clear()` on both sides, and `forget_voice_metadata()` too: the gender
    cache is a module-level dict, so a test that resolved Alice as female would otherwise
    answer for the next test's differently-labelled Alice and the second test would pass
    because of the first.
    """
    get_settings.cache_clear()
    forget_voice_metadata()
    monkeypatch.setenv("DATABASE_DIR", str(tmp_path))
    monkeypatch.setenv("PROJECTS_DIR", str(tmp_path / "projects"))
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "tts"))
    yield tmp_path
    forget_voice_metadata()
    get_settings.cache_clear()


async def _build_project(slug: str, config: dict | None = None, stakeholders: int = 1) -> None:
    """A real project database through the real path, with a run and some people on it."""
    async with get_connection(slug) as conn:
        await insert_project(
            conn,
            slug=slug,
            llm_mode="standard",
            sector="test",
            config_json=json.dumps(config or {}),
        )
        async with conn.execute("SELECT id FROM projects WHERE slug=?", (slug,)) as cur:
            project_id = (await cur.fetchone())["id"]
        await conn.execute(
            "INSERT INTO orchestration_runs (project_id, status) VALUES (?, 'running')",
            (project_id,),
        )
        for n in range(stakeholders):
            await conn.execute(
                "INSERT INTO stakeholders (project_id, name) VALUES (?, ?)",
                (project_id, f"Person {n + 1}"),
            )
        await conn.commit()


def _make_project(slug: str, config: dict | None = None, stakeholders: int = 1) -> None:
    asyncio.run(_build_project(slug, config, stakeholders))


def _mock_voice_metadata(monkeypatch, genders: dict[str, str | None]) -> list[str]:
    """Answer `GET /v1/voices/{id}` from a table, and record every id actually asked about.

    The recorded list is what proves `random` asks nothing - a claim about the *absence* of a
    request, which no assertion about the answer could make.
    """
    asked: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        voice_id = str(request.url).rsplit("/", 1)[-1]
        asked.append(voice_id)
        if voice_id not in genders:
            return httpx.Response(404, json={"detail": "not found"})
        gender = genders[voice_id]
        labels = {"accent": "british"}
        if gender is not None:
            labels["gender"] = gender
        return httpx.Response(200, json={"voice_id": voice_id, "labels": labels})

    # A **fresh** client per call, matching production: `voice_metadata._client` opens one for
    # the lookup and closes it, deliberately not borrowing the process-global keep-alive client
    # whose connection pool is bound to the request loop. A helper returning one shared client
    # would hand the second lookup a closed one - which is the test noticing the shape of the
    # thing it is standing in for, and the right way round.
    monkeypatch.setattr(
        "api.services.voice_metadata._client",
        lambda: httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )

    settings = get_settings()
    monkeypatch.setattr(settings, "elevenlabs_api_key", "test-key", raising=False)
    monkeypatch.setattr("api.services.voice_metadata.get_settings", lambda: settings)
    return asked


def _create_sessions(slug: str, sessions: list[dict], run_id: int = 1) -> str:
    """Drive the tool exactly as the crew does - synchronously, from no event loop."""
    tool = InterviewSessionTool(slug=slug, orchestration_run_id=run_id)
    return tool._run("create", sessions, [])


def _rows(slug: str, project_dir) -> list[sqlite3.Row]:
    con = sqlite3.connect(str(project_dir / f"{slug}.db"))
    con.row_factory = sqlite3.Row
    try:
        return con.execute(
            "SELECT session_token, interviewer_agent_id, voice_config "
            "FROM interview_sessions ORDER BY id"
        ).fetchall()
    finally:
        con.close()


def _plan(n: int = 1, **extra) -> list[dict]:
    return [
        {"stakeholder_id": i + 1, "name": f"Person {i + 1}", "node_label": "Goods-in", **extra}
        for i in range(n)
    ]


# --- The schema -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_database_at_version_16_gains_the_interviewer_column(project_dir):
    """Fails on `_SCHEMA_VERSION` 16 and passes on 17.

    `get_connection` only re-runs the migration block when `PRAGMA user_version <
    _SCHEMA_VERSION`, so a migration added without the bump never runs on any database that
    has already been opened once - no error, no warning, and every existing deployment stamps
    NULL into a column it does not have. Driven against a database actually stamped at 16
    rather than asserted from the source.
    """
    import api.database as db

    slug = "legacy-interviewer-db"
    async with db.get_connection(slug):
        pass
    con = sqlite3.connect(str(project_dir / f"{slug}.db"))
    con.execute("ALTER TABLE interview_sessions DROP COLUMN interviewer_agent_id")
    con.execute("PRAGMA user_version = 16")
    con.commit()
    con.close()
    db._MIGRATED.discard(slug)

    async with db.get_connection(slug) as conn:
        async with conn.execute("PRAGMA table_info(interview_sessions)") as cur:
            cols = {row["name"] async for row in cur}
    assert "interviewer_agent_id" in cols


@pytest.mark.asyncio
async def test_the_migration_skips_itself_rather_than_raising(project_dir):
    """Guarded with `PRAGMA table_info`, driven rather than read.

    A migration that raises takes every later migration in the block down with it, and the
    later ones are the ones nobody is looking at.
    """
    import api.database as db

    slug = "twice-migrated"
    async with db.get_connection(slug):
        pass
    db._MIGRATED.discard(slug)
    async with db.get_connection(slug) as conn:
        await db._migrate_interview_sessions_interviewer(conn)
        async with conn.execute("PRAGMA table_info(interview_sessions)") as cur:
            names = [row["name"] async for row in cur]
    assert names.count("interviewer_agent_id") == 1


# --- The roster -----------------------------------------------------------------------------


def test_the_roster_is_the_interviewers_the_crew_builds():
    """Derived from who has a voice, held against who the crew actually builds.

    `interviewer_agent_ids` reads `AGENT_IDENTITY` for agents carrying a `voice_id`, on the
    rule `agents/identity.py` states: `voice_id` is None for every agent that does not speak.
    That is a derivation from an existing declaration rather than a new list beside it - but a
    derivation is a guess until something independent agrees with it, so this holds it against
    `discovery_interviews`, which declares its interviewers by building them.

    If an agent is ever given a voice for some other purpose, this fails and somebody decides,
    rather than that agent quietly joining the interviewing roster.
    """
    from api.services.run_service import _CREW_AGENT_NAMES

    crew_interviewers = {
        agent_id
        for agent_id in _CREW_AGENT_NAMES["discovery_interviews"]
        if agent_id.endswith("interviewer")
    }
    assert set(interviewer_agent_ids()) == crew_interviewers == {AVERY, LAURA}


def test_no_module_maps_an_agent_to_a_sex():
    """The prohibition, as a mechanism rather than a paragraph.

    The obvious implementation of `always_female` is two lines mapping `second_interviewer` to
    female. It would be the sixth declaration of voice facts on a branch that exists to end the
    first five, and it would be **wrong** the first time a project used `project_agent_config`
    to give an interviewer a different voice - which is the whole point of the table Task 1
    added. Task 2 named Laura `second_interviewer` rather than `female_interviewer` for the
    same reason, and asserted it about her id; this asserts it about the code that reads it.

    An AST walk over string *constants*, not a substring search over the text, and the
    difference is the one CLAUDE.md records three sweeps making: prose naming an agent is the
    explanation of why the rule exists - both modules' docstrings do exactly that - while a
    literal `"second_interviewer"` is the rule being broken. A substring search cannot tell
    them apart, and would have had to be weakened until it saw nothing at all.
    """
    import ast
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    for module in ("api/services/interviewer_selection.py", "api/services/voice_metadata.py"):
        tree = ast.parse((root / module).read_text())
        literals = {
            node.value
            for node in ast.walk(tree)
            if isinstance(node, ast.Constant) and isinstance(node.value, str)
        }
        for agent_id in (AVERY, LAURA):
            assert agent_id not in literals, (
                f"{module} names {agent_id} as a literal - the selection must read the voices' "
                f"own metadata, never a roster of who is which sex"
            )


# --- The selection --------------------------------------------------------------------------


def test_always_female_never_yields_the_male_interviewer(project_dir, monkeypatch):
    """The brief's first named test, driven over thirty sessions rather than one.

    One session would pass by luck one time in two under a broken implementation that ignored
    the setting entirely, so the batch size is load-bearing: thirty sessions is
    one-in-a-billion by chance. Every row is checked, not the batch's first.
    """
    _mock_voice_metadata(monkeypatch, {AVERY_VOICE_ID: "male", LAURA_VOICE_ID: "female"})
    slug = "always-female"
    _make_project(slug, {"interviewer_selection": "always_female"}, stakeholders=30)

    out = _create_sessions(slug, _plan(30))
    assert not out.startswith("Error"), out

    rows = _rows(slug, project_dir)
    assert len(rows) == 30
    assert {r["interviewer_agent_id"] for r in rows} == {LAURA}
    for row in rows:
        assert json.loads(row["voice_config"])["elevenlabs_voice_id"] == LAURA_VOICE_ID


def test_always_male_never_yields_the_female_interviewer(project_dir, monkeypatch):
    """The mirror, and it is not redundant.

    Without it, an implementation that always chose Laura - ignoring the setting and simply
    preferring the newer agent - would pass the test above on every run. This is the same
    control-and-override pairing Task 1's resolver tests are built on: an arm asserted alone is
    an arm that cannot be distinguished from a constant.
    """
    _mock_voice_metadata(monkeypatch, {AVERY_VOICE_ID: "male", LAURA_VOICE_ID: "female"})
    slug = "always-male"
    _make_project(slug, {"interviewer_selection": "always_male"}, stakeholders=30)

    _create_sessions(slug, _plan(30))

    rows = _rows(slug, project_dir)
    assert {r["interviewer_agent_id"] for r in rows} == {AVERY}


def test_the_sex_follows_the_configured_voice_and_not_the_agent(project_dir, monkeypatch):
    """Give Avery a female voice, and `always_female` gives you Avery.

    This is what "the API's metadata is the authority" means in practice, and it is the case a
    hardcoded agent-to-sex map gets wrong while looking entirely correct. The project's
    override is a real `project_agent_config` row, resolved through `resolve_agent_config` -
    the same path everything else on this branch resolves through.
    """
    from api.database import upsert_agent_config
    from api.services.agent_config_service import CONFIG_FIELDS

    slug = "avery-resung"
    _make_project(slug, {"interviewer_selection": "always_female"}, stakeholders=5)

    async def _configure() -> None:
        async with get_connection(slug) as conn:
            async with conn.execute("SELECT id FROM projects WHERE slug=?", (slug,)) as cur:
                project_id = (await cur.fetchone())["id"]
            fields = dict.fromkeys(CONFIG_FIELDS, None)
            fields["voice_id"] = "A-FEMALE-VOICE-FOR-AVERY"
            await upsert_agent_config(conn, project_id=project_id, agent_id=AVERY, **fields)

    asyncio.run(_configure())
    # Laura's own voice is male on this project's account, so the only female voice in play is
    # the one Avery was given. An implementation reading a table would answer Laura.
    _mock_voice_metadata(
        monkeypatch,
        {"A-FEMALE-VOICE-FOR-AVERY": "female", LAURA_VOICE_ID: "male"},
    )

    _create_sessions(slug, _plan(5))

    rows = _rows(slug, project_dir)
    assert {r["interviewer_agent_id"] for r in rows} == {AVERY}
    assert {
        json.loads(r["voice_config"])["elevenlabs_voice_id"] for r in rows
    } == {"A-FEMALE-VOICE-FOR-AVERY"}


def test_random_is_stamped_once_and_does_not_change_on_re_read(project_dir, monkeypatch):
    """The brief's second named test, and the one that matters.

    A random choice re-rolled on every read gives a participant a different interviewer each
    time they open their link - and one who paused halfway comes back to a stranger. So this
    reads each session **five times** and requires the same answer every time, and it reads
    through `get_session_with_script`, the function the portal actually calls, rather than
    through the table directly.

    The setting is then changed to `always_male` and the sessions re-read: the stamp must not
    move. That half is the sp57 property proper - a configuration edited between an invite and
    an interview must not rewrite an interview that has already been issued.
    """
    from api.services.interview_service import get_session_with_script

    _mock_voice_metadata(monkeypatch, {AVERY_VOICE_ID: "male", LAURA_VOICE_ID: "female"})
    slug = "random-stamped"
    _make_project(slug, {"interviewer_selection": "random"}, stakeholders=20)

    _create_sessions(slug, _plan(20))
    stamped = {
        r["session_token"]: (r["interviewer_agent_id"], r["voice_config"])
        for r in _rows(slug, project_dir)
    }
    assert len(stamped) == 20

    async def _read_all() -> dict[str, tuple[str, str]]:
        seen = {}
        for token in stamped:
            result = await get_session_with_script(token)
            assert result is not None
            session = result["session"]
            seen[token] = (
                session["interviewer_agent_id"],
                json.dumps(session["voice_config"], sort_keys=True),
            )
        return seen

    first = asyncio.run(_read_all())
    for _ in range(4):
        assert asyncio.run(_read_all()) == first

    # Now change the project's mind. The stamp is what conducted the interview; the setting is
    # only what would be chosen for a session created from now on.
    async def _switch() -> None:
        async with get_connection(slug) as conn:
            await conn.execute(
                "UPDATE projects SET config_json=? WHERE slug=?",
                (json.dumps({"interviewer_selection": "always_male"}), slug),
            )
            await conn.commit()

    asyncio.run(_switch())
    after = {
        r["session_token"]: (r["interviewer_agent_id"], r["voice_config"])
        for r in _rows(slug, project_dir)
    }
    assert after == stamped


def test_random_actually_varies_across_a_batch(project_dir, monkeypatch):
    """The control for the test above, and it is not the same claim.

    "Stable on re-read" is satisfied by an implementation that always picks Avery, which is
    also what a broken `random` looks like. Twenty sessions from two interviewers give a
    one-in-half-a-million chance of a genuine sweep, so a single-valued result here is a
    finding rather than luck.
    """
    _mock_voice_metadata(monkeypatch, {AVERY_VOICE_ID: "male", LAURA_VOICE_ID: "female"})
    slug = "random-varies"
    _make_project(slug, {"interviewer_selection": "random"}, stakeholders=20)

    _create_sessions(slug, _plan(20))

    chosen = {r["interviewer_agent_id"] for r in _rows(slug, project_dir)}
    assert chosen == {AVERY, LAURA}


def test_random_asks_elevenlabs_nothing(project_dir, monkeypatch):
    """The shipped default makes no network call, and that is asserted rather than reasoned.

    `random` is the default for every project that has never touched the setting, so if it
    needed voice metadata then every interview programme on every deployment would depend on
    ElevenLabs being reachable at session-creation time to answer a question nobody asked.
    """
    asked = _mock_voice_metadata(monkeypatch, {AVERY_VOICE_ID: "male", LAURA_VOICE_ID: "female"})
    slug = "random-offline"
    _make_project(slug, {"interviewer_selection": "random"}, stakeholders=3)

    _create_sessions(slug, _plan(3))

    assert asked == []


def test_a_project_that_has_never_set_the_setting_gets_random(project_dir, monkeypatch):
    """No key in `config_json` is not a missing project - it is a project that predates the
    setting, and there was one interviewer then. `random` over the roster is the honest
    reading, and it is the value `ProjectSettings` declares as the default."""
    asked = _mock_voice_metadata(monkeypatch, {})
    slug = "unset-selection"
    _make_project(slug, {}, stakeholders=4)

    _create_sessions(slug, _plan(4))

    assert asked == []
    assert {r["interviewer_agent_id"] for r in _rows(slug, project_dir)} <= {AVERY, LAURA}


def test_a_sex_no_voice_carries_creates_no_sessions_at_all(project_dir, monkeypatch):
    """Refused, loudly, with nothing written - because the choice is permanent.

    If ElevenLabs cannot show that any interviewer's voice is female, the alternatives are to
    stamp a man on every session in the programme or to create none. The first cannot be undone
    by fixing the cause afterwards: the sessions are already issued and the stamp is not
    re-derived. So it refuses, before the first INSERT, and the message names what to change.
    """
    _mock_voice_metadata(monkeypatch, {AVERY_VOICE_ID: "male", LAURA_VOICE_ID: "male"})
    slug = "no-female-voice"
    _make_project(slug, {"interviewer_selection": "always_female"}, stakeholders=3)

    out = _create_sessions(slug, _plan(3))

    assert out.startswith("Error")
    assert "female" in out
    assert _rows(slug, project_dir) == []


def test_an_unreachable_provider_refuses_rather_than_shuffling(project_dir, monkeypatch):
    """A transport failure is "I could not establish that" and not "not female".

    The two are different, and only one of them is a reason to pick somebody. Answering the
    other way would turn `always_female` into `random` on any deployment having a bad minute -
    silently, and permanently, because the answer is stamped.
    """
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("elevenlabs unreachable")

    monkeypatch.setattr(
        "api.services.voice_metadata._client",
        lambda: httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )
    settings = get_settings()
    monkeypatch.setattr(settings, "elevenlabs_api_key", "test-key", raising=False)
    monkeypatch.setattr("api.services.voice_metadata.get_settings", lambda: settings)

    slug = "provider-down"
    _make_project(slug, {"interviewer_selection": "always_female"}, stakeholders=2)

    out = _create_sessions(slug, _plan(2))

    assert out.startswith("Error")
    assert _rows(slug, project_dir) == []


def test_a_missing_api_key_is_not_a_fact_about_a_voice(project_dir, monkeypatch):
    """`ask_voice_sex` swallows transport failures and must not swallow this one.

    A missing key is a deployment fault an operator can fix, not a property of a voice, and it
    is the case that would otherwise be true on every deployment that has not configured
    ElevenLabs at all - turning the setting into a coin toss everywhere at once.
    """
    from api.services.voice_metadata import ask_voice_sex

    settings = get_settings()
    monkeypatch.setattr(settings, "elevenlabs_api_key", "", raising=False)
    monkeypatch.setattr("api.services.voice_metadata.get_settings", lambda: settings)

    with pytest.raises(ValueError, match="ELEVENLABS_API_KEY"):
        asyncio.run(ask_voice_sex(AVERY_VOICE_ID))


def test_a_voice_with_no_gender_label_is_unknown_rather_than_a_match(project_dir, monkeypatch):
    """ElevenLabs answering 200 with no `gender` in `labels` is the provider saying nothing.

    Treating "no label" as a match would make `always_female` select a voice whose sex nobody
    has established, which is the failure the setting exists to prevent.
    """
    _mock_voice_metadata(monkeypatch, {AVERY_VOICE_ID: None, LAURA_VOICE_ID: None})
    slug = "unlabelled-voices"
    _make_project(slug, {"interviewer_selection": "always_female"}, stakeholders=2)

    out = _create_sessions(slug, _plan(2))

    assert out.startswith("Error")
    assert _rows(slug, project_dir) == []


def test_the_gender_of_one_voice_is_asked_once_per_batch(project_dir, monkeypatch):
    """Thirty sessions, two questions. Resolution happens once for the batch, before the first
    INSERT - so a thirty-person programme does not ask ElevenLabs the same question thirty
    times, and does not open a second connection to this database mid-write-transaction."""
    asked = _mock_voice_metadata(
        monkeypatch, {AVERY_VOICE_ID: "male", LAURA_VOICE_ID: "female"}
    )
    slug = "asked-once"
    _make_project(slug, {"interviewer_selection": "always_male"}, stakeholders=30)

    _create_sessions(slug, _plan(30))

    assert sorted(asked) == sorted({AVERY_VOICE_ID, LAURA_VOICE_ID})


# --- The stamp ------------------------------------------------------------------------------


def test_the_stamp_carries_the_voice_the_model_and_the_locale(project_dir, monkeypatch):
    """All four, because the model is the field this branch nearly shipped without.

    Task 1 made `model_id` a column, a resolved field and a required argument to `synthesise`
    and `speak` - and the live session `/speak` door still passed the default, because it holds
    a session token rather than a slug. Configured, stored, and reaching nothing. The session
    is the only place that door can learn it, so it is stamped here.
    """
    _mock_voice_metadata(monkeypatch, {AVERY_VOICE_ID: "male", LAURA_VOICE_ID: "female"})
    slug = "stamp-shape"
    _make_project(slug, {"interviewer_selection": "always_male"}, stakeholders=1)

    _create_sessions(slug, _plan(1))

    stamp = json.loads(_rows(slug, project_dir)[0]["voice_config"])
    assert stamp == {
        "elevenlabs_voice_id": AVERY_VOICE_ID,
        "language": "en",
        "country_code": "GB",
        "model_id": DEFAULT_TTS_MODEL_ID,
    }


def test_the_stamp_is_the_projects_configuration_and_not_the_plans(project_dir, monkeypatch):
    """A `voice_config` in the plan is ignored, and this is the assertion that says so.

    It used to be stored as given, which meant the voice a participant heard was whatever a
    language model copied out of `VOICE_LOCALE_TABLE` in its own prompt - a prose table naming
    ElevenLabs' stock Rachel, a female voice, for the male interviewer. **A stamped value beats
    everything**, so as long as the plan supplied it, no amount of correcting defaults
    elsewhere could reach a real interview.

    The table itself is still in Taylor's prompt and its retirement is Task 4's. What changed
    here is that it no longer reaches a session.
    """
    _mock_voice_metadata(monkeypatch, {AVERY_VOICE_ID: "male", LAURA_VOICE_ID: "female"})
    slug = "plan-ignored"
    _make_project(slug, {"interviewer_selection": "always_male"}, stakeholders=1)

    _create_sessions(
        slug,
        _plan(
            1,
            voice_config={
                "language": "en",
                "country_code": "GB",
                "elevenlabs_voice_id": RACHEL,
            },
        ),
    )

    stamp = json.loads(_rows(slug, project_dir)[0]["voice_config"])
    assert stamp["elevenlabs_voice_id"] == AVERY_VOICE_ID
    assert RACHEL not in json.dumps(stamp)


def test_the_transcripts_say_who_conducted_them(project_dir, monkeypatch):
    """`get_transcripts` carries the interviewer out with each transcript.

    `interview_transcripts` is a per-*run* artefact and the interviewer is a per-*session*
    choice, so a programme conducted by two people produces one artefact recording both - and
    it can only do that if the identity travels with the transcript. Read off the row, never
    re-derived from the project's current setting.
    """
    _mock_voice_metadata(monkeypatch, {AVERY_VOICE_ID: "male", LAURA_VOICE_ID: "female"})
    slug = "transcripts-say"
    _make_project(slug, {"interviewer_selection": "always_female"}, stakeholders=1)
    _create_sessions(slug, _plan(1))

    con = sqlite3.connect(str(project_dir / f"{slug}.db"))
    con.execute(
        "UPDATE interview_sessions SET status='completed', transcript_json=?",
        (json.dumps([{"question": "q", "answer": "a"}]),),
    )
    con.commit()
    con.close()

    tool = InterviewSessionTool(slug=slug, orchestration_run_id=1)
    transcripts = json.loads(tool._run("get_transcripts", [], []))

    assert len(transcripts) == 1
    assert transcripts[0]["interviewer_agent_id"] == LAURA
    assert transcripts[0]["voice_config"]["elevenlabs_voice_id"] == LAURA_VOICE_ID


def test_the_transcript_artefact_is_still_averys_alone(project_dir):
    """The ownership decision this task had to make, recorded as an assertion.

    `OUTPUT_OWNERS` gives `interview_transcripts` to `stakeholder_interviewer` and `check_write`
    compares by equality, so Laura cannot write it. That is **left exactly as it was**, and the
    reasoning is that the two roles are different sizes: the interviewer a participant meets is
    chosen per session, while `interview_transcripts` is one artefact per crew run covering the
    whole programme. No single agent could own a per-run artefact under a per-session choice, so
    widening ownership to a set would not have made Laura the owner of anything - it would have
    weakened the refusal for a case that cannot arise, since the crew gives the interviewing
    task to one agent and `test_the_crew_builds_both_interviewers_and_gives_the_task_to_one`
    holds it there.

    What the per-session fact needed was somewhere to go, not somewhere else to be owned, and
    `test_the_transcripts_say_who_conducted_them` above is where it goes.

    So `tests/test_second_interviewer.py::test_handing_her_averys_task_verbatim_would_be_
    refused_twice` still passes, and both refusals are still live. This test states that this is
    a decision rather than an oversight, and it fails if somebody widens ownership without
    revisiting the argument.
    """
    from agents.tools.ownership import OUTPUT_OWNERS, check_write

    assert OUTPUT_OWNERS["interview_transcripts"] == AVERY
    assert check_write("interview_transcripts", LAURA) is not None
    assert check_write("interview_transcripts", AVERY) is None


# --- What reaches the synthesis call ---------------------------------------------------------


def _capture_tts(monkeypatch) -> list[dict]:
    """Point `synthesise`'s client at a `MockTransport` and record every request.

    The wire, not the call. Moving a security gate to *after* synthesis still answered 403 on
    this branch, and only a wire assertion caught that the private voice had already been
    spoken; a stamped value nothing sends is the same defect one layer along.
    """
    seen: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append({"url": str(request.url), "json": json.loads(request.content)})
        return httpx.Response(200, content=b"AUDIO-BYTES")

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    monkeypatch.setattr("api.services.interview_service.get_tts_client", lambda: client)
    settings = get_settings()
    monkeypatch.setattr(settings, "elevenlabs_api_key", "test-key", raising=False)
    monkeypatch.setattr("api.services.interview_service.get_settings", lambda: settings)
    return seen


async def _speak(token: str, text: str) -> httpx.Response:
    from api.main import app

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        return await client.post(f"/api/interviews/{token}/speak", json={"text": text})


def test_the_stamped_voice_and_model_are_what_reach_elevenlabs(project_dir, monkeypatch):
    """Step 4 of the brief: assert what reaches the synthesis call, not what the table holds.

    The session is stamped with a voice and a model no default would produce, and both are read
    off the **request** ElevenLabs would have received. A test asserting the row would pass for
    a door that read the row and then sent the default, which is what that door did until this
    change.
    """
    _mock_voice_metadata(monkeypatch, {AVERY_VOICE_ID: "male", LAURA_VOICE_ID: "female"})
    slug = "wire-stamp"
    _make_project(slug, {"interviewer_selection": "always_female"}, stakeholders=1)

    async def _configure() -> None:
        from api.database import upsert_agent_config
        from api.services.agent_config_service import CONFIG_FIELDS

        async with get_connection(slug) as conn:
            async with conn.execute("SELECT id FROM projects WHERE slug=?", (slug,)) as cur:
                project_id = (await cur.fetchone())["id"]
            fields = dict.fromkeys(CONFIG_FIELDS, None)
            fields["voice_id"] = LAURA_VOICE_ID
            fields["model_id"] = "eleven_multilingual_v2"
            await upsert_agent_config(conn, project_id=project_id, agent_id=LAURA, **fields)

    asyncio.run(_configure())
    _create_sessions(slug, _plan(1))
    token = _rows(slug, project_dir)[0]["session_token"]

    seen = _capture_tts(monkeypatch)
    resp = asyncio.run(_speak(token, "Tell me about goods-in."))

    assert resp.status_code == 200
    assert len(seen) == 1
    assert seen[0]["url"].endswith(f"/text-to-speech/{LAURA_VOICE_ID}")
    assert seen[0]["json"]["model_id"] == "eleven_multilingual_v2"


def test_the_speak_door_takes_no_voice_from_its_caller(project_dir, monkeypatch):
    """A field the client fills is a field the client decides.

    The portal used to send `voice_id`, read from the session with a hardcoded fallback in the
    component, so the voice a participant heard was decided in a browser from a constant no
    server could read. `TestSpeakRequest` lost the same field for the same reason one door up.
    A caller naming a voice must not be able to be spoken in it.
    """
    from api.routers.interviews import SpeakRequest

    assert "voice_id" not in SpeakRequest.model_fields
    assert "model_id" not in SpeakRequest.model_fields

    _mock_voice_metadata(monkeypatch, {AVERY_VOICE_ID: "male", LAURA_VOICE_ID: "female"})
    slug = "no-caller-voice"
    _make_project(slug, {"interviewer_selection": "always_male"}, stakeholders=1)
    _create_sessions(slug, _plan(1))
    token = _rows(slug, project_dir)[0]["session_token"]

    seen = _capture_tts(monkeypatch)

    async def _post() -> httpx.Response:
        from api.main import app

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            return await client.post(
                f"/api/interviews/{token}/speak",
                json={"text": "Hello.", "voice_id": RACHEL},
            )

    resp = asyncio.run(_post())

    assert resp.status_code == 200
    assert seen[0]["url"].endswith(f"/text-to-speech/{AVERY_VOICE_ID}")
    assert RACHEL not in seen[0]["url"]


def test_an_unstamped_session_is_refused_rather_than_spoken(project_dir, monkeypatch):
    """The deleted fallback's case, refused at the server as well as in the portal.

    Every session created before this change carries whatever the plan gave it, which may be
    nothing. A fallback would hide the only bug it could be covering - a session created with
    no resolved configuration - by conducting the interview in a voice nobody chose, which is
    exactly what happened for the whole life of `DEFAULT_VOICE_CONFIG`.
    """
    _mock_voice_metadata(monkeypatch, {AVERY_VOICE_ID: "male", LAURA_VOICE_ID: "female"})
    slug = "unstamped-session"
    _make_project(slug, {"interviewer_selection": "always_male"}, stakeholders=1)
    _create_sessions(slug, _plan(1))

    con = sqlite3.connect(str(project_dir / f"{slug}.db"))
    con.execute("UPDATE interview_sessions SET voice_config=NULL")
    con.commit()
    con.close()
    token = _rows(slug, project_dir)[0]["session_token"]

    seen = _capture_tts(monkeypatch)
    resp = asyncio.run(_speak(token, "Hello."))

    assert resp.status_code == 422
    assert seen == [], "the door synthesised before refusing"


def test_a_stamp_predating_the_model_keeps_the_model_it_was_spoken_with(project_dir, monkeypatch):
    """A legacy stamp is not a bug, and is not treated as one.

    Sessions created before `model_id` joined the stamp carry a voice and no model. They were
    spoken through `DEFAULT_TTS_MODEL_ID` on every utterance, so that is what they keep - a
    re-derivation would be wrong here in the other direction, and refusing them would take a
    running interview programme down for a field that did not exist when it started.
    """
    _mock_voice_metadata(monkeypatch, {AVERY_VOICE_ID: "male", LAURA_VOICE_ID: "female"})
    slug = "legacy-stamp"
    _make_project(slug, {"interviewer_selection": "always_male"}, stakeholders=1)
    _create_sessions(slug, _plan(1))

    con = sqlite3.connect(str(project_dir / f"{slug}.db"))
    con.execute(
        "UPDATE interview_sessions SET voice_config=?",
        (json.dumps({
            "elevenlabs_voice_id": "AN-OLD-VOICE",
            "language": "en",
            "country_code": "GB",
        }),),
    )
    con.commit()
    con.close()
    token = _rows(slug, project_dir)[0]["session_token"]

    seen = _capture_tts(monkeypatch)
    resp = asyncio.run(_speak(token, "Hello."))

    assert resp.status_code == 200
    assert seen[0]["url"].endswith("/text-to-speech/AN-OLD-VOICE")
    assert seen[0]["json"]["model_id"] == DEFAULT_TTS_MODEL_ID


# --- The setting ----------------------------------------------------------------------------


def test_the_setting_is_declared_and_is_not_platform_tier():
    """It decides tone, not where a project's material is sent.

    `_PLATFORM_TIER_SETTINGS` holds the eight fields a `project_admin` may not change because
    they move data across a boundary - the mode, the local URLs, the six model ids. Which
    interviewer a participant meets is not one of them, and putting it there would refuse the
    people sp44 widened those fifteen doors *for*.
    """
    from api.models import ProjectSettings
    from api.routers.projects import _PLATFORM_TIER_SETTINGS

    field = ProjectSettings.model_fields["interviewer_selection"]
    assert field.default == "random"
    assert "interviewer_selection" not in _PLATFORM_TIER_SETTINGS


def test_an_unrecognised_setting_value_is_read_as_random(project_dir):
    """`config_json` is a stored JSON blob, so a hand-edited or older row may hold anything.

    `random` is the safe reading: it selects somebody from the declared roster, which is what
    every project did before the setting existed. The alternative - refusing - would take an
    interview programme down over a typo in a field that has a sensible default.
    """
    from api.services.interviewer_selection import project_interviewer_selection

    slug = "odd-value"
    _make_project(slug, {"interviewer_selection": "always_nonbinary"})

    assert asyncio.run(project_interviewer_selection(slug)) == "random"


def test_a_blank_slug_is_refused_rather_than_answered():
    """The rule `project_llm_mode` and `resolve_agent_config` both follow, and for the reason
    the first of them learned expensively: a forgotten slug must not become a quiet default.
    Two seams disagreeing about what a blank slug means is worse than either rule."""
    from api.services.interviewer_selection import project_interviewer_selection

    for slug in ("", "   ", "\t"):
        with pytest.raises(ValueError, match="requires a slug"):
            asyncio.run(project_interviewer_selection(slug))


def test_resolving_a_selection_creates_no_database(project_dir):
    """Probing a slug must not materialise one file per guess - the rule `caller_roles` and
    `_stakeholder_matches_invite` already follow, reaching here because the selection resolves
    on a path a public interview link can start."""
    selection = asyncio.run(resolve_interviewer_selection("no-such-engagement"))

    assert selection.mode == "random"
    assert set(selection.eligible) == {AVERY, LAURA}
    assert not (project_dir / "no-such-engagement.db").exists()


def test_a_seeded_rng_makes_the_choice_reproducible(project_dir, monkeypatch):
    """`pick()` takes its randomness from an injected `Random`, so the selection is testable
    without patching the module. Passing the clock, or in this case the dice, rather than
    reading it - the rule CLAUDE.md states for `today` and which applies identically here."""
    _mock_voice_metadata(monkeypatch, {AVERY_VOICE_ID: "male", LAURA_VOICE_ID: "female"})
    slug = "seeded"
    _make_project(slug, {"interviewer_selection": "random"})

    first = asyncio.run(resolve_interviewer_selection(slug, rng=random.Random(7)))
    second = asyncio.run(resolve_interviewer_selection(slug, rng=random.Random(7)))

    assert [first.pick() for _ in range(10)] == [second.pick() for _ in range(10)]


def test_every_agent_identity_that_speaks_is_resolvable(project_dir):
    """The roster is read out of `AGENT_IDENTITY`, so every member must resolve.

    An id in the roster that `resolve_agent_config` rejects would raise `UnknownAgent` at
    session creation - in a crew run, at the point an interview programme starts.
    """
    for agent_id in interviewer_agent_ids():
        assert agent_id in AGENT_IDENTITY
        assert AGENT_IDENTITY[agent_id].voice_id


def test_no_interviewer_available_is_its_own_error_type():
    """A refusal a caller can distinguish from a bug. `InterviewSessionTool._create` catches
    exactly this and turns it into the agent-readable error string; catching `RuntimeError`
    broadly there would have swallowed real faults into "no sessions created"."""
    assert issubclass(NoInterviewerAvailable, RuntimeError)


# --- The review's findings ---------------------------------------------------------------


def _local_voices_server():
    """A throwaway HTTP/1.1 server answering the voices endpoint, on an ephemeral port.

    Real sockets, deliberately. The defect this exists for lives in an httpx **connection
    pool**, and every other test in this file installs a `MockTransport`, which has no pool -
    so the mock is one layer away from the thing that breaks. Nothing here reaches ElevenLabs:
    it is 127.0.0.1 on a port the OS picks, and it is shut down in a `finally`.
    """
    import json as _json
    import threading
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    class Handler(BaseHTTPRequestHandler):
        # HTTP/1.1, and this line is the whole test. `BaseHTTPRequestHandler` defaults to
        # HTTP/1.0, which closes the connection after every response - so httpx pools nothing,
        # and the cross-loop hazard cannot arise. Written without it, this test **passed under
        # the exact defect it was built for**, in isolation and in the suite. A negative result
        # is only evidence if the mutation could have been observed, and here the fixture was
        # quietly preventing it - the same shape as the `DATA_DIR` demonstration Task 1's third
        # round recorded, arriving in the fixture rather than in the assertion.
        protocol_version = "HTTP/1.1"

        def do_GET(self):  # noqa: N802 - BaseHTTPRequestHandler's interface
            body = _json.dumps({"labels": {"gender": "female"}}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    server.daemon_threads = True
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def test_a_gender_lookup_on_its_own_loop_leaves_the_shared_client_usable(monkeypatch):
    """The metadata lookup must not borrow the process-global keep-alive client.

    `InterviewSessionTool._create` resolves the selection under `asyncio.run` on a CrewAI
    worker thread - a different, short-lived event loop from the one serving requests. An httpx
    connection pool holds anyio primitives bound to the loop that created it, so a lookup made
    through `get_tts_client()` breaks in **both** directions: it fails with "bound to a
    different event loop" if a request pooled a connection first, and the *next* participant's
    `POST /speak` fails with "Event loop is closed" if the crew went first. The second is a 500
    to a participant, and the portal treats a failed `/speak` as "skip the audio and continue" -
    so the question is displayed and never spoken, silently.

    The sequence below is that scenario in miniature. `get_tts_client()` stands in for `speak`,
    which uses exactly that client; the middle step is what the tool does. Under the code as
    first shipped this test raises on the second step, and again on the third.
    """
    from api.services.http_clients import close_http_clients, get_tts_client

    server = _local_voices_server()
    url = f"http://127.0.0.1:{server.server_port}/v1/voices"
    monkeypatch.setattr("api.services.voice_metadata._VOICES_URL", url)
    settings = get_settings()
    monkeypatch.setattr(settings, "elevenlabs_api_key", "test-key", raising=False)
    monkeypatch.setattr("api.services.voice_metadata.get_settings", lambda: settings)

    from api.services.voice_metadata import voice_gender

    async def speak_like() -> int:
        resp = await get_tts_client().get(f"{url}/warm")
        return resp.status_code

    loop = asyncio.new_event_loop()
    try:
        # 1. A request pools a connection on the request loop, as `speak` does.
        assert loop.run_until_complete(speak_like()) == 200
        # 2. The crew resolves a selection on its own loop, as the tool does.
        assert asyncio.run(voice_gender("VOICE-A")) == "female"
        # 3. The next participant speaks, on the original loop.
        assert loop.run_until_complete(speak_like()) == 200
    finally:
        loop.run_until_complete(close_http_clients())
        loop.close()
        server.shutdown()
        server.server_close()


def test_the_lookup_opens_its_own_client_and_closes_it(monkeypatch):
    """Stated as a property, because the test above needs sockets and this one does not.

    A short-lived client per lookup is the fix; a helper that handed back one shared client
    would pass the wire tests and reinstate the defect. Two lookups, two clients, both closed.
    """
    import httpx as _httpx

    from api.services import voice_metadata

    opened: list[_httpx.AsyncClient] = []
    real = voice_metadata._client

    def spy() -> _httpx.AsyncClient:
        client = _httpx.AsyncClient(
            transport=_httpx.MockTransport(
                lambda request: _httpx.Response(200, json={"labels": {"gender": "male"}})
            )
        )
        opened.append(client)
        return client

    monkeypatch.setattr(voice_metadata, "_client", spy)
    settings = get_settings()
    monkeypatch.setattr(settings, "elevenlabs_api_key", "test-key", raising=False)
    monkeypatch.setattr(voice_metadata, "get_settings", lambda: settings)

    assert asyncio.run(voice_metadata.voice_gender("V1")) == "male"
    assert asyncio.run(voice_metadata.voice_gender("V2")) == "male"

    assert len(opened) == 2, "the lookup reused a client instead of opening its own"
    assert all(c.is_closed for c in opened), "a lookup left its client open"
    assert real is not voice_metadata.get_tts_client if hasattr(voice_metadata, "get_tts_client") else True


def test_the_metadata_module_does_not_reach_for_the_shared_client():
    """The shared client is named nowhere in this module - asserted by AST, not by substring.

    The prose above `_client` names `get_tts_client` at length, explaining why it must not be
    used, and a substring search would read that explanation as the defect. The walk looks for
    a *call*, which is the same distinction the sole-caller guard in `test_agent_config.py` had
    to learn.
    """
    import ast
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    tree = ast.parse((root / "api/services/voice_metadata.py").read_text())
    called = {
        getattr(node.func, "id", None) or getattr(node.func, "attr", None)
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
    }
    assert "get_tts_client" not in called


def test_a_provider_that_cannot_be_asked_is_not_reported_as_an_answer(project_dir, monkeypatch):
    """The refusal must not say "according to ElevenLabs" when ElevenLabs was never reached.

    This is the failure the two unconfirmed assumptions produce - the voices endpoint not
    answering for these ids, or the labels being spelled otherwise - and the wrong sentence
    sends an operator to reconfigure a correct voice. It arrives inside a tool result to a
    language model mid-run, so it may be the only account of the failure anybody reads.
    """
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("elevenlabs unreachable")

    monkeypatch.setattr(
        "api.services.voice_metadata._client",
        lambda: httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )
    settings = get_settings()
    monkeypatch.setattr(settings, "elevenlabs_api_key", "test-key", raising=False)
    monkeypatch.setattr("api.services.voice_metadata.get_settings", lambda: settings)

    slug = "cannot-ask"
    _make_project(slug, {"interviewer_selection": "always_female"}, stakeholders=2)

    out = _create_sessions(slug, _plan(2))

    assert out.startswith("Error")
    assert "could not be asked" in out
    assert "ELEVENLABS_API_KEY" in out
    assert "do not reconfigure" in out
    # And it must not assert the provider's answer, which is the thing it does not have.
    assert "according to ElevenLabs" not in out
    assert "reports no interviewer" not in out
    assert _rows(slug, project_dir) == []


def test_a_provider_that_answered_without_a_label_says_so(project_dir, monkeypatch):
    """The middle state: asked, answered, and it carries no `gender` for these voices.

    Distinct from both neighbours - the repair is to label the voices, not to check the key and
    not to choose a different voice - and a single collapsed message could name only one of the
    three.
    """
    _mock_voice_metadata(monkeypatch, {AVERY_VOICE_ID: None, LAURA_VOICE_ID: None})
    slug = "no-labels"
    _make_project(slug, {"interviewer_selection": "always_female"}, stakeholders=2)

    out = _create_sessions(slug, _plan(2))

    assert out.startswith("Error")
    assert "gave no sex for" in out
    assert "label those voices" in out
    assert "could not be asked" not in out


def test_a_provider_that_answered_otherwise_says_that_instead(project_dir, monkeypatch):
    """The third state, and the only one where "no configured voice is female" is known."""
    _mock_voice_metadata(monkeypatch, {AVERY_VOICE_ID: "male", LAURA_VOICE_ID: "male"})
    slug = "answered-male"
    _make_project(slug, {"interviewer_selection": "always_female"}, stakeholders=2)

    out = _create_sessions(slug, _plan(2))

    assert out.startswith("Error")
    assert "reports no interviewer's configured voice as female" in out
    assert "could not be asked" not in out
    assert "gave no sex for" not in out


def test_every_refusal_says_that_nothing_was_written(project_dir, monkeypatch):
    """Three sentences, one invariant. Whatever the cause, no session exists - and the operator
    needs to know that before they know why, because it is what tells them the programme has
    not half-started."""
    from api.services.interviewer_selection import _why_nobody
    from api.services.voice_metadata import VoiceSexAnswer

    roster = [AVERY, LAURA]
    cases = [
        {a: VoiceSexAnswer(label=None, answered=False) for a in roster},
        {a: VoiceSexAnswer(label=None, answered=True) for a in roster},
        {a: VoiceSexAnswer(label="male", answered=True) for a in roster},
        {AVERY: VoiceSexAnswer(label="male", answered=True),
         LAURA: VoiceSexAnswer(label=None, answered=False)},
    ]
    for answers in cases:
        message = _why_nobody("always_female", "female", roster, answers)
        assert "No sessions were created" in message
        assert "stamped on the session at creation" in message
        assert "interviewer_selection" in message


# --- The name and the face a participant reads --------------------------------------------


def _branding(token: str) -> dict:
    from api.services.interview_service import get_session_with_script

    async def _read():
        result = await get_session_with_script(token)
        assert result is not None
        return result["branding"]

    return asyncio.run(_read())


def test_the_participant_reads_the_name_of_whoever_is_speaking(project_dir, monkeypatch):
    """The name and the face come from the session's stamp, not from a project brand field.

    This is the defect the review raised to Critical, and it was **not** confined to the
    sex-specific modes: `random` is the shipped default and the roster is both interviewers, so
    roughly half of every project's sessions put Laura's voice behind Avery's name and Avery's
    photograph. `brand_interviewer_name` defaulted to the literal "Avery Singh", so every
    project that had ever saved settings held it and the server could not tell a brand decision
    from an inheritance - and no UI has ever offered the field.

    Both interviewers are driven, because asserting one is asserting a constant.
    """
    _mock_voice_metadata(monkeypatch, {AVERY_VOICE_ID: "male", LAURA_VOICE_ID: "female"})

    for mode, expected_name, expected_image in (
        ("always_female", "Laura Nelson", ""),
        ("always_male", "Avery Singh", "/agents/avery-singh.jpg"),
    ):
        slug = f"who-speaks-{mode}"
        _make_project(slug, {"interviewer_selection": mode}, stakeholders=1)
        _create_sessions(slug, _plan(1))
        token = _rows(slug, project_dir)[0]["session_token"]

        branding = _branding(token)
        assert branding["interviewer_name"] == expected_name
        assert branding["interviewer_image_url"] == expected_image


def test_a_brand_name_left_over_from_one_interviewer_does_not_win(project_dir, monkeypatch):
    """The stored literal must not override the stamp, which is the whole of the defect.

    Every project on the deployment has `"brand_interviewer_name": "Avery Singh"` in its
    `config_json`, written there by the model default rather than by anybody's decision. If
    that value still won, this task would have shipped a woman's voice behind a man's name on
    the default configuration.
    """
    _mock_voice_metadata(monkeypatch, {AVERY_VOICE_ID: "male", LAURA_VOICE_ID: "female"})
    slug = "stale-brand"
    _make_project(
        slug,
        {
            "interviewer_selection": "always_female",
            "brand_interviewer_name": "Avery Singh",
            "brand_interviewer_image_url": "/agents/avery-singh.jpg",
        },
        stakeholders=1,
    )
    _create_sessions(slug, _plan(1))
    token = _rows(slug, project_dir)[0]["session_token"]

    branding = _branding(token)
    assert branding["interviewer_name"] == "Laura Nelson"
    assert branding["interviewer_image_url"] == ""


def test_a_projects_own_name_for_an_interviewer_is_honoured(project_dir, monkeypatch):
    """The control. A resolver that ignored the project entirely would pass both tests above.

    `project_agent_config` is where a project renames an agent now - keyed on the permanent
    `agent_id`, per agent rather than one name for whoever turns up.
    """
    from api.database import upsert_agent_config
    from api.services.agent_config_service import CONFIG_FIELDS

    _mock_voice_metadata(monkeypatch, {AVERY_VOICE_ID: "male", LAURA_VOICE_ID: "female"})
    slug = "renamed-interviewer"
    _make_project(slug, {"interviewer_selection": "always_female"}, stakeholders=1)

    async def _configure() -> None:
        async with get_connection(slug) as conn:
            async with conn.execute("SELECT id FROM projects WHERE slug=?", (slug,)) as cur:
                project_id = (await cur.fetchone())["id"]
            fields = dict.fromkeys(CONFIG_FIELDS, None)
            fields["display_name"] = "Dr Laura Nelson"
            fields["image_url"] = "/agents/laura.jpg"
            await upsert_agent_config(conn, project_id=project_id, agent_id=LAURA, **fields)

    asyncio.run(_configure())
    _create_sessions(slug, _plan(1))
    token = _rows(slug, project_dir)[0]["session_token"]

    branding = _branding(token)
    assert branding["interviewer_name"] == "Dr Laura Nelson"
    assert branding["interviewer_image_url"] == "/agents/laura.jpg"


def test_a_session_with_no_stamp_reads_as_the_interviewer_who_took_it(project_dir, monkeypatch):
    """A legacy session has an answer, and it is a fact rather than a default.

    Before the stamp there was exactly one interviewer, so `stakeholder_interviewer` is what
    conducted every session created before this commit. The same shape as the legacy `model_id`
    rule at the speak door: history, not a guess.
    """
    _mock_voice_metadata(monkeypatch, {AVERY_VOICE_ID: "male", LAURA_VOICE_ID: "female"})
    slug = "legacy-interviewer"
    _make_project(slug, {"interviewer_selection": "always_female"}, stakeholders=1)
    _create_sessions(slug, _plan(1))

    con = sqlite3.connect(str(project_dir / f"{slug}.db"))
    con.execute("UPDATE interview_sessions SET interviewer_agent_id=NULL")
    con.commit()
    con.close()
    token = _rows(slug, project_dir)[0]["session_token"]

    assert _branding(token)["interviewer_name"] == "Avery Singh"


def test_resolving_the_interviewer_does_not_migrate_the_participants_database(project_dir):
    """The public interview path must not run the migration block, and now reads a table.

    `interview_db_connection` exists precisely because "a public interview request is not the
    place to discover a schema change", so the resolution is handed that connection rather than
    opening its own through `get_connection`. Asserted by AST over `interview_service.py`: it
    must call `resolve_agent_config_with` and never `resolve_agent_config`.
    """
    import ast
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    tree = ast.parse((root / "api/services/interview_service.py").read_text())
    called = {
        getattr(node.func, "id", None) or getattr(node.func, "attr", None)
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
    }
    assert "resolve_agent_config_with" in called
    assert "resolve_agent_config" not in called


def test_an_unmigrated_database_answers_the_defaults_rather_than_five_hundred(project_dir, monkeypatch):
    """`interview_db_connection` runs no migrations, so the overrides table may not exist.

    A project database not opened through `get_connection` since `project_agent_config` landed
    does not have it, and this is the participant's *first* request. "No overrides table" means
    "no overrides", so the defaults are the correct answer - and the alternative is a 500 on a
    link somebody was emailed.
    """
    _mock_voice_metadata(monkeypatch, {AVERY_VOICE_ID: "male", LAURA_VOICE_ID: "female"})
    slug = "unmigrated-db"
    _make_project(slug, {"interviewer_selection": "always_male"}, stakeholders=1)
    _create_sessions(slug, _plan(1))
    token = _rows(slug, project_dir)[0]["session_token"]

    con = sqlite3.connect(str(project_dir / f"{slug}.db"))
    con.execute("DROP TABLE project_agent_config")
    con.commit()
    con.close()

    assert _branding(token)["interviewer_name"] == "Avery Singh"


# --- The artefact, not only the tool's return value -----------------------------------------


def _avery():
    """A real Avery, because `Task(agent=...)` validates what it is given."""
    from unittest.mock import MagicMock

    from crewai import LLM
    from agents.discovery.stakeholder_interviewer import create_stakeholder_interviewer

    return create_stakeholder_interviewer(slug="t", llm=MagicMock(spec=LLM), tools=[])

def test_averys_compile_instruction_names_every_field_the_tool_returns(project_dir, monkeypatch):
    """The artefact is what has to say who conducted each interview, not the tool's return.

    `_get_transcripts` supplies `interviewer_agent_id` and `voice_config`, but Avery's task
    specifies the exact element shape she compiles into `interview_transcripts`, and it named
    neither - so the artefact would not have carried the interviewer however faithfully the
    tool returned it. That is this codebase's recurring failure arriving in an *argument*: the
    ownership decision rests on "the transcript now says who conducted each interview", and
    that sentence was one layer along from anything asserted.

    The expected fields are **derived from a real tool call**, not listed here, so the two
    cannot drift apart in either direction.
    """
    from agents.discovery.stakeholder_interviewer import create_stakeholder_interviewer_task

    _mock_voice_metadata(monkeypatch, {AVERY_VOICE_ID: "male", LAURA_VOICE_ID: "female"})
    slug = "artefact-shape"
    _make_project(slug, {"interviewer_selection": "always_female"}, stakeholders=1)
    _create_sessions(slug, _plan(1))

    con = sqlite3.connect(str(project_dir / f"{slug}.db"))
    con.execute(
        "UPDATE interview_sessions SET status='completed', transcript_json=?",
        (json.dumps([{"question": "q", "answer": "a"}]),),
    )
    con.commit()
    con.close()

    tool = InterviewSessionTool(slug=slug, orchestration_run_id=1)
    returned = json.loads(tool._run("get_transcripts", [], []))[0]

    task = create_stakeholder_interviewer_task(agent=_avery(), context_tasks=[])

    # **The element block, not the whole description**, and the difference is not pedantry: the
    # first version of this assertion searched the description and passed while the field was
    # missing from the shape, because the sentence *below* the shape happens to name it. That
    # is the same trap CLAUDE.md records as "the refusal message quotes the key it is refusing"
    # - an assertion satisfied by text the author of the test put there. Found by power-check.
    opening = 'each element is:\n'
    start = task.description.index(opening) + len(opening)
    element = task.description[start:task.description.index("   }\n", start)]

    # `transcript_json` is the one field the compile step deliberately reshapes - it becomes
    # `qa_pairs`. Everything else the tool hands over must appear in the shape itself, or it
    # cannot reach the interview_transcripts artefact however faithfully the tool returns it.
    for field in set(returned) - {"transcript_json"}:
        assert field in element, (
            f"get_transcripts returns {field!r} and Avery's compile instruction does not name "
            f"it in the element shape, so it cannot reach the interview_transcripts artefact"
        )


def test_averys_prompt_does_not_promise_the_plans_voice_is_used(project_dir):
    """The prompt said the tool stores the plan's `voice_config` and to pass entries through
    unchanged. It ignores the plan's voice as of this task, and an instruction describing
    behaviour the code does not have is how an agent is taught to correct something it must
    not touch."""
    from agents.discovery.stakeholder_interviewer import create_stakeholder_interviewer_task

    task = create_stakeholder_interviewer_task(agent=_avery(), context_tasks=[])
    assert "any voice_config in the plan is ignored" in task.description
    assert "Each row stores the session_token, stakeholder_id, node_label, and script_id." in (
        task.description
    )


# --- The fixture writer that had no production caller ---------------------------------------


def test_no_production_module_creates_an_interview_session_but_the_tool():
    """`insert_interview_session` has left `api/database.py`.

    It had no production caller, it had drifted two columns behind the only thing that does
    create sessions, and by this task the sessions it wrote were **refused** by the speak door
    for carrying no stamped voice. CLAUDE.md's rule is "delete it, or make it the producer" -
    it cannot be the producer, because the producer is a synchronous CrewAI tool on `sqlite3`,
    so it is deleted from production and lives in `tests/support_interview_sessions.py` where a
    fixture writer belongs and cannot drift away from a caller it does not have.
    """
    import ast
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    assert "def insert_interview_session" not in (root / "api/database.py").read_text()

    # A text search rather than an AST one, deliberately: the tool's statement is assembled
    # from adjacent string literals, so no single `ast.Constant` holds the whole phrase and a
    # constant-keyed walk would report that *nothing* inserts a session - a green that means
    # the opposite of what it says. `INTO interview_sessions` appears in no comment and in no
    # CREATE statement, which is what makes the plainer technique the right one here.
    inserting = {
        str(path.relative_to(root))
        for directory in ("api", "agents", "scripts")
        for path in (root / directory).rglob("*.py")
        if "INTO interview_sessions" in path.read_text()
    }
    assert inserting == {"agents/tools/interview_session_tool.py"}
