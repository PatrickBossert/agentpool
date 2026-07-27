"""reviewer may review and request changes but cannot approve. dev_mode keeps
outbound email away from real stakeholders until deliberately switched off."""
import pytest

from api.services.stakeholder_service import VALID_ROLES


def test_reviewer_is_a_valid_project_role():
    assert "reviewer" in VALID_ROLES


def test_the_four_roles_are_exactly_these():
    assert VALID_ROLES == {"recipient", "governing", "actor", "reviewer"}


def test_dev_mode_defaults_to_true():
    """A scheduler that emails real stakeholders the first time it runs correctly
    is a worse failure than one that emails nobody."""
    from api.models import ProjectSettings
    assert ProjectSettings(sector="rail").dev_mode is True


@pytest.mark.asyncio
async def test_dev_mode_round_trips_through_the_settings_endpoint(client):
    await client.post("/projects", json={
        "client_slug": "devmode-test", "llm_mode": "standard", "sector": "rail",
    })
    got = await client.get("/projects/devmode-test/settings")
    assert got.json()["dev_mode"] is True

    body = got.json()
    body["dev_mode"] = False
    patched = await client.patch("/projects/devmode-test/settings", json=body)
    assert patched.status_code == 200
    assert patched.json()["dev_mode"] is False

    again = await client.get("/projects/devmode-test/settings")
    assert again.json()["dev_mode"] is False


@pytest.mark.asyncio
async def test_reviewer_role_is_accepted_on_a_stakeholder(client):
    await client.post("/projects", json={
        "client_slug": "reviewer-test", "llm_mode": "standard", "sector": "rail",
    })
    resp = await client.post("/projects/reviewer-test/stakeholders", json={
        "name": "Reviewing Person", "email": "reviewer@example.test",
        "project_role": "reviewer",
    })
    assert resp.status_code in (200, 201)
    assert resp.json()["project_role"] == "reviewer"
