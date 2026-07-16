from __future__ import annotations

import json
import random
from dataclasses import replace
from datetime import date, datetime, timezone
from hashlib import sha256
from pathlib import Path
from typing import cast

import pytest

from stock_analysis.ai_lab.contracts import PROMPT_VERSION
from stock_analysis.ai_lab.evidence import (
    _numeric_ranking_bytes,
    load_stability_trial,
    validate_selection_evidence,
    validate_stability_campaign,
    write_rejected_selection_evidence,
    write_selection_evidence,
    write_stability_campaign,
)
from stock_analysis.ai_lab.providers import (
    DEEPSEEK_SYSTEM_MESSAGE,
    GEMINI_SYSTEM_MESSAGE,
    ProviderExchange,
)
from stock_analysis.ai_lab.selection import (
    LEGACY_STABILITY_PROMPT_VERSION,
    build_selection_plan,
    create_selection,
)


def _response(symbol: str) -> str:
    return json.dumps(
        {
            "picks": [
                {
                    "symbol": symbol,
                    "confidence_score": 8,
                    "reasoning": "综合候选评分支持该候选的相对排序。",
                    "risk_note": "仅依据综合候选评分，风险解读仍有信息边界。",
                }
            ]
        },
        ensure_ascii=False,
    )


def _exchange(prompt: str, response: str) -> ProviderExchange:
    request = json.dumps(
        {
            "model": "deepseek-v4-flash",
            "messages": [
                {"role": "system", "content": DEEPSEEK_SYSTEM_MESSAGE},
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.2,
            "thinking": {"type": "disabled"},
            "max_tokens": 8192,
            "response_format": {"type": "json_object"},
        },
        ensure_ascii=False,
    ).encode()
    response_body = json.dumps(
        {
            "model": "deepseek-v4-flash-20260715",
            "choices": [{"message": {"content": response}}],
        },
        ensure_ascii=False,
    ).encode()
    return ProviderExchange(
        provider="deepseek",
        model="deepseek-v4-flash",
        endpoint="https://api.deepseek.com/v1/chat/completions",
        request_method="POST",
        request_headers=(
            ("Content-Type", "application/json"),
            ("Authorization", "<redacted>"),
        ),
        request_body=request,
        response_body=response_body,
        response_text=response,
        actual_model="deepseek-v4-flash-20260715",
        extraction_error=None,
        timeout_seconds=17.0,
    )


def _gemini_exchange(prompt: str, response: str) -> ProviderExchange:
    request = json.dumps(
        {
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": {
                "temperature": 0.2,
                "responseMimeType": "application/json",
            },
            "systemInstruction": {"parts": [{"text": GEMINI_SYSTEM_MESSAGE}]},
        },
        ensure_ascii=False,
    ).encode()
    response_body = json.dumps(
        {
            "modelVersion": "gemini-2.5-flash-20260715",
            "candidates": [{"content": {"parts": [{"text": response}]}}],
        },
        ensure_ascii=False,
    ).encode()
    return ProviderExchange(
        provider="gemini",
        model="gemini-2.5-flash",
        endpoint=(
            "https://generativelanguage.googleapis.com/v1beta/models/"
            "gemini-2.5-flash:generateContent"
        ),
        request_method="POST",
        request_headers=(
            ("Content-Type", "application/json"),
            ("x-goog-api-key", "<redacted>"),
        ),
        request_body=request,
        response_body=response_body,
        response_text=response,
        actual_model="gemini-2.5-flash-20260715",
        extraction_error=None,
        timeout_seconds=17.0,
    )


def test_complete_evidence_is_byte_exact_append_only_and_validated(
    cn_manifest: Path, tmp_path: Path
) -> None:
    plan = build_selection_plan(
        market="CN",
        candidates_path=cn_manifest,
        as_of=date(2026, 7, 15),
        top_n=1,
    )
    response = _response("600000.SH")
    exchange = _exchange(plan.prompt, response)
    artifact = create_selection(
        plan,
        response,
        generated_at=datetime(2026, 7, 15, 2, tzinfo=timezone.utc),
    )
    output = tmp_path / "evidence"

    assert write_selection_evidence(plan, exchange, artifact, output) == output
    manifest = validate_selection_evidence(output)

    assert manifest["status"] == "complete"
    assert manifest["requested_model_alias"] == "deepseek-v4-flash"
    assert manifest["response_model"] == "deepseek-v4-flash-20260715"
    assert manifest["response_extraction_error"] is None
    assert manifest["api_calls"] == 1
    assert manifest["transport_contract"] == "passed"
    assert manifest["ranking_contract"] == "passed"
    assert manifest["publication_contract"] == "passed"
    assert manifest["ranking_diagnostic_path"] is None
    assert manifest["available_at"] == "2026-07-15T02:00:00+00:00"
    assert manifest["provider_parameters"] == {
        "temperature": 0.2,
        "thinking": {"type": "disabled"},
        "max_tokens": 8192,
        "response_format": {"type": "json_object"},
    }
    assert (output / "candidate_input.json").read_bytes() == cn_manifest.read_bytes()
    assert (output / "prompt.txt").read_text(encoding="utf-8") == plan.prompt
    assert (output / "model_response.txt").read_text(encoding="utf-8") == response
    assert json.loads((output / "provider_response_body.bin").read_bytes())["choices"]
    envelope = json.loads((output / "http_request_envelope.json").read_bytes())
    assert envelope["headers"]["Authorization"] == "<redacted>"
    assert "owner-secret" not in json.dumps(envelope)
    ranking = json.loads((output / "numeric_ranking.json").read_bytes())
    assert [row["numeric_rank"] for row in ranking["rows"]] == [1, 2, 3]
    assert [row["symbol"] for row in ranking["rows"]] == [
        "600000.SH",
        "000001.SZ",
        "430047.BJ",
    ]

    with pytest.raises(FileExistsError, match="refusing overwrite"):
        write_selection_evidence(plan, exchange, artifact, output)


def test_evidence_validation_rejects_tampering(
    cn_manifest: Path, tmp_path: Path
) -> None:
    plan = build_selection_plan(
        market="CN", candidates_path=cn_manifest, as_of=date(2026, 7, 15), top_n=1
    )
    response = _response("600000.SH")
    artifact = create_selection(
        plan,
        response,
        generated_at=datetime(2026, 7, 15, 2, tzinfo=timezone.utc),
    )
    output = write_selection_evidence(
        plan, _exchange(plan.prompt, response), artifact, tmp_path / "evidence"
    )
    (output / "prompt.txt").write_text("tampered", encoding="utf-8")

    with pytest.raises(ValueError, match="hash mismatch"):
        validate_selection_evidence(output)


def test_evidence_writer_rejects_candidate_changed_after_plan(
    cn_manifest: Path, tmp_path: Path
) -> None:
    plan = build_selection_plan(
        market="CN", candidates_path=cn_manifest, as_of=date(2026, 7, 15), top_n=1
    )
    response = _response("600000.SH")
    artifact = create_selection(
        plan,
        response,
        generated_at=datetime(2026, 7, 15, 2, tzinfo=timezone.utc),
    )
    cn_manifest.write_bytes(cn_manifest.read_bytes() + b"\n")
    output = tmp_path / "changed-candidate"

    with pytest.raises(ValueError, match="candidate input changed"):
        write_selection_evidence(
            plan, _exchange(plan.prompt, response), artifact, output
        )

    assert not output.exists()


def test_stability_writer_rejects_candidate_changed_after_plan(
    cn_manifest: Path, tmp_path: Path
) -> None:
    plan = build_selection_plan(
        market="CN", candidates_path=cn_manifest, as_of=date(2026, 7, 15), top_n=1
    )
    cn_manifest.write_bytes(cn_manifest.read_bytes() + b"\n")
    output = tmp_path / "changed-candidate-campaign"

    with pytest.raises(ValueError, match="candidate input changed"):
        write_stability_campaign(plan, output, campaign_id="changed-candidate")

    assert not output.exists()


def test_complete_evidence_revalidates_selection_lineage(
    cn_manifest: Path, tmp_path: Path
) -> None:
    output = _complete_evidence(cn_manifest, tmp_path)
    selection = json.loads((output / "selection.json").read_bytes())
    selection["lineage"]["prompt_sha256"] = "0" * 64
    _rewrite_indexed_file(
        output,
        "selection.json",
        json.dumps(selection, ensure_ascii=False).encode(),
    )

    with pytest.raises(ValueError, match="archived inputs"):
        validate_selection_evidence(output)


@pytest.mark.parametrize("message_index", [0, 1])
def test_complete_evidence_requires_request_to_contain_exact_messages(
    message_index: int, cn_manifest: Path, tmp_path: Path
) -> None:
    output = _complete_evidence(cn_manifest, tmp_path)
    request = json.loads((output / "provider_request_body.json").read_bytes())
    request["messages"][message_index]["content"] = "changed message"
    request_payload = json.dumps(request, ensure_ascii=False).encode()
    _rewrite_indexed_file(output, "provider_request_body.json", request_payload)
    envelope = json.loads((output / "http_request_envelope.json").read_bytes())
    envelope["body_sha256"] = sha256(request_payload).hexdigest()
    _rewrite_indexed_file(
        output,
        "http_request_envelope.json",
        json.dumps(envelope, ensure_ascii=False).encode(),
    )

    with pytest.raises(ValueError, match="exact messages"):
        validate_selection_evidence(output)


def test_complete_evidence_rejects_model_response_lineage_mismatch(
    cn_manifest: Path, tmp_path: Path
) -> None:
    output = _complete_evidence(cn_manifest, tmp_path)
    _rewrite_indexed_file(output, "model_response.txt", b'{"picks": []}')

    with pytest.raises(ValueError, match="extracted model response"):
        validate_selection_evidence(output)


def test_complete_evidence_reparses_response_model_from_raw_bytes(
    cn_manifest: Path, tmp_path: Path
) -> None:
    output = _complete_evidence(cn_manifest, tmp_path)
    manifest_path = output / "manifest.json"
    manifest = json.loads(manifest_path.read_bytes())
    manifest["response_model"] = "deepseek-chat-tampered"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(ValueError, match="response model"):
        validate_selection_evidence(output)


def test_rejected_evidence_reparses_extraction_error_from_raw_bytes(
    cn_manifest: Path, tmp_path: Path
) -> None:
    plan = build_selection_plan(
        market="CN", candidates_path=cn_manifest, as_of=date(2026, 7, 15), top_n=1
    )
    invalid = replace(
        _exchange(plan.prompt, "unused"),
        response_body=b"not-json",
        response_text=None,
        actual_model=None,
        extraction_error="provider_response_invalid_json",
    )
    output = write_rejected_selection_evidence(
        plan, invalid, tmp_path / "invalid-response"
    )
    manifest_path = output / "manifest.json"
    manifest = json.loads(manifest_path.read_bytes())
    manifest["response_extraction_error"] = "provider_response_schema_invalid"
    manifest["rejection"] = "provider_response_schema_invalid"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(ValueError, match="extraction status"):
        validate_selection_evidence(output)


def test_gemini_evidence_reparses_raw_response_and_model(
    us_manifest: Path, tmp_path: Path
) -> None:
    plan = build_selection_plan(
        market="US", candidates_path=us_manifest, as_of=date(2026, 7, 15), top_n=1
    )
    response = json.dumps(
        {
            "picks": [
                {
                    "symbol": "AAPL",
                    "confidence_score": 8,
                    "reasoning": (
                        "The overall candidate score supports the relative rank "
                        "for AAPL."
                    ),
                    "risk_note": (
                        "The overall candidate score leaves uncertainty for AAPL."
                    ),
                }
            ]
        }
    )
    artifact = create_selection(
        plan,
        response,
        generated_at=datetime(2026, 7, 15, 14, tzinfo=timezone.utc),
    )
    output = write_selection_evidence(
        plan,
        _gemini_exchange(plan.prompt, response),
        artifact,
        tmp_path / "gemini-evidence",
    )

    manifest = validate_selection_evidence(output)

    assert manifest["response_model"] == "gemini-2.5-flash-20260715"


def test_complete_evidence_rejects_candidate_and_manifest_mismatch(
    cn_manifest: Path, tmp_path: Path
) -> None:
    output = _complete_evidence(cn_manifest, tmp_path)
    candidate = output / "candidate_input.json"
    _rewrite_indexed_file(output, candidate.name, candidate.read_bytes() + b"\n")

    with pytest.raises(ValueError, match="input_sha256"):
        validate_selection_evidence(output)


def test_complete_evidence_rejects_manifest_provider_mismatch(
    cn_manifest: Path, tmp_path: Path
) -> None:
    output = _complete_evidence(cn_manifest, tmp_path)
    manifest_path = output / "manifest.json"
    manifest = json.loads(manifest_path.read_bytes())
    manifest["provider"] = "gemini"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(ValueError, match="manifest provider"):
        validate_selection_evidence(output)


def test_rejected_response_keeps_a_closed_evidence_record(
    cn_manifest: Path, tmp_path: Path
) -> None:
    plan = build_selection_plan(
        market="CN", candidates_path=cn_manifest, as_of=date(2026, 7, 15), top_n=1
    )
    response = '{"picks":[]}'
    output = write_rejected_selection_evidence(
        plan,
        _exchange(plan.prompt, response),
        tmp_path / "rejected",
        generated_at=datetime(2026, 7, 15, 3, tzinfo=timezone.utc),
    )

    manifest = validate_selection_evidence(output)
    assert manifest["status"] == "rejected"
    assert manifest["selection_path"] is None
    assert manifest["rejection"] == "selection_validation_failed"
    assert not (output / "selection.json").exists()


def test_rejected_evidence_revalidates_prompt_request_and_candidate(
    cn_manifest: Path, tmp_path: Path
) -> None:
    plan = build_selection_plan(
        market="CN", candidates_path=cn_manifest, as_of=date(2026, 7, 15), top_n=1
    )
    output = write_rejected_selection_evidence(
        plan,
        _exchange(plan.prompt, '{"picks": []}'),
        tmp_path / "rejected-cross-file",
        generated_at=datetime(2026, 7, 15, 3, tzinfo=timezone.utc),
    )
    prompt = output / "prompt.txt"
    _rewrite_indexed_file(output, prompt.name, prompt.read_bytes() + b" ")

    with pytest.raises(ValueError, match="archived prompt"):
        validate_selection_evidence(output)


def test_rejected_evidence_reason_must_match_exchange_state(
    cn_manifest: Path, tmp_path: Path
) -> None:
    plan = build_selection_plan(
        market="CN", candidates_path=cn_manifest, as_of=date(2026, 7, 15), top_n=1
    )

    with pytest.raises(ValueError, match="may only fail selection validation"):
        write_rejected_selection_evidence(
            plan,
            _exchange(plan.prompt, '{"picks": []}'),
            tmp_path / "bad-rejection",
            rejection="provider_response_invalid_json",
        )


def test_stability_campaign_matches_frozen_five_arm_design_and_rebuilds_bytes(
    cn_manifest: Path, tmp_path: Path
) -> None:
    base = build_selection_plan(
        market="CN",
        candidates_path=cn_manifest,
        as_of=date(2026, 7, 15),
        top_n=1,
        style="momentum",
    )
    generated_at = datetime(2026, 7, 16, 1, tzinfo=timezone.utc)
    output = write_stability_campaign(
        base,
        tmp_path / "campaign-a",
        campaign_id="deepseek-stability-v2",
        generated_at=generated_at,
    )
    rebuilt = write_stability_campaign(
        base,
        tmp_path / "campaign-b",
        campaign_id="deepseek-stability-v2",
        generated_at=generated_at,
    )
    manifest = validate_stability_campaign(output)

    assert manifest["api_calls"] == 0
    assert manifest["available_at"] is None
    assert manifest["campaign_id"] == "deepseek-stability-v2"
    assert manifest["shuffle_seeds"] == [101, 202, 303]
    assert manifest["opaque_seed"] == 404
    assert manifest["prompt_version"] == LEGACY_STABILITY_PROMPT_VERSION
    assert PROMPT_VERSION == "2026-07-16.4"
    assert "response_example" not in json.loads(base.prompt)
    assert "response_schema" in json.loads(base.prompt)
    assert _tree_bytes(output) == _tree_bytes(rebuilt)
    variants = manifest["variants"]
    assert isinstance(variants, list)
    typed_variants = cast(list[dict[str, object]], variants)
    assert [item["trial_id"] for item in typed_variants] == [
        "canonical",
        "shuffle_101",
        "shuffle_202",
        "shuffle_303",
        "opaque_404",
    ]
    plans = [
        load_stability_trial(output / str(item["trial_path"]))
        for item in typed_variants
    ]
    assert plans[0].presentation_order == base.presentation_order
    for seed, plan in zip((101, 202, 303), plans[1:4], strict=True):
        expected = list(base.presentation_order)
        random.Random(seed).shuffle(expected)
        assert plan.presentation_order == tuple(expected)
        assert plan.symbol_aliases == ()
        assert plan.prompt_version == LEGACY_STABILITY_PROMPT_VERSION
        assert "response_example" in json.loads(plan.prompt)
        assert "response_schema" not in json.loads(plan.prompt)
    assert plans[4].presentation_order == base.presentation_order
    assert len(plans[4].symbol_aliases) == 3
    assert len(plans[4].name_aliases) == 3
    anonymous_prompt = json.loads(plans[4].prompt)
    assert {row["symbol"] for row in anonymous_prompt["candidates"]} == {
        "C001",
        "C002",
        "C003",
    }
    assert {row["name"] for row in anonymous_prompt["candidates"]} == {
        "候选001",
        "候选002",
        "候选003",
    }
    for candidate in base.universe.candidates:
        assert candidate.symbol not in plans[4].prompt
        assert candidate.name not in plans[4].prompt
    opaque_trial = json.loads(
        (output / "trials/opaque_404/trial.json").read_text(encoding="utf-8")
    )
    mapping = opaque_trial["identity_mapping"]
    assert [row["identity_sha256"] for row in mapping] == sorted(
        row["identity_sha256"] for row in mapping
    )
    selection = create_selection(
        plans[4],
        _response(dict(plans[4].symbol_aliases)["600000.SH"]),
        generated_at=datetime(2026, 7, 16, 2, tzinfo=timezone.utc),
    )
    assert selection.picks[0].symbol == "600000.SH"

    with pytest.raises(FileExistsError, match="refusing overwrite"):
        write_stability_campaign(
            base,
            output,
            campaign_id="deepseek-stability-v2",
        )


def test_hot_sector_numeric_ranking_uses_relevance_then_score(
    cn_manifest: Path, tmp_path: Path
) -> None:
    payload = json.loads(cn_manifest.read_bytes())
    rows = payload["candidate_universe"]
    rows[0]["relevance"] = 0.9
    rows[0]["score"] = 1.0
    rows[1]["relevance"] = 0.8
    rows[1]["score"] = 7.0
    rows[2]["relevance"] = 0.8
    rows[2]["score"] = 8.0
    cn_manifest.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    plan = build_selection_plan(
        market="CN", candidates_path=cn_manifest, as_of=date(2026, 7, 15), top_n=1
    )
    output = write_stability_campaign(
        plan, tmp_path / "numeric-contract", campaign_id="numeric-contract"
    )
    ranking = json.loads((output / "numeric_ranking.json").read_bytes())

    assert ranking["ranking_method"] == "relevance_desc_score_desc_symbol_asc"
    assert [row["symbol"] for row in ranking["rows"]] == [
        "600000.SH",
        "430047.BJ",
        "000001.SZ",
    ]
    assert [row["relevance"] for row in ranking["rows"]] == [0.9, 0.8, 0.8]


def test_non_hot_numeric_ranking_keeps_score_contract(us_manifest: Path) -> None:
    plan = build_selection_plan(
        market="US", candidates_path=us_manifest, as_of=date(2026, 7, 15), top_n=1
    )
    ranking = json.loads(_numeric_ranking_bytes(plan))

    assert ranking["ranking_method"] == "score_desc_symbol_asc"
    assert [row["symbol"] for row in ranking["rows"]] == ["AAPL", "BRK.B", "MSFT"]
    assert all("relevance" not in row for row in ranking["rows"])


def test_hot_sector_numeric_ranking_rejects_nonfinite_relevance(
    cn_manifest: Path,
) -> None:
    plan = build_selection_plan(
        market="CN", candidates_path=cn_manifest, as_of=date(2026, 7, 15), top_n=1
    )
    first = plan.universe.candidates[0]
    bad_first = replace(first, features={**first.features, "relevance": float("nan")})
    bad_universe = replace(
        plan.universe,
        candidates=(bad_first, *plan.universe.candidates[1:]),
    )

    with pytest.raises(ValueError, match="requires finite relevance"):
        _numeric_ranking_bytes(replace(plan, universe=bad_universe))


def _complete_evidence(candidate_path: Path, tmp_path: Path) -> Path:
    plan = build_selection_plan(
        market="CN",
        candidates_path=candidate_path,
        as_of=date(2026, 7, 15),
        top_n=1,
    )
    response = _response("600000.SH")
    artifact = create_selection(
        plan,
        response,
        generated_at=datetime(2026, 7, 15, 2, tzinfo=timezone.utc),
    )
    return write_selection_evidence(
        plan,
        _exchange(plan.prompt, response),
        artifact,
        tmp_path / "complete-cross-file",
    )


def _rewrite_indexed_file(root: Path, relative: str, payload: bytes) -> None:
    (root / relative).write_bytes(payload)
    manifest_path = root / "manifest.json"
    manifest = json.loads(manifest_path.read_bytes())
    manifest["files"][relative] = {
        "sha256": sha256(payload).hexdigest(),
        "bytes": len(payload),
    }
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")


def _tree_bytes(root: Path) -> dict[str, bytes]:
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in root.rglob("*")
        if path.is_file()
    }


def test_stability_loader_rejects_changed_prompt(
    cn_manifest: Path, tmp_path: Path
) -> None:
    base = build_selection_plan(
        market="CN", candidates_path=cn_manifest, as_of=date(2026, 7, 15), top_n=1
    )
    output = write_stability_campaign(
        base,
        tmp_path / "campaign",
        campaign_id="tamper-test",
    )
    manifest = validate_stability_campaign(output)
    variants = manifest["variants"]
    assert isinstance(variants, list)
    typed_variants = cast(list[dict[str, object]], variants)
    trial_path = output / str(typed_variants[0]["trial_path"])
    prompt_path = trial_path.parent / "prompt.txt"
    prompt_path.write_text("changed", encoding="utf-8")

    with pytest.raises(ValueError, match="hash mismatch"):
        load_stability_trial(trial_path)


def test_presentation_order_and_aliases_fail_closed(cn_manifest: Path) -> None:
    with pytest.raises(ValueError, match="complete candidate permutation"):
        build_selection_plan(
            market="CN",
            candidates_path=cn_manifest,
            as_of=date(2026, 7, 15),
            top_n=1,
            presentation_order=["600000.SH"],
        )
    with pytest.raises(ValueError, match="complete candidate universe"):
        build_selection_plan(
            market="CN",
            candidates_path=cn_manifest,
            as_of=date(2026, 7, 15),
            top_n=1,
            symbol_aliases={"600000.SH": "C001"},
        )
