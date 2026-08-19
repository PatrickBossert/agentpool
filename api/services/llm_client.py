# api/services/llm_client.py
"""One provider call for a project, routed by that project's llm_mode.

This exists because "route it locally" is two different protocols, not one setting.

Agents build `LLM(model=f"openai/{model}", base_url=...)`, and LiteLLM POSTs
`{base_url}/chat/completions`. Anything that reached for `AsyncAnthropic(base_url=...)`
instead POSTed `{base_url}/v1/messages` - and, because `local_fast_url` already ends in
`/v1`, actually `{base_url}/v1/v1/messages`. Ollama serves no `/v1/messages` at any path, so
every such call raised `NotFoundError` on a correctly configured sensitive project. The
settings agreed; the wire format did not.

So the sensitive branch here speaks the OpenAI chat-completions protocol, exactly as the
agent path does, built from the same `local_<tier>_url` and `local_<tier>_model` settings
through the same reader. httpx rather than the `openai` package: httpx is a declared
dependency in requirements.txt and already on this path, while `openai` is only present
transitively via litellm.

The standard branch reads `anthropic_<tier>_model` from the project's own settings too. A
hardcoded model here would be a second authority for a fact the project already states.
"""
from __future__ import annotations

import logging

import httpx

from api.services.chroma_client import project_llm_mode
from api.services.deployment_modes import Capability, project_permits
from api.services.http_clients import get_anthropic_client, get_local_llm_client

_log = logging.getLogger(__name__)

# The two capability tiers agents declare. The settings keys each one binds to are not
# restated here - resolve_model imports agents.model_registry's own _TIER_SETTINGS table, so
# there is still exactly one place that says which setting holds which model.
_TIERS = ("fast", "deep")


class LocalModelError(RuntimeError):
    """The local provider could not be reached, or answered with an error.

    Distinct from LocalModelUnavailable, which means nothing was configured at all. This one
    means it was configured and did not work - a wrong URL, a model the server has not
    pulled, a server that is not running.
    """


class UnsupportedByLocalModelPath(RuntimeError):
    """The call carries content the local chat-completions path cannot express.

    Refused rather than downgraded. Dropping the unsupported part and sending the rest would
    silently answer a different question; sending it hosted would be the egress the project's
    resolved grants refuse.

    **Renamed from `UnsupportedForSensitiveProject`**, which became a misnomer the moment a
    project could be narrowed without being sensitive: a `standard` project with
    `force_local_inference` set reaches this by the same branch. The name says what is true in
    every case - the local path cannot carry this block - rather than naming one of the reasons
    a project might be on it. Six references across two files, no test and no UI naming it, so
    the rename was cheaper than leaving a name that has to be explained.
    """


def _strip_provider_prefix(model: str) -> str:
    """`anthropic/claude-opus-4-6` -> `claude-opus-4-6`.

    The project settings hold LiteLLM-form names, because that is what crewai.LLM wants. The
    Anthropic SDK wants the bare id, and no Anthropic model id contains a slash.
    """
    return model.split("/", 1)[1] if "/" in model else model


def resolve_model(slug: str, tier: str) -> tuple[str, str | None]:
    """The model this project runs a `tier` call on, and its base URL if it is local.

    Returns ``(model, base_url)``; ``base_url`` is None on the hosted path. Raises
    LocalModelUnavailable when the project's mode is not granted hosted inference and the
    tier is unconfigured - never a hosted fallback, and never the other tier's model.
    """
    if tier not in _TIERS:
        raise ValueError(f"unknown tier {tier!r} - expected one of {_TIERS}")
    # Imported inside the function: agents.model_registry pulls in crewai, which is slow and
    # is not needed to import an api.services module.
    from agents.model_registry import (
        _local_model_unavailable,
        _project_setting,
        _setting_default,
        _TIER_SETTINGS,
    )

    # The same grant the crew path asks, so the two cannot answer differently for one project.
    # That sentence is why this site moved to `project_permits` alongside the crew path rather
    # than being left on `permits`: a project forcing local inference would otherwise send its
    # crew prompts to Ollama and its elaboration press and Agent Chat to Anthropic, which is
    # both a false measurement and the two answering differently for one project.
    # `project_llm_mode` is read inside the refusal and only to word it - see the note beside
    # the same branch in agents/model_registry.py.
    if not project_permits(slug, Capability.HOSTED_INFERENCE):
        model_key, url_key = _TIER_SETTINGS[(tier, "sensitive")]
        model = _project_setting(slug, model_key, _setting_default(model_key))
        base_url = _project_setting(slug, url_key, _setting_default(url_key))
        if not model or not base_url:
            raise _local_model_unavailable(
                slug, project_llm_mode(slug), tier, model_key, url_key
            )
        return model, base_url

    model_key, _ = _TIER_SETTINGS[(tier, "standard")]
    model = _project_setting(slug, model_key, _setting_default(model_key))
    if not model:
        raise ValueError(
            f"Project '{slug}' has no model configured for the '{tier}' tier "
            f"({model_key} is blank)."
        )
    return _strip_provider_prefix(model), None


def _to_openai_messages(
    messages: list[dict], system: str | None
) -> list[dict]:
    """Anthropic-shaped messages -> OpenAI chat messages.

    Text-only. A content block this cannot carry raises rather than being dropped: see
    UnsupportedByLocalModelPath.
    """
    out: list[dict] = []
    if system:
        out.append({"role": "system", "content": system})
    for message in messages:
        content = message["content"]
        if isinstance(content, str):
            out.append({"role": message["role"], "content": content})
            continue
        text_parts = []
        for block in content:
            if block.get("type") != "text":
                raise UnsupportedByLocalModelPath(
                    f"This message carries a '{block.get('type')}' content block, which the "
                    f"local model path cannot send. This project is not permitted to send "
                    f"prompts to a hosted model, so the request is refused rather than sent "
                    f"there or silently stripped of the attachment. Remove the attachment, or "
                    f"ask an administrator to change the project setting that keeps its "
                    f"inference local."
                )
            text_parts.append(block["text"])
        out.append({"role": message["role"], "content": "\n\n".join(text_parts)})
    return out


async def project_completion(
    slug: str,
    tier: str,
    messages: list[dict],
    *,
    system: str | None = None,
    max_tokens: int = 1024,
) -> str:
    """A single completion for this project, on the model its llm_mode binds to `tier`.

    `messages` are Anthropic-shaped - `{"role": ..., "content": str | [block, ...]}` - and are
    translated for the local path. Returns the reply text.

    Raises LocalModelUnavailable (nothing configured), LocalModelError (configured but the
    call failed), or UnsupportedByLocalModelPath (content the local path cannot carry).
    Callers on a request path are expected to turn these into a clear refusal; nothing here
    ever answers a sensitive project from a hosted model.
    """
    if not slug:
        raise ValueError(
            "project_completion requires a project slug: the model, and whether it is local "
            "at all, are properties of the project. Defaulting would route a sensitive "
            "project's content to a hosted model."
        )
    model, base_url = resolve_model(slug, tier)

    if base_url is None:
        client = get_anthropic_client()
        kwargs: dict = {"model": model, "max_tokens": max_tokens, "messages": messages}
        if system:
            kwargs["system"] = system
        response = await client.messages.create(**kwargs)
        return response.content[0].text.strip()

    payload = {
        "model": model,
        "max_tokens": max_tokens,
        "messages": _to_openai_messages(messages, system),
    }
    url = f"{base_url.rstrip('/')}/chat/completions"
    try:
        response = await get_local_llm_client().post(url, json=payload)
        response.raise_for_status()
        data = response.json()
        return data["choices"][0]["message"]["content"].strip()
    except httpx.HTTPStatusError as exc:
        raise LocalModelError(
            f"Local model '{model}' at {url} answered {exc.response.status_code}."
        ) from exc
    except httpx.HTTPError as exc:
        raise LocalModelError(f"Local model '{model}' at {url} could not be reached: {exc}") from exc
    except (KeyError, IndexError, TypeError, ValueError) as exc:
        raise LocalModelError(
            f"Local model '{model}' at {url} returned a response this could not read: {exc}"
        ) from exc
