"""Helpers for legacy compatibility shims."""

from __future__ import annotations

import warnings


def warn_legacy_import(legacy_path: str, new_path: str) -> None:
    """Emit a deprecation warning for a legacy import path."""

    warnings.warn(
        f"{legacy_path} is deprecated; import {new_path} instead.",
        DeprecationWarning,
        stacklevel=2,
    )

