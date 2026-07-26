import pytest
from unittest.mock import patch, AsyncMock, MagicMock


def test_format_retrieved_labels_each_chunk_with_its_source():
    from api.services.agent_chat_service import _format_retrieved
    out = _format_retrieved([
        {"text": "alpha text", "filename": "a.pdf", "doc_id": 1},
        {"text": "beta text", "filename": "b.docx", "doc_id": 2},
    ])
    assert "Retrieved from project documents" in out
    assert "[a.pdf] alpha text" in out
    assert "[b.docx] beta text" in out


def test_format_retrieved_empty_returns_empty_string():
    from api.services.agent_chat_service import _format_retrieved
    assert _format_retrieved([]) == ""


@pytest.mark.asyncio
async def test_retrieved_chunks_reach_the_system_prompt(client):
    """The user's message is used as the query and results land in the prompt."""
    await client.post("/projects", json={
        "client_slug": "rag-test", "llm_mode": "standard", "sector": "rail",
    })

    captured = {}

    async def fake_create(**kwargs):
        captured["system"] = kwargs.get("system", "")
        r = MagicMock()
        r.content = [MagicMock(text="ok")]
        return r

    with patch("api.services.agent_chat_service.AsyncAnthropic") as mock_cls, \
         patch("api.services.agent_chat_service.retrieve_chunks") as mock_search:
        mock_search.return_value = [
            {"text": "the warehouse runs two shifts", "filename": "ops.pdf", "doc_id": 1},
        ]
        inst = AsyncMock()
        inst.messages.create = fake_create
        mock_cls.return_value = inst

        resp = await client.post("/projects/rag-test/agent-chat", json={
            "agent_name": "Interview Coordinator",
            "message": "how many shifts?",
            "history": [],
        })

    assert resp.status_code == 200
    mock_search.assert_called_once()
    assert mock_search.call_args.args[0] == "rag-test"
    assert mock_search.call_args.args[1] == "how many shifts?"
    assert "the warehouse runs two shifts" in captured["system"]
    assert "[ops.pdf]" in captured["system"]


@pytest.mark.asyncio
async def test_no_retrieval_results_produces_no_retrieval_section(client):
    await client.post("/projects", json={
        "client_slug": "rag-empty", "llm_mode": "standard", "sector": "rail",
    })
    captured = {}

    async def fake_create(**kwargs):
        captured["system"] = kwargs.get("system", "")
        r = MagicMock()
        r.content = [MagicMock(text="ok")]
        return r

    with patch("api.services.agent_chat_service.AsyncAnthropic") as mock_cls, \
         patch("api.services.agent_chat_service.retrieve_chunks", return_value=[]):
        inst = AsyncMock()
        inst.messages.create = fake_create
        mock_cls.return_value = inst
        await client.post("/projects/rag-empty/agent-chat", json={
            "agent_name": "Interview Coordinator", "message": "hello", "history": [],
        })

    assert "Retrieved from project documents" not in captured["system"]


import base64
from pathlib import Path


def test_image_media_types_cover_every_accepted_suffix():
    from api.routers.agent_chat import _IMAGE_SUFFIXES
    from api.services.agent_chat_service import IMAGE_MEDIA_TYPES
    assert set(IMAGE_MEDIA_TYPES) == _IMAGE_SUFFIXES


@pytest.mark.asyncio
async def test_image_becomes_a_base64_content_block(client, tmp_path):
    """An attached image is sent to Claude as an image block, not as text."""
    await client.post("/projects", json={
        "client_slug": "vision-test", "llm_mode": "standard", "sector": "rail",
    })

    png_bytes = b"\x89PNG\r\n\x1a\nFAKEIMAGEDATA"
    img = tmp_path / "chart.png"
    img.write_bytes(png_bytes)

    from api.database import get_connection, fetch_project, insert_document
    async with get_connection("vision-test") as conn:
        project = await fetch_project(conn, slug="vision-test")
        doc_id = await insert_document(
            conn, project_id=project["id"], filename="chart.png",
            original_name="chart.png", file_path=str(img),
            content_type="image/png", size_bytes=len(png_bytes),
        )

    captured = {}

    async def fake_create(**kwargs):
        captured["messages"] = kwargs.get("messages", [])
        r = MagicMock()
        r.content = [MagicMock(text="ok")]
        return r

    with patch("api.services.agent_chat_service.AsyncAnthropic") as mock_cls, \
         patch("api.services.agent_chat_service.retrieve_chunks", return_value=[]):
        inst = AsyncMock()
        inst.messages.create = fake_create
        mock_cls.return_value = inst
        resp = await client.post("/projects/vision-test/agent-chat", json={
            "agent_name": "Interview Coordinator",
            "message": "what does this show?",
            "history": [],
            "injected_docs": [
                {"doc_id": doc_id, "original_name": "chart.png", "is_image": True}
            ],
        })

    assert resp.status_code == 200
    final = captured["messages"][-1]
    blocks = final["content"]
    assert isinstance(blocks, list)
    image_blocks = [b for b in blocks if b["type"] == "image"]
    assert len(image_blocks) == 1
    assert image_blocks[0]["source"]["media_type"] == "image/png"
    assert image_blocks[0]["source"]["data"] == base64.b64encode(png_bytes).decode()
    text_blocks = [b for b in blocks if b["type"] == "text"]
    assert text_blocks[0]["text"] == "what does this show?"


@pytest.mark.asyncio
async def test_text_only_turn_sends_a_plain_string(client):
    """With no images the message stays a plain string - no needless block wrapping."""
    await client.post("/projects", json={
        "client_slug": "vision-none", "llm_mode": "standard", "sector": "rail",
    })
    captured = {}

    async def fake_create(**kwargs):
        captured["messages"] = kwargs.get("messages", [])
        r = MagicMock()
        r.content = [MagicMock(text="ok")]
        return r

    with patch("api.services.agent_chat_service.AsyncAnthropic") as mock_cls, \
         patch("api.services.agent_chat_service.retrieve_chunks", return_value=[]):
        inst = AsyncMock()
        inst.messages.create = fake_create
        mock_cls.return_value = inst
        await client.post("/projects/vision-none/agent-chat", json={
            "agent_name": "Interview Coordinator", "message": "hi", "history": [],
        })

    assert captured["messages"][-1]["content"] == "hi"
