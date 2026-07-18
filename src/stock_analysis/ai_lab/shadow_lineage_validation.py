"""Archived manifest checks for prospective and legacy shadow lineage."""

from __future__ import annotations

import re
from collections.abc import Mapping
from datetime import datetime
from pathlib import Path

from .contracts import LEGACY_SHADOW_CAMPAIGN_SCHEMA_VERSION
from .selection import SelectionPlan
from .shadow_lineage import (
    EvidenceStatus,
    load_shadow_decision_plan,
    load_shadow_launch_receipt,
    validate_shadow_decision_plan,
    validate_shadow_launch_receipt,
)

LINEAGE_IDENTITY_FIELDS = (
    "evidence_status",
    "decision_plan_sha256",
    "launch_receipt_sha256",
)

_SHA256 = re.compile(r"^[0-9a-f]{64}$")


def evidence_status(manifest: Mapping[str, object]) -> EvidenceStatus:
    """Classify lineage without allowing a legacy artifact to claim binding."""

    if manifest.get("schema_version") == LEGACY_SHADOW_CAMPAIGN_SCHEMA_VERSION:
        if any(field in manifest for field in LINEAGE_IDENTITY_FIELDS):
            raise ValueError("legacy shadow cannot claim prospective lineage")
        return "legacy_unbound"
    present = [field in manifest for field in LINEAGE_IDENTITY_FIELDS]
    if not any(present):
        return "legacy_unbound"
    if not all(present):
        raise ValueError("shadow launch lineage fields are incomplete")
    status = manifest.get("evidence_status")
    decision_digest = manifest.get("decision_plan_sha256")
    receipt_digest = manifest.get("launch_receipt_sha256")
    if status == "legacy_unbound":
        if decision_digest is not None or receipt_digest is not None:
            raise ValueError("legacy_unbound shadow cannot contain launch digests")
        return "legacy_unbound"
    if status == "prospective_bound":
        for field, value in (
            ("decision_plan_sha256", decision_digest),
            ("launch_receipt_sha256", receipt_digest),
        ):
            if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
                raise ValueError(f"shadow {field} is invalid")
        return "prospective_bound"
    raise ValueError("shadow evidence_status is invalid")


def validate_archived_shadow_lineage(
    root: Path,
    manifest: Mapping[str, object],
    plan: SelectionPlan,
) -> None:
    """Rebuild every provider/model/plan/candidate/date/arm binding."""

    decision = load_shadow_decision_plan(root / "decision-plan.json")
    receipt = load_shadow_launch_receipt(root / "launch-receipt.json")
    if decision.decision_plan_sha256 != manifest.get("decision_plan_sha256"):
        raise ValueError("shadow decision_plan_sha256 differs from archived plan")
    if receipt.launch_receipt_sha256 != manifest.get("launch_receipt_sha256"):
        raise ValueError("shadow launch_receipt_sha256 differs from archived receipt")
    campaign_id = manifest.get("campaign_id")
    signal_date = manifest.get("signal_date")
    if not isinstance(campaign_id, str) or not isinstance(signal_date, str):
        raise ValueError("shadow lineage campaign/date is invalid")
    validate_shadow_decision_plan(
        plan,
        decision,
        campaign_id=campaign_id,
        signal_date=decision.signal_date,
    )
    if signal_date != decision.signal_date.isoformat():
        raise ValueError("shadow signal_date differs from decision plan")
    validate_shadow_launch_receipt(decision, receipt)
    if (
        receipt.provider != manifest.get("provider")
        or receipt.model_parameters != manifest.get("model_parameters")
        or receipt.model_partition != manifest.get("model_partition")
    ):
        raise ValueError("shadow model identity differs from launch receipt")
    generated_at = _datetime_value(manifest.get("generated_at"))
    if receipt.issued_at > generated_at:
        raise ValueError("shadow launch receipt was issued after execution")


def _datetime_value(value: object) -> datetime:
    if not isinstance(value, str):
        raise ValueError("shadow generated_at is invalid")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise ValueError("shadow generated_at is invalid") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("shadow generated_at must include a UTC offset")
    return parsed


__all__ = [
    "LINEAGE_IDENTITY_FIELDS",
    "evidence_status",
    "validate_archived_shadow_lineage",
]
