# tests/test_projects_api.py
import json
import shutil
from pathlib import Path

import pytest

from api.config import get_settings


@pytest.fixture(autouse=True)
def clean_test_state():
    """Remove any leftover test-rail state before each test, **where the app actually looks**.

    This asked `get_settings` to forget its cache and then cleaned two hardcoded paths, which
    is only the same directory while nobody overrides the environment. `tests/conftest.py`
    sets `DATABASE_DIR` with `os.environ.setdefault`, so exporting it - which is how two
    sessions run pytest at once without deleting each other's databases - made this fixture
    scrub a directory nothing was using while the real one kept its rows.

    Three tests failed that way and were catalogued for weeks as "fail against a fresh
    database": `test_portfolio_register_returns_data` wrote its fixture file to the hardcoded
    projects directory and the endpoint read the configured one, so it asserted `0 == 1` and
    read as a product defect. It was a path disagreement inside the test.

    The wider consequence is worth stating because it made every count on this project
    provisional: **the suite's green depended on those two paths coinciding**, so a clean
    checkout, a new machine or CI did not reproduce it. Read the directories off the settings
    the code under test reads, and the question of which run poisoned which stops existing.
    """
    get_settings.cache_clear()
    settings = get_settings()
    for d in (Path(settings.database_dir), Path(settings.projects_dir)):
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
    "review_gates": True,
    "slack_channel": "#test",
    "approver_name": "Approver Fixture", "approver_email": "approver@fixture.test",}


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
    resp = await client.post("/projects", json={"client_slug": "minimal-co", "sector": "retail", "approver_name": "Approver Fixture", "approver_email": "approver@fixture.test"})
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
    # Written where the endpoint reads, not where it used to. This line asserting 0 == 1 was
    # catalogued as a fresh-database failure for weeks; it was this path.
    outputs_dir = Path(get_settings().projects_dir) / "test-rail" / "outputs"
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

    # Fetched at the URL the door RETURNED, not at a path written here.
    #
    # This asserted `data["url"] == "/api/projects/..."` and then fetched
    # `/projects/test-rail/branding/image` - a different string - so it proved the file was
    # servable somewhere and the door returned something, and never that the two agreed. They
    # did not: nothing serves `/api/projects/...`, and this door has stored an address that
    # 404s since it was written. It went unseen because no deployment has ever uploaded a
    # header image, so the value was never fetched outside this test.
    #
    # Found on 7 September when the agent portrait door copied the line and its image came back
    # broken in the browser. A URL is a promise that something answers; the assertion is to ask.
    img_resp = await client.get(data["url"])
    assert img_resp.status_code == 200, (
        f"the URL the door returned does not resolve: {data['url']!r}"
    )
    assert "image" in img_resp.headers.get("content-type", "")


def test_every_branding_content_type_has_a_magic_prefix():
    """The allowlist and the prefix table are held equal, because the failure is silent.

    `data[:4].startswith(b"")` is `True` for every payload, so a fourth type added to
    `_IMAGE_CONTENT_TYPES` with no entry in `_MAGIC_BYTES` would get a **vacuous** check and
    nothing on screen would say the door had stopped verifying it. That was live here until the
    lookup became a subscript: it was `.get(file.content_type, b"")`, keyed on the *raw* header
    rather than the validated value, so the default was one type away from being reachable.

    The same guard as `test_every_accepted_content_type_has_a_magic_prefix` on the agent
    portrait door, which is the neighbour this one was found beside - two doors doing the same
    check and only one of them holding it is how the next sweep finds the second.
    """
    from api.routers.projects import _IMAGE_CONTENT_TYPES, _MAGIC_BYTES

    assert set(_MAGIC_BYTES) == set(_IMAGE_CONTENT_TYPES)
    assert all(prefix for prefix in _MAGIC_BYTES.values()), (
        "an empty prefix is a prefix of everything, which is no check at all"
    )


@pytest.mark.asyncio
async def test_a_branding_payload_that_is_not_the_type_it_declares_is_refused(
    client, tmp_path, monkeypatch
):
    """The prefix check itself, which had no test of its own at all.

    Without this, the subscript above could be deleted along with the whole check and the suite
    would stay green - the table-equality test proves the tables agree and says nothing about
    the door consulting them.

    **On its own slug, under its own DATABASE_DIR**, and both halves are load-bearing. Written
    first as a re-POST of `PROJECT_PAYLOAD`, it left `test-rail` created and made
    `test_create_project_returns_201` answer 200 on **the next run** - passing once and failing
    for ever afterwards, which is precisely the trap CLAUDE.md says shipped through eight
    reviews. `clean_test_state` above does not save it: that fixture rmtrees the hardcoded
    `/tmp/agentpool_test`, so under an exported DATABASE_DIR it cleans a directory nothing is
    using. Two of the five pre-existing failures in this suite have the same root cause.
    """
    monkeypatch.setenv("DATABASE_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("PROJECTS_DIR", str(tmp_path / "projects"))
    get_settings.cache_clear()

    slug = "branding-magic-byte-check"
    created = await client.post("/projects", json={**PROJECT_PAYLOAD, "client_slug": slug})
    assert created.status_code in (200, 201), created.text

    login = await client.post(
        "/auth/login", data={"username": "admin", "password": "test-admin-pw"}
    )
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

    resp = await client.post(
        f"/projects/{slug}/branding/image",
        headers=headers,
        files={"file": ("header.png", b"\xff\xd8\xff\xe0 not a png", "image/png")},
    )
    assert resp.status_code == 422, resp.text
    assert resp.json()["detail"] == "File content does not match declared content type"

    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_branding_in_session_response():
    """get_session_with_script returns a branding key."""
    import json as _json
    from pathlib import Path
    from unittest.mock import AsyncMock, MagicMock, patch

    from tests.test_interview_service import _stub_interview_db_connection

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
        patch(
            "api.services.interview_service.interview_db_connection",
            _stub_interview_db_connection(),
        ),
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

