from __future__ import annotations

import json
from datetime import date, datetime, timezone
from hashlib import sha256
from pathlib import Path
from typing import Any, cast

import pytest

from stock_analysis.ai_lab.alias_contracts import alias_maps_sha256
from stock_analysis.ai_lab.evidence import (
    validate_selection_evidence,
    write_rejected_selection_evidence,
    write_selection_evidence,
)
from stock_analysis.ai_lab.evidence_consistency import provider_parameters
from stock_analysis.ai_lab.frozen_plan import load_pick_plan, write_pick_plan
from stock_analysis.ai_lab.providers import (
    DEEPSEEK_SYSTEM_MESSAGE,
    ProviderExchange,
    call_deepseek_exchange,
)
from stock_analysis.ai_lab.selection import build_selection_plan, create_selection
from stock_analysis.app.cli import main


def _response(*symbols: str, grounded: bool = True) -> str:
    reasoning = (
        "综合候选评分支持该候选的相对排序。" if grounded else "该候选看起来更有吸引力。"
    )
    return json.dumps(
        {
            "picks": [
                {
                    "symbol": symbol,
                    "confidence_score": 8,
                    "reasoning": reasoning,
                    "risk_note": "综合候选评分仍有信息边界。",
                }
                for symbol in symbols
            ]
        },
        ensure_ascii=False,
    )


def _exchange(plan: Any, response: str) -> ProviderExchange:
    request = {
        "model": plan.model,
        "messages": [
            {"role": "system", "content": DEEPSEEK_SYSTEM_MESSAGE},
            {"role": "user", "content": plan.prompt},
        ],
        **provider_parameters(plan),
    }
    response_body = json.dumps(
        {
            "model": f"{plan.model}-actual",
            "choices": [{"message": {"content": response}}],
        },
        ensure_ascii=False,
    ).encode()
    return ProviderExchange(
        provider=plan.provider,
        model=plan.model,
        endpoint="https://api.deepseek.com/v1/chat/completions",
        request_method="POST",
        request_headers=(
            ("Content-Type", "application/json"),
            ("Authorization", "<redacted>"),
        ),
        request_body=json.dumps(request, ensure_ascii=False).encode(),
        response_body=response_body,
        response_text=response,
        actual_model=f"{plan.model}-actual",
        extraction_error=None,
        timeout_seconds=17.0,
    )


def _opaque_aliases() -> tuple[dict[str, str], dict[str, str]]:
    return (
        {
            "600000.SH": "C001",
            "000001.SZ": "C002",
            "430047.BJ": "C003",
        },
        {
            "600000.SH": "候选甲",
            "000001.SZ": "候选乙",
            "430047.BJ": "候选丙",
        },
    )


def test_deepseek_thinking_request_has_no_temperature(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DEEPSEEK_API_KEY", "owner-key")
    observed: list[dict[str, object]] = []

    def transport(request: Any, _timeout: float) -> bytes:
        observed.append(json.loads(cast(bytes, request.data)))
        return b'{"model":"deepseek-v4-pro","choices":[{"message":{"content":"{}"}}]}'

    call_deepseek_exchange(
        "prompt",
        model="deepseek-v4-pro",
        thinking="enabled",
        reasoning_effort="max",
        max_tokens=32768,
        transport=transport,
    )
    payload = observed[0]
    assert payload["thinking"] == {"type": "enabled"}
    assert payload["reasoning_effort"] == "max"
    assert payload["max_tokens"] == 32768
    assert payload["response_format"] == {"type": "json_object"}
    assert "temperature" not in payload


@pytest.mark.parametrize("max_tokens", [0, -1, 65537, True])
def test_deepseek_rejects_unsafe_output_budget(
    max_tokens: int, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("DEEPSEEK_API_KEY", "owner-key")
    with pytest.raises(ValueError, match="max_tokens"):
        call_deepseek_exchange("prompt", max_tokens=max_tokens)


def test_selection_plan_freezes_thinking_semantics(cn_manifest: Path) -> None:
    enabled = build_selection_plan(
        market="CN",
        candidates_path=cn_manifest,
        as_of=date(2026, 7, 15),
        top_n=1,
        model="deepseek-v4-pro",
        thinking="enabled",
        max_tokens=32768,
    )
    assert enabled.reasoning_effort == "high"
    assert provider_parameters(enabled) == {
        "thinking": {"type": "enabled"},
        "reasoning_effort": "high",
        "max_tokens": 32768,
        "response_format": {"type": "json_object"},
    }
    with pytest.raises(ValueError, match="requires thinking enabled"):
        build_selection_plan(
            market="CN",
            candidates_path=cn_manifest,
            as_of=date(2026, 7, 15),
            top_n=1,
            thinking="disabled",
            reasoning_effort="high",
        )


def test_pick_plan_round_trip_freezes_order_and_inference(
    cn_manifest: Path, tmp_path: Path
) -> None:
    order = ("430047.BJ", "600000.SH", "000001.SZ")
    symbol_aliases, name_aliases = _opaque_aliases()
    plan = build_selection_plan(
        market="CN",
        candidates_path=cn_manifest,
        as_of=date(2026, 7, 15),
        top_n=1,
        model="deepseek-v4-pro",
        thinking="enabled",
        reasoning_effort="max",
        max_tokens=32768,
        presentation_order=order,
        symbol_aliases=symbol_aliases,
        name_aliases=name_aliases,
    )
    root = write_pick_plan(
        plan,
        tmp_path / "frozen",
        campaign_id="month_v1",
        trial_id="20260715_pro_shuffle",
        generated_at=datetime(2026, 7, 15, tzinfo=timezone.utc),
    )
    rebuilt = load_pick_plan(root / "plan.json")
    assert rebuilt.prompt == plan.prompt
    assert rebuilt.presentation_order == order
    assert rebuilt.model == "deepseek-v4-pro"
    assert rebuilt.thinking == "enabled"
    assert rebuilt.reasoning_effort == "max"
    assert rebuilt.max_tokens == 32768
    assert rebuilt.source_candidate_path == str(cn_manifest.resolve())
    assert rebuilt.campaign_id == "month_v1"
    assert rebuilt.trial_id == "20260715_pro_shuffle"
    assert rebuilt.plan_sha256 == sha256((root / "plan.json").read_bytes()).hexdigest()
    assert rebuilt.research_only is True
    assert dict(rebuilt.symbol_aliases) == symbol_aliases
    assert dict(rebuilt.name_aliases) == name_aliases
    for identity in (*symbol_aliases, "浦发银行", "平安银行", "诺思兰德"):
        assert identity not in rebuilt.prompt
    frozen = json.loads((root / "plan.json").read_bytes())
    assert frozen["campaign_id"] == "month_v1"
    assert frozen["trial_id"] == "20260715_pro_shuffle"
    assert frozen["api_calls"] == 0
    assert (
        frozen["symbol_aliases_sha256"]
        == sha256((root / "symbol_aliases.json").read_bytes()).hexdigest()
    )
    assert (
        frozen["name_aliases_sha256"]
        == sha256((root / "name_aliases.json").read_bytes()).hexdigest()
    )
    assert frozen["alias_maps_sha256"] == alias_maps_sha256(
        symbol_aliases, name_aliases
    )


def test_pick_plan_tampering_fails_receipt(cn_manifest: Path, tmp_path: Path) -> None:
    plan = build_selection_plan(
        market="CN",
        candidates_path=cn_manifest,
        as_of=date(2026, 7, 15),
        top_n=1,
    )
    root = write_pick_plan(plan, tmp_path / "frozen")
    payload = json.loads((root / "plan.json").read_bytes())
    payload["model"] = "deepseek-v4-pro"
    (root / "plan.json").write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match="receipt"):
        load_pick_plan(root / "plan.json")


@pytest.mark.parametrize(
    "relative",
    [
        "candidate_input.json",
        "prompt.txt",
        "numeric_ranking.json",
        "receipt.json",
        "symbol_aliases.json",
        "name_aliases.json",
    ],
)
def test_pick_plan_rejects_symlinked_indexed_files(
    relative: str, cn_manifest: Path, tmp_path: Path
) -> None:
    symbol_aliases, name_aliases = _opaque_aliases()
    plan = build_selection_plan(
        market="CN",
        candidates_path=cn_manifest,
        as_of=date(2026, 7, 15),
        top_n=1,
        symbol_aliases=symbol_aliases,
        name_aliases=name_aliases,
    )
    root = write_pick_plan(plan, tmp_path / "frozen")
    indexed = root / relative
    external = tmp_path / f"external-{Path(relative).name}"
    external.write_bytes(indexed.read_bytes())
    indexed.unlink()
    indexed.symlink_to(external)
    with pytest.raises(ValueError, match="symlink"):
        load_pick_plan(root / "plan.json")


def test_pick_plan_rejects_alias_path_traversal(
    cn_manifest: Path, tmp_path: Path
) -> None:
    symbol_aliases, name_aliases = _opaque_aliases()
    plan = build_selection_plan(
        market="CN",
        candidates_path=cn_manifest,
        as_of=date(2026, 7, 15),
        top_n=1,
        symbol_aliases=symbol_aliases,
        name_aliases=name_aliases,
    )
    root = write_pick_plan(plan, tmp_path / "frozen")
    outside = tmp_path / "outside-aliases.json"
    outside.write_bytes((root / "symbol_aliases.json").read_bytes())
    payload = json.loads((root / "plan.json").read_bytes())
    payload["symbol_aliases_path"] = "../outside-aliases.json"
    payload["files"]["../outside-aliases.json"] = _record(outside.read_bytes())
    _rewrite_pick_plan(root, payload)
    with pytest.raises(ValueError, match="unsafe|paths|escapes"):
        load_pick_plan(root / "plan.json")


def test_opaque_prompt_rejects_residual_real_identity(cn_manifest: Path) -> None:
    symbol_aliases, name_aliases = _opaque_aliases()
    name_aliases["600000.SH"] = "浦发银行替身"
    with pytest.raises(ValueError, match="exposes a real candidate identity"):
        build_selection_plan(
            market="CN",
            candidates_path=cn_manifest,
            as_of=date(2026, 7, 15),
            top_n=1,
            symbol_aliases=symbol_aliases,
            name_aliases=name_aliases,
        )


def test_pick_plan_rejects_traversal_even_when_indexed(
    cn_manifest: Path, tmp_path: Path
) -> None:
    plan = build_selection_plan(
        market="CN",
        candidates_path=cn_manifest,
        as_of=date(2026, 7, 15),
        top_n=1,
    )
    root = write_pick_plan(plan, tmp_path / "frozen")
    outside = tmp_path / "outside.txt"
    outside.write_text("outside", encoding="utf-8")
    payload = json.loads((root / "plan.json").read_bytes())
    payload["prompt_path"] = "../outside.txt"
    payload["files"]["../outside.txt"] = _record(outside.read_bytes())
    _rewrite_pick_plan(root, payload)
    with pytest.raises(ValueError, match="unsafe|paths|escapes"):
        load_pick_plan(root / "plan.json")


def test_pick_plan_requires_references_in_file_index(
    cn_manifest: Path, tmp_path: Path
) -> None:
    plan = build_selection_plan(
        market="CN",
        candidates_path=cn_manifest,
        as_of=date(2026, 7, 15),
        top_n=1,
    )
    root = write_pick_plan(plan, tmp_path / "frozen")
    payload = json.loads((root / "plan.json").read_bytes())
    payload["prompt_path"] = "plan.json"
    _rewrite_pick_plan(root, payload)
    with pytest.raises(ValueError, match="files index"):
        load_pick_plan(root / "plan.json")


def test_cli_pick_plan_and_trial_preserve_frozen_parameters(
    cn_manifest: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    order = ["430047.BJ", "000001.SZ", "600000.SH"]
    order_path = tmp_path / "order.json"
    order_path.write_text(json.dumps(order), encoding="utf-8")
    root = tmp_path / "frozen"

    def unexpected_call(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("pick-plan must not call a provider")

    monkeypatch.setattr(
        "stock_analysis.app.cli.call_plan_provider_exchange", unexpected_call
    )
    assert (
        main(
            [
                "cn",
                "pick-plan",
                "--candidates",
                str(cn_manifest),
                "--as-of",
                "2026-07-15",
                "--top-n",
                "1",
                "--style",
                "momentum",
                "--model",
                "deepseek-v4-pro",
                "--prompt-profile",
                "production_v4",
                "--presentation-order-file",
                str(order_path),
                "--thinking",
                "enabled",
                "--reasoning-effort",
                "max",
                "--max-tokens",
                "32768",
                "--campaign-id",
                "month_v1",
                "--trial-id",
                "date_pro_shuffle",
                "--output-dir",
                str(root),
            ]
        )
        == 0
    )
    observed: list[tuple[str, str, str | None, int]] = []

    def frozen_exchange(plan: Any, **_kwargs: object) -> ProviderExchange:
        observed.append(
            (plan.model, plan.thinking, plan.reasoning_effort, plan.max_tokens)
        )
        return _exchange(plan, _response(order[0]))

    monkeypatch.setattr(
        "stock_analysis.app.cli.call_plan_provider_exchange", frozen_exchange
    )
    assert (
        main(
            [
                "cn",
                "trial",
                "--plan",
                str(root / "plan.json"),
                "--output",
                str(tmp_path / "selection.json"),
            ]
        )
        == 0
    )
    assert observed == [("deepseek-v4-pro", "enabled", "max", 32768)]
    evidence = validate_selection_evidence(tmp_path / "selection.json.evidence")
    assert evidence["source_candidate_path"] == str(cn_manifest.resolve())
    assert evidence["campaign_id"] == "month_v1"
    assert evidence["trial_id"] == "date_pro_shuffle"
    assert (
        evidence["plan_sha256"] == sha256((root / "plan.json").read_bytes()).hexdigest()
    )
    assert evidence["research_only"] is True


def test_rejected_publication_preserves_passed_ranking(
    cn_manifest: Path, tmp_path: Path
) -> None:
    plan = build_selection_plan(
        market="CN",
        candidates_path=cn_manifest,
        as_of=date(2026, 7, 15),
        top_n=1,
    )
    response = _response("600000.SH", grounded=False)
    with pytest.raises(ValueError):
        create_selection(plan, response)
    output = write_rejected_selection_evidence(
        plan,
        _exchange(plan, response),
        tmp_path / "rejected",
        generated_at=datetime(2026, 7, 15, tzinfo=timezone.utc),
    )
    manifest = validate_selection_evidence(output)
    assert manifest["transport_contract"] == "passed"
    assert manifest["ranking_contract"] == "passed"
    assert manifest["publication_contract"] == "failed"
    assert manifest["ranking_diagnostic_path"] == "ranking_diagnostic.json"
    diagnostic = json.loads((output / "ranking_diagnostic.json").read_bytes())
    assert diagnostic["symbols"] == ["600000.SH"]
    assert set(diagnostic) == {"schema_version", "artifact_type", "symbols"}


def test_valid_publication_cannot_be_written_as_rejected(
    cn_manifest: Path, tmp_path: Path
) -> None:
    plan = build_selection_plan(
        market="CN",
        candidates_path=cn_manifest,
        as_of=date(2026, 7, 15),
        top_n=1,
    )
    response = _response("600000.SH")
    with pytest.raises(ValueError, match="cannot be archived as rejected"):
        write_rejected_selection_evidence(
            plan,
            _exchange(plan, response),
            tmp_path / "false-rejection",
            generated_at=datetime(2026, 7, 15, tzinfo=timezone.utc),
        )


def test_valid_v2_response_cannot_validate_with_rejected_status(
    cn_manifest: Path, tmp_path: Path
) -> None:
    output = _complete_evidence(cn_manifest, tmp_path / "valid-status")
    manifest_path = output / "manifest.json"
    manifest = json.loads(manifest_path.read_bytes())
    manifest["status"] = "rejected"
    manifest["selection_path"] = None
    manifest["rejection"] = "selection_validation_failed"
    manifest["files"].pop("selection.json")
    (output / "selection.json").unlink()
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(ValueError, match="status does not match"):
        validate_selection_evidence(output)


def test_invalid_v2_response_cannot_validate_with_complete_status(
    cn_manifest: Path, tmp_path: Path
) -> None:
    plan = build_selection_plan(
        market="CN",
        candidates_path=cn_manifest,
        as_of=date(2026, 7, 15),
        top_n=1,
    )
    response = _response("600000.SH", grounded=False)
    output = write_rejected_selection_evidence(
        plan,
        _exchange(plan, response),
        tmp_path / "false-complete",
        generated_at=datetime(2026, 7, 15, tzinfo=timezone.utc),
    )
    manifest_path = output / "manifest.json"
    manifest = json.loads(manifest_path.read_bytes())
    manifest["status"] = "complete"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(ValueError, match="status does not match"):
        validate_selection_evidence(output)


def test_structurally_invalid_response_fails_ranking(
    cn_manifest: Path, tmp_path: Path
) -> None:
    plan = build_selection_plan(
        market="CN",
        candidates_path=cn_manifest,
        as_of=date(2026, 7, 15),
        top_n=1,
    )
    response = _response("601398.SH")
    output = write_rejected_selection_evidence(
        plan, _exchange(plan, response), tmp_path / "rejected"
    )
    manifest = validate_selection_evidence(output)
    assert manifest["ranking_contract"] == "failed"
    assert manifest["publication_contract"] == "not_evaluated"
    assert manifest["ranking_diagnostic_path"] is None
    assert not (output / "ranking_diagnostic.json").exists()


def test_manifest_inference_tampering_disagrees_with_raw_request(
    cn_manifest: Path, tmp_path: Path
) -> None:
    plan = build_selection_plan(
        market="CN",
        candidates_path=cn_manifest,
        as_of=date(2026, 7, 15),
        top_n=1,
    )
    response = _response("600000.SH")
    artifact = create_selection(
        plan, response, generated_at=datetime(2026, 7, 15, tzinfo=timezone.utc)
    )
    output = write_selection_evidence(
        plan, _exchange(plan, response), artifact, tmp_path / "evidence"
    )
    manifest_path = output / "manifest.json"
    manifest = json.loads(manifest_path.read_bytes())
    manifest["provider_parameters"] = {
        "thinking": {"type": "enabled"},
        "reasoning_effort": "high",
        "max_tokens": 8192,
        "response_format": {"type": "json_object"},
    }
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(ValueError, match="provider request"):
        validate_selection_evidence(output)


def test_raw_request_tampering_disagrees_with_manifest(
    cn_manifest: Path, tmp_path: Path
) -> None:
    plan = build_selection_plan(
        market="CN",
        candidates_path=cn_manifest,
        as_of=date(2026, 7, 15),
        top_n=1,
    )
    response = _response("600000.SH")
    artifact = create_selection(
        plan, response, generated_at=datetime(2026, 7, 15, tzinfo=timezone.utc)
    )
    output = write_selection_evidence(
        plan, _exchange(plan, response), artifact, tmp_path / "evidence"
    )
    request_path = output / "provider_request_body.json"
    request = json.loads(request_path.read_bytes())
    request["temperature"] = 0.7
    request_bytes = json.dumps(request).encode()
    request_path.write_bytes(request_bytes)
    envelope_path = output / "http_request_envelope.json"
    envelope = json.loads(envelope_path.read_bytes())
    envelope["body_sha256"] = sha256(request_bytes).hexdigest()
    envelope_bytes = json.dumps(envelope).encode()
    envelope_path.write_bytes(envelope_bytes)
    manifest_path = output / "manifest.json"
    manifest = json.loads(manifest_path.read_bytes())
    manifest["files"]["provider_request_body.json"] = _record(request_bytes)
    manifest["files"]["http_request_envelope.json"] = _record(envelope_bytes)
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(ValueError, match="request parameters"):
        validate_selection_evidence(output)


def test_evidence_rejects_internal_symlink(cn_manifest: Path, tmp_path: Path) -> None:
    output = _complete_evidence(cn_manifest, tmp_path / "internal-symlink")
    prompt = output / "prompt.txt"
    copy = output / "prompt-copy.txt"
    content = prompt.read_bytes()
    copy.write_bytes(content)
    prompt.unlink()
    prompt.symlink_to(copy.name)
    manifest_path = output / "manifest.json"
    manifest = json.loads(manifest_path.read_bytes())
    manifest["files"]["prompt-copy.txt"] = _record(content)
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(ValueError, match="symlink"):
        validate_selection_evidence(output)


def test_legacy_v1_evidence_remains_valid(cn_manifest: Path, tmp_path: Path) -> None:
    plan = build_selection_plan(
        market="CN",
        candidates_path=cn_manifest,
        as_of=date(2026, 7, 15),
        top_n=1,
        model="deepseek-chat",
    )
    response = _response("600000.SH")
    artifact = create_selection(
        plan, response, generated_at=datetime(2026, 7, 15, tzinfo=timezone.utc)
    )
    output = write_selection_evidence(
        plan, _exchange(plan, response), artifact, tmp_path / "legacy"
    )
    request_path = output / "provider_request_body.json"
    request = json.loads(request_path.read_bytes())
    request.pop("thinking")
    request.pop("max_tokens")
    request_bytes = json.dumps(request).encode()
    request_path.write_bytes(request_bytes)
    envelope_path = output / "http_request_envelope.json"
    envelope = json.loads(envelope_path.read_bytes())
    envelope["body_sha256"] = sha256(request_bytes).hexdigest()
    envelope_bytes = json.dumps(envelope).encode()
    envelope_path.write_bytes(envelope_bytes)
    manifest_path = output / "manifest.json"
    manifest = json.loads(manifest_path.read_bytes())
    manifest["schema_version"] = "1.0.0"
    manifest["provider_parameters"] = {
        "temperature": 0.2,
        "response_format": {"type": "json_object"},
    }
    for field in (
        "transport_contract",
        "ranking_contract",
        "publication_contract",
        "ranking_diagnostic_path",
    ):
        manifest.pop(field)
    manifest["files"]["provider_request_body.json"] = _record(request_bytes)
    manifest["files"]["http_request_envelope.json"] = _record(envelope_bytes)
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    validated = validate_selection_evidence(output)
    assert validated["schema_version"] == "1.0.0"


def test_legacy_v1_rejected_evidence_keeps_historical_status_semantics(
    cn_manifest: Path, tmp_path: Path
) -> None:
    output = _complete_evidence(cn_manifest, tmp_path / "legacy-rejected")
    _convert_complete_bundle_to_legacy_rejected(output)
    manifest = validate_selection_evidence(output)
    assert manifest["schema_version"] == "1.0.0"
    assert manifest["status"] == "rejected"


def _record(payload: bytes) -> dict[str, object]:
    return {"sha256": sha256(payload).hexdigest(), "bytes": len(payload)}


def _complete_evidence(candidates: Path, root: Path) -> Path:
    plan = build_selection_plan(
        market="CN",
        candidates_path=candidates,
        as_of=date(2026, 7, 15),
        top_n=1,
    )
    response = _response("600000.SH")
    artifact = create_selection(
        plan,
        response,
        generated_at=datetime(2026, 7, 15, tzinfo=timezone.utc),
    )
    return write_selection_evidence(
        plan,
        _exchange(plan, response),
        artifact,
        root / "evidence",
    )


def _rewrite_pick_plan(root: Path, payload: dict[str, Any]) -> None:
    core = dict(payload)
    core.pop("files", None)
    receipt = {
        "schema_version": "1.0.0",
        "artifact_type": "ai_pick_plan_receipt",
        "plan_core_sha256": sha256(_json_bytes(core)).hexdigest(),
    }
    receipt_bytes = _json_bytes(receipt)
    (root / "receipt.json").write_bytes(receipt_bytes)
    payload["files"]["receipt.json"] = _record(receipt_bytes)
    (root / "plan.json").write_bytes(_json_bytes(payload))


def _json_bytes(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True).encode("utf-8")
        + b"\n"
    )


def _convert_complete_bundle_to_legacy_rejected(output: Path) -> None:
    request_path = output / "provider_request_body.json"
    request = json.loads(request_path.read_bytes())
    request.pop("thinking")
    request.pop("max_tokens")
    request_bytes = json.dumps(request).encode()
    request_path.write_bytes(request_bytes)
    envelope_path = output / "http_request_envelope.json"
    envelope = json.loads(envelope_path.read_bytes())
    envelope["body_sha256"] = sha256(request_bytes).hexdigest()
    envelope_bytes = json.dumps(envelope).encode()
    envelope_path.write_bytes(envelope_bytes)
    manifest_path = output / "manifest.json"
    manifest = json.loads(manifest_path.read_bytes())
    manifest["schema_version"] = "1.0.0"
    manifest["status"] = "rejected"
    manifest["selection_path"] = None
    manifest["rejection"] = "selection_validation_failed"
    manifest["provider_parameters"] = {
        "temperature": 0.2,
        "response_format": {"type": "json_object"},
    }
    for field in (
        "provider_parameter_schema",
        "campaign_id",
        "trial_id",
        "plan_sha256",
        "transport_contract",
        "ranking_contract",
        "publication_contract",
        "ranking_diagnostic_path",
    ):
        manifest.pop(field, None)
    manifest["files"].pop("selection.json")
    (output / "selection.json").unlink()
    manifest["files"]["provider_request_body.json"] = _record(request_bytes)
    manifest["files"]["http_request_envelope.json"] = _record(envelope_bytes)
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
