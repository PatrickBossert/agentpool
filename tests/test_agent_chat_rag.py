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
