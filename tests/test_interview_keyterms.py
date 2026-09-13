# tests/test_interview_keyterms.py
"""The recogniser is told the project's own words.

A general-purpose speech recogniser has never heard of the client, so the terms an interview
turns on are the ones it is least likely to get right. This is the vocabulary that goes to
Deepgram, and the property that matters is not that the list is non-empty - it is that the list
is **this engagement's**. A hardcoded list would satisfy a single-project assertion perfectly,
so every assertion here is a pair: this project has it, that project does not.
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import httpx
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from api.config import get_settings
from api.services import interview_service
from api.services.interview_keyterms import (
    MAX_KEYTERMS,
    build_keyterms,
    harvest_strings,
    terms_in_prose,
)
from api.services.interview_service import (
    DEEPGRAM_KEYTERM_PARAM,
    DEEPGRAM_MODEL,
    deepgram_listen_params,
    generate_deepgram_token,
    keyterms_for_project,
)

# Two engagements with nothing in common. The names are the point: each list below must be
# reachable from one project and unreachable from the other, or the builder is a constant.
IBERDROLA_LEDGER = [
    ("1.1", "Renewals CapEx Allocation"),
    ("1.2", "Network Asset Management"),
    ("2.1", "Connections Delivery"),
]
IBERDROLA_SCRIPT = {
    "Order Fulfilment": {
        "node_label": "Connections Delivery",
        "welcome_message": (
            "Thank you for making the time. This conversation is about how work reaches "
            "Iberdrola's group reporting, and how the RIIO-T3 submission is assembled."
        ),
        "sections": [
            {
                "title": "Operations",
                "questions": [
                    {
                        "text": "How does SP Energy Networks decide what Iberdrola sees first?",
                        "probing_instructions": "Press gently on whether Ofgem is consulted.",
                    }
                ],
            }
        ],
        "closing_message": "Thank you.",
    }
}

HARBOUR_LEDGER = [
    ("1.1", "Berth Allocation"),
    ("1.2", "Pilotage Scheduling"),
]
HARBOUR_SCRIPT = {
    "Vessel Handling": {
        "node_label": "Berth Allocation",
        "welcome_message": "This conversation is about how Clydeport schedules a berth.",
        "sections": [
            {
                "title": "Scheduling",
                "questions": [{"text": "Where does Peel Ports set the priority?", "probing_instructions": ""}],
            }
        ],
    }
}


def _seed_project(db_dir: Path, projects_dir: Path, slug: str, ledger, script) -> None:
    """One project database with a value chain ledger, and one scripts artefact beside it."""
    db_dir.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_dir / f"{slug}.db")
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS projects (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            slug TEXT UNIQUE NOT NULL
        );
        CREATE TABLE IF NOT EXISTS value_chain_ledger (
            node_id TEXT PRIMARY KEY,
            project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
            label TEXT NOT NULL,
            active INTEGER NOT NULL DEFAULT 1
        );
        """
    )
    conn.execute("INSERT OR IGNORE INTO projects (id, slug) VALUES (1, ?)", (slug,))
    conn.executemany(
        "INSERT OR REPLACE INTO value_chain_ledger (node_id, project_id, label) VALUES (?, 1, ?)",
        ledger,
    )
    conn.commit()
    conn.close()

    outputs = projects_dir / slug / "outputs"
    outputs.mkdir(parents=True, exist_ok=True)
    (outputs / "interview_scripts.json").write_text(json.dumps(script))


@pytest.fixture
def two_engagements(tmp_path, monkeypatch):
    """Two seeded projects and one with nothing at all, in a directory of this test's own.

    `monkeypatch.setenv` plus `get_settings.cache_clear()` on **both** sides, per CLAUDE.md:
    the settings object is cached for the process, and a test that points it somewhere and does
    not put it back poisons every later test that reads a directory off it.
    """
    db_dir = tmp_path / "db"
    projects_dir = tmp_path / "projects"
    monkeypatch.setenv("DATABASE_DIR", str(db_dir))
    monkeypatch.setenv("PROJECTS_DIR", str(projects_dir))
    get_settings.cache_clear()

    _seed_project(db_dir, projects_dir, "sp-gs-am", IBERDROLA_LEDGER, IBERDROLA_SCRIPT)
    _seed_project(db_dir, projects_dir, "other-project", HARBOUR_LEDGER, HARBOUR_SCRIPT)
    # The control for step 5: a project database that exists and holds neither ledger nor
    # scripts. Created through sqlite so the file is real rather than absent - "no table" and
    # "no database" are different failures and both have to answer the same way.
    conn = sqlite3.connect(db_dir / "bare-project.db")
    conn.execute("CREATE TABLE IF NOT EXISTS projects (id INTEGER PRIMARY KEY, slug TEXT)")
    conn.commit()
    conn.close()

    yield
    get_settings.cache_clear()


# ---------------------------------------------------------------------------
# Step 3 - the terms come from the project
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_the_keyterms_are_this_project_s_own_words(two_engagements):
    """Two projects with different registries get different keyterms.

    Asserted in **both** directions for both engagements. "Iberdrola is in sp-gs-am's list" is
    satisfied by any function that returns a fixed list containing Iberdrola; only the second
    half of each pair can tell a project-derived answer from a constant.
    """
    ours = await keyterms_for_project("sp-gs-am")
    theirs = await keyterms_for_project("other-project")

    assert "Iberdrola" in ours
    assert "Iberdrola" not in theirs

    assert "Clydeport" in theirs
    assert "Clydeport" not in ours

    # The registry half, which is a different source from the prose half and could fail alone.
    assert "Renewals CapEx Allocation" in ours
    assert "Renewals CapEx Allocation" not in theirs
    assert "Berth Allocation" in theirs
    assert "Berth Allocation" not in ours


@pytest.mark.asyncio
async def test_both_sources_reach_the_list_and_the_registry_leads(two_engagements):
    """Labels first, then prose - and the list is stable across calls.

    The order is asserted because it decides what survives the cap. A registry label is declared
    vocabulary; a proper noun in a question is inferred, and inference goes second.
    """
    ours = await keyterms_for_project("sp-gs-am")
    assert ours[: len(IBERDROLA_LEDGER)] == [label for _, label in IBERDROLA_LEDGER]
    # Multi-word proper nouns out of the prose, which the registry does not carry.
    assert "SP Energy Networks" in ours
    assert "RIIO-T3" in ours
    assert ours == await keyterms_for_project("sp-gs-am")


@pytest.mark.asyncio
async def test_a_retired_node_is_not_in_the_vocabulary(two_engagements, tmp_path):
    """`active = 0` is how a ledger retires an id, and a retired activity is not current words."""
    conn = sqlite3.connect(Path(get_settings().database_dir) / "sp-gs-am.db")
    conn.execute("UPDATE value_chain_ledger SET active = 0 WHERE node_id = '1.1'")
    conn.commit()
    conn.close()
    assert "Renewals CapEx Allocation" not in await keyterms_for_project("sp-gs-am")
    # And the rest of the registry is untouched, so this is about `active` rather than about
    # the read having broken.
    assert "Network Asset Management" in await keyterms_for_project("sp-gs-am")


# ---------------------------------------------------------------------------
# Step 5 - a project with nothing connects with nothing, rather than failing
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_a_project_with_no_registry_and_no_scripts_has_no_keyterms(two_engagements):
    """Empty, not an exception. The control without which a fix that never connected passes.

    Three shapes of nothing, because they fail in three different places: a database with no
    ledger table at all, a slug with no database file, and a slug that is not a project.
    """
    assert await keyterms_for_project("bare-project") == []
    assert await keyterms_for_project("no-such-project") == []
    assert await keyterms_for_project("") == []


@pytest.mark.asyncio
async def test_asking_an_unknown_slug_materialises_no_database(two_engagements):
    """A read must never create a project database, and this one had two ways to.

    The ledger half guards on the file existing. The scripts half did not, and it does not touch
    sqlite in any obvious way - but `current_output_path` resolves its ledger row through
    `get_project_id`, which is a bare `sqlite3.connect`, and sqlite creates the file it is
    pointed at. So asking for an unknown slug's vocabulary left an empty database behind.

    Unreachable from the door, which only ever holds a slug it resolved a session out of.
    Asserted anyway: CLAUDE.md states the rule for `caller_roles` and `_stakeholder_matches_
    invite` without an exception for hard-to-reach callers, and a standing rule is not kept by
    the reachability of the places that break it.
    """
    db_dir = Path(get_settings().database_dir)
    before = {p.name for p in db_dir.glob("*.db")}

    assert await keyterms_for_project("never-heard-of-it") == []
    assert await keyterms_for_project("") == []

    assert {p.name for p in db_dir.glob("*.db")} == before


@pytest.mark.asyncio
async def test_a_project_with_nothing_still_gets_a_connection_to_open(two_engagements):
    """And the parameters it would connect with are complete and carry no keyterm at all.

    An absent `keyterm` key rather than an empty one: `keyterm=` with no value is a term
    Deepgram would be asked to boost, and the point of this case is that it is asked for none.
    """
    params = deepgram_listen_params(await keyterms_for_project("bare-project"), "en")
    assert params["model"] == DEEPGRAM_MODEL
    assert params["language"] == "en"
    assert DEEPGRAM_KEYTERM_PARAM not in params


# ---------------------------------------------------------------------------
# The model and the parameter are one decision
# ---------------------------------------------------------------------------

def test_the_model_and_the_boost_parameter_are_chosen_together():
    """`keyterm` is Nova-3's feature; `keywords` is Nova-2's, and the mismatch is silent.

    Deepgram ignores a parameter the model does not implement rather than refusing the
    connection, so the wrong pairing is a socket that opens, transcribes, and boosts nothing -
    which is indistinguishable from this task never having been done. The pairing is therefore
    asserted rather than commented, and the assertion names both halves.
    """
    assert DEEPGRAM_MODEL.startswith("nova-3")
    assert DEEPGRAM_KEYTERM_PARAM == "keyterm"
    params = deepgram_listen_params(["Iberdrola"], "en")
    assert params["keyterm"] == ["Iberdrola"]
    assert "keywords" not in params


@pytest.mark.parametrize(
    "keyterms, language",
    [
        (["Iberdrola"], "en"),
        ([], "en"),
        ([], ""),
        ([], "cy"),
        (["Iberdrola", "renewals programme"], "cy"),
    ],
)
def test_every_connection_opts_out_of_the_model_improvement_programme(keyterms, language):
    """Deepgram's default is **opted in**, so omitting this parameter is a decision.

    Parametrised over every shape the other two inputs take, because the property is that it is
    unconditional: a project with no registry, an engagement with no language stamped, and one
    with both must all carry it. A single-shape assertion would be satisfied by a value set
    beside the keyterms, and the branch a participant's speech actually travels on - a project
    whose vocabulary came back empty - would be the one that opted in.

    Asserted as the string the URL will carry rather than a bool, because `urlencode` renders
    Python's `True` as `True` and Deepgram reads `true`.
    """
    assert deepgram_listen_params(keyterms, language)["mip_opt_out"] == "true"


def test_the_language_is_the_sessions_and_falls_back_to_english():
    assert deepgram_listen_params([], "cy")["language"] == "cy"
    assert deepgram_listen_params([], "")["language"] == "en"


# ---------------------------------------------------------------------------
# The extraction rules, driven directly and in both directions
# ---------------------------------------------------------------------------

def test_a_sentence_initial_capital_is_not_a_proper_noun():
    """The rule is positional, so this is the case it exists for - and its opposite.

    Driven both ways deliberately: a test that only checks "How" is absent passes against an
    extractor that returns nothing at all.
    """
    terms = terms_in_prose("How does the team decide? Please describe the escalation.")
    assert terms == []

    terms = terms_in_prose("How does Iberdrola decide? Please describe Ofgem's escalation.")
    assert "Iberdrola" in terms
    assert "Ofgem" in terms
    assert "How" not in terms
    assert "Please" not in terms


def test_a_sentence_opener_is_dropped_from_the_run_it_begins():
    """The case the positional rule missed, which is the one an interview script is full of.

    A sentence-opening capital was discarded only when the run was **one word** long, so every
    question beginning "If ISS...", "Does GS UK...", "Before I..." kept the opener glued to the
    proper noun beside it. Keyterm prompting biases towards the literal phrase, so "If ISS" is
    worse than useless: it boosts nothing and it takes a place on a capped list of a hundred.

    Measured on the live `sp-gs-am` scripts, v37, on the path a deployment without a value chain
    ledger takes: **16 of the 100 slots** before this, none after.

    The test the module already had drove `"How does Iberdrola decide?"` - where a lowercase
    word separates the opener from the name - so it drove the rule "both ways" in the one
    dimension that could not fail.
    """
    terms = terms_in_prose(
        "If Iberdrola reviews it, escalate. Does Fraikin know? Before ISS arrives, check."
    )
    assert terms == ["Iberdrola", "Fraikin", "ISS"]
    # And the openers are gone rather than merely unjoined.
    assert not [t for t in terms if t.split()[0] in {"If", "Does", "Before"}]


def test_the_cost_of_that_rule_is_the_first_word_of_a_name_that_opens_a_sentence():
    """Stated where it is paid, because it is a real loss and not a rounding error.

    The rule cannot tell "If Iberdrola" from "SP Energy Networks" without a word list, which is
    the one thing this module refuses to be. So a multi-word name that **only ever** opens a
    sentence arrives one word short. That is still the safe direction - "Energy Networks" boosts
    the two words it keeps, where "If Iberdrola" boosts nothing - and the same name used
    anywhere mid-sentence is picked up whole, which in a real script it invariably is.
    """
    assert terms_in_prose("SP Energy Networks owns the asset.") == ["Energy Networks"]
    # Mid-sentence, in the same corpus, and the whole name is kept - which is why the loss is
    # bounded in practice rather than merely acceptable in principle.
    assert "SP Energy Networks" in terms_in_prose(
        "SP Energy Networks owns the asset. The asset is owned by SP Energy Networks."
    )


def test_a_possessive_is_the_name_without_the_possessive():
    assert terms_in_prose("The board reviews Iberdrola's submission.") == ["Iberdrola"]


def test_a_run_of_capitals_is_one_term_rather_than_several():
    terms = terms_in_prose("Work reaches SP Energy Networks before anybody else.")
    assert "SP Energy Networks" in terms
    assert "Energy" not in terms


def test_a_term_too_short_or_too_common_is_dropped():
    # A lone mid-sentence capital that says nothing about any engagement.
    assert terms_in_prose("The review lands in March and is signed off.") == []
    # Too short to be distinctive, and not an acronym.
    assert terms_in_prose("The plan names Ada as the owner.") == []
    # An acronym of three characters is kept - they are the most valuable terms on the list.
    assert "SPT" in terms_in_prose("The plan names SPT as the owner.")


def test_the_most_used_term_leads():
    text = "Work reaches Ofgem. Ofgem reviews it. Somewhere Iberdrola signs it off."
    assert terms_in_prose(text)[0] == "Ofgem"


def test_the_list_is_capped():
    """A vocabulary of everything boosts nothing."""
    labels = [f"Distinctive Activity Number {n}" for n in range(MAX_KEYTERMS + 40)]
    assert len(build_keyterms(labels, "")) == MAX_KEYTERMS


def test_a_label_that_is_a_sentence_is_not_a_term():
    long_label = "The way in which this organisation allocates its renewals expenditure each year"
    assert build_keyterms([long_label, "Berth Allocation"], "") == ["Berth Allocation"]


def test_the_same_term_from_both_sources_appears_once():
    assert build_keyterms(
        ["Berth Allocation"], "Everything begins at Berth Allocation each morning."
    ) == ["Berth Allocation"]


def test_every_string_in_a_script_is_harvested():
    """Named fields would be a second declaration of Maya's output shape, free to fall behind."""
    harvested = harvest_strings(IBERDROLA_SCRIPT)
    assert "Press gently on whether Ofgem is consulted." in harvested
    assert any("Iberdrola" in s for s in harvested)


# ---------------------------------------------------------------------------
# The door, and the grant it hands over
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_the_grant_is_read_the_way_deepgram_answers_it(monkeypatch):
    """`POST /v1/auth/grant` answers `access_token`, and this read `key` until now.

    Asserted against a real `httpx.AsyncClient` over a `MockTransport` rather than by swapping
    the client class, so the request's actual URL, method, headers and body are what the
    assertions see. Nothing reaches the network: the transport is the wire.
    """
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["auth"] = request.headers.get("authorization")
        seen["body"] = request.content
        return httpx.Response(200, json={"access_token": "jwt-from-deepgram", "expires_in": 30})

    real_client = httpx.AsyncClient
    monkeypatch.setattr(
        interview_service.httpx,
        "AsyncClient",
        lambda *a, **kw: real_client(transport=httpx.MockTransport(handler)),
    )
    settings_obj = get_settings()
    monkeypatch.setattr(settings_obj, "deepgram_api_key", "dg-key", raising=False)

    assert await generate_deepgram_token() == "jwt-from-deepgram"
    assert seen["url"] == "https://api.deepgram.com/v1/auth/grant"
    assert seen["auth"] == "Token dg-key"
    # `grant_type` is not a field Deepgram's grant endpoint has, and sending one that is not
    # documented is how a door comes to look configured while being ignored.
    assert b"grant_type" not in (seen["body"] or b"")


@pytest.mark.asyncio
async def test_the_token_door_answers_the_projects_own_words(two_engagements, monkeypatch):
    """One request, two answers - a grant and a vocabulary - and both are this project's.

    The grant expires in thirty seconds, which is why the vocabulary rides with it rather than
    costing a second round trip out of that window.
    """
    from api.main import app
    from api.routers import interviews as interviews_router

    db_path = Path(get_settings().database_dir) / "sp-gs-am.db"
    conn = sqlite3.connect(db_path)
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS interview_sessions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            project_id INTEGER,
            stakeholder_id INTEGER,
            orchestration_run_id INTEGER,
            node_label TEXT,
            script_id TEXT,
            session_token TEXT UNIQUE,
            status TEXT DEFAULT 'pending',
            interviewer_agent_id TEXT,
            voice_config TEXT,
            responses_json TEXT,
            ratings_json TEXT,
            started_at TEXT,
            completed_at TEXT,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        );
        """
    )
    # **A language deliberately unlike the default.** `deepgram_listen_params` falls back to
    # "en", and "en" is also what a natural fixture would seed - so a door that never read the
    # session's stamp at all would answer "en" and satisfy every assertion. That is CLAUDE.md's
    # "a sentinel drawn from the system's own defaults cannot fail", and this is a task whose
    # whole subject is that class of defect. "cy" can only have come from this row.
    conn.execute(
        "INSERT INTO interview_sessions (session_token, node_label, voice_config, status) "
        "VALUES ('tok-1', 'Connections Delivery', ?, 'pending')",
        (json.dumps({"elevenlabs_voice_id": "V", "language": "cy", "country_code": "GB"}),),
    )
    conn.commit()
    conn.close()

    async def fake_grant() -> str:
        return "jwt-for-the-browser"

    monkeypatch.setattr(interviews_router, "generate_deepgram_token", fake_grant)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/interviews/tok-1/deepgram-token")

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["token"] == "jwt-for-the-browser"
    assert body["listen_params"]["model"] == DEEPGRAM_MODEL
    assert "Iberdrola" in body["listen_params"][DEEPGRAM_KEYTERM_PARAM]
    assert "Clydeport" not in body["listen_params"][DEEPGRAM_KEYTERM_PARAM]
    # The session's stamped language, read off the row rather than defaulted.
    assert body["listen_params"]["language"] == "cy"
    # And no second copy of the vocabulary beside the parameters that carry it: a key nothing
    # reads is dead payload and a second place an auditor has to check for what leaves.
    assert "keyterms" not in body


@pytest.mark.asyncio
async def test_a_deployment_with_no_deepgram_key_refuses_rather_than_pretending(
    two_engagements, monkeypatch
):
    """503, so the browser can tell "no recogniser here" from "no session"."""
    from api.main import app
    from api.routers import interviews as interviews_router

    conn = sqlite3.connect(Path(get_settings().database_dir) / "sp-gs-am.db")
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS interview_sessions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_token TEXT UNIQUE,
            node_label TEXT,
            voice_config TEXT,
            status TEXT DEFAULT 'pending'
        );
        """
    )
    conn.execute(
        "INSERT OR IGNORE INTO interview_sessions (session_token, node_label) VALUES ('tok-2', 'x')"
    )
    conn.commit()
    conn.close()

    async def refuse() -> str:
        raise ValueError("DEEPGRAM_API_KEY not configured")

    monkeypatch.setattr(interviews_router, "generate_deepgram_token", refuse)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/interviews/tok-2/deepgram-token")
    assert resp.status_code == 503


# ---------------------------------------------------------------------------
# Step 7 - what leaves the deployment now
# ---------------------------------------------------------------------------

def test_the_participant_speech_reach_is_declared_and_names_both_things_that_travel():
    """The row changes; the gating does not.

    Deepgram was a commitment on the privacy page about a path that did not exist - the portal's
    recogniser was the browser's own and the token door had no caller. It has one now, and the
    declaration has to name **both** things that travel, not only the one an auditor would guess.
    A row naming the audio alone reads as an assurance about the whole connection, which is the
    correction sp62 made to the ElevenLabs row for exactly the same reason.

    Ungated is asserted rather than assumed, the way the participant-image row asserts it: a
    grant appearing here would say a mode stands between an interview and Deepgram, and none
    does - that is the decision CLAUDE.md records, and it is the finding rather than an omission.
    """
    from agents.egress import (
        ALL_GRANTS,
        NO_GRANTS,
        PARTICIPANT_SPEECH_EGRESS,
        Reach,
        _destination,
    )

    assert PARTICIPANT_SPEECH_EGRESS.reaches is Reach.PARTICIPANT_TRANSCRIPTION
    sends = PARTICIPANT_SPEECH_EGRESS.sends
    assert "speech" in sends, "the audio is not named"
    # The half that is new, and the half a reader would not guess from "transcription".
    assert "value chain" in sends and "interview scripts" in sends, (
        "the project's own vocabulary travels with the connection and is not named"
    )

    granted = _destination(Reach.PARTICIPANT_TRANSCRIPTION, ALL_GRANTS)
    withheld = _destination(Reach.PARTICIPANT_TRANSCRIPTION, NO_GRANTS)
    assert granted is withheld, "a grant appears to move this reach, and none does"
    assert granted.leaves_deployment is True
