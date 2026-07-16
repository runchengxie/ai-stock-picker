"""Normalize provider inference settings before a selection request is built."""

from __future__ import annotations

from .contracts import Provider
from .providers import (
    DEFAULT_DEEPSEEK_MAX_TOKENS,
    DEFAULT_DEEPSEEK_THINKING,
    ProviderParameterSchema,
    ReasoningEffort,
    ThinkingMode,
    deepseek_provider_parameters,
)


def inference_parameters(
    provider: Provider,
    *,
    thinking: ThinkingMode | None,
    reasoning_effort: ReasoningEffort | None,
    max_tokens: int | None,
    parameter_schema: ProviderParameterSchema,
) -> tuple[ThinkingMode | None, ReasoningEffort | None, int | None]:
    """Return the validated inference settings supported by one provider."""

    if provider != "deepseek":
        if (
            thinking is not None
            or reasoning_effort is not None
            or max_tokens is not None
            or parameter_schema != "explicit_v2"
        ):
            raise ValueError("DeepSeek inference parameters require the CN market")
        return None, None, None
    if parameter_schema == "legacy_v1":
        if (
            thinking is not None
            or reasoning_effort is not None
            or max_tokens is not None
        ):
            raise ValueError("legacy_v1 does not accept inference parameters")
        return None, None, None
    if parameter_schema != "explicit_v2":
        raise ValueError("unsupported DeepSeek parameter schema")
    selected_thinking = thinking or DEFAULT_DEEPSEEK_THINKING
    selected_effort = reasoning_effort
    if selected_thinking == "enabled" and selected_effort is None:
        selected_effort = "high"
    selected_max_tokens = (
        max_tokens if max_tokens is not None else DEFAULT_DEEPSEEK_MAX_TOKENS
    )
    deepseek_provider_parameters(
        thinking=selected_thinking,
        reasoning_effort=selected_effort,
        max_tokens=selected_max_tokens,
    )
    return selected_thinking, selected_effort, selected_max_tokens


__all__ = ["inference_parameters"]
