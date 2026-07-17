"""Strict provider-response parsing shared by selection profiles."""

from __future__ import annotations

from pydantic import ValidationError

from .contracts import ModelSelection

_MAX_RESPONSE_BYTES = 1_000_000


def parse_response(response_text: str) -> ModelSelection:
    if len(response_text.encode()) > _MAX_RESPONSE_BYTES:
        raise ValueError("provider output exceeds the 1 MB safety limit")
    text = response_text.strip()
    if text.startswith("```json\n") and text.endswith("\n```"):
        text = text[len("```json\n") : -len("\n```")].strip()
    elif "```" in text:
        raise ValueError("provider output contains malformed markdown fences")
    try:
        return ModelSelection.model_validate_json(text, strict=True)
    except ValidationError as exc:
        raise ValueError(f"provider output violates the strict schema: {exc}") from exc


__all__ = ["parse_response"]
