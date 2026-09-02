from __future__ import annotations

import json
from pathlib import Path

import pytest

from stock_analysis.app.cli import main


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _selection(path: Path, *symbols: str) -> None:
    payload = {
        "artifact_type": "ai_stock_selection",
        "picks": [
            {"rank": rank, "symbol": symbol}
            for rank, symbol in enumerate(symbols, 1)
        ],
    }
    _write_json(path, payload)
    evidence = path.with_suffix(".evidence")
    _write_json(
        evidence / "manifest.json",
        {
            "artifact_type": "ai_selection_evidence",
            "status": "complete",
            "campaign_id": "demo-order-sensitivity",
            "trial_id": path.stem,
            "top_n": 3,
            "selection_path": "selection.json",
        },
    )
    _write_json(evidence / "selection.json", payload)


def test_stability_summary_cli_writes_json_and_prints_human_summary(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    campaign = tmp_path / "campaign"
    _write_json(
        campaign / "manifest.json",
        {
            "schema_version": "2.0.0",
            "artifact_type": "ai_stability_campaign",
            "status": "planned",
            "campaign_id": "demo-order-sensitivity",
            "top_n": 3,
            "variants": [
                {"trial_id": "canonical"},
                {"trial_id": "shuffle_101"},
            ],
        },
    )
    results = tmp_path / "results"
    _selection(results / "canonical.json", "999001.SZ", "999002.SZ", "999003.SZ")
    _selection(results / "shuffle_101.json", "999001.SZ", "999003.SZ", "999002.SZ")
    output = tmp_path / "summary.json"

    code = main(
        [
            "cn",
            "stability-summary",
            "--campaign-dir",
            str(campaign),
            "--results-dir",
            str(results),
            "--output",
            str(output),
        ]
    )

    assert code == 0
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["artifact_type"] == "ai_stability_summary"
    assert payload["status"] == "complete"
    stdout = capsys.readouterr().out
    assert "campaign=demo-order-sensitivity" in stdout
    assert "top1_agreement_vs_canonical=100.0%" in stdout
    assert f"summary_json={output.resolve()}" in stdout
