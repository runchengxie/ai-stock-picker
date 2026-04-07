"""Compatibility alias for the execution LongPort client."""

from __future__ import annotations

import sys

from .._compat import warn_legacy_import
from ..execution.broker import longport_client as _impl

warn_legacy_import(
    "stock_analysis.broker.longport_client",
    "stock_analysis.execution.broker.longport_client",
)
sys.modules[__name__] = _impl
