# tests/test_chat_retrieval_service.py
from unittest.mock import patch, MagicMock


def _client_returning(documents, metadatas, count=10):
    col = MagicMock()
    col.count.return_value = count
    col.query.return_value = {"documents": [documents], "metadatas": [metadatas]}
    client = MagicMock()
    client.get_collection.return_value = col
    return client, col


def test_returns_attributed_chunks():
    client, col = _client_returning(
        ["chunk one", "chunk two"],
        [{"filename": "a.pdf", "doc_id": 1}, {"filename": "b.docx", "doc_id": 2}],
    )
    with patch("api.services.chat_retrieval_service.get_chroma_client", return_value=client):
        from api.services.chat_retrieval_service import search
        result = search("acme", "what is the process?", k=2)

    assert result == [
        {"text": "chunk one", "filename": "a.pdf", "doc_id": 1},
        {"text": "chunk two", "filename": "b.docx", "doc_id": 2},
    ]
    client.get_collection.assert_called_once_with("acme_docs")
    col.query.assert_called_once_with(query_texts=["what is the process?"], n_results=2)


def test_returns_empty_when_collection_missing():
    client = MagicMock()
    client.get_collection.side_effect = Exception("not found")
    with patch("api.services.chat_retrieval_service.get_chroma_client", return_value=client):
        from api.services.chat_retrieval_service import search
        assert search("acme", "anything") == []


def test_returns_empty_when_client_unreachable():
    with patch("api.services.chat_retrieval_service.get_chroma_client",
               side_effect=Exception("connection refused")):
        from api.services.chat_retrieval_service import search
        assert search("acme", "anything") == []


def test_returns_empty_for_empty_collection():
    client, _ = _client_returning([], [], count=0)
    with patch("api.services.chat_retrieval_service.get_chroma_client", return_value=client):
        from api.services.chat_retrieval_service import search
        assert search("acme", "anything") == []


def test_caps_n_results_at_collection_count():
    client, col = _client_returning(["only chunk"], [{"filename": "a.pdf", "doc_id": 1}], count=1)
    with patch("api.services.chat_retrieval_service.get_chroma_client", return_value=client):
        from api.services.chat_retrieval_service import search
        search("acme", "q", k=6)
    col.query.assert_called_once_with(query_texts=["q"], n_results=1)


def test_tolerates_missing_metadata():
    client, _ = _client_returning(["chunk"], [None])
    with patch("api.services.chat_retrieval_service.get_chroma_client", return_value=client):
        from api.services.chat_retrieval_service import search
        assert search("acme", "q") == [
            {"text": "chunk", "filename": "unknown", "doc_id": None}
        ]
