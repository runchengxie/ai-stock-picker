from __future__ import annotations

import json
from pathlib import Path

from stock_analysis.ai_lab.stability_analysis import summarize_stability_results


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


def test_disjoint_ranking_reports_zero_overlap_without_crashing(tmp_path: Path) -> None:
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
    _selection(results / "shuffle_101.json", "999004.SZ", "999005.SZ", "999006.SZ")

    summary = summarize_stability_results(campaign, results)

    arm = next(arm for arm in summary["arms"] if arm["trial_id"] == "shuffle_101")
    assert arm["top_n_jaccard_vs_canonical"] == 0.0
    assert arm["mean_absolute_rank_shift_vs_canonical"] is None
    assert summary["aggregate"]["mean_absolute_rank_shift_vs_canonical"] is None
