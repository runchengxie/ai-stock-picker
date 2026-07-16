"""Exact provider request-envelope validation."""

from __future__ import annotations

from collections.abc import Mapping

from .providers import DEEPSEEK_SYSTEM_MESSAGE, GEMINI_SYSTEM_MESSAGE
from .selection import SelectionPlan


def validate_provider_request(
    plan: SelectionPlan,
    request: Mapping[str, object],
    parameters: Mapping[str, object],
) -> None:
    """Require the full request body to match the frozen selection plan."""

    if plan.provider == "deepseek":
        _validate_deepseek_request(plan, request, parameters)
    else:
        _validate_gemini_request(plan, request, parameters)


def _validate_deepseek_request(
    plan: SelectionPlan,
    request: Mapping[str, object],
    parameters: Mapping[str, object],
) -> None:
    expected_parameters = {"model": plan.model, **parameters}
    allowed = {"model", "messages", *expected_parameters}
    if set(request) != allowed:
        raise ValueError("provider request contains unexpected parameters")
    actual = {field: request.get(field) for field in expected_parameters}
    if actual != expected_parameters:
        raise ValueError("provider request parameters do not match the selection plan")
    expected_messages = [
        {"role": "system", "content": DEEPSEEK_SYSTEM_MESSAGE},
        {"role": "user", "content": plan.prompt},
    ]
    if request.get("messages") != expected_messages:
        raise ValueError("provider request does not contain the exact messages")


def _validate_gemini_request(
    plan: SelectionPlan,
    request: Mapping[str, object],
    parameters: Mapping[str, object],
) -> None:
    if set(request) != {"contents", "generationConfig", "systemInstruction"}:
        raise ValueError("provider request contains unexpected parameters")
    expected_generation = {
        "temperature": parameters.get("temperature"),
        "responseMimeType": parameters.get("response_mime_type"),
    }
    if request.get("generationConfig") != expected_generation:
        raise ValueError("provider request parameters do not match the selection plan")
    expected_contents = [{"role": "user", "parts": [{"text": plan.prompt}]}]
    expected_system = {"parts": [{"text": GEMINI_SYSTEM_MESSAGE}]}
    if (
        request.get("contents") != expected_contents
        or request.get("systemInstruction") != expected_system
    ):
        raise ValueError("provider request does not contain the exact messages")


__all__ = ["validate_provider_request"]
