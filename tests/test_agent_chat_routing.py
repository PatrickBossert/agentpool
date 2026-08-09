# tests/test_agent_chat_routing.py
"""Agent Chat is subject to the same secure-mode guarantee as the crews.

The panel assembles a project's agent outputs, Chroma chunks of the client's ingested
documents, base64 images from those documents, and the conversation so far, then sends the
lot to a model. llm_mode appeared nowhere in the module: every one of those went to hosted
Haiku, on a sensitive project as readily as on any other. From the consultant's point of view
that panel is the agents, and CLAUDE.md now states there is no always-hosted path left.

Every assertion here is on the request that went out, through a fake httpx transport, rather
than on a swapped-out client class - the protocol and the destination are both part of the
property.
"""
import base64
import json
from pathlib import Path

import httpx
import pytest
import pytest_asyncio

from api.config import get_settings


@pytest_asyncio.fixture
async def two_chat_projects(tmp_path, monkeypatch):
    """One sensitive project and one standard one, built through the real schema.

    get_connection runs the migrations on open, so this is the same shape production has -
    the agent chat path reads a dozen tables and a hand-rolled subset would drift.
    """
    monkeypatch.setenv("DATABASE_DIR", str(tmp_path))
    monkeypatch.setenv("PROJECTS_DIR", str(tmp_path / "projects"))
    get_settings.cache_clear()
    from api.database import get_connection, insert_project
    from api.services import chroma_client

    local = {"local_fast_model": "gemma4:fast", "local_fast_url": "http://localhost:11999/v1"}
    async with get_connection("sense-chat") as conn:
        await insert_project(conn, slug="sense-chat", llm_mode="sensitive", sector="rail",
                             config_json=json.dumps(local))
    async with get_connection("open-chat") as conn:
        await insert_project(conn, slug="open-chat", llm_mode="standard", sector="rail",
                             config_json=json.dumps({}))
    chroma_client._MODE_CACHE.clear()
    yield tmp_path
    chroma_client._MODE_CACHE.clear()
    get_settings.cache_clear()


def _capture_local_calls(monkeypatch, *, reply: str = "Local answer."):
    """Point the shared local-model client at an httpx.MockTransport and record requests."""
    from api.services import http_clients

    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200, json={"choices": [{"message": {"role": "assistant", "content": reply}}]}
        )

    monkeypatch.setattr(
        http_clients, "_local_llm_client",
        httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )
    return requests


@pytest.mark.asyncio
async def test_a_sensitive_project_s_chat_never_reaches_a_hosted_model(
    two_chat_projects, monkeypatch, client
):
    """The whole panel, end to end: the outputs, the retrieved chunks, and the question."""
    requests = _capture_local_calls(monkeypatch)

    response = await client.post(
        "/projects/sense-chat/agent-chat",
        json={"agent_name": "Roadmap Generator",
              "message": "Which initiative is first?",
              "history": []},
    )

    assert response.status_code == 200, response.text
    assert response.json()["response"] == "Local answer."
    assert len(requests) == 1, "agent chat did not reach the project's local model"
    assert str(requests[0].url) == "http://localhost:11999/v1/chat/completions"
    body = json.loads(requests[0].content)
    assert body["model"] == "gemma4:fast"
    # The system prompt carries the project context, so it has to travel by the local route
    # too - not be dropped on the way across protocols.
    assert body["messages"][0]["role"] == "system"
    assert "sense-chat" in body["messages"][0]["content"]


@pytest.mark.asyncio
async def test_a_sensitive_project_refuses_an_image_rather_than_sending_it(
    two_chat_projects, monkeypatch, client
):
    """Refused, with a message, rather than quietly stripped or quietly sent.

    Image content blocks are an Anthropic message shape; the local chat-completions path this
    routes through cannot carry them. Dropping them would answer a different question from the
    one asked, and sending them hosted is the leak.
    """
    tmp_path = two_chat_projects
    from api.database import get_connection, fetch_project, insert_document

    image = tmp_path / "site-plan.png"
    image.write_bytes(base64.b64decode(
        b"iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
    ))
    async with get_connection("sense-chat") as conn:
        project = await fetch_project(conn, slug="sense-chat")
        doc_id = await insert_document(
            conn, project_id=project["id"], filename="site-plan.png",
            original_name="site-plan.png", file_path=str(image),
            content_type="image/png", size_bytes=image.stat().st_size,
        )

    requests = _capture_local_calls(monkeypatch)
    response = await client.post(
        "/projects/sense-chat/agent-chat",
        json={"agent_name": "Roadmap Generator",
              "message": "What does this show?",
              "history": [],
              "injected_docs": [{"doc_id": doc_id, "original_name": "site-plan.png",
                                 "is_image": True}]},
    )

    assert response.status_code == 503, response.text
    assert "sensitive" in response.json()["detail"].lower()
    assert requests == [], "the refusal must happen before anything is sent anywhere"


@pytest.mark.asyncio
async def test_a_standard_project_s_chat_still_goes_hosted_on_its_own_fast_model(
    two_chat_projects, monkeypatch, client
):
    """The other side of the switch, and no hardcoded model on it either."""
    from unittest.mock import AsyncMock, MagicMock
    from api.services import llm_client

    block = MagicMock()
    block.text = "Hosted answer."
    reply = MagicMock()
    reply.content = [block]
    hosted = MagicMock()
    hosted.messages.create = AsyncMock(return_value=reply)
    monkeypatch.setattr(llm_client, "get_anthropic_client", lambda: hosted)
    requests = _capture_local_calls(monkeypatch)

    response = await client.post(
        "/projects/open-chat/agent-chat",
        json={"agent_name": "Roadmap Generator", "message": "And here?", "history": []},
    )

    assert response.status_code == 200, response.text
    assert response.json()["response"] == "Hosted answer."
    assert requests == []
    sent = hosted.messages.create.await_args.kwargs
    assert sent["model"] == "claude-haiku-4-5-20251001", (
        "the hosted branch must read the project's anthropic_fast_model, not a literal"
    )
