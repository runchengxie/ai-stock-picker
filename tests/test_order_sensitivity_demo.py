from __future__ import annotations

from datetime import date
from pathlib import Path

from stock_analysis.ai_lab.evidence import write_stability_campaign
from stock_analysis.ai_lab.selection import build_selection_plan


def test_order_sensitivity_demo_generates_five_network_free_arms(
    tmp_path: Path,
) -> None:
    repository_root = Path(__file__).resolve().parents[1]
    candidates = repository_root / "experiments/order-sensitivity/candidates.json"
    plan = build_selection_plan(
        market="CN",
        candidates_path=candidates,
        as_of=date(2026, 6, 30),
        top_n=3,
        style="momentum",
    )

    campaign = write_stability_campaign(
        plan,
        tmp_path / "campaign",
        campaign_id="order-sensitivity-demo-v1",
    )

    manifest = (campaign / "manifest.json").read_text(encoding="utf-8")
    assert '"api_calls": 0' in manifest
    assert all(
        (campaign / f"trials/{trial_id}/trial.json").is_file()
        for trial_id in (
            "canonical",
            "shuffle_101",
            "shuffle_202",
            "shuffle_303",
            "opaque_404",
        )
    )
