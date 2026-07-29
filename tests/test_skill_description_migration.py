# tests/test_skill_description_migration.py
"""A description somebody edited belongs to them.

Baseline seeding merges an existing skill's agents but never touched its description,
so the two rewritten in SP20a never reached an existing database. This replaces them -
but only where nobody has edited them.

Note: api/database.py's ``init_system_db`` migrates the pre-relational ``agent_skills``
table into ``skills`` (+ ``agent_skill_assignments``) and drops it, so a current
system.db only ever has ``skills``. These tests write directly to ``skills`` to match
what /admin/skills/seed actually reads and writes.
"""
import pytest

from api.services.skills_service import BASELINE_SKILLS

OLD_PHASE_GATING = (
    "Block every downstream dispatch until the project team explicitly confirms "
    "human review. If review is pending, output the review request and halt — "
    "never proceed without confirmation."
)


def _baseline_description(name: str) -> str:
    for skill in BASELINE_SKILLS:
        if skill["name"] == name:
            return skill["description"]
    raise AssertionError(f"{name!r} is not a baseline skill")


async def _store_skill(name: str, description: str) -> None:
    from api.database import get_system_connection
    async with get_system_connection() as conn:
        await conn.execute("DELETE FROM skills WHERE lower(name)=lower(?)", (name,))
        await conn.execute(
            "INSERT INTO skills (name, description) VALUES (?,?)",
            (name, description),
        )
        await conn.commit()


async def _stored_description(name: str) -> str:
    from api.database import get_system_connection
    async with get_system_connection() as conn:
        async with conn.execute(
            "SELECT description FROM skills WHERE lower(name)=lower(?)", (name,)
        ) as cur:
            row = await cur.fetchone()
    return row["description"] if row else ""


@pytest.fixture(autouse=True)
async def clean():
    yield
    from api.database import get_system_connection
    async with get_system_connection() as conn:
        await conn.execute("DELETE FROM skills WHERE lower(name)='phase gating'")
        await conn.commit()


@pytest.mark.asyncio
async def test_an_untouched_description_is_replaced(client):
    await _store_skill("Phase Gating", OLD_PHASE_GATING)
    assert (await client.post("/admin/skills/seed")).status_code == 200
    assert await _stored_description("Phase Gating") == _baseline_description("Phase Gating")


@pytest.mark.asyncio
async def test_an_edited_description_is_left_alone(client):
    """One character different is still somebody's edit."""
    edited = OLD_PHASE_GATING + " Also check the budget."
    await _store_skill("Phase Gating", edited)
    assert (await client.post("/admin/skills/seed")).status_code == 200
    assert await _stored_description("Phase Gating") == edited


@pytest.mark.asyncio
async def test_a_missing_skill_is_still_seeded(client):
    """The migration must not break the ordinary insert-if-absent path."""
    from api.database import get_system_connection
    async with get_system_connection() as conn:
        await conn.execute("DELETE FROM skills WHERE lower(name)='phase gating'")
        await conn.commit()

    assert (await client.post("/admin/skills/seed")).status_code == 200
    assert await _stored_description("Phase Gating") == _baseline_description("Phase Gating")
