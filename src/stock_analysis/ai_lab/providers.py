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
from typing import Any, cast

Transport = Callable[[urllib.request.Request, float], bytes]

_MODEL_NAME = re.compile(r"^[A-Za-z0-9._-]{1,100}$")
_MAX_PROMPT_BYTES = 2_000_000
_MAX_HTTP_RESPONSE_BYTES = 2_000_000


class ProviderError(RuntimeError):
    """A sanitized provider configuration, transport, or response failure."""


def call_deepseek(
    prompt: str,
    *,
    model: str = "deepseek-chat",
    timeout: float = 120,
    transport: Transport | None = None,
) -> str:
    """Call DeepSeek using only ``DEEPSEEK_API_KEY``."""

    api_key = os.environ.get("DEEPSEEK_API_KEY", "").strip()
    if not api_key:
        raise ProviderError("DEEPSEEK_API_KEY is required for CN picks")
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
    body = _post_json(
        "https://api.deepseek.com/v1/chat/completions",
        payload,
        credential_headers={"Authorization": f"Bearer {api_key}"},
        timeout=timeout,
        transport=transport,
    )
    try:
        choices = _list_field(body, "choices")
        message = _dict_field(_dict_item(choices, 0), "message")
        return _nonempty_string(message.get("content"), "DeepSeek content")
    except (IndexError, TypeError, ValueError) as exc:
        raise ProviderError("DeepSeek returned an invalid response schema") from exc


def call_gemini(
    prompt: str,
    *,
    model: str = "gemini-2.5-flash",
    timeout: float = 120,
    transport: Transport | None = None,
) -> str:
    """Call Gemini using only ``GEMINI_API_KEY``."""

    api_key = os.environ.get("GEMINI_API_KEY", "").strip()
    if not api_key:
        raise ProviderError("GEMINI_API_KEY is required for US picks")
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
    # urllib copies regular headers onto redirected requests. Credentials are
    # deliberately unredirected so a provider redirect cannot exfiltrate them.
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


def _validate_model(model: str) -> None:
    if _MODEL_NAME.fullmatch(model) is None:
        raise ProviderError("model name contains unsupported characters")


def _validate_request(prompt: str, timeout: float) -> None:
    if not math.isfinite(timeout) or timeout <= 0:
        raise ProviderError("timeout must be a positive finite number")
    if len(prompt.encode()) > _MAX_PROMPT_BYTES:
        raise ProviderError("prompt exceeds the 2 MB safety limit")


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


__all__ = ["ProviderError", "Transport", "call_deepseek", "call_gemini"]
