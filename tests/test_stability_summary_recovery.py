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


def test_uses_complete_evidence_selection_when_external_output_is_missing(
    tmp_path: Path,
) -> None:
    campaign = tmp_path / "campaign"
    _write_json(
        campaign / "manifest.json",
        {
            "artifact_type": "ai_stability_campaign",
            "status": "planned",
            "campaign_id": "demo-order-sensitivity",
            "top_n": 3,
            "variants": [{"trial_id": "canonical"}],
        },
    )
    results = tmp_path / "results"
    payload = {
        "artifact_type": "ai_stock_selection",
        "picks": [
            {"rank": 1, "symbol": "999001.SZ"},
            {"rank": 2, "symbol": "999002.SZ"},
            {"rank": 3, "symbol": "999003.SZ"},
        ],
    }
    evidence = results / "canonical.evidence"
    _write_json(
        evidence / "manifest.json",
        {
            "artifact_type": "ai_selection_evidence",
            "status": "complete",
            "campaign_id": "demo-order-sensitivity",
            "trial_id": "canonical",
            "top_n": 3,
            "selection_path": "selection.json",
        },
    )
    _write_json(evidence / "selection.json", payload)

    summary = summarize_stability_results(campaign, results)

    canonical = next(arm for arm in summary["arms"] if arm["trial_id"] == "canonical")
    assert canonical["status"] == "complete"
    assert canonical["ranking_source"] == "canonical.evidence/selection.json"
    assert canonical["ranking"] == ["999001.SZ", "999002.SZ", "999003.SZ"]
