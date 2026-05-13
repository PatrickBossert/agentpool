# tests/test_interviews_router.py
"""Tests for public interview API endpoints."""
from unittest.mock import AsyncMock, patch

import pytest


FAKE_SESSION = {
    "session": {
        "id": 1,
        "session_token": "test-token-abc",
        "node_label": "Stakeholder A",
        "status": "pending",
    },
    "script": {"questions": []},
}


# ---------------------------------------------------------------------------
# 1. GET /{session_token} — not found
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_interview_session_not_found(client):
    r = await client.get("/api/interviews/unknown-token-xyz")
    assert r.status_code == 404
    assert r.json()["detail"] == "Session not found"


# ---------------------------------------------------------------------------
# 2. GET /{session_token} — success
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_interview_session_success(client):
    with patch(
        "api.routers.interviews.get_session_with_script",
        new_callable=AsyncMock,
        return_value=FAKE_SESSION,
    ):
        r = await client.get("/api/interviews/test-token-abc")
    assert r.status_code == 200
    data = r.json()
    assert data["session"]["session_token"] == "test-token-abc"
    assert "script" in data


# ---------------------------------------------------------------------------
# 3. POST /{session_token}/speak — not found
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_speak_not_found(client):
    r = await client.post(
        "/api/interviews/unknown-token-xyz/speak",
        json={"text": "Hello", "voice_id": "voice_123"},
    )
    assert r.status_code == 404
    assert r.json()["detail"] == "Session not found"


# ---------------------------------------------------------------------------
# 4. POST /{session_token}/speak — success
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_speak_success(client):
    fake_audio = b"\xff\xfb\x90\x00" * 16  # fake MP3 bytes

    with patch(
        "api.routers.interviews.get_session_with_script",
        new_callable=AsyncMock,
        return_value=FAKE_SESSION,
    ), patch(
        "api.routers.interviews.speak",
        new_callable=AsyncMock,
        return_value=fake_audio,
    ):
        r = await client.post(
            "/api/interviews/test-token-abc/speak",
            json={"text": "Hello there", "voice_id": "voice_123"},
        )

    assert r.status_code == 200
    assert r.headers["content-type"] == "audio/mpeg"
    assert r.content == fake_audio


# ---------------------------------------------------------------------------
# 5. POST /{session_token}/elaboration-press — success
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_elaboration_press_success(client):
    with patch(
        "api.routers.interviews.get_session_with_script",
        new_callable=AsyncMock,
        return_value=FAKE_SESSION,
    ), patch(
        "api.routers.interviews.elaboration_press",
        new_callable=AsyncMock,
        return_value="Could you expand on that point?",
    ):
        r = await client.post(
            "/api/interviews/test-token-abc/elaboration-press",
            json={
                "question_text": "What are your main challenges?",
                "response_text": "Many things.",
                "probing_instructions": "Ask for specifics.",
                "stakeholder_name": "Alice",
            },
        )

    assert r.status_code == 200
    assert r.json() == {"press_text": "Could you expand on that point?"}


# ---------------------------------------------------------------------------
# 6. PATCH /{session_token}/complete — success
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_complete_interview_success(client):
    with patch(
        "api.routers.interviews.complete_session",
        new_callable=AsyncMock,
        return_value=True,
    ):
        r = await client.patch(
            "/api/interviews/test-token-abc/complete",
            json={"qa_pairs": [{"q": "What?", "a": "This."}]},
        )

    assert r.status_code == 200
    assert r.json() == {"ok": True}
