"""Strict contracts for model output and persisted selection artifacts."""

from __future__ import annotations

import json
import re
from datetime import date, datetime, time, timedelta
from hashlib import sha256
from typing import Literal
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .ranking_policy_contract import (
    BOUNDED_RANKING_POLICY,
    BOUNDED_RANKING_PROMPT_VERSION,
    BOUNDED_RANKING_V2_POLICY,
    BOUNDED_RANKING_V2_PROMPT_VERSION,
    BOUNDED_RANKING_V3_POLICY,
    BOUNDED_RANKING_V3_PROMPT_VERSION,
    RISK_VETO_POLICY,
    RISK_VETO_PROMPT_VERSION,
)

SCHEMA_VERSION = "1.0.0"
CONTRACT_INFO_SCHEMA_VERSION = "1.2.0"
CONTRACT_INFO_ARTIFACT_TYPE = "ai_stock_picker_contract_info"
HOT_SECTOR_V2_SOURCE_CONCEPTS_POLICY_ID = "hotsector.source_concepts.theme_only"
HOT_SECTOR_V2_SOURCE_CONCEPTS_POLICY_VERSION = "1.0.0"
HOT_SECTOR_V2_SOURCE_CONCEPTS_POLICY_SHA256 = (
    "d14282e8047367ba61ea762cd3c3de56162329c12f1778c9681246ec7f0f0b40"
)
LEGACY_SHADOW_CAMPAIGN_SCHEMA_VERSION = "1.0.0"
SHADOW_CAMPAIGN_SCHEMA_VERSION = "1.1.0"
SHADOW_REPETITIONS = 3
SHADOW_MIN_VALID_REPETITIONS = 2
SHADOW_REPETITION_NAMES = tuple(
    f"repetition-{index:02d}" for index in range(1, SHADOW_REPETITIONS + 1)
)
SHADOW_TOMBSTONE_REASONS = frozenset(
    {
        "provider_call_failed",
        "transport_contract_failed",
        "ranking_contract_failed",
        "decision_contract_failed",
        "watchdog_missing_repetition",
        "insufficient_valid_repetitions",
        "insufficient_consensus_agreement",
    }
)
PROMPT_VERSION: Literal["2026-07-17.6"] = "2026-07-17.6"
RANKING_ONLY_PROMPT_VERSION: Literal["2026-07-17.1"] = "2026-07-17.1"
LEGACY_STABILITY_PROMPT_VERSION: Literal["2026-07-15.3"] = "2026-07-15.3"

Market = Literal["CN", "US"]
Provider = Literal["deepseek", "gemini"]
Style = Literal["momentum", "quality", "growth"]
PromptProfile = Literal[
    "production_v4",
    "legacy_stability_v3",
    "ranking_only_v1",
    "bounded_ranking_v1",
    "bounded_ranking_v2",
    "bounded_ranking_v3",
    "risk_veto_v1",
]
InputContract = Literal[
    "hot_sector_candidate_universe_v1",
    "hot_sector_candidate_universe_v2",
    "generic_json_manifest",
    "legacy_csv",
]
TemporalStatus = Literal["contemporaneous", "retrospective_simulation"]
PointInTimeAssurance = Literal["signal_date_only", "unverified"]
ReadablePromptVersion = Literal[
    "2026-07-15.2",
    "2026-07-15.3",
    "2026-07-16.4",
    "2026-07-17.1",
    "2026-07-17.2",
    "2026-07-17.5",
    "2026-07-17.6",
    "2026-07-17.7",
    "2026-07-18.8",
]

_PROMPT_VERSIONS: dict[PromptProfile, ReadablePromptVersion] = {
    "production_v4": PROMPT_VERSION,
    "legacy_stability_v3": LEGACY_STABILITY_PROMPT_VERSION,
    "ranking_only_v1": RANKING_ONLY_PROMPT_VERSION,
    "bounded_ranking_v1": BOUNDED_RANKING_PROMPT_VERSION,
    "bounded_ranking_v2": BOUNDED_RANKING_V2_PROMPT_VERSION,
    "bounded_ranking_v3": BOUNDED_RANKING_V3_PROMPT_VERSION,
    "risk_veto_v1": RISK_VETO_PROMPT_VERSION,
}

_CN_SYMBOL = re.compile(r"^\d{6}\.(?:SH|SZ|BJ)$")
_US_SYMBOL = re.compile(r"^[A-Z][A-Z0-9]*(?:[.-][A-Z0-9]+)?$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


def validate_prompt_profile(value: str) -> PromptProfile:
    """Return a supported prompt profile with its narrow static type."""

    if value not in _PROMPT_VERSIONS:
        raise ValueError("unsupported prompt profile")
    return value


def prompt_version_for_profile(value: str) -> ReadablePromptVersion:
    """Resolve the artifact version owned by one prompt profile."""

    return _PROMPT_VERSIONS[validate_prompt_profile(value)]


def contract_info(market: Market) -> dict[str, object]:
    """Return the versioned machine contract exposed to downstream consumers."""

    provider: Provider = "deepseek" if market == "CN" else "gemini"
    profiles: dict[str, object] = {
        "production_v4": {
            "prompt_version": PROMPT_VERSION,
            "output_contract": "publication_selection",
        },
        "ranking_only_v1": {
            "prompt_version": RANKING_ONLY_PROMPT_VERSION,
            "output_contract": "research_selection_or_ranking_diagnostic",
        },
        "legacy_stability_v3": {
            "prompt_version": LEGACY_STABILITY_PROMPT_VERSION,
            "output_contract": "legacy_stability_selection",
        },
    }
    if market == "CN":
        profiles["bounded_ranking_v1"] = {
            "prompt_version": BOUNDED_RANKING_PROMPT_VERSION,
            "output_contract": "research_selection_or_ranking_diagnostic",
            "ranking_policy": BOUNDED_RANKING_POLICY.contract_record(),
        }
        profiles["bounded_ranking_v2"] = {
            "prompt_version": BOUNDED_RANKING_V2_PROMPT_VERSION,
            "output_contract": "research_selection_or_ranking_diagnostic",
            "ranking_policy": BOUNDED_RANKING_V2_POLICY.contract_record(),
        }
        profiles["bounded_ranking_v3"] = {
            "prompt_version": BOUNDED_RANKING_V3_PROMPT_VERSION,
            "output_contract": "strict_ranking_selection",
            "ranking_policy": BOUNDED_RANKING_V3_POLICY.contract_record(),
        }
        profiles["risk_veto_v1"] = {
            "prompt_version": RISK_VETO_PROMPT_VERSION,
            "output_contract": "strict_risk_veto_decision",
            "risk_veto_policy": RISK_VETO_POLICY.contract_record(),
        }
    payload: dict[str, object] = {
        "schema_version": CONTRACT_INFO_SCHEMA_VERSION,
        "artifact_type": CONTRACT_INFO_ARTIFACT_TYPE,
        "market": market,
        "provider": provider,
        "selection_contract": {
            "schema_version": SCHEMA_VERSION,
            "artifact_type": "ai_stock_selection",
        },
        "prompt_profiles": profiles,
        "model_response_contracts": {
            "publication_selection": _schema_record(ModelSelection.model_json_schema()),
            "ranking_selection": _schema_record(
                RankingModelSelection.model_json_schema()
            ),
            "risk_veto_decision": _schema_record(
                RiskVetoModelDecision.model_json_schema()
            ),
        },
    }
    if market == "CN":
        payload["accepted_candidate_contracts"] = {
            "hot_sector_candidate_universe_v1": {"schema_version": "1.0.0"},
            "hot_sector_candidate_universe_v2": {
                "schema_version": "2.0.0",
                "source_concepts_policy_id": (HOT_SECTOR_V2_SOURCE_CONCEPTS_POLICY_ID),
                "source_concepts_policy_version": (
                    HOT_SECTOR_V2_SOURCE_CONCEPTS_POLICY_VERSION
                ),
                "source_concepts_policy_sha256": (
                    HOT_SECTOR_V2_SOURCE_CONCEPTS_POLICY_SHA256
                ),
            },
        }
        payload["shadow_campaign_contract"] = {
            "schema_version": SHADOW_CAMPAIGN_SCHEMA_VERSION,
            "prompt_profiles": {
                "bounded_ranking_v3": BOUNDED_RANKING_V3_PROMPT_VERSION,
                "risk_veto_v1": RISK_VETO_PROMPT_VERSION,
            },
            "repetitions": SHADOW_REPETITIONS,
            "min_valid_repetitions": SHADOW_MIN_VALID_REPETITIONS,
            "providers": ["deepseek", "openai"],
            "partition_layout": "campaign/arm/provider--model/date/repetition",
            "model_partition_source": "ai_shadow_launch_receipt",
            "arms": ["bounded_ranking", "risk_veto"],
            "decision_plan_artifact_type": "ai_shadow_decision_plan",
            "launch_receipt_artifact_type": "ai_shadow_launch_receipt",
            "evidence_statuses": ["prospective_bound", "legacy_unbound"],
            "repetition_artifact_type": "ai_shadow_repetition",
            "consensus_artifact_type": "ai_shadow_consensus",
            "ranking_eligibility": "ranking_contract=passed",
            "repetition_eligibility": {
                "bounded_ranking": "ranking_contract=passed",
                "risk_veto": "decision_contract=passed",
            },
        }
    payload["contract_sha256"] = canonical_contract_sha256(payload)
    ContractInfoArtifact.model_validate(payload, strict=True)
    return payload


def contract_info_json_schema() -> dict[str, object]:
    """Return the JSON Schema for the machine-readable contract-info envelope."""

    return ContractInfoArtifact.model_json_schema()


def canonical_contract_sha256(payload: dict[str, object]) -> str:
    """Hash one contract payload after removing its self-referential digest."""

    core = dict(payload)
    core.pop("contract_sha256", None)
    return sha256(_canonical_json(core)).hexdigest()


def _schema_record(schema: dict[str, object]) -> dict[str, object]:
    return {
        "json_schema": schema,
        "sha256": sha256(_canonical_json(schema)).hexdigest(),
    }


def _canonical_json(value: object) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode()


def validate_symbol(symbol: str, market: Market) -> str:
    """Normalize and validate a market-specific symbol."""

    normalized = symbol.strip().upper()
    pattern = _CN_SYMBOL if market == "CN" else _US_SYMBOL
    max_length = 9 if market == "CN" else 15
    if len(normalized) > max_length or pattern.fullmatch(normalized) is None:
        raise ValueError(f"invalid {market} symbol: {symbol!r}")
    return normalized


class ModelPick(BaseModel):
    """Only fields that an LLM is permitted to choose."""

    model_config = ConfigDict(extra="forbid", strict=True)

    symbol: str = Field(min_length=1, max_length=15)
    confidence_score: int = Field(ge=1, le=10)
    reasoning: str = Field(default="", max_length=1000)
    risk_note: str = Field(default="", max_length=500)

    @field_validator("symbol")
    @classmethod
    def normalize_symbol(cls, value: str) -> str:
        return value.strip().upper()


class ModelSelection(BaseModel):
    """Strict JSON object expected directly from a provider."""

    model_config = ConfigDict(extra="forbid", strict=True)

    picks: list[ModelPick]


class RankingModelPick(BaseModel):
    """Minimal response item for ranking-only and bounded research profiles."""

    model_config = ConfigDict(extra="forbid", strict=True)

    symbol: str = Field(min_length=1, max_length=15)
    confidence_score: int = Field(ge=1, le=10)

    @field_validator("symbol")
    @classmethod
    def normalize_symbol(cls, value: str) -> str:
        return value.strip().upper()


class RankingModelSelection(BaseModel):
    """Canonical strict provider schema for research-only rankings."""

    model_config = ConfigDict(extra="forbid", strict=True)

    picks: list[RankingModelPick]


RiskCode = Literal[
    "overheat",
    "instability",
    "liquidity",
    "evidence_conflict",
    "none",
]


class RiskVetoModelDecision(BaseModel):
    """Canonical strict provider schema for one optional risk veto."""

    model_config = ConfigDict(extra="forbid", strict=True)

    veto_symbol: str = Field(min_length=1, max_length=15)
    risk_code: RiskCode

    @field_validator("veto_symbol")
    @classmethod
    def normalize_symbol(cls, value: str) -> str:
        return value.strip().upper()

    @model_validator(mode="after")
    def validate_none_pair(self) -> RiskVetoModelDecision:
        if (self.veto_symbol == "NONE") != (self.risk_code == "none"):
            raise ValueError("NONE veto_symbol and none risk_code must be paired")
        return self


class ContractInfoArtifact(BaseModel):
    """Schema of the additive machine handshake exposed to consumers."""

    model_config = ConfigDict(extra="forbid", strict=True)

    schema_version: Literal["1.1.0", "1.2.0"]
    artifact_type: Literal["ai_stock_picker_contract_info"]
    market: Market
    provider: Provider
    selection_contract: dict[str, object]
    prompt_profiles: dict[str, object]
    model_response_contracts: dict[str, object]
    accepted_candidate_contracts: dict[str, object] | None = None
    shadow_campaign_contract: dict[str, object] | None = None
    contract_sha256: str

    @model_validator(mode="after")
    def validate_market_capabilities(self) -> ContractInfoArtifact:
        has_cn_capabilities = (
            self.accepted_candidate_contracts is not None
            and self.shadow_campaign_contract is not None
        )
        if has_cn_capabilities != (self.market == "CN"):
            raise ValueError("CN contract-info capabilities are inconsistent")
        if canonical_contract_sha256(self.model_dump(exclude_none=True)) != (
            self.contract_sha256
        ):
            raise ValueError("contract-info digest is inconsistent")
        return self


class StockPick(BaseModel):
    """A validated pick enriched exclusively from the candidate universe."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    rank: int = Field(ge=1)
    symbol: str = Field(min_length=1, max_length=15)
    name: str = Field(min_length=1, max_length=200)
    topic: str = Field(min_length=1, max_length=500)
    confidence_score: int = Field(ge=1, le=10)
    reasoning: str = Field(default="", max_length=1000)
    risk_note: str = Field(default="", max_length=500)


class Lineage(BaseModel):
    """Content-addressed inputs used to create an artifact."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    candidate_path: str = Field(min_length=1)
    input_sha256: str
    candidate_symbols_sha256: str
    prompt_sha256: str
    response_sha256: str

    @field_validator(
        "input_sha256",
        "candidate_symbols_sha256",
        "prompt_sha256",
        "response_sha256",
    )
    @classmethod
    def validate_hash(cls, value: str) -> str:
        if _SHA256.fullmatch(value) is None:
            raise ValueError("expected a lowercase SHA-256 digest")
        return value


class SelectionArtifact(BaseModel):
    """Versioned and self-auditing AI selection artifact."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    schema_version: Literal["1.0.0"] = "1.0.0"
    artifact_type: Literal["ai_stock_selection"] = "ai_stock_selection"
    market: Market
    selection_as_of: date
    candidate_observation_date: date | None
    candidate_generated_at: datetime | None
    data_cutoff: date | None
    upstream_execution_not_before: Literal["next_trading_session"] | None
    generated_at: datetime
    provider: Provider
    model: str = Field(min_length=1, max_length=100)
    prompt_version: ReadablePromptVersion = PROMPT_VERSION
    style: Style
    input_contract: InputContract
    temporal_status: TemporalStatus
    point_in_time_assurance: PointInTimeAssurance
    strict_point_in_time: Literal[False] = False
    eligible_as_oos_evidence: Literal[False] = False
    evidence_limitations: tuple[str, ...] = Field(min_length=1)
    input_count: int = Field(gt=0)
    requested_top_n: int = Field(gt=0)
    selection_method: Literal["llm_candidate_rerank"] = "llm_candidate_rerank"
    lineage: Lineage
    picks: tuple[StockPick, ...]

    @model_validator(mode="after")
    def validate_artifact(self) -> SelectionArtifact:
        self._validate_provider_and_timestamps()
        self._validate_temporal_status()
        self._validate_lineage_assurance()
        self._validate_pick_set()
        return self

    def _validate_provider_and_timestamps(self) -> None:
        expected_provider = "deepseek" if self.market == "CN" else "gemini"
        if self.provider != expected_provider:
            raise ValueError(
                f"provider {self.provider!r} does not match market {self.market}"
            )
        if self.generated_at.tzinfo is None or self.generated_at.utcoffset() is None:
            raise ValueError("generated_at must include a UTC offset")
        if self.generated_at.utcoffset() != timedelta(0):
            raise ValueError("generated_at must be normalized to UTC")
        if self.candidate_generated_at is not None:
            if (
                self.candidate_generated_at.tzinfo is None
                or self.candidate_generated_at.utcoffset() is None
            ):
                raise ValueError("candidate_generated_at must include a UTC offset")
            if self.candidate_generated_at.utcoffset() != timedelta(0):
                raise ValueError("candidate_generated_at must be normalized to UTC")
            if self.candidate_generated_at > self.generated_at:
                raise ValueError("candidate_generated_at must not follow generated_at")

    def _validate_temporal_status(self) -> None:
        if len(self.evidence_limitations) != len(set(self.evidence_limitations)):
            raise ValueError("evidence_limitations must be unique")
        if any(not limitation.strip() for limitation in self.evidence_limitations):
            raise ValueError("evidence_limitations must not contain empty strings")
        market_timezone = ZoneInfo(
            "Asia/Shanghai" if self.market == "CN" else "America/New_York"
        )
        generated_market_date = self.generated_at.astimezone(market_timezone).date()
        if generated_market_date < self.selection_as_of:
            raise ValueError("generated_at precedes selection_as_of")
        expected_temporal_status: TemporalStatus = (
            "retrospective_simulation"
            if generated_market_date > self.selection_as_of
            else "contemporaneous"
        )
        if self.temporal_status != expected_temporal_status:
            raise ValueError(
                "temporal_status does not match generated_at in the market timezone"
            )
        has_retrospective_limit = (
            "selection_generated_after_as_of" in self.evidence_limitations
        )
        if (self.temporal_status == "retrospective_simulation") != (
            has_retrospective_limit
        ):
            raise ValueError(
                "temporal_status and evidence_limitations are inconsistent"
            )

    def _validate_lineage_assurance(self) -> None:
        recognized_hot_contract = self.input_contract in {
            "hot_sector_candidate_universe_v1",
            "hot_sector_candidate_universe_v2",
        }
        if (self.point_in_time_assurance == "signal_date_only") != (
            recognized_hot_contract
        ):
            raise ValueError(
                "signal_date_only must match the recognized hot-sector contract"
            )
        if recognized_hot_contract:
            if (
                self.candidate_observation_date is None
                or self.data_cutoff != self.candidate_observation_date
                or self.candidate_generated_at is None
                or self.upstream_execution_not_before != "next_trading_session"
            ):
                raise ValueError(
                    "recognized hot-sector lineage requires complete candidate timing"
                )
            required_hot_limitations = {
                "rotation_publisher_receipt_unavailable",
                "candidate_artifact_does_not_establish_out_of_sample_validity",
            }
            if not required_hot_limitations.issubset(self.evidence_limitations):
                raise ValueError(
                    "recognized hot-sector lineage requires canonical OOS limitations"
                )
            candidate_market_time = self.candidate_generated_at.astimezone(
                ZoneInfo("Asia/Shanghai")
            )
            candidate_market_date = candidate_market_time.date()
            if candidate_market_date < self.candidate_observation_date:
                raise ValueError(
                    "candidate_generated_at precedes candidate_observation_date"
                )
            if (
                candidate_market_date == self.candidate_observation_date
                and candidate_market_time.timetz().replace(tzinfo=None) < time(16, 0)
            ):
                raise ValueError(
                    "candidate_generated_at precedes the completed EOD cutoff"
                )
            if (
                candidate_market_date > self.candidate_observation_date
                and "post_observation_reconstruction_not_oos"
                not in self.evidence_limitations
            ):
                raise ValueError(
                    "post-observation candidate generation requires its OOS limitation"
                )
        if (
            self.candidate_observation_date is not None
            and self.candidate_observation_date > self.selection_as_of
        ):
            raise ValueError(
                "candidate_observation_date must not follow selection_as_of"
            )
        if (
            self.data_cutoff is not None
            and self.candidate_observation_date is not None
            and self.data_cutoff > self.candidate_observation_date
        ):
            raise ValueError("data_cutoff must not follow candidate_observation_date")

    def _validate_pick_set(self) -> None:
        if len(self.picks) != self.requested_top_n:
            raise ValueError("picks must contain exactly requested_top_n items")
        if self.requested_top_n > self.input_count:
            raise ValueError("requested_top_n exceeds input_count")
        symbols = [pick.symbol for pick in self.picks]
        if len(symbols) != len(set(symbols)):
            raise ValueError("pick symbols must be unique")
        if [pick.rank for pick in self.picks] != list(
            range(1, self.requested_top_n + 1)
        ):
            raise ValueError("pick ranks must be contiguous and ordered from 1")
        for pick in self.picks:
            validate_symbol(pick.symbol, self.market)


__all__ = [
    "CONTRACT_INFO_ARTIFACT_TYPE",
    "CONTRACT_INFO_SCHEMA_VERSION",
    "ContractInfoArtifact",
    "BOUNDED_RANKING_PROMPT_VERSION",
    "BOUNDED_RANKING_V2_PROMPT_VERSION",
    "BOUNDED_RANKING_V3_PROMPT_VERSION",
    "InputContract",
    "HOT_SECTOR_V2_SOURCE_CONCEPTS_POLICY_ID",
    "HOT_SECTOR_V2_SOURCE_CONCEPTS_POLICY_SHA256",
    "HOT_SECTOR_V2_SOURCE_CONCEPTS_POLICY_VERSION",
    "LEGACY_STABILITY_PROMPT_VERSION",
    "LEGACY_SHADOW_CAMPAIGN_SCHEMA_VERSION",
    "Lineage",
    "Market",
    "ModelPick",
    "ModelSelection",
    "RankingModelPick",
    "RankingModelSelection",
    "RISK_VETO_PROMPT_VERSION",
    "RiskCode",
    "RiskVetoModelDecision",
    "PROMPT_VERSION",
    "RANKING_ONLY_PROMPT_VERSION",
    "PointInTimeAssurance",
    "PromptProfile",
    "Provider",
    "ReadablePromptVersion",
    "SCHEMA_VERSION",
    "SHADOW_CAMPAIGN_SCHEMA_VERSION",
    "SHADOW_MIN_VALID_REPETITIONS",
    "SHADOW_REPETITIONS",
    "SHADOW_REPETITION_NAMES",
    "SHADOW_TOMBSTONE_REASONS",
    "SelectionArtifact",
    "StockPick",
    "Style",
    "TemporalStatus",
    "contract_info",
    "contract_info_json_schema",
    "canonical_contract_sha256",
    "prompt_version_for_profile",
    "validate_prompt_profile",
    "validate_symbol",
]
