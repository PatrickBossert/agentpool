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
    # `is_closed` on the underlying httpx client, matching both siblings above. Without it a
    # closed client is handed out for the life of the process: the two plain httpx clients have
    # always rebuilt on that condition and this one did not, which is the sort of asymmetry that
    # reads as deliberate and is not.
    if _anthropic_client is None or getattr(_anthropic_client._client, "is_closed", False):
        from api.config import get_settings

        # A response event hook, so the rate-limit headers are read where they actually arrive.
        #
        # Anthropic publishes **no balance endpoint**; the only headroom signal that exists is
        # the `anthropic-ratelimit-*` set on every response. The SDK hands call sites a parsed
        # `Message` with the headers discarded, so reading them at the call site means switching
        # to `messages.with_raw_response.create` - which breaks every existing mock that stubs
        # `messages.create`, fourteen tests' worth, none of them about monitoring.
        #
        # At the transport there is nothing to rewrite: the hook sees every Anthropic response
        # this deployment receives, no call site changes, and a test that fakes the client never
        # reaches the transport so it never fires. That is what makes this indicator free, which
        # is the only condition on which it was worth having at all.
        #
        # The hook must never raise - an exception here would fail a completion that succeeded -
        # and `note_anthropic_headers` guarantees that for itself.
        async def _note_rate_limit_headers(response: httpx.Response) -> None:
            from api.services.provider_health import note_anthropic_headers

            note_anthropic_headers(response.headers)

        _anthropic_client = AsyncAnthropic(
            api_key=get_settings().anthropic_api_key,
            http_client=httpx.AsyncClient(event_hooks={"response": [_note_rate_limit_headers]}),
        )
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
