from __future__ import annotations

import json
from pathlib import Path

import pytest

from stock_analysis.app.commands import targets as targets_cmd
from stock_analysis.contracts.targets import read_targets_json, write_targets_json


@pytest.mark.unit
def test_write_targets_json_schema_v2_roundtrip(tmp_path: Path) -> None:
    out_path = tmp_path / "targets.json"

    write_targets_json(
        out_path,
        asof="2025-09-05",
        source="research",
        target_gross_exposure=0.9,
        targets=[
            {"symbol": "AAPL", "market": "US", "target_weight": 0.6},
            {"symbol": "700", "market": "HK", "target_weight": 0.3},
        ],
    )

    raw = json.loads(out_path.read_text(encoding="utf-8"))
    assert raw["schema_version"] == 2
    assert raw["target_gross_exposure"] == 0.9
    assert raw["targets"][1]["market"] == "HK"

    parsed = read_targets_json(out_path, require_schema_v2=True)
    assert parsed.schema_version == 2
    assert parsed.target_gross_exposure == pytest.approx(0.9)
    assert [target.key for target in parsed.targets] == ["AAPL.US", "700.HK"]


@pytest.mark.unit
def test_read_targets_json_rejects_legacy_for_canonical_execution(
    tmp_path: Path,
) -> None:
    legacy_path = tmp_path / "legacy_targets.json"
    legacy_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "source": "ai_pick",
                "asof": "2025-09-05",
                "tickers": ["AAPL", "MSFT"],
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="stockq targets gen"):
        read_targets_json(legacy_path, require_schema_v2=True)


@pytest.mark.unit
@pytest.mark.parametrize(
    ("source", "json_root_name", "payload_key", "expected_source"),
    [
        ("ai", "ai_pick", "picks", "ai_lab"),
        ("preliminary", "preliminary", "rows", "research"),
    ],
)
def test_run_targets_gen_normalizes_result_json_to_schema_v2(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    source: str,
    json_root_name: str,
    payload_key: str,
    expected_source: str,
) -> None:
    outputs_dir = tmp_path / "outputs"
    json_root = outputs_dir / json_root_name / "2025"
    json_root.mkdir(parents=True)
    result_path = json_root / "2025-09-05.json"
    result_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "trade_date": "2025-09-05",
                payload_key: [{"ticker": "AAPL"}, {"ticker": "MSFT"}],
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(targets_cmd, "OUTPUTS_DIR", outputs_dir)
    monkeypatch.setattr(targets_cmd, "AI_PORTFOLIO_JSON_DIR", outputs_dir / "ai_pick")
    monkeypatch.setattr(
        targets_cmd, "QUANT_PORTFOLIO_JSON_DIR", outputs_dir / "preliminary"
    )
    monkeypatch.setattr(targets_cmd, "AI_PORTFOLIO_FILE", outputs_dir / "ai.xlsx")
    monkeypatch.setattr(
        targets_cmd, "QUANT_PORTFOLIO_FILE", outputs_dir / "preliminary.xlsx"
    )

    rc = targets_cmd.run_targets_gen(source=source)
    assert rc == 0

    target_path = outputs_dir / "targets" / "2025-09-05.json"
    parsed = read_targets_json(target_path, require_schema_v2=True)
    assert parsed.source == expected_source
    assert parsed.asof == "2025-09-05"
    assert [target.key for target in parsed.targets] == ["AAPL.US", "MSFT.US"]
    assert parsed.targets[0].target_weight == pytest.approx(0.5)
