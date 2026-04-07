"""Compatibility alias for execution rebalancing services."""

from __future__ import annotations

import sys

from .._compat import warn_legacy_import
from ..execution.services import rebalancer as _impl

warn_legacy_import(
    "stock_analysis.services.rebalancer",
    "stock_analysis.execution.services.rebalancer",
)
sys.modules[__name__] = _impl
