"""Provider-neutral HTTPS clients for model reranking."""

from __future__ import annotations

import json
import math
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Literal, cast

ProviderKind = Literal["deepseek", "gemini", "openai-compatible"]
Transport = Callable[[urllib.request.Request, float], bytes]

_MODEL_NAME = re.compile(r"^[A-Za-z0-9._:/-]{1,100}$")
_ENV_NAME = re.compile(r"^[A-Z][A-Z0-9_]{0,127}$")
_MAX_PROMPT_BYTES = 2_000_000
_MAX_HTTP_RESPONSE_BYTES = 2_000_000


class ProviderError(RuntimeError):
    """Sanitized provider configuration, transport, or response failure."""


@dataclass(frozen=True, slots=True)
class ProviderConfig:
    """Resolved provider settings used by one selection plan."""

    name: str
    provider_api: str
    model: str
    endpoint: str
    api_key_env: str


def resolve_provider_config(
    provider: ProviderKind,
    *,
    model: str | None = None,
    base_url: str | None = None,
    api_key_env: str | None = None,
) -> ProviderConfig:
    """Resolve built-in or OpenAI-compatible provider settings."""

    if provider == "deepseek":
        _reject_custom_transport_options(base_url, api_key_env, provider)
        return ProviderConfig(
            name="deepseek",
            provider_api="openai-chat-completions-v1",
            model=_validated_model(model or "deepseek-chat"),
            endpoint="https://api.deepseek.com/v1/chat/completions",
            api_key_env="DEEPSEEK_API_KEY",
        )
    if provider == "gemini":
        _reject_custom_transport_options(base_url, api_key_env, provider)
        return ProviderConfig(
            name="gemini",
            provider_api="gemini-generate-content-v1beta",
            model=_validated_model(model or "gemini-2.5-flash"),
            endpoint="https://generativelanguage.googleapis.com/v1beta/models",
            api_key_env="GEMINI_API_KEY",
        )
    if not base_url or not api_key_env or not model:
        raise ProviderError(
            "openai-compatible requires --model, --base-url, and --api-key-env"
        )
    return ProviderConfig(
        name="openai-compatible",
        provider_api="openai-chat-completions-v1",
        model=_validated_model(model),
        endpoint=_validated_https_endpoint(base_url),
        api_key_env=_validated_env_name(api_key_env),
    )


def call_provider(
    prompt: str,
    config: ProviderConfig,
    *,
    temperature: float,
    timeout: float = 120.0,
    transport: Transport | None = None,
    api_key: str | None = None,
) -> str:
    """Call a provider using an explicit key or its dedicated environment variable."""

    _validate_request(prompt, temperature, timeout)
    credential = (api_key if api_key is not None else os.environ.get(config.api_key_env, "")).strip()
    if not credential:
        raise ProviderError(f"{config.api_key_env} is required for {config.name}")
    if config.provider_api == "gemini-generate-content-v1beta":
        return _call_gemini(
            prompt, config, credential, temperature, timeout, transport
        )
    return _call_openai_compatible(
        prompt, config, credential, temperature, timeout, transport
    )


def _call_openai_compatible(
    prompt: str,
    config: ProviderConfig,
    api_key: str,
    temperature: float,
    timeout: float,
    transport: Transport | None,
) -> str:
    payload: dict[str, object] = {
        "model": config.model,
        "messages": [
            {
                "role": "system",
                "content": (
                    "Rerank only the supplied candidate universe. Return strict JSON "
                    "and never invent a symbol."
                ),
            },
            {"role": "user", "content": prompt},
        ],
        "temperature": temperature,
        "response_format": {"type": "json_object"},
    }
    body = _post_json(
        config.endpoint,
        payload,
        credential_headers={"Authorization": f"Bearer {api_key}"},
        timeout=timeout,
        transport=transport,
    )
    try:
        choices = _list_field(body, "choices")
        message = _dict_field(_dict_item(choices, 0), "message")
        return _nonempty_string(message.get("content"), "provider content")
    except (IndexError, TypeError, ValueError) as exc:
        raise ProviderError(
            "provider returned an invalid chat-completions schema"
        ) from exc


def _call_gemini(
    prompt: str,
    config: ProviderConfig,
    api_key: str,
    temperature: float,
    timeout: float,
    transport: Transport | None,
) -> str:
    encoded_model = urllib.parse.quote(config.model, safe="")
    url = f"{config.endpoint}/{encoded_model}:generateContent"
    payload: dict[str, object] = {
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": temperature,
            "responseMimeType": "application/json",
        },
        "systemInstruction": {
            "parts": [
                {
                    "text": (
                        "Rerank only supplied candidates. Return strict JSON and "
                        "never invent a symbol."
                    )
                }
            ]
        },
    }
    body = _post_json(
        url,
        payload,
        credential_headers={"x-goog-api-key": api_key},
        timeout=timeout,
        transport=transport,
    )
    try:
        candidates = _list_field(body, "candidates")
        content = _dict_field(_dict_item(candidates, 0), "content")
        parts = _list_field(content, "parts")
        return _nonempty_string(_dict_item(parts, 0).get("text"), "Gemini text")
    except (IndexError, TypeError, ValueError) as exc:
        raise ProviderError("Gemini returned an invalid response schema") from exc


def _post_json(
    url: str,
    payload: dict[str, object],
    *,
    credential_headers: dict[str, str],
    timeout: float,
    transport: Transport | None,
) -> dict[str, object]:
    request = urllib.request.Request(
        url,
        data=json.dumps(payload, ensure_ascii=False).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    for name, value in credential_headers.items():
        request.add_unredirected_header(name, value)
    sender = transport or _default_transport
    try:
        raw = sender(request, timeout)
        if len(raw) > _MAX_HTTP_RESPONSE_BYTES:
            raise ProviderError("provider response exceeds the 2 MB safety limit")
        decoded = json.loads(raw)
    except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError) as exc:
        raise ProviderError("provider request failed") from exc
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ProviderError("provider returned invalid JSON") from exc
    if not isinstance(decoded, dict):
        raise ProviderError("provider response must be a JSON object")
    return cast(dict[str, object], decoded)


def _default_transport(request: urllib.request.Request, timeout: float) -> bytes:
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return cast(bytes, response.read(_MAX_HTTP_RESPONSE_BYTES + 1))


def _validated_model(model: str) -> str:
    normalized = model.strip()
    if _MODEL_NAME.fullmatch(normalized) is None:
        raise ProviderError("model name contains unsupported characters")
    return normalized


def _validated_env_name(name: str) -> str:
    normalized = name.strip()
    if _ENV_NAME.fullmatch(normalized) is None:
        raise ProviderError("api key environment variable name is invalid")
    return normalized


def _validated_https_endpoint(url: str) -> str:
    text = url.strip()
    parsed = urllib.parse.urlsplit(text)
    if (
        parsed.scheme != "https"
        or not parsed.netloc
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
    ):
        raise ProviderError(
            "custom provider endpoint must be an HTTPS URL without credentials, "
            "query, or fragment"
        )
    return text.rstrip("/")


def _reject_custom_transport_options(
    base_url: str | None, api_key_env: str | None, provider: str
) -> None:
    if base_url is not None or api_key_env is not None:
        raise ProviderError(
            f"{provider} uses a fixed endpoint and credential environment variable"
        )


def _validate_request(prompt: str, temperature: float, timeout: float) -> None:
    if not math.isfinite(timeout) or timeout <= 0:
        raise ProviderError("timeout must be a positive finite number")
    if not math.isfinite(temperature) or not 0.0 <= temperature <= 2.0:
        raise ProviderError("temperature must be finite in [0, 2]")
    if len(prompt.encode()) > _MAX_PROMPT_BYTES:
        raise ProviderError("prompt exceeds the 2 MB safety limit")


def _list_field(payload: dict[str, object], field: str) -> list[object]:
    value = payload.get(field)
    if not isinstance(value, list):
        raise TypeError(field)
    return cast(list[object], value)


def _dict_field(payload: dict[str, object], field: str) -> dict[str, object]:
    value = payload.get(field)
    if not isinstance(value, dict):
        raise TypeError(field)
    return cast(dict[str, object], value)


def _dict_item(items: list[object], index: int) -> dict[str, object]:
    value: Any = items[index]
    if not isinstance(value, dict):
        raise TypeError(index)
    return cast(dict[str, object], value)


def _nonempty_string(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(field)
    return value


__all__ = [
    "ProviderConfig",
    "ProviderError",
    "ProviderKind",
    "Transport",
    "call_provider",
    "resolve_provider_config",
]
