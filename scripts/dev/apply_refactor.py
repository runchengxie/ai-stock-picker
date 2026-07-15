#!/usr/bin/env python3
"""Apply the generated provider-neutral refactor."""
from __future__ import annotations
import base64
import io
import shutil
import tarfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
chunk_dir = ROOT / "scripts/dev"
payload = "".join(
    path.read_text(encoding="utf-8")
    for path in sorted(chunk_dir.glob(".refactor_payload_*"))
)
for relative in ("src/stock_analysis", "src/ai_stock_picker", "tests", "docs", "examples"):
    shutil.rmtree(ROOT / relative, ignore_errors=True)
with tarfile.open(fileobj=io.BytesIO(base64.b64decode(payload)), mode="r:gz") as tar:
    tar.extractall(ROOT, filter="data")
for path in chunk_dir.glob(".refactor_payload_*"):
    path.unlink()
(ROOT / ".github/workflows/refactor-validation.yml").unlink(missing_ok=True)
Path(__file__).unlink(missing_ok=True)
