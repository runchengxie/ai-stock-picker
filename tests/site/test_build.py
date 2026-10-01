"""Publishing tests exercise provenance and filesystem safety, not chart styling."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def load_builder():
    spec = importlib.util.spec_from_file_location(
        "site_builder", ROOT / "scripts/site/build.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def snapshot() -> dict:
    return {
        "schema_version": "research_site.v1",
        "reviewed_on": "2026-10-01",
        "research_only": True,
        "strict_point_in_time": False,
        "eligible_as_oos_evidence": False,
        "sources": [{"id": "report", "file": "report.json", "sha256": "a" * 64}],
        "studies": {},
        "daily": {"rows": [], "offline_rehearsal": None},
    }


def test_checksum_mismatch_cannot_publish(tmp_path: Path) -> None:
    builder = load_builder()
    source = tmp_path / "snapshot.json"
    source.write_text(json.dumps(snapshot()))
    with pytest.raises(ValueError, match="SHA-256"):
        builder.read_snapshot(source, "b" * 64)


@pytest.mark.parametrize(
    "field,value",
    [("strict_point_in_time", True), ("research_only", False)],
)
def test_source_cannot_upgrade_evidence(field: str, value: bool) -> None:
    builder = load_builder()
    data = snapshot()
    data[field] = value
    with pytest.raises(ValueError, match="evidence"):
        builder.validate_snapshot(data)


def test_rejects_unreviewed_payload_fields() -> None:
    builder = load_builder()
    data = snapshot()
    data["api_key"] = "must never publish"
    with pytest.raises(ValueError, match="fields"):
        builder.validate_snapshot(data)


def test_daily_status_is_not_inferred_from_a_valid_stock_list() -> None:
    builder = load_builder()
    data = snapshot()
    data["daily"]["rows"] = [{"evidence_status": "legacy_unbound"}]
    with pytest.raises(ValueError, match="prospective"):
        builder.validate_snapshot(data)


def test_build_never_overwrites_a_site(tmp_path: Path) -> None:
    builder = load_builder()
    output = tmp_path / "published"
    output.mkdir()
    marker = output / "keep.txt"
    marker.write_text("existing site")
    with pytest.raises(FileExistsError):
        builder.stage_site(ROOT / "site", snapshot(), output)
    assert marker.read_text() == "existing site"


def test_build_output_must_stay_outside_checkout() -> None:
    builder = load_builder()
    with pytest.raises(ValueError, match="outside"):
        builder.stage_site(ROOT / "site", snapshot(), ROOT / "generated-site")


def test_disagreeing_arm_totals_are_rejected() -> None:
    builder = load_builder()
    data = snapshot()
    data["studies"]["stability"] = {
        "source_ids": ["report"],
        "calls": 100,
        "days": 20,
        "passed": 34,
        "required": 95,
        "arms": {"canonical": 35},
    }
    with pytest.raises(ValueError, match="counts"):
        builder.validate_snapshot(data)


def test_false_return_backtest_claim_is_rejected() -> None:
    builder = load_builder()
    data = snapshot()
    data["studies"]["models"] = {
        "source_ids": ["report"],
        "return_backtest_executed": True,
    }
    with pytest.raises(ValueError, match="not run"):
        builder.validate_snapshot(data)
