#!/usr/bin/env python3
"""Validate a reviewed snapshot and stage its original bytes outside the checkout."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _load_validator():
    source = Path(__file__).with_name("build.py")
    spec = importlib.util.spec_from_file_location("research_site_builder", source)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load the research snapshot validator")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.read_snapshot


def stage_snapshot(snapshot: Path, expected_sha256: str, output: Path) -> Path:
    """Validate a pinned release asset and stage its unchanged bytes at output."""
    output = output.expanduser().resolve()
    if output == ROOT or ROOT in output.parents:
        raise ValueError("staged snapshot must stay outside the checkout")

    raw = snapshot.expanduser().read_bytes()
    read_snapshot = _load_validator()
    read_snapshot(snapshot.expanduser(), expected_sha256)
    if hashlib.sha256(raw).hexdigest() != expected_sha256:
        raise ValueError("research snapshot SHA-256 mismatch")

    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("xb") as stream:
        stream.write(raw)
    return output


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    pin = json.loads((ROOT / "site/research-source.json").read_text())
    stage_snapshot(args.snapshot, pin["sha256"], args.output)


if __name__ == "__main__":
    main()
