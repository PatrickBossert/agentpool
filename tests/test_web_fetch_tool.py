# tests/test_web_fetch_tool.py
from unittest.mock import patch, MagicMock
import pytest
import requests as req_lib
from agents.tools.web_fetch_tool import WebFetchTool


@pytest.fixture
def tool():
    return WebFetchTool()


def test_returns_stripped_text_on_success(tool):
    html = "<html><body><p>Hello world</p></body></html>"
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.text = html
    with patch("agents.tools.web_fetch_tool.requests.get", return_value=mock_response):
        result = tool._run(url="https://example.com")
    assert "Hello world" in result
    assert "<p>" not in result


def test_truncates_long_content(tool):
    html = "<html><body>" + ("x" * 20_000) + "</body></html>"
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.text = html
    with patch("agents.tools.web_fetch_tool.requests.get", return_value=mock_response):
        result = tool._run(url="https://example.com")
    assert len(result) <= 8_100


def test_returns_error_on_non_200(tool):
    mock_response = MagicMock()
    mock_response.status_code = 404
    with patch("agents.tools.web_fetch_tool.requests.get", return_value=mock_response):
        result = tool._run(url="https://example.com/missing")
    assert "Error" in result
    assert "404" in result


def test_returns_error_on_connection_failure(tool):
    with patch("agents.tools.web_fetch_tool.requests.get", side_effect=req_lib.RequestException("timeout")):
        result = tool._run(url="https://unreachable.example.com")
    assert "Error" in result


def test_strips_script_and_style_tags(tool):
    html = "<html><head><style>body{color:red}</style></head><body><script>alert(1)</script><p>Content</p></body></html>"
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.text = html
    with patch("agents.tools.web_fetch_tool.requests.get", return_value=mock_response):
        result = tool._run(url="https://example.com")
    assert "Content" in result
    assert "alert" not in result
    assert "color:red" not in result
