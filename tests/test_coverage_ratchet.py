from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import ModuleType


def load_module() -> ModuleType:
    path = Path(__file__).resolve().parents[1] / "scripts/dev/coverage_ratchet.py"
    spec = importlib.util.spec_from_file_location("coverage_ratchet", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_coverage_ratchet_passes_and_fails(tmp_path: Path) -> None:
    module = load_module()
    coverage = tmp_path / "coverage.json"
    baseline = tmp_path / "baseline.json"
    coverage.write_text(
        json.dumps(
            {
                "totals": {
                    "percent_statements_covered": 90.0,
                    "percent_branches_covered": 70.0,
                }
            }
        ),
        encoding="utf-8",
    )
    baseline.write_text(
        json.dumps({"statements": 86.5, "branches": 66.3}), encoding="utf-8"
    )
    assert module.check_coverage(coverage, baseline) == []
    baseline.write_text(
        json.dumps({"statements": 91.0, "branches": 71.0}), encoding="utf-8"
    )
    failures = module.check_coverage(coverage, baseline)
    assert len(failures) == 2
