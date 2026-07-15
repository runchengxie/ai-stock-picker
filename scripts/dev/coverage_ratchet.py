#!/usr/bin/env python3
"""Fail when statement or branch coverage falls below the recorded baseline."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import cast


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _read_object(path: Path) -> dict[str, object]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ValueError(f"missing coverage file: {path}") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid JSON in {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"expected a JSON object in {path}")
    return cast(dict[str, object], payload)


def _percentage(payload: dict[str, object], field: str) -> float:
    value = payload.get(field)
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ValueError(f"coverage field {field} must be numeric")
    return float(value)


def check_coverage(coverage_path: Path, baseline_path: Path) -> list[str]:
    """Return human-readable failures for coverage below baseline."""

    coverage = _read_object(coverage_path)
    totals = coverage.get("totals")
    if not isinstance(totals, dict):
        raise ValueError("coverage JSON is missing totals")
    baseline = _read_object(baseline_path)
    actuals = {
        "statements": _percentage(
            cast(dict[str, object], totals), "percent_statements_covered"
        ),
        "branches": _percentage(
            cast(dict[str, object], totals), "percent_branches_covered"
        ),
    }
    failures: list[str] = []
    for name, actual in actuals.items():
        minimum = _percentage(baseline, name)
        if actual + 1e-9 < minimum:
            failures.append(f"{name}: {actual:.2f}% < baseline {minimum:.2f}%")
    return failures


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    root = _repo_root()
    parser.add_argument("--coverage", type=Path, default=root / ".coverage.json")
    parser.add_argument(
        "--baseline", type=Path, default=root / "scripts/dev/coverage_baseline.json"
    )
    args = parser.parse_args(argv)
    try:
        failures = check_coverage(args.coverage, args.baseline)
    except ValueError as exc:
        print(f"coverage ratchet: {exc}", file=sys.stderr)
        return 2
    if failures:
        print("Coverage ratchet failed:", file=sys.stderr)
        for failure in failures:
            print(f"- {failure}", file=sys.stderr)
        return 1
    print("Coverage ratchet passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
