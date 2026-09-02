from __future__ import annotations

import json
from pathlib import Path

import pytest

from stock_analysis.ai_lab.stability_analysis import (
    render_stability_summary,
    summarize_stability_results,
    write_stability_summary,
)


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _campaign(tmp_path: Path) -> Path:
    root = tmp_path / "campaign"
    variants = [
        {"trial_id": "canonical"},
        {"trial_id": "shuffle_101"},
        {"trial_id": "shuffle_202"},
        {"trial_id": "shuffle_303"},
        {"trial_id": "opaque_404"},
    ]
    _write_json(
        root / "manifest.json",
        {
            "schema_version": "2.0.0",
            "artifact_type": "ai_stability_campaign",
            "status": "planned",
            "campaign_id": "demo-order-sensitivity",
            "top_n": 3,
            "variants": variants,
        },
    )
    return root


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


def test_writes_deterministic_summary_and_refuses_overwrite(tmp_path: Path) -> None:
    summary = {"z": 1, "a": {"b": 2}}
    output = tmp_path / "summary.json"

    assert write_stability_summary(summary, output) == output.resolve()
    assert output.read_text(encoding="utf-8") == (
        '{\n  "a": {\n    "b": 2\n  },\n  "z": 1\n}\n'
    )

    with pytest.raises(FileExistsError, match="stability summary already exists"):
        write_stability_summary(summary, output)


def test_renders_short_human_summary(tmp_path: Path) -> None:
    campaign = _campaign(tmp_path)
    results = tmp_path / "results"
    _selection(results / "canonical.json", "999001.SZ", "999002.SZ", "999003.SZ")
    _selection(results / "shuffle_101.json", "999001.SZ", "999003.SZ", "999002.SZ")

    summary = summarize_stability_results(campaign, results)
    rendered = render_stability_summary(summary)

    assert "campaign=demo-order-sensitivity" in rendered
    assert "status=partial" in rendered
    assert "completed_noncanonical_arms=1/4" in rendered
    assert "top1_agreement_vs_canonical=100.0%" in rendered
    assert "exact_ranking_agreement_vs_canonical=0.0%" in rendered
    assert "missing_trials=shuffle_202,shuffle_303,opaque_404" in rendered
