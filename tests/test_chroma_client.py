# tests/test_chroma_client.py
"""CloudClient vs HttpClient selection for a standard-mode project.

get_chroma_client takes a slug (see tests/test_secure_mode_routing.py for the per-project,
sensitive-vs-standard routing this exists to express). These two tests keep their original,
narrower purpose: given a project already resolved as "standard", the choice between
CloudClient and HttpClient still turns on chroma_api_key alone.

Mode resolution is stubbed rather than exercised, since the database lookup path is covered
separately. It is stubbed **at `project_llm_mode`**, patched on the module where
`get_chroma_client` looks the name up. It used to be stubbed by writing "standard" straight
into `chroma_client._MODE_CACHE`, which is worse in two ways that are easy to miss: these
tests would have passed with `project_llm_mode` broken outright, and reaching into another
module's private global is the habit
`tests/test_process_cache.py::test_no_other_test_file_reaches_into_a_private_cache` now
refuses - thirty-two of those reaches had accumulated across eight files, each
re-implementing the isolation `conftest.reset_process_caches` provides once.
"""
from unittest.mock import patch


def test_uses_cloud_client_when_api_key_set():
    with patch("api.services.chroma_client.chromadb") as m_chroma, \
         patch("api.services.chroma_client.get_settings") as m_settings, \
         patch("api.services.chroma_client.project_llm_mode", return_value="standard"):
        m_settings.return_value.chroma_api_key = "ck-test"
        m_settings.return_value.chroma_tenant = "tenant-1"
        m_settings.return_value.chroma_database = "db-1"
        from api.services.chroma_client import get_chroma_client

        get_chroma_client("standard-proj")
    m_chroma.CloudClient.assert_called_once_with(
        tenant="tenant-1", database="db-1", api_key="ck-test"
    )
    m_chroma.HttpClient.assert_not_called()


def test_uses_http_client_when_no_api_key():
    with patch("api.services.chroma_client.chromadb") as m_chroma, \
         patch("api.services.chroma_client.get_settings") as m_settings, \
         patch("api.services.chroma_client.project_llm_mode", return_value="standard"):
        m_settings.return_value.chroma_api_key = ""
        m_settings.return_value.chroma_host = "localhost"
        m_settings.return_value.chroma_port = 8002
        from api.services.chroma_client import get_chroma_client

        get_chroma_client("standard-proj")
    m_chroma.HttpClient.assert_called_once_with(host="localhost", port=8002)
    m_chroma.CloudClient.assert_not_called()
