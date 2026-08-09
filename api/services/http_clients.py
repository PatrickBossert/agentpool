"""Long-lived HTTP clients for the interview request path.

Both providers were called through a client constructed per request, which meant a fresh
TLS handshake for every question spoken and every follow-up generated: 478ms per call
against 264ms shared, so 213ms wasted on every utterance. At twenty concurrent interviews
it is also twenty times the sockets and handshakes for no benefit.
"""
import httpx
from anthropic import AsyncAnthropic

_tts_client: httpx.AsyncClient | None = None
_anthropic_client: AsyncAnthropic | None = None
_local_llm_client: httpx.AsyncClient | None = None


def get_tts_client() -> httpx.AsyncClient:
    """The shared client for ElevenLabs."""
    global _tts_client
    if _tts_client is None or _tts_client.is_closed:
        _tts_client = httpx.AsyncClient(timeout=30.0)
    return _tts_client


def get_anthropic_client() -> AsyncAnthropic:
    """The shared Anthropic client, used for every standard-mode hosted call.

    The key comes from settings rather than from the SDK's own environment lookup: settings
    read `.env`, which pydantic-settings does not copy into os.environ, so a deployment
    configured only through `.env` would otherwise leave the SDK with no key.
    """
    global _anthropic_client
    if _anthropic_client is None:
        from api.config import get_settings
        _anthropic_client = AsyncAnthropic(api_key=get_settings().anthropic_api_key)
    return _anthropic_client


def get_local_llm_client() -> httpx.AsyncClient:
    """The shared client for an OpenAI-compatible local model server.

    A plain httpx client, deliberately: a sensitive project's local model is reached over the
    same chat-completions protocol LiteLLM uses for the agents, not over the Anthropic
    Messages API. Keeping it here rather than inside api.services.llm_client is what lets a
    test substitute an httpx.MockTransport and inspect the real request - method, URL, and
    body - so a protocol mismatch fails the test instead of being absorbed by a fake client
    class.

    The timeout is generous because callers on a request path impose their own budget - the
    elaboration press wraps its call in asyncio.wait_for - and a local model under load is
    slow rather than broken.
    """
    global _local_llm_client
    if _local_llm_client is None or _local_llm_client.is_closed:
        _local_llm_client = httpx.AsyncClient(timeout=120.0)
    return _local_llm_client


async def close_http_clients() -> None:
    """Close on application shutdown. Every getter rebuilds on demand afterwards."""
    global _tts_client, _anthropic_client, _local_llm_client
    if _tts_client is not None and not _tts_client.is_closed:
        await _tts_client.aclose()
    _tts_client = None
    if _anthropic_client is not None:
        await _anthropic_client.close()
    _anthropic_client = None
    if _local_llm_client is not None and not _local_llm_client.is_closed:
        await _local_llm_client.aclose()
    _local_llm_client = None
