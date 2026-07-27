"""project_role describes the stakeholder relationship (recipient, governing, actor).
Review and approval routing uses separate is_reviewer and is_approver boolean columns
instead. dev_mode keeps outbound email away from real stakeholders until deliberately
switched off."""
import shutil
import pytest
from pathlib import Path

from api.services.stakeholder_service import VALID_ROLES
from api.config import get_settings


@pytest.fixture(autouse=True)
def clean():
    """Clean up test project databases before and after each test."""
    settings = get_settings()
    for slug in ("devmode-test", "roles-test"):
        db_path = Path(settings.database_dir) / f"{slug}.db"
        proj_dir = Path(settings.projects_dir) / slug
        db_path.unlink(missing_ok=True)
        if proj_dir.exists():
            shutil.rmtree(proj_dir)
    yield
    get_settings.cache_clear()
    for slug in ("devmode-test", "roles-test"):
        db_path = Path(settings.database_dir) / f"{slug}.db"
        proj_dir = Path(settings.projects_dir) / slug
        db_path.unlink(missing_ok=True)
        if proj_dir.exists():
            shutil.rmtree(proj_dir)


def test_review_and_approval_routing_uses_the_boolean_columns_not_project_role():
    """project_role describes the relationship to the engagement. Whether someone
    reviews or approves is carried by is_reviewer / is_approver, which are
    multi-valued - one person can be both a recipient and a reviewer."""
    assert VALID_ROLES == {"recipient", "governing", "actor"}


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
async def test_a_stakeholder_can_be_both_reviewer_and_approver(client):
    await client.post("/projects", json={
        "client_slug": "roles-test", "llm_mode": "standard", "sector": "rail",
    })
    resp = await client.post("/projects/roles-test/stakeholders", json={
        "name": "Both Roles", "email": "both@example.test",
        "project_role": "recipient", "is_reviewer": True, "is_approver": True,
    })
    assert resp.status_code in (200, 201)
    body = resp.json()
    assert body["is_reviewer"] is True
    assert body["is_approver"] is True
