"""Small, provider-bound HTTPS clients with no cross-provider key fallback."""

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
from typing import Any, cast

Transport = Callable[[urllib.request.Request, float], bytes]

_MODEL_NAME = re.compile(r"^[A-Za-z0-9._-]{1,100}$")
_MAX_PROMPT_BYTES = 2_000_000
_MAX_HTTP_RESPONSE_BYTES = 2_000_000


class ProviderError(RuntimeError):
    """A sanitized provider configuration, transport, or response failure."""


@dataclass(frozen=True, slots=True)
class ProviderExchange:
    """Credential-free material needed to reproduce and audit one provider call."""

    provider: str
    model: str
    endpoint: str
    request_method: str
    request_headers: tuple[tuple[str, str], ...]
    request_body: bytes
    response_body: bytes
    response_text: str | None
    actual_model: str | None
    extraction_error: str | None
    timeout_seconds: float


def call_deepseek(
    prompt: str,
    *,
    model: str = "deepseek-chat",
    timeout: float = 120,
    transport: Transport | None = None,
    api_key: str | None = None,
) -> str:
    """Call DeepSeek using an explicit owner key or ``DEEPSEEK_API_KEY``."""

    exchange = call_deepseek_exchange(
        prompt,
        model=model,
        timeout=timeout,
        transport=transport,
        api_key=api_key,
    )
    if exchange.response_text is None:
        raise ProviderError("DeepSeek returned an invalid response schema")
    return exchange.response_text


def call_deepseek_exchange(
    prompt: str,
    *,
    model: str = "deepseek-chat",
    timeout: float = 120,
    transport: Transport | None = None,
    api_key: str | None = None,
) -> ProviderExchange:
    """Call DeepSeek and retain a credential-free, byte-exact exchange."""

    credential = _resolve_api_key(api_key, "DEEPSEEK_API_KEY", "CN")
    _validate_model(model)
    _validate_request(prompt, timeout)
    payload: dict[str, object] = {
        "model": model,
        "messages": [
            {
                "role": "system",
                "content": (
                    "You rerank only the supplied candidate universe. "
                    "Return strict JSON and never invent a symbol."
                ),
            },
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.2,
        "response_format": {"type": "json_object"},
    }
    endpoint = "https://api.deepseek.com/v1/chat/completions"
    request_body, response_body = _post_raw(
        endpoint,
        payload,
        credential_headers={"Authorization": f"Bearer {credential}"},
        timeout=timeout,
        transport=transport,
    )
    _reject_credential_echo(response_body, credential)
    body, decode_error = _decode_object(response_body)
    actual_model = _optional_string(body.get("model")) if body is not None else None
    response_text: str | None = None
    extraction_error = decode_error
    if body is not None:
        try:
            choices = _list_field(body, "choices")
            message = _dict_field(_dict_item(choices, 0), "message")
            response_text = _nonempty_string(message.get("content"), "DeepSeek content")
        except (IndexError, TypeError, ValueError):
            extraction_error = "provider_response_schema_invalid"
    return ProviderExchange(
        provider="deepseek",
        model=model,
        endpoint=endpoint,
        request_method="POST",
        request_headers=(
            ("Content-Type", "application/json"),
            ("Authorization", "<redacted>"),
        ),
        request_body=request_body,
        response_body=response_body,
        response_text=response_text,
        actual_model=actual_model,
        extraction_error=extraction_error,
        timeout_seconds=timeout,
    )


def call_gemini(
    prompt: str,
    *,
    model: str = "gemini-2.5-flash",
    timeout: float = 120,
    transport: Transport | None = None,
    api_key: str | None = None,
) -> str:
    """Call Gemini using an explicit owner key or ``GEMINI_API_KEY``."""

    exchange = call_gemini_exchange(
        prompt,
        model=model,
        timeout=timeout,
        transport=transport,
        api_key=api_key,
    )
    if exchange.response_text is None:
        raise ProviderError("Gemini returned an invalid response schema")
    return exchange.response_text


def call_gemini_exchange(
    prompt: str,
    *,
    model: str = "gemini-2.5-flash",
    timeout: float = 120,
    transport: Transport | None = None,
    api_key: str | None = None,
) -> ProviderExchange:
    """Call Gemini and retain a credential-free, byte-exact exchange."""

    credential = _resolve_api_key(api_key, "GEMINI_API_KEY", "US")
    _validate_model(model)
    _validate_request(prompt, timeout)
    encoded_model = urllib.parse.quote(model, safe="")
    url = (
        "https://generativelanguage.googleapis.com/v1beta/models/"
        f"{encoded_model}:generateContent"
    )
    payload: dict[str, object] = {
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": 0.2,
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
    request_body, response_body = _post_raw(
        url,
        payload,
        credential_headers={"x-goog-api-key": credential},
        timeout=timeout,
        transport=transport,
    )
    _reject_credential_echo(response_body, credential)
    body, decode_error = _decode_object(response_body)
    actual_model = (
        _optional_string(body.get("modelVersion")) if body is not None else None
    )
    response_text: str | None = None
    extraction_error = decode_error
    if body is not None:
        try:
            candidates = _list_field(body, "candidates")
            content = _dict_field(_dict_item(candidates, 0), "content")
            parts = _list_field(content, "parts")
            response_text = _nonempty_string(
                _dict_item(parts, 0).get("text"), "Gemini text"
            )
        except (IndexError, TypeError, ValueError):
            extraction_error = "provider_response_schema_invalid"
    return ProviderExchange(
        provider="gemini",
        model=model,
        endpoint=url,
        request_method="POST",
        request_headers=(
            ("Content-Type", "application/json"),
            ("x-goog-api-key", "<redacted>"),
        ),
        request_body=request_body,
        response_body=response_body,
        response_text=response_text,
        actual_model=actual_model,
        extraction_error=extraction_error,
        timeout_seconds=timeout,
    )


def _post_raw(
    url: str,
    payload: dict[str, object],
    *,
    credential_headers: dict[str, str],
    timeout: float,
    transport: Transport | None,
) -> tuple[bytes, bytes]:
    request_body = json.dumps(payload, ensure_ascii=False).encode()
    request = urllib.request.Request(
        url,
        data=request_body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    # urllib copies regular headers onto redirected requests. Credentials are
    # deliberately unredirected so a provider redirect cannot exfiltrate them.
    for name, value in credential_headers.items():
        request.add_unredirected_header(name, value)
    sender = transport or _default_transport
    try:
        raw = sender(request, timeout)
        if len(raw) > _MAX_HTTP_RESPONSE_BYTES:
            raise ProviderError("provider response exceeds the 2 MB safety limit")
    except urllib.error.HTTPError as exc:
        retryable = exc.code == 429 or 500 <= exc.code < 600
        classification = "retryable" if retryable else "nonretryable"
        raise ProviderError(
            f"provider request failed: {classification}:http_{exc.code}"
        ) from exc
    except (urllib.error.URLError, TimeoutError) as exc:
        raise ProviderError("provider request failed: retryable:network") from exc
    return request_body, raw


def _default_transport(request: urllib.request.Request, timeout: float) -> bytes:
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return cast(bytes, response.read(_MAX_HTTP_RESPONSE_BYTES + 1))


def _validate_model(model: str) -> None:
    if _MODEL_NAME.fullmatch(model) is None:
        raise ProviderError("model name contains unsupported characters")


def _resolve_api_key(explicit: str | None, variable: str, market: str) -> str:
    value = explicit if explicit is not None else os.environ.get(variable, "")
    credential = value.strip()
    if not credential:
        raise ProviderError(f"{variable} is required for {market} picks")
    return credential


def _validate_request(prompt: str, timeout: float) -> None:
    if not math.isfinite(timeout) or timeout <= 0:
        raise ProviderError("timeout must be a positive finite number")
    if len(prompt.encode()) > _MAX_PROMPT_BYTES:
        raise ProviderError("prompt exceeds the 2 MB safety limit")


def _reject_credential_echo(response_body: bytes, credential: str) -> None:
    encoded = credential.encode()
    if encoded and encoded in response_body:
        raise ProviderError("provider response contained credential material")


def _decode_object(raw: bytes) -> tuple[dict[str, object] | None, str | None]:
    try:
        decoded = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None, "provider_response_invalid_json"
    if not isinstance(decoded, dict):
        return None, "provider_response_not_object"
    return cast(dict[str, object], decoded), None


def _optional_string(value: object) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def _list_field(payload: dict[str, object], field: str) -> list[object]:
    value = payload.get(field)
    if not isinstance(value, list):
        raise TypeError(field)
    return value


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
    "ProviderError",
    "ProviderExchange",
    "Transport",
    "call_deepseek",
    "call_deepseek_exchange",
    "call_gemini",
    "call_gemini_exchange",
]
