from __future__ import annotations

import json
from datetime import date, datetime, timezone
from hashlib import sha256
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest
from conftest import write_manifest

from stock_analysis.ai_lab.frozen_plan import load_pick_plan, write_pick_plan
from stock_analysis.ai_lab.providers import OPENAI_SYSTEM_MESSAGE, ProviderExchange
from stock_analysis.ai_lab.ranking_policy import policy_partitions
from stock_analysis.ai_lab.ranking_policy_contract import BOUNDED_RANKING_V3_POLICY
from stock_analysis.ai_lab.selection import build_selection_plan
from stock_analysis.ai_lab.shadow_campaign import ShadowModel, run_shadow_day
from stock_analysis.ai_lab.shadow_contract import (
    shadow_response_schema,
    shadow_response_schema_name,
)
from stock_analysis.ai_lab.shadow_lineage import (
    canonical_content_sha256,
    load_shadow_decision_plan,
    load_shadow_launch_receipt,
    write_shadow_decision_plan,
    write_shadow_launch_receipt,
)
from stock_analysis.ai_lab.shadow_validation import (
    validate_shadow_day,
    validate_shadow_repetition,
)

_SIGNAL_DATE = date(2026, 7, 15)
_AFTER_CLOSE = datetime(2026, 7, 15, 8, 30, tzinfo=timezone.utc)


def _frozen_plan(tmp_path: Path) -> Any:
    rows = [
        {
            "ts_code": f"{600000 + index:06d}.SH",
            "name": f"候选{index:02d}",
            "score": 100.0 - index,
            "relevance": 1.0 - index / 100,
            "source_topics": [f"主题{index % 3}"],
            "source_concepts": [f"概念{index % 4}"],
            "trend_score": round(1.0 - index / 50, 4),
            "risk_score": round(0.9 - index / 100, 4),
        }
        for index in range(1, 21)
    ]
    candidates = write_manifest(tmp_path / "candidates.json", rows=rows)
    plan = build_selection_plan(
        market="CN",
        candidates_path=candidates,
        as_of=_SIGNAL_DATE,
        top_n=10,
        style="momentum",
        prompt_profile="bounded_ranking_v3",
    )
    root = write_pick_plan(plan, tmp_path / "frozen-plan")
    return load_pick_plan(root / "plan.json")


def _response(plan: Any) -> str:
    locked, boundary = policy_partitions(plan.universe, BOUNDED_RANKING_V3_POLICY)
    picks = [
        {"symbol": symbol, "confidence_score": 8} for symbol in (*locked, *boundary[:3])
    ]
    return json.dumps({"picks": picks}, ensure_ascii=False)


def _exchange(plan: Any, model: ShadowModel) -> ProviderExchange:
    response = _response(plan)
    request = {
        "model": model.model,
        "instructions": OPENAI_SYSTEM_MESSAGE,
        "input": plan.prompt,
        "store": False,
        "max_output_tokens": model.max_output_tokens,
        "text": {
            "format": {
                "type": "json_schema",
                "name": shadow_response_schema_name(plan),
                "strict": True,
                "schema": shadow_response_schema(plan),
            }
        },
    }
    raw_response = {
        "model": f"{model.model}-actual",
        "output": [
            {
                "type": "message",
                "content": [{"type": "output_text", "text": response}],
            }
        ],
    }
    return ProviderExchange(
        provider="openai",
        model=model.model,
        endpoint="https://api.openai.com/v1/responses",
        request_method="POST",
        request_headers=(
            ("Content-Type", "application/json"),
            ("Authorization", "<redacted>"),
        ),
        request_body=json.dumps(request, ensure_ascii=False).encode(),
        response_body=json.dumps(raw_response, ensure_ascii=False).encode(),
        response_text=response,
        actual_model=f"{model.model}-actual",
        extraction_error=None,
        timeout_seconds=17.0,
    )


def _lineage(tmp_path: Path, plan: Any) -> tuple[Path, Path]:
    decision_path = write_shadow_decision_plan(
        plan,
        tmp_path / "decision",
        campaign_id="prompt-8-prospective",
        signal_date=_SIGNAL_DATE,
    )
    receipt_path = write_shadow_launch_receipt(
        decision_path,
        tmp_path / "receipt",
        provider="openai",
        model="gpt-test",
        issued_at=_AFTER_CLOSE,
    )
    return decision_path, receipt_path


def _run_bound(tmp_path: Path) -> tuple[Any, Any, Path, Path]:
    plan = _frozen_plan(tmp_path)
    decision_path, receipt_path = _lineage(tmp_path, plan)
    with patch(
        "stock_analysis.ai_lab.shadow_campaign.call_shadow_provider",
        side_effect=lambda owner_plan, receipt_model, _repetition, _timeout: _exchange(
            owner_plan, receipt_model
        ),
    ):
        result = run_shadow_day(
            plan,
            tmp_path / "shadow",
            campaign_id="prompt-8-prospective",
            signal_date=_SIGNAL_DATE,
            decision_plan=decision_path,
            launch_receipt=receipt_path,
            generated_at=_AFTER_CLOSE,
        )
    return plan, result, decision_path, receipt_path


def test_bound_shadow_derives_model_and_reports_complete_lineage(
    tmp_path: Path,
) -> None:
    _plan, result, decision_path, receipt_path = _run_bound(tmp_path)
    decision = load_shadow_decision_plan(decision_path)
    receipt = load_shadow_launch_receipt(receipt_path)
    summary = validate_shadow_day(result.day_root)

    assert result.day_root.parent.name == receipt.model_partition
    assert summary["evidence_status"] == "prospective_bound"
    assert summary["decision_plan_sha256"] == decision.decision_plan_sha256
    assert summary["launch_receipt_sha256"] == receipt.launch_receipt_sha256
    manifest = json.loads(
        (result.day_root / "repetition-01" / "manifest.json").read_bytes()
    )
    assert manifest["provider"] == "openai"
    assert manifest["model_parameters"] == receipt.model_parameters
    assert (result.day_root / "repetition-01" / "decision-plan.json").is_file()
    assert (result.day_root / "repetition-01" / "launch-receipt.json").is_file()


def test_canonical_hash_and_validator_reject_rehashed_plan_tampering(
    tmp_path: Path,
) -> None:
    _plan, result, _decision_path, _receipt_path = _run_bound(tmp_path)
    repetition = result.day_root / "repetition-01"
    plan_path = repetition / "decision-plan.json"
    payload = json.loads(plan_path.read_bytes())
    assert payload["content_sha256"] == canonical_content_sha256(payload)
    payload["campaign_id"] = "tampered-campaign"
    encoded = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True).encode()
    plan_path.write_bytes(encoded)
    manifest_path = repetition / "manifest.json"
    manifest = json.loads(manifest_path.read_bytes())
    manifest["files"]["decision-plan.json"] = {
        "sha256": sha256(encoded).hexdigest(),
        "bytes": len(encoded),
    }
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="canonical content hash"):
        validate_shadow_repetition(repetition)


@pytest.mark.parametrize(
    ("model", "message"),
    [
        (ShadowModel(provider="deepseek", model="deepseek-test"), "provider differs"),
        (ShadowModel(provider="openai", model="gpt-other"), "model differs"),
    ],
)
def test_runtime_provider_and_model_must_match_receipt(
    tmp_path: Path, model: ShadowModel, message: str
) -> None:
    plan = _frozen_plan(tmp_path)
    decision_path, receipt_path = _lineage(tmp_path, plan)

    with (
        patch(
            "stock_analysis.ai_lab.shadow_campaign.call_shadow_provider",
            side_effect=AssertionError("provider must not be called"),
        ),
        pytest.raises(ValueError, match=message),
    ):
        run_shadow_day(
            plan,
            tmp_path / "shadow",
            campaign_id="prompt-8-prospective",
            signal_date=_SIGNAL_DATE,
            shadow_model=model,
            decision_plan=decision_path,
            launch_receipt=receipt_path,
            generated_at=_AFTER_CLOSE,
        )
    assert not (tmp_path / "shadow").exists()


def test_missing_receipt_fails_closed_but_injected_cosplay_is_legacy_unbound(
    tmp_path: Path,
) -> None:
    plan = _frozen_plan(tmp_path)
    decision_path, _receipt_path = _lineage(tmp_path, plan)

    with pytest.raises(ValueError, match="both decision plan and launch receipt"):
        run_shadow_day(
            plan,
            tmp_path / "formal-shadow",
            campaign_id="prompt-8-prospective",
            signal_date=_SIGNAL_DATE,
            decision_plan=decision_path,
            generated_at=_AFTER_CLOSE,
        )

    model = ShadowModel(provider="openai", model="gpt-test")
    result = run_shadow_day(
        plan,
        tmp_path / "cosplay-shadow",
        campaign_id="prompt-8-prospective",
        signal_date=_SIGNAL_DATE,
        shadow_model=model,
        generated_at=_AFTER_CLOSE,
        caller=lambda owner_plan, owner_model, _repetition, _timeout: _exchange(
            owner_plan, owner_model
        ),
    )
    summary = validate_shadow_day(result.day_root)
    assert summary["evidence_status"] == "legacy_unbound"
    assert summary["decision_plan_sha256"] is None
    assert summary["launch_receipt_sha256"] is None


def test_injected_caller_cannot_claim_bound_launch_lineage(tmp_path: Path) -> None:
    plan = _frozen_plan(tmp_path)
    decision_path, receipt_path = _lineage(tmp_path, plan)
    model = ShadowModel(provider="openai", model="gpt-test")

    with pytest.raises(ValueError, match="cannot create prospective_bound"):
        run_shadow_day(
            plan,
            tmp_path / "shadow",
            campaign_id="prompt-8-prospective",
            signal_date=_SIGNAL_DATE,
            shadow_model=model,
            decision_plan=decision_path,
            launch_receipt=receipt_path,
            generated_at=_AFTER_CLOSE,
            caller=lambda owner_plan, owner_model, _repetition, _timeout: _exchange(
                owner_plan, owner_model
            ),
        )


def test_existing_schema_11_cosplay_without_lineage_fields_is_legacy_unbound(
    tmp_path: Path,
) -> None:
    plan = _frozen_plan(tmp_path)
    model = ShadowModel(provider="openai", model="gpt-test")
    result = run_shadow_day(
        plan,
        tmp_path / "cosplay-shadow",
        campaign_id="legacy-schema-11",
        signal_date=_SIGNAL_DATE,
        shadow_model=model,
        generated_at=_AFTER_CLOSE,
        caller=lambda owner_plan, owner_model, _repetition, _timeout: _exchange(
            owner_plan, owner_model
        ),
    )
    fields = (
        "evidence_status",
        "decision_plan_sha256",
        "launch_receipt_sha256",
    )
    for name in ("repetition-01", "repetition-02", "repetition-03", "consensus"):
        manifest_path = result.day_root / name / "manifest.json"
        manifest = json.loads(manifest_path.read_bytes())
        for field in fields:
            manifest.pop(field)
        manifest_path.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

    summary = validate_shadow_day(result.day_root)
    assert summary["evidence_status"] == "legacy_unbound"
    assert summary["decision_plan_sha256"] is None
    manifest_path = result.day_root / "repetition-01" / "manifest.json"
    manifest = json.loads(manifest_path.read_bytes())
    manifest["evidence_status"] = "legacy_unbound"
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="lineage fields are incomplete"):
        validate_shadow_repetition(result.day_root / "repetition-01")


def test_lineage_and_day_artifacts_are_append_only(tmp_path: Path) -> None:
    plan, result, decision_path, _receipt_path = _run_bound(tmp_path)
    with pytest.raises(FileExistsError, match="refusing overwrite"):
        write_shadow_decision_plan(
            plan,
            tmp_path / "decision",
            campaign_id="prompt-8-prospective",
            signal_date=_SIGNAL_DATE,
        )
    with pytest.raises(FileExistsError, match="refusing overwrite"):
        write_shadow_launch_receipt(
            decision_path,
            tmp_path / "receipt",
            provider="openai",
            model="gpt-test",
            issued_at=_AFTER_CLOSE,
        )
    with pytest.raises(FileExistsError, match="already exists"):
        run_shadow_day(
            plan,
            tmp_path / "shadow",
            campaign_id="prompt-8-prospective",
            signal_date=_SIGNAL_DATE,
            decision_plan=tmp_path / "decision" / "decision-plan.json",
            launch_receipt=tmp_path / "receipt" / "launch-receipt.json",
            generated_at=_AFTER_CLOSE,
        )
    assert result.day_root.is_dir()
