# tests/test_skill_agent_migration.py
"""An agent assignment somebody edited belongs to them.

Baseline seeding merges an existing skill's agents but never removes one, so taking
"Value Chain Mapper" off "Diagram Rendering" in the seed data never reaches a database that
has already been seeded. This corrects it - but only where the stored assignment still
matches the list as it shipped, exactly. That is the same self-limiting shape as the
description correction in test_skill_description_migration.py.
"""
import pytest

from api.routers.skills import _SUPERSEDED_AGENTS
from api.services.skills_service import BASELINE_SKILLS

SKILL = "Diagram Rendering"


def _baseline_agents(name: str) -> list[str]:
    for skill in BASELINE_SKILLS:
        if skill["name"] == name:
            return skill["agents"]
    raise AssertionError(f"{name!r} is not a baseline skill")


async def _store_skill(name: str, agents: list[str]) -> None:
    from api.database import get_system_connection
    async with get_system_connection() as conn:
        async with conn.execute(
            "SELECT id FROM skills WHERE lower(name)=lower(?)", (name,)
        ) as cur:
            for row in await cur.fetchall():
                await conn.execute(
                    "DELETE FROM agent_skill_assignments WHERE skill_id=?", (row["id"],)
                )
        await conn.execute("DELETE FROM skills WHERE lower(name)=lower(?)", (name,))
        cur = await conn.execute(
            "INSERT INTO skills (name, description, source, status) VALUES (?,?,?,?)",
            (name, _baseline_description(name), "baseline", "approved"),
        )
        skill_id = cur.lastrowid
        await conn.executemany(
            "INSERT INTO agent_skill_assignments (skill_id, agent_name) VALUES (?,?)",
            [(skill_id, a) for a in agents],
        )
        await conn.commit()


def _baseline_description(name: str) -> str:
    for skill in BASELINE_SKILLS:
        if skill["name"] == name:
            return skill["description"]
    raise AssertionError(f"{name!r} is not a baseline skill")


async def _stored_agents(name: str) -> list[str]:
    from api.database import get_system_connection
    async with get_system_connection() as conn:
        async with conn.execute(
            "SELECT a.agent_name FROM agent_skill_assignments a "
            "JOIN skills s ON s.id = a.skill_id WHERE lower(s.name)=lower(?)",
            (name,),
        ) as cur:
            rows = await cur.fetchall()
    return sorted(r["agent_name"] for r in rows)


@pytest.fixture(autouse=True)
async def clean():
    yield
    from api.database import get_system_connection
    async with get_system_connection() as conn:
        async with conn.execute(
            "SELECT id FROM skills WHERE lower(name)=lower(?)", (SKILL,)
        ) as cur:
            for row in await cur.fetchall():
                await conn.execute(
                    "DELETE FROM agent_skill_assignments WHERE skill_id=?", (row["id"],)
                )
        await conn.execute("DELETE FROM skills WHERE lower(name)=lower(?)", (SKILL,))
        await conn.commit()


@pytest.mark.asyncio
async def test_the_mapper_is_removed_from_an_untouched_assignment(client):
    await _store_skill(SKILL, _SUPERSEDED_AGENTS[SKILL.lower()])
    assert (await client.post("/admin/skills/seed")).status_code == 200
    assert await _stored_agents(SKILL) == sorted(_baseline_agents(SKILL))
    assert "Value Chain Mapper" not in await _stored_agents(SKILL)


@pytest.mark.asyncio
async def test_the_architect_still_holds_the_skill_afterwards(client):
    """The correction removes one agent, not the skill - that agent still draws diagrams."""
    await _store_skill(SKILL, _SUPERSEDED_AGENTS[SKILL.lower()])
    assert (await client.post("/admin/skills/seed")).status_code == 200
    assert "Enterprise Architect" in await _stored_agents(SKILL)


@pytest.mark.asyncio
async def test_an_edited_assignment_is_left_alone(client):
    """One agent different is still somebody's edit, so nothing is touched - including the
    Value Chain Mapper entry, which stays because the list is no longer the shipped one."""
    edited = _SUPERSEDED_AGENTS[SKILL.lower()] + ["Portfolio Manager"]
    await _store_skill(SKILL, edited)
    assert (await client.post("/admin/skills/seed")).status_code == 200
    assert await _stored_agents(SKILL) == sorted(edited)


@pytest.mark.asyncio
async def test_running_the_seed_twice_changes_nothing_further(client):
    await _store_skill(SKILL, _SUPERSEDED_AGENTS[SKILL.lower()])
    assert (await client.post("/admin/skills/seed")).status_code == 200
    once = await _stored_agents(SKILL)
    assert (await client.post("/admin/skills/seed")).status_code == 200
    assert await _stored_agents(SKILL) == once


@pytest.mark.asyncio
async def test_a_missing_skill_is_still_seeded_without_the_mapper(client):
    """The correction must not break the ordinary insert-if-absent path."""
    assert (await client.post("/admin/skills/seed")).status_code == 200
    stored = await _stored_agents(SKILL)
    assert "Enterprise Architect" in stored
    assert "Value Chain Mapper" not in stored
