"""Compatibility alias for execution account snapshot services."""

from __future__ import annotations

import sys

from .._compat import warn_legacy_import
from ..execution.services import account_snapshot as _impl

warn_legacy_import(
    "stock_analysis.services.account_snapshot",
    "stock_analysis.execution.services.account_snapshot",
)
sys.modules[__name__] = _impl
