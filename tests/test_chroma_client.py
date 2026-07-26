# tests/test_chroma_client.py
from unittest.mock import patch, MagicMock


def test_uses_cloud_client_when_api_key_set():
    with patch("api.services.chroma_client.chromadb") as m_chroma, \
         patch("api.services.chroma_client.get_settings") as m_settings:
        m_settings.return_value.chroma_api_key = "ck-test"
        m_settings.return_value.chroma_tenant = "tenant-1"
        m_settings.return_value.chroma_database = "db-1"
        from api.services.chroma_client import get_chroma_client
        get_chroma_client()
    m_chroma.CloudClient.assert_called_once_with(
        tenant="tenant-1", database="db-1", api_key="ck-test"
    )
    m_chroma.HttpClient.assert_not_called()


def test_uses_http_client_when_no_api_key():
    with patch("api.services.chroma_client.chromadb") as m_chroma, \
         patch("api.services.chroma_client.get_settings") as m_settings:
        m_settings.return_value.chroma_api_key = ""
        m_settings.return_value.chroma_host = "localhost"
        m_settings.return_value.chroma_port = 8002
        from api.services.chroma_client import get_chroma_client
        get_chroma_client()
    m_chroma.HttpClient.assert_called_once_with(host="localhost", port=8002)
    m_chroma.CloudClient.assert_not_called()
