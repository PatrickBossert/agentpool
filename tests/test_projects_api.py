# tests/test_projects_api.py
import json
import shutil
from pathlib import Path

import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport

from api.config import get_settings


@pytest.fixture(autouse=True)
def clean_test_state():
    """Remove any leftover test-rail state before each test."""
    get_settings.cache_clear()
    db_dir = Path("/tmp/agentpool_test")
    proj_dir = Path("/tmp/agentpool_test_projects")
    for d in (db_dir, proj_dir):
        if d.exists():
            shutil.rmtree(d)
        d.mkdir(parents=True, exist_ok=True)
    yield


PROJECT_PAYLOAD = {
    "client_slug": "test-rail",
    "llm_mode": "standard",
    "sector": "transport",
    "stakeholder_groups": ["Operations", "Customer"],
    "value_stream_labels": ["Asset Mgmt"],
    "roadmap_time_axis": "quarters",
    "crews_enabled": ["requirements"],
    "review_gates": True,
    "slack_channel": "#test",
}


@pytest.mark.asyncio
async def test_create_project_returns_201(client):
    resp = await client.post("/projects", json=PROJECT_PAYLOAD)
    assert resp.status_code == 201
    data = resp.json()
    assert data["slug"] == "test-rail"
    assert data["status"] == "created"


@pytest.mark.asyncio
async def test_create_project_idempotent(client):
    await client.post("/projects", json=PROJECT_PAYLOAD)
    resp = await client.post("/projects", json=PROJECT_PAYLOAD)
    assert resp.status_code == 200
    data = resp.json()
    assert data["slug"] == "test-rail"


@pytest.mark.asyncio
async def test_get_project_status(client):
    await client.post("/projects", json=PROJECT_PAYLOAD)
    resp = await client.get("/projects/test-rail/status")
    assert resp.status_code == 200
    data = resp.json()
    assert data["project_slug"] == "test-rail"
    assert "crew_runs" in data


@pytest.mark.asyncio
async def test_get_status_unknown_project_returns_404(client):
    resp = await client.get("/projects/does-not-exist/status")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_create_project_minimal_payload(client):
    """POST /projects with only client_slug + sector uses model defaults."""
    resp = await client.post("/projects", json={"client_slug": "minimal-co", "sector": "retail"})
    assert resp.status_code == 201
    data = resp.json()
    assert data["slug"] == "minimal-co"
    assert data["status"] == "created"


@pytest.mark.asyncio
async def test_get_project_status_includes_orchestration_run_field(client):
    await client.post("/projects", json=PROJECT_PAYLOAD)
    resp = await client.get("/projects/test-rail/status")
    assert resp.status_code == 200
    data = resp.json()
    assert "latest_orchestration_run" in data
    assert data["latest_orchestration_run"] is None


@pytest.mark.asyncio
async def test_portfolio_register_empty(client):
    """Returns [] when project exists but portfolio_register.json does not."""
    await client.post("/projects", json=PROJECT_PAYLOAD)
    resp = await client.get("/projects/test-rail/portfolio-register")
    assert resp.status_code == 200
    assert resp.json() == []


@pytest.mark.asyncio
async def test_portfolio_register_returns_data(client):
    """Returns parsed JSON array when portfolio_register.json exists on disk."""
    await client.post("/projects", json=PROJECT_PAYLOAD)

    register = [
        {
            "rank": 1,
            "id": "VP-001",
            "title": "Modernise Asset Management",
            "change_articulation": "Replaces manual inspection logs with IoT-driven data.",
            "impacted_stakeholder_groups": ["Operations", "Safety"],
            "value_estimate": "High",
            "score_financial": 7.0,
            "score_financial_rationale": "Reduces OpEx by automating inspections.",
            "score_financial_unit": "NPV £M",
            "score_manufactured": 6.5,
            "score_manufactured_rationale": "Extends asset life through predictive maintenance.",
            "score_manufactured_unit": "Asset replacement value £M",
            "score_intellectual": 5.5,
            "score_intellectual_rationale": "Generates proprietary sensor datasets.",
            "score_intellectual_unit": "R&D £M / IP count",
            "score_human": 6.0,
            "score_human_rationale": "Upskills maintenance staff in data analysis.",
            "score_human_unit": "FTE-days / skills uplift",
            "score_social_relationship": 5.5,
            "score_social_relationship_rationale": "Improves regulator confidence through transparency.",
            "score_social_relationship_unit": "NPS / beneficiary count",
            "score_natural": 6.0,
            "score_natural_rationale": "Reduces unnecessary site visits and emissions.",
            "score_natural_unit": "CO₂e t / water ML / land ha",
            "score_safety": 8.0,
            "score_safety_rationale": "Early fault detection reduces RIDDOR-reportable incidents.",
            "score_safety_unit": "RIDDOR rate / safety risk score",
            "score_performance": 7.5,
            "score_performance_rationale": "Increases asset availability by reducing unplanned outages.",
            "score_performance_unit": "Throughput % / availability %",
            "total_score": 68.25,
            "weights_used": {
                "financial": 20,
                "manufactured": 10,
                "intellectual": 5,
                "human": 5,
                "social_relationship": 5,
                "natural": 20,
                "safety": 20,
                "performance": 15,
            },
        }
    ]
    outputs_dir = Path("/tmp/agentpool_test_projects/test-rail/outputs")
    outputs_dir.mkdir(parents=True, exist_ok=True)
    (outputs_dir / "portfolio_register.json").write_text(
        json.dumps(register), encoding="utf-8"
    )

    resp = await client.get("/projects/test-rail/portfolio-register")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["id"] == "VP-001"
    assert data[0]["score_financial"] == 7.0
    assert data[0]["weights_used"]["safety"] == 20
    assert data[0]["total_score"] == 68.25


@pytest.mark.asyncio
async def test_portfolio_register_unknown_project(client):
    """Returns 404 when the project does not exist."""
    resp = await client.get("/projects/nonexistent/portfolio-register")
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Branding image upload and serve
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_branding_image_upload_and_serve(client):
    """Upload a small PNG, verify 200 with url field; GET returns image content-type."""
    # Create project
    await client.post("/projects", json=PROJECT_PAYLOAD)

    # Obtain a JWT token
    login_resp = await client.post(
        "/auth/login", data={"username": "admin", "password": "test-admin-pw"}
    )
    assert login_resp.status_code == 200
    token = login_resp.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    # Minimal 1×1 red PNG (valid PNG bytes)
    png_bytes = (
        b"\x89PNG\r\n\x1a\n"
        b"\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x02"
        b"\x00\x00\x00\x90wS\xde"
        b"\x00\x00\x00\x0cIDATx\x9cc\xf8\x0f\x00\x00\x01\x01\x00\x05\x18\xd8N"
        b"\x00\x00\x00\x00IEND\xaeB`\x82"
    )

    resp = await client.post(
        "/projects/test-rail/branding/image",
        headers=headers,
        files={"file": ("header.png", png_bytes, "image/png")},
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert "url" in data
    assert data["url"] == "/api/projects/test-rail/branding/image"

    # GET the image endpoint (no auth)
    img_resp = await client.get("/projects/test-rail/branding/image")
    assert img_resp.status_code == 200
    assert "image" in img_resp.headers.get("content-type", "")


@pytest.mark.asyncio
async def test_branding_in_session_response():
    """get_session_with_script returns a branding key."""
    import json as _json
    from pathlib import Path
    from unittest.mock import AsyncMock, MagicMock, patch

    slug = "branding-proj"
    fake_db = "/tmp/agentpool_test/" + slug + ".db"
    fake_session = {
        "id": 1,
        "session_token": "tok-branding",
        "node_label": "exec_interview",
        "status": "pending",
    }

    with (
        patch(
            "api.services.interview_service._find_session_db", new_callable=AsyncMock
        ) as mock_find,
        patch(
            "api.services.interview_service.fetch_interview_session",
            new_callable=AsyncMock,
        ) as mock_fetch,
        patch("api.services.interview_service.get_settings") as mock_settings,
        patch("aiosqlite.connect"),
    ):
        mock_find.return_value = fake_db
        mock_fetch.return_value = fake_session
        settings_obj = MagicMock()
        settings_obj.projects_dir = "/tmp/agentpool_test_projects"
        mock_settings.return_value = settings_obj

        from api.services.interview_service import get_session_with_script

        result = await get_session_with_script("tok-branding")

    assert result is not None
    assert "branding" in result
    assert "header_image_url" in result["branding"]
    assert "primary_color" in result["branding"]
    assert "text_color" in result["branding"]
    # Defaults when no config stored
    assert result["branding"]["primary_color"] == "#0d9488"
    assert result["branding"]["text_color"] == "#1f2937"


# ── Node template assignment fixtures and tests ───────────────────────────────

@pytest_asyncio.fixture
async def auth_client():
    """AsyncClient with a valid Bearer token for the test admin user."""
    system_db = Path("/tmp/agentpool_test/system.db")
    system_db.unlink(missing_ok=True)
    get_settings.cache_clear()

    from api.main import app
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        login = await ac.post("/auth/login", data={"username": "admin", "password": "test-admin-pw"})
        token = login.json()["access_token"]
        ac.headers.update({"Authorization": f"Bearer {token}"})
        yield ac

    system_db.unlink(missing_ok=True)
    get_settings.cache_clear()


@pytest_asyncio.fixture
async def create_project(auth_client):
    """Create the test-rail project and return its slug."""
    resp = await auth_client.post("/projects", json=PROJECT_PAYLOAD)
    assert resp.status_code in (200, 201)
    return resp.json()["slug"]


@pytest.mark.asyncio
async def test_list_node_templates_empty(auth_client, create_project):
    slug = create_project
    resp = await auth_client.get(f"/projects/{slug}/node-templates")
    assert resp.status_code == 200
    assert resp.json() == []


@pytest.mark.asyncio
async def test_upsert_node_template(auth_client, create_project):
    slug = create_project
    resp = await auth_client.put(
        f"/projects/{slug}/node-templates/Goods-in%20Inspection",
        json={"interview_template_id": 1, "questionnaire_template_id": None},
    )
    assert resp.status_code == 200
    # Verify it appears in list
    list_resp = await auth_client.get(f"/projects/{slug}/node-templates")
    assignments = list_resp.json()
    assert any(a["node_label"] == "Goods-in Inspection" for a in assignments)


@pytest.mark.asyncio
async def test_publish_node_template_not_found(auth_client, create_project):
    slug = create_project
    resp = await auth_client.post(
        f"/projects/{slug}/node-templates/NonExistentNode/publish",
        json={"name": "T1", "description": ""},
    )
    assert resp.status_code == 404


PUBLISH_NODE_LABEL = "FrontlineInterview"
PUBLISH_SCRIPTS = {
    PUBLISH_NODE_LABEL: {
        "node_label": PUBLISH_NODE_LABEL, "level": "L2", "research_brief": "b",
        "sections": [{"section_id": "S1", "title": "Opening", "questions": []}],
    }
}


@pytest_asyncio.fixture
async def versioned_scripts_project(create_project):
    """A project whose only interview_scripts artefact is versioned - what every real
    project has, since insert_agent_output_sync renames every output it records to a _vN
    suffix and leaves nothing at the bare interview_scripts.json path."""
    slug = create_project
    from agents.tools._db import insert_agent_output_sync

    outputs = Path(get_settings().projects_dir) / slug / "outputs"
    outputs.mkdir(parents=True, exist_ok=True)
    draft = outputs / "interview_scripts.json"
    draft.write_text(json.dumps(PUBLISH_SCRIPTS))
    insert_agent_output_sync(slug, "interview_coordinator", "interview_scripts", str(draft))
    assert not draft.exists()
    return slug


@pytest.mark.asyncio
async def test_publishing_a_template_finds_the_current_scripts(auth_client, versioned_scripts_project):
    """It raised 404 for any project whose scripts are versioned, which is all of them.
    A non-404 status alone would pass against an endpoint that fabricates a response without
    reading anything, so this also checks the template actually landed in the system db with
    the right content."""
    slug = versioned_scripts_project
    resp = await auth_client.post(
        f"/projects/{slug}/node-templates/{PUBLISH_NODE_LABEL}/publish",
        json={"name": "Frontline", "description": ""},
    )
    assert resp.status_code == 200
    template_id = resp.json()["template_id"]
    assert template_id

    import aiosqlite
    from api.database import fetch_template, get_system_db_path, init_system_db

    async with aiosqlite.connect(str(get_system_db_path())) as sys_conn:
        sys_conn.row_factory = aiosqlite.Row
        await init_system_db(sys_conn)
        tpl = await fetch_template(sys_conn, template_id)
    assert tpl is not None
    assert tpl["name"] == "Frontline"
    schema = json.loads(tpl["schema_json"])
    assert schema["sections"][0]["section_id"] == "S1"


PUBLISH_ROLE_NODE_LABEL = "FrontlineRoleInterview"
PUBLISH_ROLE_SCRIPTS = {
    PUBLISH_ROLE_NODE_LABEL: {
        "node_label": PUBLISH_ROLE_NODE_LABEL, "level": "L1", "perspective": "F",
        "research_brief": "b",
        "sections": [{"section_id": "S1", "title": "Opening", "questions": []}],
    }
}


@pytest_asyncio.fixture
async def versioned_role_scripts_project(create_project):
    slug = create_project
    from agents.tools._db import insert_agent_output_sync

    outputs = Path(get_settings().projects_dir) / slug / "outputs"
    outputs.mkdir(parents=True, exist_ok=True)
    draft = outputs / "interview_scripts.json"
    draft.write_text(json.dumps(PUBLISH_ROLE_SCRIPTS))
    insert_agent_output_sync(slug, "interview_coordinator", "interview_scripts", str(draft))
    assert not draft.exists()
    return slug


@pytest.mark.asyncio
async def test_publishing_a_role_node_template_strips_its_perspective(
    auth_client, versioned_role_scripts_project
):
    """`level` alone used to carry a role node's identity ('F'), and was stripped. Since the
    split, that identity moved to `perspective` - stripping only `level` would leave a
    published template announcing which stakeholder segment ('F') it was written for, in the
    one place role nuance is explicitly not supposed to live (see value_chain_mapper's "Do
    NOT put role nuance on the node" rule - a template is exactly that kind of shared,
    reusable node-level artefact).
    """
    slug = versioned_role_scripts_project
    resp = await auth_client.post(
        f"/projects/{slug}/node-templates/{PUBLISH_ROLE_NODE_LABEL}/publish",
        json={"name": "Frontline Role", "description": ""},
    )
    assert resp.status_code == 200
    template_id = resp.json()["template_id"]

    import aiosqlite
    from api.database import fetch_template, get_system_db_path, init_system_db

    async with aiosqlite.connect(str(get_system_db_path())) as sys_conn:
        sys_conn.row_factory = aiosqlite.Row
        await init_system_db(sys_conn)
        tpl = await fetch_template(sys_conn, template_id)
    schema = json.loads(tpl["schema_json"])
    assert "level" not in schema
    assert "perspective" not in schema
