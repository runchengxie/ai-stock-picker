"""Offline validation for owner-generated shadow campaign artifacts."""

from __future__ import annotations

import re
from collections.abc import Mapping
from datetime import timezone
from hashlib import sha256
from pathlib import Path
from typing import cast
from zoneinfo import ZoneInfo

from .bundle_paths import reject_symlink_path, safe_bundle_path
from .contracts import (
    LEGACY_SHADOW_CAMPAIGN_SCHEMA_VERSION,
    SHADOW_CAMPAIGN_SCHEMA_VERSION,
    SHADOW_MIN_VALID_REPETITIONS,
    SHADOW_REPETITION_NAMES,
    SHADOW_REPETITIONS,
    PromptProfile,
    Style,
)
from .evidence_consistency import numeric_ranking_bytes
from .providers import ProviderExchange
from .ranking_policy_contract import (
    BOUNDED_RANKING_V2_PROMPT_VERSION,
    BOUNDED_RANKING_V3_PROMPT_VERSION,
    RISK_VETO_POLICY,
    RISK_VETO_PROMPT_VERSION,
)
from .selection import SelectionPlan, build_selection_plan
from .shadow_contract import (
    RiskDecision,
    bounded_consensus_payload,
    read_risk_decision,
    risk_veto_consensus_payload,
    shadow_arm_for_profile,
    shadow_response_schema,
    shadow_response_schema_name,
    shadow_schema_for_profile,
)
from .shadow_exchange_validation import validate_shadow_exchange
from .shadow_lineage_validation import (
    LINEAGE_IDENTITY_FIELDS as _LINEAGE_IDENTITY_FIELDS,
)
from .shadow_lineage_validation import (
    evidence_status as _evidence_status,
)
from .shadow_lineage_validation import (
    validate_archived_shadow_lineage as _validate_prospective_lineage,
)
from .shadow_policy_validation import (
    bounded_policy_partitions as _policy_partitions,
)
from .shadow_policy_validation import (
    risk_policy_partitions as _risk_policy_partitions,
)
from .shadow_validation_support import (
    campaign_day_roots as _campaign_day_roots,
)
from .shadow_validation_support import (
    date_value as _date_value,
)
from .shadow_validation_support import (
    datetime_value as _datetime_value,
)
from .shadow_validation_support import (
    digest as _digest,
)
from .shadow_validation_support import (
    indexed_file as _indexed_file,
)
from .shadow_validation_support import (
    read_object as _read_object,
)
from .shadow_validation_support import (
    validate_campaign_pins as _validate_campaign_pins,
)
from .shadow_validation_support import (
    validate_files as _validate_files,
)
from .shadow_validation_support import (
    validate_model_identity as _validate_model_identity,
)
from .shadow_validation_support import (
    validate_tombstone_reason as _validate_tombstone_reason,
)
from .shadow_validation_support import (
    validated_bundle_root as _validated_bundle_root,
)

_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_NETWORK_FILES = {
    "http_request_envelope.json",
    "provider_request_body.json",
    "provider_response_body.bin",
}
_COMMON_IDENTITY_FIELDS = (
    "schema_version",
    "campaign_id",
    "signal_date",
    "provider",
    "model_partition",
    "model_parameters",
    "prompt_profile",
    "prompt_version",
    "prompt_sha256",
    "plan_sha256",
    "style",
    "top_n",
    "candidate_snapshot_path",
    "candidate_observation_date",
    "candidate_generated_at",
    "input_contract",
    "input_sha256",
    "candidate_symbols_sha256",
    "strict_point_in_time",
    "eligible_as_oos_evidence",
    "research_only",
)


def validate_shadow_repetition(root: str | Path) -> dict[str, object]:
    """Validate one terminal repetition directory and its hash index."""

    path = _validated_bundle_root(root, "shadow repetition")
    manifest = _read_object(path / "manifest.json")
    if manifest.get("schema_version") not in {
        LEGACY_SHADOW_CAMPAIGN_SCHEMA_VERSION,
        SHADOW_CAMPAIGN_SCHEMA_VERSION,
    }:
        raise ValueError("shadow repetition schema_version is invalid")
    if manifest.get("artifact_type") != "ai_shadow_repetition":
        raise ValueError("shadow repetition artifact_type is invalid")
    status = manifest.get("status")
    if status not in {"complete", "tombstone"}:
        raise ValueError("shadow repetition status is invalid")
    _validate_files(path, manifest)
    _validate_common_manifest(manifest)
    _validate_repetition_file_set(manifest)
    _validate_owner_evidence(path, manifest)
    arm = _manifest_arm(manifest)
    ranking_path = manifest.get("ranking_path")
    decision_path = manifest.get("decision_path")
    if status == "complete":
        if arm == "risk_veto":
            if (
                manifest.get("decision_contract") != "passed"
                or decision_path != "decision.json"
                or ranking_path is not None
            ):
                raise ValueError(
                    "complete risk-veto repetition requires a passed decision"
                )
            read_shadow_risk_decision(path, manifest)
        else:
            if (
                manifest.get("ranking_contract") != "passed"
                or ranking_path != "ranking.json"
            ):
                raise ValueError("complete shadow repetition requires a passed ranking")
            read_shadow_ranking(path, manifest)
        if manifest.get("tombstone_reason") is not None:
            raise ValueError(
                "complete shadow repetition cannot have a tombstone reason"
            )
    else:
        _validate_tombstone_reason(manifest.get("tombstone_reason"))
        if (
            ranking_path is not None
            or decision_path is not None
            or manifest.get("ranking_contract") == "passed"
            or manifest.get("decision_contract") == "passed"
        ):
            raise ValueError(
                "shadow repetition tombstone cannot preserve a passed rank"
            )
    return manifest


def _manifest_file_sha256(manifest: Mapping[str, object], file_name: str) -> str:
    files = manifest.get("files")
    if not isinstance(files, Mapping):
        raise ValueError("shadow manifest files index is invalid")
    metadata = files.get(file_name)
    if not isinstance(metadata, Mapping):
        raise ValueError(f"shadow manifest does not index {file_name}")
    digest = metadata.get("sha256")
    if not isinstance(digest, str) or _SHA256.fullmatch(digest) is None:
        raise ValueError(f"shadow manifest {file_name} hash is invalid")
    return digest


def validate_shadow_day(day_dir: str | Path) -> dict[str, object]:
    """Fail closed on all repetition and consensus artifacts for one model/date."""

    day = Path(day_dir).expanduser()
    reject_symlink_path(day, label="shadow day")
    day = day.resolve()
    if not day.is_dir():
        raise ValueError("shadow day must be a directory")
    expected = {*SHADOW_REPETITION_NAMES, "consensus"}
    actual = {item.name for item in day.iterdir()}
    if actual != expected:
        raise ValueError(
            "shadow day must contain exactly three repetitions and consensus"
        )
    manifests = [
        validate_shadow_repetition(day / name) for name in SHADOW_REPETITION_NAMES
    ]
    _validate_day_identity(day, manifests)
    consensus_root = _validated_bundle_root(day / "consensus", "shadow consensus")
    consensus = _read_object(consensus_root / "manifest.json")
    _validate_consensus_manifest(consensus_root, consensus, manifests)
    selected_symbols: list[str] | None = None
    if consensus["status"] == "complete":
        payload = _read_object(
            _indexed_file(consensus_root, consensus, "consensus_path")
        )
        selected_symbols = cast(list[str], payload["selected_symbols"])
    numeric_fallback = _numeric_fallback_symbols(consensus)
    arm = _manifest_arm(consensus)
    numeric_ranking_hashes = {
        _manifest_file_sha256(item, "numeric_ranking.json") for item in manifests
    }
    if len(numeric_ranking_hashes) != 1:
        raise ValueError("shadow repetitions do not share one numeric ranking artifact")
    return {
        "valid": True,
        "campaign_id": consensus["campaign_id"],
        "model_partition": consensus["model_partition"],
        "arm": arm,
        "signal_date": consensus["signal_date"],
        "input_contract": consensus["input_contract"],
        "input_sha256": consensus["input_sha256"],
        "candidate_symbols_sha256": consensus["candidate_symbols_sha256"],
        "numeric_ranking_sha256": numeric_ranking_hashes.pop(),
        "consensus_manifest_sha256": sha256(
            (consensus_root / "manifest.json").read_bytes()
        ).hexdigest(),
        "prompt_version": consensus["prompt_version"],
        "prompt_profile": consensus["prompt_profile"],
        "plan_sha256": consensus["plan_sha256"],
        "decision_plan_sha256": consensus.get("decision_plan_sha256"),
        "launch_receipt_sha256": consensus.get("launch_receipt_sha256"),
        "evidence_status": _evidence_status(consensus),
        "repetition_statuses": [item["status"] for item in manifests],
        "valid_repetitions": consensus["valid_repetitions"],
        "consensus_status": consensus["status"],
        "selected_symbols": selected_symbols,
        "numeric_fallback_symbols": numeric_fallback,
        "effective_symbols": selected_symbols or numeric_fallback,
        "selection_source": (
            f"{arm}_consensus" if selected_symbols is not None else "numeric_fallback"
        ),
        "consensus_path": str(consensus_root / "consensus.json")
        if consensus["status"] == "complete"
        else None,
    }


def _numeric_fallback_symbols(consensus: Mapping[str, object]) -> list[str]:
    if _manifest_arm(consensus) == "risk_veto":
        policy = consensus.get("risk_veto_policy")
        if not isinstance(policy, dict):
            raise ValueError("shadow risk_veto_policy is invalid")
        selected = policy.get("selected_symbols")
        if (
            not isinstance(selected, list)
            or len(selected) != RISK_VETO_POLICY.selected_count
            or any(not isinstance(item, str) or not item for item in selected)
        ):
            raise ValueError("shadow risk-veto Numeric selection is invalid")
        return cast(list[str], selected)
    policy = consensus.get("ranking_policy")
    if not isinstance(policy, dict):
        raise ValueError("shadow ranking_policy is invalid")
    locked = policy.get("locked_prefix_symbols")
    boundary = policy.get("boundary_symbols")
    if not isinstance(locked, list) or not isinstance(boundary, list):
        raise ValueError("shadow ranking_policy partitions are invalid")
    if (
        len(locked) != 7
        or len(boundary) != 8
        or any(not isinstance(item, str) for item in [*locked, *boundary])
    ):
        raise ValueError("shadow ranking_policy partitions are invalid")
    return cast(list[str], [*locked, *boundary[:3]])


def validate_shadow_campaign(campaign_root: str | Path) -> dict[str, object]:
    """Validate every model/date day beneath one campaign partition."""

    root = Path(campaign_root).expanduser()
    reject_symlink_path(root, label="shadow campaign")
    root = root.resolve()
    if not root.is_dir() or _IDENTIFIER.fullmatch(root.name) is None:
        raise ValueError("shadow campaign root is invalid")
    days: list[dict[str, object]] = []
    records: list[tuple[dict[str, object], dict[str, object]]] = []
    for day_root in _campaign_day_roots(root):
        summary = validate_shadow_day(day_root)
        days.append(summary)
        records.append(
            (summary, _read_object(day_root / "consensus" / "manifest.json"))
        )
    if not days:
        raise ValueError("shadow campaign contains no model/date partitions")
    if any(item["campaign_id"] != root.name for item in days):
        raise ValueError("shadow campaign path does not match artifact campaign_id")
    _validate_campaign_pins(records)
    return {
        "valid": True,
        "campaign_id": root.name,
        "day_count": len(days),
        "complete_consensus_count": sum(
            item["consensus_status"] == "complete" for item in days
        ),
        "days": days,
    }


def _validate_day_identity(day: Path, manifests: list[dict[str, object]]) -> None:
    first = manifests[0]
    arm = _manifest_arm(first)
    policy_field = "risk_veto_policy" if arm == "risk_veto" else "ranking_policy"
    fields = (*_COMMON_IDENTITY_FIELDS, policy_field)
    if first.get("schema_version") != LEGACY_SHADOW_CAMPAIGN_SCHEMA_VERSION:
        fields = (*fields, "arm", *_LINEAGE_IDENTITY_FIELDS)
    for field in fields:
        if any(item.get(field) != first.get(field) for item in manifests[1:]):
            raise ValueError(f"shadow repetition {field} differs within one day")
    if first.get("signal_date") != day.name:
        raise ValueError("shadow day path does not match signal_date")
    if first.get("model_partition") != day.parent.name:
        raise ValueError("shadow model path does not match model_partition")
    if first.get("schema_version") == LEGACY_SHADOW_CAMPAIGN_SCHEMA_VERSION:
        campaign_name = day.parent.parent.name
    else:
        if day.parent.parent.name != arm:
            raise ValueError("shadow arm path does not match artifact arm")
        campaign_name = day.parent.parent.parent.name
    if first.get("campaign_id") != campaign_name:
        raise ValueError("shadow campaign path does not match campaign_id")
    if [item.get("repetition") for item in manifests] != [1, 2, 3]:
        raise ValueError("shadow repetition numbers are not canonical")


def _validate_consensus_manifest(
    root: Path,
    consensus: dict[str, object],
    repetitions: list[dict[str, object]],
) -> None:
    if consensus.get("schema_version") not in {
        LEGACY_SHADOW_CAMPAIGN_SCHEMA_VERSION,
        SHADOW_CAMPAIGN_SCHEMA_VERSION,
    }:
        raise ValueError("shadow consensus schema_version is invalid")
    if consensus.get("artifact_type") != "ai_shadow_consensus":
        raise ValueError("shadow consensus artifact_type is invalid")
    _validate_files(root, consensus)
    _validate_common_manifest(consensus)
    if consensus.get("repetitions") != SHADOW_REPETITIONS:
        raise ValueError("shadow consensus repetitions is invalid")
    if consensus.get("min_valid_repetitions") != SHADOW_MIN_VALID_REPETITIONS:
        raise ValueError("shadow consensus min_valid_repetitions is invalid")
    _validate_consensus_identity(consensus, repetitions[0])
    valid = [
        index
        for index, manifest in enumerate(repetitions, start=1)
        if manifest["status"] == "complete"
    ]
    if consensus.get("valid_repetitions") != valid:
        raise ValueError("shadow consensus valid_repetitions is inconsistent")
    if len(valid) < SHADOW_MIN_VALID_REPETITIONS:
        _validate_consensus_tombstone(consensus, "insufficient_valid_repetitions")
        return
    expected = _consensus_from_archives(root.parent, repetitions)
    if expected is None:
        _validate_consensus_tombstone(consensus, "insufficient_consensus_agreement")
        return
    _validate_complete_consensus(root, consensus, expected)


def _validate_consensus_identity(
    consensus: Mapping[str, object], repetition: Mapping[str, object]
) -> None:
    arm = _manifest_arm(consensus)
    policy_field = "risk_veto_policy" if arm == "risk_veto" else "ranking_policy"
    fields = (*_COMMON_IDENTITY_FIELDS, policy_field)
    if consensus.get("schema_version") != LEGACY_SHADOW_CAMPAIGN_SCHEMA_VERSION:
        fields = (*fields, "arm", *_LINEAGE_IDENTITY_FIELDS)
    for field in fields:
        if consensus.get(field) != repetition.get(field):
            raise ValueError(f"shadow consensus {field} differs from repetitions")


def _validate_consensus_tombstone(
    consensus: Mapping[str, object], expected_reason: str
) -> None:
    if consensus.get("status") != "tombstone":
        raise ValueError("missing consensus requires a tombstone")
    _validate_tombstone_reason(consensus.get("tombstone_reason"))
    if consensus.get("tombstone_reason") != expected_reason:
        raise ValueError("shadow consensus tombstone reason is inconsistent")
    if consensus.get("consensus_path") is not None or consensus.get("files") != {}:
        raise ValueError("consensus tombstone cannot contain output")


def _validate_complete_consensus(
    root: Path,
    consensus: Mapping[str, object],
    expected: Mapping[str, object],
) -> None:
    if consensus.get("status") != "complete":
        raise ValueError("sufficient repetitions require complete consensus")
    if consensus.get("tombstone_reason") is not None:
        raise ValueError("complete consensus cannot have tombstone reason")
    if set(cast(dict[str, object], consensus["files"])) != {"consensus.json"}:
        raise ValueError("complete consensus file set is invalid")
    consensus_path = _indexed_file(root, consensus, "consensus_path")
    payload = _read_object(consensus_path)
    if payload != expected:
        raise ValueError("shadow consensus does not match archived repetitions")


def _consensus_from_archives(
    day_root: Path, repetitions: list[dict[str, object]]
) -> dict[str, object] | None:
    profile = cast(str, repetitions[0]["prompt_profile"])
    candidate_name = cast(str, repetitions[0]["candidate_snapshot_path"])
    style = cast(Style, repetitions[0]["style"])
    plan = build_selection_plan(
        market="CN",
        candidates_path=day_root / SHADOW_REPETITION_NAMES[0] / candidate_name,
        as_of=_date_value(repetitions[0].get("signal_date"), "signal_date"),
        top_n=10,
        style=style,
        prompt_profile=cast(PromptProfile, profile),
    )
    if _manifest_arm(repetitions[0]) == "risk_veto":
        decisions = [
            (
                index,
                read_shadow_risk_decision(
                    day_root / SHADOW_REPETITION_NAMES[index - 1], manifest
                ),
            )
            for index, manifest in enumerate(repetitions, start=1)
            if manifest["status"] == "complete"
        ]
        return risk_veto_consensus_payload(plan, decisions)
    rankings = [
        (
            index,
            read_shadow_ranking(
                day_root / SHADOW_REPETITION_NAMES[index - 1], manifest
            ),
        )
        for index, manifest in enumerate(repetitions, start=1)
        if manifest["status"] == "complete"
    ]
    return bounded_consensus_payload(plan, rankings)


def read_shadow_ranking(root: Path, manifest: Mapping[str, object]) -> tuple[str, ...]:
    """Read one hash-indexed canonical ranking after structural validation."""

    payload = _read_object(_indexed_file(root, manifest, "ranking_path"))
    if payload.get("schema_version") != "1.0.0":
        raise ValueError("shadow ranking schema_version is invalid")
    if payload.get("artifact_type") != "ai_ranking_diagnostic":
        raise ValueError("shadow ranking artifact_type is invalid")
    symbols = payload.get("symbols")
    if (
        not isinstance(symbols, list)
        or len(symbols) != 10
        or any(not isinstance(item, str) or not item for item in symbols)
    ):
        raise ValueError("shadow ranking symbols are invalid")
    if len(symbols) != len(set(symbols)):
        raise ValueError("shadow ranking symbols must be unique")
    result = tuple(cast(list[str], symbols))
    locked, boundary = _policy_partitions(manifest)
    if result[:7] != locked or not set(result[7:]).issubset(boundary):
        raise ValueError("shadow ranking violates the archived bounded policy")
    return result


def read_shadow_risk_decision(
    root: Path, manifest: Mapping[str, object]
) -> RiskDecision:
    """Read one hash-indexed risk-veto decision after policy validation."""

    payload = _read_object(_indexed_file(root, manifest, "decision_path"))
    decision = read_risk_decision(payload)
    selected, _reserves = _risk_policy_partitions(manifest)
    if decision[0] is not None and decision[0] not in selected:
        raise ValueError("shadow risk-veto decision is outside Numeric Top10")
    return decision


def _validate_common_manifest(manifest: Mapping[str, object]) -> None:
    profile = manifest.get("prompt_profile")
    if not isinstance(profile, str):
        raise ValueError("shadow prompt profile is invalid")
    if manifest.get("schema_version") != shadow_schema_for_profile(profile):
        raise ValueError("shadow schema_version is invalid")
    campaign_id = manifest.get("campaign_id")
    if not isinstance(campaign_id, str) or _IDENTIFIER.fullmatch(campaign_id) is None:
        raise ValueError("shadow campaign_id is invalid")
    signal_date = _date_value(manifest.get("signal_date"), "signal_date")
    generated_at = _datetime_value(manifest.get("generated_at"), "generated_at")
    generated_local = generated_at.astimezone(ZoneInfo("Asia/Shanghai"))
    if generated_local.date() < signal_date or (
        generated_local.date() == signal_date
        and (generated_local.hour, generated_local.minute) < (16, 0)
    ):
        raise ValueError("shadow generated_at precedes the signal-date close")
    expected_versions = {
        "bounded_ranking_v2": BOUNDED_RANKING_V2_PROMPT_VERSION,
        "bounded_ranking_v3": BOUNDED_RANKING_V3_PROMPT_VERSION,
        "risk_veto_v1": RISK_VETO_PROMPT_VERSION,
    }
    if manifest.get("prompt_version") != expected_versions.get(profile):
        raise ValueError("shadow prompt contract is invalid")
    if manifest.get("top_n") != 10:
        raise ValueError("shadow top_n is invalid")
    if manifest.get("style") not in {"momentum", "quality"}:
        raise ValueError("shadow style is invalid")
    for field in (
        "prompt_sha256",
        "plan_sha256",
        "input_sha256",
        "candidate_symbols_sha256",
    ):
        value = manifest.get(field)
        if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
            raise ValueError(f"shadow {field} is invalid")
    if manifest.get("candidate_snapshot_path") not in {
        "candidate_input.json",
        "candidate_input.csv",
    }:
        raise ValueError("shadow candidate_snapshot_path is invalid")
    if (
        manifest.get("strict_point_in_time") is not False
        or manifest.get("eligible_as_oos_evidence") is not False
        or manifest.get("research_only") is not True
    ):
        raise ValueError("shadow research evidence flags are invalid")
    _evidence_status(manifest)
    _validate_model_identity(manifest)
    if _manifest_arm(manifest) == "risk_veto":
        _risk_policy_partitions(manifest)
    else:
        _policy_partitions(manifest)


def _manifest_arm(manifest: Mapping[str, object]) -> str:
    profile = manifest.get("prompt_profile")
    if not isinstance(profile, str):
        raise ValueError("shadow prompt profile is invalid")
    arm = shadow_arm_for_profile(profile)
    if manifest.get("schema_version") == LEGACY_SHADOW_CAMPAIGN_SCHEMA_VERSION:
        if profile != "bounded_ranking_v2" or "arm" in manifest:
            raise ValueError("legacy shadow arm contract is invalid")
        return arm
    if manifest.get("arm") != arm:
        raise ValueError("shadow arm is inconsistent with prompt profile")
    return arm


def _validate_repetition_file_set(manifest: Mapping[str, object]) -> None:
    records = cast(dict[str, object], manifest["files"])
    names = set(records)
    candidates = {
        name
        for name in names
        if name in {"candidate_input.json", "candidate_input.csv"}
    }
    if len(candidates) != 1:
        raise ValueError("shadow repetition requires one candidate snapshot")
    if candidates != {manifest.get("candidate_snapshot_path")}:
        raise ValueError("shadow candidate snapshot path is inconsistent")
    lineage_files = (
        {"decision-plan.json", "launch-receipt.json"}
        if _evidence_status(manifest) == "prospective_bound"
        else set()
    )
    base = {
        *candidates,
        "numeric_ranking.json",
        "prompt.txt",
        *lineage_files,
    }
    status = manifest.get("status")
    arm = _manifest_arm(manifest)
    if status == "complete":
        output_name = "decision.json" if arm == "risk_veto" else "ranking.json"
        expected = {*base, *_NETWORK_FILES, "model_response.txt", output_name}
        if names != expected:
            raise ValueError("complete shadow repetition file set is invalid")
        valid_contracts = manifest.get("transport_contract") == "passed" and (
            manifest.get("decision_contract") == "passed"
            and manifest.get("ranking_contract") == "not_evaluated"
            and manifest.get("publication_contract") == "not_applicable"
            if arm == "risk_veto"
            else manifest.get("ranking_contract") == "passed"
            and manifest.get("publication_contract") in {"passed", "failed"}
        )
        if not valid_contracts:
            raise ValueError("complete shadow repetition contracts are inconsistent")
        return
    risk_base_contracts = (
        "failed",
        "not_evaluated",
        "not_evaluated",
        "not_applicable",
    )
    reason = manifest.get("tombstone_reason")
    if reason in {"provider_call_failed", "watchdog_missing_repetition"}:
        allowed = {frozenset(base)}
        expected_contracts = (
            risk_base_contracts
            if arm == "risk_veto"
            else ("failed", "not_evaluated", "not_evaluated")
        )
    elif reason == "transport_contract_failed":
        allowed = {
            frozenset(base),
            frozenset({*base, *_NETWORK_FILES}),
        }
        expected_contracts = (
            risk_base_contracts
            if arm == "risk_veto"
            else ("failed", "not_evaluated", "not_evaluated")
        )
    elif reason == "ranking_contract_failed":
        allowed = {
            frozenset({*base, *_NETWORK_FILES, "model_response.txt"}),
        }
        expected_contracts = ("passed", "failed", "not_evaluated")
    elif reason == "decision_contract_failed" and arm == "risk_veto":
        allowed = {
            frozenset({*base, *_NETWORK_FILES, "model_response.txt"}),
        }
        expected_contracts = (
            "passed",
            "not_evaluated",
            "failed",
            "not_applicable",
        )
    else:
        raise ValueError("shadow repetition tombstone reason is invalid")
    if frozenset(names) not in allowed:
        raise ValueError("shadow repetition tombstone file set is invalid")
    actual_contracts = (
        (
            manifest.get("transport_contract"),
            manifest.get("ranking_contract"),
            manifest.get("decision_contract"),
            manifest.get("publication_contract"),
        )
        if arm == "risk_veto"
        else (
            manifest.get("transport_contract"),
            manifest.get("ranking_contract"),
            manifest.get("publication_contract"),
        )
    )
    if actual_contracts != expected_contracts:
        raise ValueError("shadow repetition tombstone contracts are inconsistent")


def _validate_owner_evidence(root: Path, manifest: Mapping[str, object]) -> None:
    candidate_name = cast(str, manifest["candidate_snapshot_path"])
    candidate_path = safe_bundle_path(root, candidate_name, label="shadow candidate")
    signal_date = _date_value(manifest.get("signal_date"), "signal_date")
    style = cast(Style, manifest.get("style"))
    profile = cast(PromptProfile, manifest.get("prompt_profile"))
    plan = build_selection_plan(
        market="CN",
        candidates_path=candidate_path,
        as_of=signal_date,
        top_n=10,
        style=style,
        prompt_profile=profile,
    )
    expected = {
        "input_contract": plan.universe.input_contract,
        "input_sha256": plan.universe.input_sha256,
        "candidate_symbols_sha256": plan.universe.candidate_symbols_sha256,
        "candidate_observation_date": (
            plan.universe.observation_date.isoformat()
            if plan.universe.observation_date is not None
            else None
        ),
        "candidate_generated_at": (
            plan.universe.source_generated_at.astimezone(timezone.utc).isoformat()
            if plan.universe.source_generated_at is not None
            else None
        ),
    }
    expected.update(plan.decision_policy_fields)
    for field, value in expected.items():
        if manifest.get(field) != value:
            raise ValueError(f"shadow {field} differs from the candidate snapshot")
    prompt = (root / "prompt.txt").read_bytes()
    if prompt != plan.prompt.encode() or _digest(prompt) != manifest.get(
        "prompt_sha256"
    ):
        raise ValueError("shadow prompt does not match the candidate snapshot")
    if (root / "numeric_ranking.json").read_bytes() != numeric_ranking_bytes(plan):
        raise ValueError("shadow numeric ranking does not match the candidate snapshot")
    if _evidence_status(manifest) == "prospective_bound":
        _validate_prospective_lineage(root, manifest, plan)
    if _NETWORK_FILES.issubset(cast(dict[str, object], manifest["files"])):
        _validate_network_evidence(root, manifest, plan)
    generated_at = _datetime_value(manifest.get("generated_at"), "generated_at")
    if (
        plan.universe.source_generated_at is not None
        and plan.universe.source_generated_at > generated_at
    ):
        raise ValueError("shadow candidate was generated after the repetition")


def _validate_network_evidence(
    root: Path, manifest: Mapping[str, object], plan: SelectionPlan
) -> None:
    envelope = _read_object(root / "http_request_envelope.json")
    if set(envelope) != {"endpoint", "method", "headers", "timeout_seconds"}:
        raise ValueError("shadow request envelope fields are invalid")
    headers = envelope.get("headers")
    if not isinstance(headers, dict) or headers != {
        "Content-Type": "application/json",
        "Authorization": "<redacted>",
    }:
        raise ValueError("shadow request envelope headers are invalid")
    timeout = envelope.get("timeout_seconds")
    if isinstance(timeout, bool) or not isinstance(timeout, int | float):
        raise ValueError("shadow request envelope timeout is invalid")
    response_path = root / "model_response.txt"
    response_text = (
        response_path.read_text(encoding="utf-8") if response_path.is_file() else None
    )
    parameters = manifest.get("model_parameters")
    if not isinstance(parameters, dict):
        raise ValueError("shadow model_parameters are invalid")
    typed_parameters = cast(dict[str, object], parameters)
    exchange = ProviderExchange(
        provider=cast(str, manifest["provider"]),
        model=cast(str, typed_parameters["model"]),
        endpoint=cast(str, envelope.get("endpoint")),
        request_method=cast(str, envelope.get("method")),
        request_headers=(
            ("Content-Type", "application/json"),
            ("Authorization", "<redacted>"),
        ),
        request_body=(root / "provider_request_body.json").read_bytes(),
        response_body=(root / "provider_response_body.bin").read_bytes(),
        response_text=response_text,
        actual_model=cast(str | None, manifest.get("actual_model")),
        extraction_error=cast(str | None, manifest.get("response_extraction_error")),
        timeout_seconds=float(timeout),
        refusal=cast(str | None, manifest.get("refusal")),
        usage=cast(dict[str, object] | None, manifest.get("usage")),
    )
    validate_shadow_exchange(
        exchange,
        prompt=plan.prompt,
        provider=cast(str, manifest["provider"]),
        model_parameters=typed_parameters,
        response_schema=shadow_response_schema(plan),
        response_schema_name=shadow_response_schema_name(plan),
    )


__all__ = [
    "read_shadow_ranking",
    "read_shadow_risk_decision",
    "validate_shadow_campaign",
    "validate_shadow_day",
    "validate_shadow_repetition",
]
