from __future__ import annotations

import json
import urllib.error
import urllib.request
from http.client import HTTPMessage
from io import BytesIO
from typing import Any, cast

import pytest

from stock_analysis.ai_lab.providers import (
    OPENAI_RESPONSES_ENDPOINT,
    ProviderError,
    call_deepseek,
    call_deepseek_exchange,
    call_gemini,
    call_openai_responses_exchange,
)


def test_deepseek_never_falls_back_to_other_provider_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "must-not-be-used")
    monkeypatch.setenv("GEMINI_API_KEY", "must-not-be-used")
    with pytest.raises(ProviderError, match="DEEPSEEK_API_KEY"):
        call_deepseek("prompt")


def test_gemini_never_falls_back_to_other_provider_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.setenv("GOOGLE_API_KEY", "must-not-be-used")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "must-not-be-used")
    with pytest.raises(ProviderError, match="GEMINI_API_KEY"):
        call_gemini("prompt")


def test_openai_responses_uses_strict_schema_store_false_and_captures_audit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "openai-secret")
    observed: list[tuple[str, dict[str, str], dict[str, object]]] = []
    schema: dict[str, object] = {
        "type": "object",
        "additionalProperties": False,
        "properties": {"picks": {"type": "array", "items": {"type": "object"}}},
        "required": ["picks"],
    }

    def transport(request: urllib.request.Request, _timeout: float) -> bytes:
        observed.append(
            (
                request.full_url,
                dict(request.unredirected_hdrs),
                json.loads(cast(Any, request.data)),
            )
        )
        return json.dumps(
            {
                "model": "gpt-test-actual",
                "output": [
                    {
                        "type": "message",
                        "content": [
                            {"type": "output_text", "text": '{"picks":[]}'},
                        ],
                    }
                ],
                "usage": {"input_tokens": 12, "output_tokens": 4},
            }
        ).encode()

    exchange = call_openai_responses_exchange(
        "prompt",
        response_schema=schema,
        model="gpt-test",
        transport=transport,
    )

    endpoint, headers, payload = observed[0]
    assert endpoint == OPENAI_RESPONSES_ENDPOINT
    assert headers["Authorization"] == "Bearer openai-secret"
    assert payload["store"] is False
    assert payload["text"] == {
        "format": {
            "type": "json_schema",
            "name": "ai_stock_ranking",
            "strict": True,
            "schema": schema,
        }
    }
    assert exchange.response_text == '{"picks":[]}'
    assert exchange.actual_model == "gpt-test-actual"
    assert exchange.usage == {"input_tokens": 12, "output_tokens": 4}
    assert exchange.refusal is None
    assert b"openai-secret" not in exchange.request_body


def test_openai_responses_captures_refusal_without_treating_it_as_text(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "owner-key")
    body = json.dumps(
        {
            "model": "gpt-test-actual",
            "output": [
                {
                    "type": "message",
                    "content": [{"type": "refusal", "refusal": "cannot comply"}],
                }
            ],
            "usage": {"total_tokens": 3},
        }
    ).encode()

    exchange = call_openai_responses_exchange(
        "prompt",
        response_schema={"type": "object"},
        model="gpt-test",
        transport=lambda _request, _timeout: body,
    )

    assert exchange.response_text is None
    assert exchange.refusal == "cannot comply"
    assert exchange.extraction_error == "provider_refusal"
    assert exchange.usage == {"total_tokens": 3}


def test_explicit_provider_key_does_not_fall_back_to_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DEEPSEEK_API_KEY", "environment-key")
    observed: list[str] = []

    def transport(request: urllib.request.Request, _timeout: float) -> bytes:
        observed.append(str(request.get_header("Authorization")))
        return b'{"choices":[{"message":{"content":"{\\"picks\\":[]}"}}]}'

    call_deepseek("prompt", api_key="file-key", transport=transport)

    assert observed == ["Bearer file-key"]


def test_deepseek_uses_fixed_https_endpoint_and_parses_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DEEPSEEK_API_KEY", "deepseek-secret")
    observed: list[
        tuple[
            str,
            dict[str, str],
            dict[str, str],
            float,
            dict[str, object],
        ]
    ] = []

    def transport(request: urllib.request.Request, timeout: float) -> bytes:
        request_data = cast(Any, request.data)
        observed.append(
            (
                request.full_url,
                dict(request.headers),
                dict(request.unredirected_hdrs),
                timeout,
                json.loads(request_data or b"{}"),
            )
        )
        return json.dumps(
            {"choices": [{"message": {"content": '{"picks": []}'}}]}
        ).encode()

    result = call_deepseek(
        "prompt", model="deepseek-chat", timeout=7.0, transport=transport
    )
    assert result == '{"picks": []}'
    url, headers, unredirected, timeout, payload = observed[0]
    assert url == "https://api.deepseek.com/v1/chat/completions"
    assert "Authorization" not in headers
    assert unredirected["Authorization"] == "Bearer deepseek-secret"
    assert timeout == 7.0
    assert payload["model"] == "deepseek-chat"
    assert payload["thinking"] == {"type": "disabled"}
    assert payload["max_tokens"] == 8192
    assert payload["temperature"] == 0.2
    assert payload["response_format"] == {"type": "json_object"}
    assert "reasoning_effort" not in payload


def test_deepseek_exchange_records_actual_model_and_preserves_invalid_raw_body(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DEEPSEEK_API_KEY", "owner-secret")
    complete_body = json.dumps(
        {
            "model": "deepseek-v3.1",
            "choices": [{"message": {"content": '{"picks":[]}'}}],
            "usage": {"prompt_tokens": 3, "completion_tokens": 2},
        }
    ).encode()

    complete = call_deepseek_exchange(
        "prompt",
        transport=lambda _request, _timeout: complete_body,
    )
    assert complete.model == "deepseek-v4-flash"
    assert complete.actual_model == "deepseek-v3.1"
    assert complete.extraction_error is None
    assert complete.usage == {"prompt_tokens": 3, "completion_tokens": 2}

    rejected = call_deepseek_exchange(
        "prompt",
        transport=lambda _request, _timeout: b"http-success-but-not-json",
    )
    assert rejected.response_body == b"http-success-but-not-json"
    assert rejected.response_text is None
    assert rejected.actual_model is None
    assert rejected.extraction_error == "provider_response_invalid_json"
    assert b"owner-secret" not in rejected.request_body
    assert all(
        value == "<redacted>"
        for name, value in rejected.request_headers
        if name != "Content-Type"
    )


def test_gemini_uses_fixed_https_endpoint_and_parses_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GEMINI_API_KEY", "gemini-secret")
    observed: list[tuple[str, dict[str, str], dict[str, str], float]] = []

    def transport(request: urllib.request.Request, timeout: float) -> bytes:
        observed.append(
            (
                request.full_url,
                dict(request.headers),
                dict(request.unredirected_hdrs),
                timeout,
            )
        )
        return json.dumps(
            {"candidates": [{"content": {"parts": [{"text": '{"picks": []}'}]}}]}
        ).encode()

    result = call_gemini(
        "prompt", model="gemini-2.5-flash", timeout=8.0, transport=transport
    )
    assert result == '{"picks": []}'
    assert observed[0][0].startswith(
        "https://generativelanguage.googleapis.com/v1beta/models/"
    )
    assert "key=" not in observed[0][0]
    assert "X-goog-api-key" not in observed[0][1]
    assert observed[0][2]["X-goog-api-key"] == "gemini-secret"
    assert observed[0][3] == 8.0


def test_credentials_are_not_copied_to_redirected_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DEEPSEEK_API_KEY", "deepseek-secret")
    observed_redirect_headers: list[dict[str, str]] = []

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
        observed_redirect_headers.append(dict(redirected.header_items()))
        return b'{"choices":[{"message":{"content":"{\\"picks\\":[]}"}}]}'

    call_deepseek("prompt", transport=transport)

    assert "Authorization" not in observed_redirect_headers[0]


@pytest.mark.parametrize("provider", ["deepseek", "gemini"])
def test_provider_rejects_unsafe_model_name(
    provider: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("DEEPSEEK_API_KEY", "key")
    monkeypatch.setenv("GEMINI_API_KEY", "key")
    function = call_deepseek if provider == "deepseek" else call_gemini
    with pytest.raises(ProviderError, match="model name"):
        function("prompt", model="../../secret")


@pytest.mark.parametrize(
    "body",
    [
        b"not-json",
        b"[]",
        b"{}",
        b'{"choices": []}',
        b'{"candidates": []}',
    ],
)
def test_provider_response_failures_are_sanitized(
    body: bytes, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("DEEPSEEK_API_KEY", "secret")

    def transport(_request: urllib.request.Request, _timeout: float) -> bytes:
        return body

    with pytest.raises(ProviderError, match="provider|DeepSeek") as error:
        call_deepseek("prompt", transport=transport)
    assert "secret" not in str(error.value)


def test_transport_error_is_sanitized(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DEEPSEEK_API_KEY", "secret")

    def transport(_request: urllib.request.Request, _timeout: float) -> bytes:
        raise urllib.error.URLError("secret internal detail")

    with pytest.raises(ProviderError, match="request failed") as error:
        call_deepseek("prompt", transport=transport)
    assert "secret internal detail" not in str(error.value)


@pytest.mark.parametrize("status", [429, 500, 503])
def test_retryable_http_status_has_machine_readable_marker(
    status: int, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("DEEPSEEK_API_KEY", "secret")

    def transport(request: urllib.request.Request, _timeout: float) -> bytes:
        raise urllib.error.HTTPError(
            request.full_url,
            status,
            "sensitive provider detail",
            HTTPMessage(),
            None,
        )

    with pytest.raises(
        ProviderError,
        match=rf"provider request failed: retryable:http_{status}",
    ) as error:
        call_deepseek("prompt", transport=transport)
    assert "sensitive provider detail" not in str(error.value)


@pytest.mark.parametrize("status", [400, 401, 402, 403])
def test_nonretryable_http_status_has_machine_readable_marker(
    status: int, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("DEEPSEEK_API_KEY", "secret")

    def transport(request: urllib.request.Request, _timeout: float) -> bytes:
        raise urllib.error.HTTPError(
            request.full_url,
            status,
            "sensitive provider detail",
            HTTPMessage(),
            None,
        )

    with pytest.raises(
        ProviderError,
        match=rf"provider request failed: nonretryable:http_{status}",
    ) as error:
        call_deepseek("prompt", transport=transport)
    assert "sensitive provider detail" not in str(error.value)


@pytest.mark.parametrize("timeout", [0.0, -1.0, float("nan"), float("inf")])
def test_timeout_must_be_positive_and_finite(
    timeout: float, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("DEEPSEEK_API_KEY", "key")
    with pytest.raises(ProviderError, match="positive finite"):
        call_deepseek("prompt", timeout=timeout)


def test_provider_enforces_prompt_and_response_limits(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DEEPSEEK_API_KEY", "key")
    with pytest.raises(ProviderError, match="prompt exceeds"):
        call_deepseek("x" * 2_000_001)

    def transport(_request: urllib.request.Request, _timeout: float) -> bytes:
        return b"x" * 2_000_001

    with pytest.raises(ProviderError, match="response exceeds"):
        call_deepseek("prompt", transport=transport)
