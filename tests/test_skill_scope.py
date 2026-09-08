# tests/test_skill_scope.py
"""A skill knows where it applies, and the injection honours it.

Until sp65 a skill applied to **every** project, because the project/global choice was
designed and never built: `skills.source_project` recorded where a rule came from and nothing
filtered injection on it. `scope` is the column the reviewer's decision is stored in and
`_skill_applies_here` is the filter that reads it.

Two things this file is careful about, both because they are the ways this could pass without
holding.

**The migration and the default are two different decisions.** The rows that predate the
column become `global`; a row written afterwards is `project`. A column that simply defaulted
to `global` would satisfy the first and silently make every future proposal universal, which
is the failure the scope exists to prevent - so both are asserted, in one test, against a
database built the way the live one actually is.

**The scope tests assert the injected text, not the row.** The property is that a rule
decided on one engagement does not reach another engagement's prompt, and the row is one
layer away from that. Each is paired with a control in the same style: a global skill that
does reach both, and a project-scoped one that does reach its own. Without those, a filter
that dropped everything and a filter that dropped nothing would each pass half of this file.

Nothing here reaches a provider. The injection path reads the database only, and the one test
that calls `propose_skill` does so against an agent with no rules already held, which returns
before any comparison is made - asserted by an autouse fixture that fails the test if the
completion seam is called at all.
"""
import sqlite3

import pytest

from api.config import get_settings
from api.services.run_service import _fetch_skill_notes, _SNAKE_TO_DISPLAY, _skill_applies_here

AGENT = "interaction_designer"
CREW = "assessment_design"
DISPLAY = _SNAKE_TO_DISPLAY[AGENT]

PROJECT_A = "scope-engagement-a"
PROJECT_B = "scope-engagement-b"

# Patrick's worked example, and the reason the scope cannot be derived from the rule's text:
# one correction on one engagement could honestly produce either of these.
GLOBAL_RULE = (
    "Do not include specific investment figures; refer to investments by their purpose."
)
PROJECT_RULE = "This client calls it the renewals programme, not the CapEx allocation."
UNATTRIBUTABLE_RULE = "A rule filed before anybody recorded which engagement it came from."


@pytest.fixture(autouse=True)
def _isolated_system_db(tmp_path, monkeypatch):
    """A system.db of this test's own, so the migration can be driven from a known start."""
    monkeypatch.setenv("DATABASE_DIR", str(tmp_path))
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture(autouse=True)
def _no_provider(monkeypatch):
    """No test in this file may reach a model.

    `propose_skill` compares a proposal against the rules the agent already holds, and that
    comparison is a network call. It is skipped when there are no candidates, which is the
    case every test here sets up - substituted rather than assumed, so a future edit that
    gives the agent a held rule fails loudly instead of spending credit.
    """
    async def _refuse(*a, **k):  # pragma: no cover - the assertion is that this never runs
        raise AssertionError("a test in test_skill_scope.py reached the completion seam")

    monkeypatch.setattr("api.services.llm_client.project_completion", _refuse)


async def _skill(description: str, *, scope: str, source_project: str | None) -> int:
    """One approved skill for Maya, written the way an approval leaves it."""
    from api.database import get_system_connection, insert_skill

    async with get_system_connection() as conn:
        return await insert_skill(
            conn, name=description[:40], description=description, source="revision",
            source_project=source_project, status="approved", scope=scope, agents=[DISPLAY],
        )


async def _scope_of(skill_id: int) -> str:
    from api.database import get_system_connection

    async with get_system_connection() as conn:
        async with conn.execute("SELECT scope FROM skills WHERE id=?", (skill_id,)) as cur:
            row = await cur.fetchone()
    assert row is not None, f"no skill with id {skill_id}"
    return row["scope"]


# ── the migration, and the default, are two decisions ──────────────────────────────────────

def _system_db_as_it_stood_before_the_column(path, rows: list[tuple[str, str]]) -> None:
    """Write a `skills` table in the shape the live deployment's actually has.

    Column-for-column what `data/system.db` held on 9 September - no `scope`, and also none
    of `source_ref`, `proposed_by_agent` or `occurrences`, which the same idempotent block
    adds. Built by hand rather than by running an older version of `init_system_db`, because
    the point is to start from the real prior shape and let the migration meet it.
    """
    conn = sqlite3.connect(str(path))
    conn.execute(
        """CREATE TABLE skills (
               id              INTEGER PRIMARY KEY AUTOINCREMENT,
               name            TEXT NOT NULL,
               description     TEXT NOT NULL,
               source          TEXT NOT NULL DEFAULT 'manual',
               source_project  TEXT,
               status          TEXT NOT NULL DEFAULT 'pending',
               flag_reason     TEXT,
               flag_suggestion TEXT,
               created_at      DATETIME DEFAULT CURRENT_TIMESTAMP,
               reviewed_at     DATETIME,
               reviewed_by     TEXT
           )"""
    )
    conn.executemany(
        "INSERT INTO skills (name, description, source, status) VALUES (?,?,'baseline','approved')",
        rows,
    )
    conn.commit()
    conn.close()


@pytest.mark.asyncio
async def test_the_existing_skills_are_global_and_a_new_one_is_not(tmp_path):
    """Two assertions because they are two decisions.

    A column that simply defaulted to `global` would satisfy the first perfectly and make
    every future proposal universal without anybody choosing it - which is the whole failure
    this task exists to prevent, and it would leave no trace anywhere else.

    The fifty-three rows on the live deployment all carry a NULL `source_project`, which the
    fixture reproduces: had they been left at the narrow default they would reach no
    engagement at all, so the migration is what keeps them working as well as what records
    the judgement.
    """
    from api.database import get_system_connection, insert_skill

    _system_db_as_it_stood_before_the_column(
        tmp_path / "system.db",
        [("Phase Gating", "Pause at the end of every phase."),
         ("Units", "State the units on every figure you carry forward.")],
    )

    async with get_system_connection() as conn:
        async with conn.execute("SELECT id, scope, source_project FROM skills ORDER BY id") as cur:
            migrated = [dict(r) async for r in cur]
        new_id = await insert_skill(
            conn, name="A rule proposed afterwards", description=PROJECT_RULE,
            source="revision", source_project=PROJECT_A, status="pending",
        )

    assert [r["scope"] for r in migrated] == ["global", "global"], (
        "a rule written when global was the only option is affirmed global by the migration"
    )
    assert all(r["source_project"] is None for r in migrated), (
        "the fixture no longer reproduces the live shape, so the test above proves less"
    )
    assert await _scope_of(new_id) == "project", (
        "a skill written after the column exists must earn its reach; a `global` default here "
        "would make every future proposal universal silently"
    )


@pytest.mark.asyncio
async def test_the_door_an_agent_proposes_through_files_a_project_scoped_rule():
    """The default asserted at the door that will actually produce these rows.

    `insert_skill`'s default is what the test above pins; this is the caller, and the two are
    different facts - `propose_skill` could name a scope of its own and nothing above would
    notice. It does not, deliberately: an agent has no standing to decide that a rule it
    inferred from one correction applies to every client, and the reviewer chooses at
    approval.
    """
    from api.services.skills_service import propose_skill

    result = await propose_skill(AGENT, PROJECT_RULE, PROJECT_A, "SC-014")

    assert result["action"] == "created"
    assert await _scope_of(result["skill_id"]) == "project"


@pytest.mark.asyncio
async def test_the_migration_does_not_run_a_second_time(tmp_path):
    """`init_system_db` runs on **every** system connection, and the backfill is unconditional
    within its branch - so if the branch were entered again it would re-widen every
    project-scoped skill on the deployment. The guard is that the column now exists; this is
    the test that says so, because nothing else would notice.
    """
    from api.database import get_system_connection

    _system_db_as_it_stood_before_the_column(
        tmp_path / "system.db", [("Units", "State the units.")]
    )
    async with get_system_connection():
        pass

    narrow = await _skill(PROJECT_RULE, scope="project", source_project=PROJECT_A)
    async with get_system_connection():  # a second, third and fourth connection
        pass
    async with get_system_connection():
        pass

    assert await _scope_of(narrow) == "project"


@pytest.mark.asyncio
async def test_the_column_refuses_a_scope_that_is_neither(tmp_path):
    """`project` and `global` are the vocabulary, and the table holds it rather than a caller.

    The same shape as `status`'s CHECK beside it. Without this a typo stores a scope that is
    not `global`, so `_skill_applies_here` reads it as project-scoped and the rule quietly
    reaches one engagement instead of all of them.
    """
    from api.database import get_system_connection, insert_skill

    async with get_system_connection() as conn:
        with pytest.raises(sqlite3.IntegrityError):
            await insert_skill(
                conn, name="Nonsense", description=GLOBAL_RULE, status="approved",
                scope="everywhere", agents=[DISPLAY],
            )


# ── the injection honours it, and the middle one is the point ──────────────────────────────

@pytest.mark.asyncio
async def test_a_global_skill_reaches_every_engagement():
    """The first control. Without it a filter that dropped everything passes the test below."""
    await _skill(GLOBAL_RULE, scope="global", source_project=PROJECT_A)

    assert GLOBAL_RULE in await _fetch_skill_notes(CREW, PROJECT_A)
    assert GLOBAL_RULE in await _fetch_skill_notes(CREW, PROJECT_B), (
        "a global skill is the agent's published instruction on every engagement, including "
        "the ones it was never proposed on"
    )


@pytest.mark.asyncio
async def test_a_project_scoped_skill_reaches_its_own_engagement():
    """The second control. Without it a filter that dropped nothing passes the test below."""
    await _skill(PROJECT_RULE, scope="project", source_project=PROJECT_A)

    assert PROJECT_RULE in await _fetch_skill_notes(CREW, PROJECT_A)


@pytest.mark.asyncio
async def test_a_project_scoped_skill_does_not_reach_another_engagement():
    """The property, and the reason the column exists.

    Asserted on the injected text rather than on the row: the row has always been able to say
    where a rule came from, and the defect was that nothing between the row and the prompt
    ever asked. A test on the stored `scope` would have passed against the code before this
    change.

    The global rule is asserted present in the same block, from the same call, so this says
    *which* skill was withheld rather than that the agent lost its library.
    """
    await _skill(PROJECT_RULE, scope="project", source_project=PROJECT_A)
    await _skill(GLOBAL_RULE, scope="global", source_project=PROJECT_A)

    injected = await _fetch_skill_notes(CREW, PROJECT_B)

    assert PROJECT_RULE not in injected, (
        "a rule decided on one engagement reached another engagement's prompt"
    )
    assert GLOBAL_RULE in injected, "the filter took the global skill with it"


@pytest.mark.asyncio
async def test_a_project_scoped_skill_that_names_no_engagement_reaches_nothing():
    """An unattributable rule cannot be shown to belong to the engagement being run.

    Withholding is the safe direction: the other default is the universal reach this column
    exists to stop being automatic. Nothing on the live deployment is in this position - the
    fifty-three rows with a NULL `source_project` are all migrated to `global` - and no writer
    produces one silently either. `propose_skill` raises on a blank slug; `POST /admin/skills`
    and `POST /admin/skills/import` can (both accept an optional `source_project`), and both
    file `pending`, so the row is in front of a reviewer before it can reach anything. The
    seed door is the one writer that approves outright, and it names `global`.
    """
    await _skill(UNATTRIBUTABLE_RULE, scope="project", source_project=None)
    await _skill(GLOBAL_RULE, scope="global", source_project=None)

    injected = await _fetch_skill_notes(CREW, PROJECT_A)

    assert UNATTRIBUTABLE_RULE not in injected
    assert GLOBAL_RULE in injected, (
        "a missing source_project must not withhold a rule a reviewer already widened"
    )


@pytest.mark.asyncio
async def test_a_row_written_before_the_column_existed_is_read_narrowly():
    """`scope` absent from the row altogether, which is what a hand-built fixture or a table
    older than this column hands the filter. It falls to `project`, not to `global` - a
    default is not a defect, but a default pointing the wrong way is.
    """
    assert _skill_applies_here(PROJECT_A, {"source_project": PROJECT_A}) is True
    assert _skill_applies_here(PROJECT_B, {"source_project": PROJECT_A}) is False
    assert _skill_applies_here(PROJECT_B, {"description": "nothing at all"}) is False


@pytest.mark.asyncio
async def test_the_status_gate_still_decides_first():
    """Scope is a second filter, never a replacement for the first.

    A pending proposal is scoped `project` and filed with the engagement it was made on, so a
    scope filter alone would inject it into that engagement's very next run - approval gate
    bypassed for the project that proposed it, which is the case the two filters together have
    to refuse.
    """
    from api.database import get_system_connection, insert_skill

    async with get_system_connection() as conn:
        await insert_skill(
            conn, name="Not yet approved", description=PROJECT_RULE, source="revision",
            source_project=PROJECT_A, status="pending", agents=[DISPLAY],
        )

    assert PROJECT_RULE not in await _fetch_skill_notes(CREW, PROJECT_A)


# ── the one writer that approves its own rows ──────────────────────────────────────────────

@pytest.mark.asyncio
async def test_the_baseline_seed_writes_global_skills(client):
    """The factory library is universal by definition, and it is the one write with no
    reviewer between it and the prompt.

    Left at the narrow default these rows would be `project`-scoped with no `source_project`,
    so every baseline skill would reach no engagement at all - and `POST
    /admin/skills/seed?force=true`, whose whole purpose is to re-apply corrected descriptions,
    would delete a working library and rebuild it dead. Asserted on the stored rows, because
    the response is a count and a count cannot tell the two apart.
    """
    from api.database import get_system_connection

    seeded = await client.post("/admin/skills/seed")
    assert seeded.status_code == 200
    assert seeded.json()["seeded"] > 0

    async with get_system_connection() as conn:
        async with conn.execute(
            "SELECT scope, COUNT(*) AS n FROM skills WHERE source='baseline' GROUP BY scope"
        ) as cur:
            by_scope = {r["scope"]: r["n"] async for r in cur}

    assert set(by_scope) == {"global"}, f"baseline skills were seeded as {by_scope}"
