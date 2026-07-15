from __future__ import annotations

import json
import urllib.error
import urllib.request
from http.client import HTTPMessage
from io import BytesIO
from typing import Any, cast

import pytest

from ai_stock_picker.providers import (
    ProviderError,
    call_provider,
    resolve_provider_config,
)


def test_resolve_built_in_and_custom_providers() -> None:
    deepseek = resolve_provider_config("deepseek")
    assert deepseek.model == "deepseek-chat"
    assert deepseek.api_key_env == "DEEPSEEK_API_KEY"

    gemini = resolve_provider_config("gemini", model="gemini-2.5-pro")
    assert gemini.model == "gemini-2.5-pro"

    custom = resolve_provider_config(
        "openai-compatible",
        model="gpt-4.1-mini",
        base_url="https://api.example.com/v1/chat/completions",
        api_key_env="CUSTOM_API_KEY",
    )
    assert custom.endpoint.endswith("chat/completions")
    assert custom.name == "openai-compatible"


def test_custom_provider_requires_safe_complete_configuration() -> None:
    with pytest.raises(ProviderError, match="requires"):
        resolve_provider_config("openai-compatible")
    with pytest.raises(ProviderError, match="HTTPS"):
        resolve_provider_config(
            "openai-compatible",
            model="m",
            base_url="http://example.com/v1/chat/completions",
            api_key_env="KEY",
        )
    with pytest.raises(ProviderError, match="environment"):
        resolve_provider_config(
            "openai-compatible",
            model="m",
            base_url="https://example.com/v1/chat/completions",
            api_key_env="bad-key",
        )
    with pytest.raises(ProviderError, match="fixed"):
        resolve_provider_config("deepseek", base_url="https://example.com")


def test_openai_compatible_call_uses_unredirected_header(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CUSTOM_API_KEY", "secret")
    config = resolve_provider_config(
        "openai-compatible",
        model="model-x",
        base_url="https://api.example.com/v1/chat/completions",
        api_key_env="CUSTOM_API_KEY",
    )
    observed: list[tuple[str, dict[str, str], dict[str, str], dict[str, Any]]] = []

    def transport(request: urllib.request.Request, _timeout: float) -> bytes:
        data = cast(Any, request.data)
        observed.append(
            (
                request.full_url,
                dict(request.headers),
                dict(request.unredirected_hdrs),
                json.loads(data or b"{}"),
            )
        )
        return b'{"choices":[{"message":{"content":"{\\"picks\\":[]}"}}]}'

    result = call_provider(
        "prompt", config, temperature=0.2, timeout=3, transport=transport
    )
    assert result == '{"picks":[]}'
    url, headers, unredirected, payload = observed[0]
    assert url == config.endpoint
    assert "Authorization" not in headers
    assert unredirected["Authorization"] == "Bearer secret"
    assert payload["model"] == "model-x"


def test_gemini_call_uses_header_and_model_url(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GEMINI_API_KEY", "secret")
    config = resolve_provider_config("gemini", model="gemini-test")
    observed: list[tuple[str, dict[str, str]]] = []

    def transport(request: urllib.request.Request, _timeout: float) -> bytes:
        observed.append((request.full_url, dict(request.unredirected_hdrs)))
        return b'{"candidates":[{"content":{"parts":[{"text":"{\\"picks\\":[]}"}]}}]}'

    result = call_provider("prompt", config, temperature=0.1, transport=transport)
    assert result == '{"picks":[]}'
    assert "gemini-test:generateContent" in observed[0][0]
    assert observed[0][1]["X-goog-api-key"] == "secret"


def test_provider_keys_do_not_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.setenv("GEMINI_API_KEY", "wrong")
    with pytest.raises(ProviderError, match="DEEPSEEK_API_KEY"):
        call_provider("prompt", resolve_provider_config("deepseek"), temperature=0.2)


def test_explicit_empty_key_does_not_fallback_to_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DEEPSEEK_API_KEY", "must-not-be-used")
    with pytest.raises(ProviderError, match="DEEPSEEK_API_KEY"):
        call_provider(
            "prompt",
            resolve_provider_config("deepseek"),
            temperature=0.2,
            api_key="",
        )


def test_credentials_are_not_copied_to_redirect(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DEEPSEEK_API_KEY", "secret")
    observed: list[dict[str, str]] = []

    def transport(request: urllib.request.Request, _timeout: float) -> bytes:
        redirected = urllib.request.HTTPRedirectHandler().redirect_request(
            request,
            BytesIO(),
            302,
            "Found",
            HTTPMessage(),
            "https://attacker.invalid/collect",
        )
        assert redirected is not None
        observed.append(dict(redirected.header_items()))
        return b'{"choices":[{"message":{"content":"{\\"picks\\":[]}"}}]}'

    call_provider(
        "prompt",
        resolve_provider_config("deepseek"),
        temperature=0.2,
        transport=transport,
    )
    assert "Authorization" not in observed[0]


def test_provider_failures_are_sanitized(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DEEPSEEK_API_KEY", "secret")

    def bad_transport(_request: urllib.request.Request, _timeout: float) -> bytes:
        raise urllib.error.URLError("secret details")

    with pytest.raises(ProviderError, match="request failed") as error:
        call_provider(
            "prompt",
            resolve_provider_config("deepseek"),
            temperature=0.2,
            transport=bad_transport,
        )
    assert "secret details" not in str(error.value)

    def invalid_json(_request: urllib.request.Request, _timeout: float) -> bytes:
        return b"not-json"

    with pytest.raises(ProviderError, match="invalid JSON"):
        call_provider(
            "prompt",
            resolve_provider_config("deepseek"),
            temperature=0.2,
            transport=invalid_json,
        )


def test_provider_request_limits(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DEEPSEEK_API_KEY", "key")
    config = resolve_provider_config("deepseek")
    with pytest.raises(ProviderError, match="timeout"):
        call_provider("prompt", config, temperature=0.2, timeout=0)
    with pytest.raises(ProviderError, match="temperature"):
        call_provider("prompt", config, temperature=float("nan"))
    with pytest.raises(ProviderError, match="prompt exceeds"):
        call_provider("x" * 2_000_001, config, temperature=0.2)

    def huge(_request: urllib.request.Request, _timeout: float) -> bytes:
        return b"x" * 2_000_001

    with pytest.raises(ProviderError, match="response exceeds"):
        call_provider("prompt", config, temperature=0.2, transport=huge)
