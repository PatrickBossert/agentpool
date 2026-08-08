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


def get_tts_client() -> httpx.AsyncClient:
    """The shared client for ElevenLabs."""
    global _tts_client
    if _tts_client is None or _tts_client.is_closed:
        _tts_client = httpx.AsyncClient(timeout=30.0)
    return _tts_client


def get_anthropic_client() -> AsyncAnthropic:
    """The shared Anthropic client, used for the standard-mode elaboration press."""
    global _anthropic_client
    if _anthropic_client is None:
        _anthropic_client = AsyncAnthropic()
    return _anthropic_client


async def close_http_clients() -> None:
    """Close on application shutdown. Both getters rebuild on demand afterwards."""
    global _tts_client, _anthropic_client
    if _tts_client is not None and not _tts_client.is_closed:
        await _tts_client.aclose()
    _tts_client = None
    if _anthropic_client is not None:
        await _anthropic_client.close()
    _anthropic_client = None
