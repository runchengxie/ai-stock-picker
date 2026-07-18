"""Exact request/response validation for research shadow provider exchanges."""

from __future__ import annotations

import json
import math
from collections.abc import Mapping
from typing import cast

from .contracts import RankingModelSelection
from .providers import (
    DEEPSEEK_SYSTEM_MESSAGE,
    OPENAI_RESPONSES_ENDPOINT,
    OPENAI_SYSTEM_MESSAGE,
    ProviderExchange,
    ReasoningEffort,
    ThinkingMode,
    deepseek_request_parameters,
    inspect_deepseek_response,
    inspect_openai_response,
)

_DEEPSEEK_ENDPOINT = "https://api.deepseek.com/v1/chat/completions"
_EXPECTED_HEADERS = (
    ("Content-Type", "application/json"),
    ("Authorization", "<redacted>"),
)


def validate_shadow_exchange(
    exchange: ProviderExchange,
    *,
    prompt: str,
    provider: str,
    model_parameters: Mapping[str, object],
    response_schema: Mapping[str, object] | None = None,
    response_schema_name: str = "ai_stock_ranking",
) -> None:
    """Require byte evidence to match the frozen provider request and raw response."""

    model = model_parameters.get("model")
    if (
        provider not in {"deepseek", "openai"}
        or not isinstance(model, str)
        or exchange.provider != provider
        or exchange.model != model
    ):
        raise ValueError("shadow provider exchange does not match its model partition")
    expected_endpoint = (
        OPENAI_RESPONSES_ENDPOINT if provider == "openai" else _DEEPSEEK_ENDPOINT
    )
    if exchange.request_method != "POST" or exchange.endpoint != expected_endpoint:
        raise ValueError("shadow provider exchange transport is invalid")
    if not math.isfinite(exchange.timeout_seconds) or exchange.timeout_seconds <= 0:
        raise ValueError("shadow provider exchange timeout is invalid")
    if tuple(exchange.request_headers) != _EXPECTED_HEADERS:
        raise ValueError("shadow provider exchange headers are inconsistent")
    if not exchange.request_body or not exchange.response_body:
        raise ValueError(
            "shadow provider exchange must preserve request and response bytes"
        )
    try:
        request = json.loads(exchange.request_body)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("shadow provider request body must contain JSON") from exc
    if not isinstance(request, dict):
        raise ValueError("shadow provider request body must be an object")
    expected_request = _expected_request(
        prompt,
        provider,
        model_parameters,
        response_schema=response_schema,
        response_schema_name=response_schema_name,
    )
    if request != expected_request:
        raise ValueError("shadow provider request differs from the frozen prompt")
    parsed = (
        inspect_openai_response(exchange.response_body)
        if provider == "openai"
        else inspect_deepseek_response(exchange.response_body)
    )
    archived = (
        exchange.response_text,
        exchange.actual_model,
        exchange.extraction_error,
        exchange.refusal,
        exchange.usage,
    )
    if archived != parsed:
        raise ValueError("shadow provider response fields differ from the raw response")


def _expected_request(
    prompt: str,
    provider: str,
    parameters: Mapping[str, object],
    *,
    response_schema: Mapping[str, object] | None,
    response_schema_name: str,
) -> dict[str, object]:
    model = cast(str, parameters["model"])
    maximum = cast(int, parameters["max_output_tokens"])
    if provider == "openai":
        return {
            "model": model,
            "instructions": OPENAI_SYSTEM_MESSAGE,
            "input": prompt,
            "store": False,
            "max_output_tokens": maximum,
            "text": {
                "format": {
                    "type": "json_schema",
                    "name": response_schema_name,
                    "strict": True,
                    "schema": dict(
                        response_schema or RankingModelSelection.model_json_schema()
                    ),
                }
            },
        }
    inference = deepseek_request_parameters(
        parameter_schema="explicit_v2",
        thinking=cast(ThinkingMode, parameters["thinking"]),
        reasoning_effort=cast(ReasoningEffort | None, parameters["reasoning_effort"]),
        max_tokens=maximum,
    )
    return {
        "model": model,
        "messages": [
            {"role": "system", "content": DEEPSEEK_SYSTEM_MESSAGE},
            {"role": "user", "content": prompt},
        ],
        **inference,
    }


__all__ = ["validate_shadow_exchange"]
