"""Compatibility alias for execution broker stubs."""

from __future__ import annotations

import sys

from ..execution.broker import _stubs as _impl

sys.modules[__name__] = _impl

