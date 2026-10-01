"""The Pages build publishes only hash-pinned, validated research data."""

from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[2]


def load_stager():
    source = ROOT / "scripts/site/stage_snapshot.py"
    spec = importlib.util.spec_from_file_location("stage_snapshot", source)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def snapshot() -> dict[str, Any]:
    return {
        "schema_version": "research_site.v1",
        "reviewed_on": "2026-10-01",
        "research_only": True,
        "strict_point_in_time": False,
        "eligible_as_oos_evidence": False,
        "sources": [],
        "studies": {},
        "daily": {"rows": [], "offline_rehearsal": None},
    }


def write_snapshot(path: Path, data: dict[str, Any]) -> str:
    raw = json.dumps(data, separators=(",", ":")).encode()
    path.write_bytes(raw)
    return hashlib.sha256(raw).hexdigest()


def test_stage_snapshot_writes_validated_data_externally(tmp_path: Path) -> None:
    stager = load_stager()
    source = tmp_path / "source.json"
    expected = write_snapshot(source, snapshot())
    output = tmp_path / "published/research.json"

    result = stager.stage_snapshot(source, expected, output)

    assert result == output
    assert output.read_bytes() == source.read_bytes()
    assert json.loads(output.read_text()) == snapshot()


def test_stage_snapshot_rejects_a_digest_mismatch(tmp_path: Path) -> None:
    stager = load_stager()
    source = tmp_path / "source.json"
    write_snapshot(source, snapshot())

    with pytest.raises(ValueError, match="SHA-256"):
        stager.stage_snapshot(source, "0" * 64, tmp_path / "published.json")


def test_stage_snapshot_rejects_nested_private_payload(tmp_path: Path) -> None:
    stager = load_stager()
    data = snapshot()
    data["daily"]["offline_rehearsal"] = {"response_bytes": "private"}
    source = tmp_path / "source.json"
    expected = write_snapshot(source, data)

    with pytest.raises(ValueError, match="public contract"):
        stager.stage_snapshot(source, expected, tmp_path / "published.json")


def test_stage_snapshot_refuses_paths_inside_checkout(tmp_path: Path) -> None:
    stager = load_stager()
    source = tmp_path / "source.json"
    expected = write_snapshot(source, snapshot())

    with pytest.raises(ValueError, match="outside"):
        stager.stage_snapshot(source, expected, ROOT / "generated-research.json")


def test_stage_snapshot_never_overwrites_existing_output(tmp_path: Path) -> None:
    stager = load_stager()
    source = tmp_path / "source.json"
    expected = write_snapshot(source, snapshot())
    output = tmp_path / "published.json"
    output.write_text("keep me")

    with pytest.raises(FileExistsError):
        stager.stage_snapshot(source, expected, output)
    assert output.read_text() == "keep me"
