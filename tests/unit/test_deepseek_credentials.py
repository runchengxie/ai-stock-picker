"""Regression tests for DeepSeek credential selection."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from unittest.mock import Mock

import pytest


def _load_deepseek_pick():
    script_path = Path(__file__).resolve().parents[2] / "scripts" / "deepseek_pick.py"
    spec = importlib.util.spec_from_file_location(
        "ai_picker_deepseek_pick", script_path
    )
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load {script_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_stock_picker_rejects_openai_key_before_network(monkeypatch):
    deepseek_pick = _load_deepseek_pick()
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "openai-only-key")
    urlopen = Mock(side_effect=AssertionError("network request must not run"))
    monkeypatch.setattr(deepseek_pick.urllib.request, "urlopen", urlopen)

    with pytest.raises(RuntimeError, match="Set DEEPSEEK_API_KEY"):
        deepseek_pick.call_deepseek("test prompt")

    urlopen.assert_not_called()
