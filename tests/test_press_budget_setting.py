"""The elaboration press budget survives the whole round trip, and reaches the press.

The defect this guards is not a wrong value, it is a vanished one. `ProjectSettings` never
declared `elaboration_press_timeout_seconds`, and pydantic v2 defaults to extra='ignore', so
the UI's PATCH was accepted and the key dropped; `update_project_settings` then wrote
`model_dump()` as the *whole* config_json, erasing any copy already stored; and the GET
endpoint, which carries `response_model=ProjectSettings`, stripped it outbound as well. The
control was dead in both directions while every layer reported success.

So these tests drive the real HTTP endpoints rather than the model, and the last one goes on
to the interview endpoint that consumes the value - a field can round-trip through settings
and still never reach `elaboration_press`, which is the layer the budget actually acts at.
"""
import json
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio

from api.config import get_settings


SETTINGS_BODY = {"sector": "rail", "llm_mode": "standard"}


@pytest_asyncio.fixture
async def project(tmp_path, monkeypatch, client):
    """A real project in an isolated database directory.

    Isolated per test rather than sharing /tmp/agentpool_test: these tests write project
    rows and read them back, and a slug left behind by an earlier run would make them pass
    once and fail afterwards.
    """
    monkeypatch.setenv("DATABASE_DIR", str(tmp_path))
    monkeypatch.setenv("PROJECTS_DIR", str(tmp_path / "projects"))
    get_settings.cache_clear()
    r = await client.post("/projects", json={"client_slug": "press-proj", "sector": "rail"})
    assert r.status_code in (200, 201), r.text
    yield "press-proj"
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_the_press_budget_is_accepted_on_patch_and_returned_on_get(project, client):
    """PATCH then GET through the API - the two directions the field was dropped in."""
    r = await client.patch(
        f"/projects/{project}/settings",
        json={**SETTINGS_BODY, "elaboration_press_timeout_seconds": 25},
    )
    assert r.status_code == 200, r.text
    assert r.json()["elaboration_press_timeout_seconds"] == 25

    r = await client.get(f"/projects/{project}/settings")
    assert r.status_code == 200, r.text
    assert r.json()["elaboration_press_timeout_seconds"] == 25


@pytest.mark.asyncio
async def test_a_zero_budget_is_rejected(project, client):
    """0 is what a cleared number input sends, and it skips every press without a word.

    `Number('') === 0` in the browser, so an operator who clears the box and saves would
    otherwise store a budget that makes `asyncio.wait_for(timeout=0)` time out immediately,
    for ever, with nothing on screen to say the follow-ups had stopped.
    """
    r = await client.patch(
        f"/projects/{project}/settings",
        json={**SETTINGS_BODY, "elaboration_press_timeout_seconds": 0},
    )
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_an_absurd_budget_is_rejected(project, client):
    """The other end of the same fence: a live interviewee will not wait five minutes."""
    r = await client.patch(
        f"/projects/{project}/settings",
        json={**SETTINGS_BODY, "elaboration_press_timeout_seconds": 300},
    )
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_the_stored_budget_is_the_one_the_press_is_given(project, client, tmp_path):
    """The layer that matters: the saved setting reaches `elaboration_press`.

    Settings can round-trip perfectly and the press still run on the hardcoded default -
    that is exactly the shape of the original defect, one layer along. This drives the
    public interview endpoint against a real session in the real project database, and
    asserts on the timeout the press call was actually handed.
    """
    from api.database import (
        get_connection, fetch_project, insert_stakeholder,
    )
    from tests.support_interview_sessions import insert_interview_session

    r = await client.patch(
        f"/projects/{project}/settings",
        json={**SETTINGS_BODY, "elaboration_press_timeout_seconds": 31},
    )
    assert r.status_code == 200, r.text

    async with get_connection(project) as conn:
        row = await fetch_project(conn, slug=project)
        stakeholder_id = await insert_stakeholder(
            conn, project_id=row["id"], name="Alice Chen", job_title="Head of Ops",
        )
        await insert_interview_session(
            conn,
            project_id=row["id"],
            orchestration_run_id=None,
            stakeholder_id=stakeholder_id,
            node_label="Head of Ops",
            session_token="budget-token",
        )

    with patch(
        "api.routers.interviews.elaboration_press",
        new_callable=AsyncMock,
        return_value="Say more?",
    ) as mock_press:
        r = await client.post(
            "/api/interviews/budget-token/elaboration-press",
            json={
                "question_text": "What slows you down?",
                "response_text": "Things.",
                "probing_instructions": "Ask for specifics.",
            },
        )

    assert r.status_code == 200, r.text
    assert mock_press.await_args.kwargs["timeout_seconds"] == 31.0


@pytest.mark.asyncio
async def test_saving_settings_does_not_erase_the_stored_budget(project, client):
    """update_project_settings writes model_dump() as the whole config_json.

    Any key the model does not declare is therefore deleted by the next unrelated save -
    a branding change, say. Asserted against config_json directly because that is the
    column the interview endpoint reads, and a response body can look right while the
    stored row does not.
    """
    from api.database import get_connection, fetch_project

    await client.patch(
        f"/projects/{project}/settings",
        json={**SETTINGS_BODY, "elaboration_press_timeout_seconds": 17},
    )
    await client.patch(
        f"/projects/{project}/settings",
        json={
            **SETTINGS_BODY,
            "elaboration_press_timeout_seconds": 17,
            "brand_interviewer_name": "Avery Singh",
        },
    )

    async with get_connection(project) as conn:
        row = await fetch_project(conn, slug=project)
    assert json.loads(row["config_json"])["elaboration_press_timeout_seconds"] == 17
