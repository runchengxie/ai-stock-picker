#!/usr/bin/env python3
"""Remove the obsolete Python namespace before validation."""

from __future__ import annotations

import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
shutil.rmtree(ROOT / "src/stock_analysis", ignore_errors=True)
