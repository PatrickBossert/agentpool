# agents/tools/web_fetch_tool.py
import re
import requests
from pydantic import BaseModel, Field
from crewai.tools import BaseTool

_CHAR_LIMIT = 8_000
_TIMEOUT = 10

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    )
}


class WebFetchToolInput(BaseModel):
    url: str = Field(description="The URL to fetch and read.")


def _strip_html(html: str) -> str:
    html = re.sub(r"<(script|style)[^>]*>.*?</(script|style)>", "", html, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<[^>]+>", " ", html)
    text = re.sub(r"\s+", " ", text).strip()
    return text


class WebFetchTool(BaseTool):
    name: str = "WebFetchTool"
    description: str = (
        "Fetch the text content of a web page given its URL. "
        "Returns the page's readable text, stripped of HTML. "
        "Use for reading research links provided for this project."
    )
    args_schema: type[BaseModel] = WebFetchToolInput

    def _run(self, url: str) -> str:
        try:
            resp = requests.get(url, headers=_HEADERS, timeout=_TIMEOUT)
        except requests.RequestException as exc:
            return f"Error fetching {url}: {exc}"
        if resp.status_code != 200:
            return f"Error fetching {url}: HTTP {resp.status_code}"
        text = _strip_html(resp.text)
        if len(text) > _CHAR_LIMIT:
            text = text[:_CHAR_LIMIT] + f"\n\n[Content truncated at {_CHAR_LIMIT} characters]"
        return text
