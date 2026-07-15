"""Strict public contracts for candidate selection artifacts."""

from __future__ import annotations

import re
from datetime import date, datetime, time, timedelta
from typing import Literal
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

SCHEMA_VERSION = "2.0.0"
PROMPT_VERSION = "2026-07-15.3"
TEMPERATURE = 0.2

Market = Literal["CN", "US"]
Style = Literal["momentum", "quality", "growth"]
ResponseLanguage = Literal["zh-CN", "en"]
InputContract = Literal[
    "stock_candidate_universe_v1",
    "hot_sector_candidate_universe_v1",
]
TemporalStatus = Literal["contemporaneous", "retrospective_simulation"]
PointInTimeAssurance = Literal["signal_date_only", "unverified"]

_CN_SYMBOL = re.compile(r"^\d{6}\.(?:SH|SZ|BJ)$")
_US_SYMBOL = re.compile(r"^[A-Z][A-Z0-9]*(?:[.-][A-Z0-9]+)?$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_PROVIDER_NAME = re.compile(r"^[a-z][a-z0-9-]{0,63}$")


def market_timezone(market: Market) -> ZoneInfo:
    """Return the timezone used for signal-date comparisons."""

    return ZoneInfo("Asia/Shanghai" if market == "CN" else "America/New_York")


def validate_symbol(symbol: str, market: Market) -> str:
    """Normalize and validate a market-specific symbol."""

    normalized = symbol.strip().upper()
    pattern = _CN_SYMBOL if market == "CN" else _US_SYMBOL
    max_length = 9 if market == "CN" else 15
    if len(normalized) > max_length or pattern.fullmatch(normalized) is None:
        raise ValueError(f"invalid {market} symbol: {symbol!r}")
    return normalized


class ModelPick(BaseModel):
    """Fields that a model is allowed to choose."""

    model_config = ConfigDict(extra="forbid", strict=True)

    symbol: str = Field(min_length=1, max_length=15)
    confidence_score: int = Field(ge=1, le=10)
    reasoning: str = Field(min_length=1, max_length=1000)
    risk_note: str = Field(min_length=1, max_length=500)

    @field_validator("symbol")
    @classmethod
    def normalize_symbol(cls, value: str) -> str:
        return value.strip().upper()


class ModelSelection(BaseModel):
    """Strict JSON object expected directly from a model provider."""

    model_config = ConfigDict(extra="forbid", strict=True)

    picks: list[ModelPick]


class StockPick(BaseModel):
    """A validated pick enriched only from the candidate manifest."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    rank: int = Field(ge=1)
    symbol: str = Field(min_length=1, max_length=15)
    name: str = Field(min_length=1, max_length=200)
    topic: str = Field(min_length=1, max_length=500)
    confidence_score: int = Field(ge=1, le=10)
    reasoning: str = Field(min_length=1, max_length=1000)
    risk_note: str = Field(min_length=1, max_length=500)


class GenerationTrace(BaseModel):
    """Content fingerprints for the inputs used to create an artifact."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    candidate_source: str = Field(min_length=1, max_length=255)
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

    @field_validator("candidate_source")
    @classmethod
    def validate_source_name(cls, value: str) -> str:
        if "/" in value or "\\" in value:
            raise ValueError("candidate_source must be a logical filename, not a path")
        return value


class SelectionArtifact(BaseModel):
    """Versioned and self-auditing model selection artifact."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    schema_version: Literal["2.0.0"] = "2.0.0"
    artifact_type: Literal["ai_stock_selection"] = "ai_stock_selection"
    market: Market
    response_language: ResponseLanguage
    selection_as_of: date
    candidate_observation_date: date
    candidate_generated_at: datetime
    data_cutoff: date
    upstream_execution_not_before: Literal["next_trading_session"] | None
    generated_at: datetime
    provider: str = Field(min_length=1, max_length=64)
    provider_api: str = Field(min_length=1, max_length=100)
    model: str = Field(min_length=1, max_length=100)
    temperature: float = Field(ge=0.0, le=2.0)
    prompt_version: Literal["2026-07-15.3"] = "2026-07-15.3"
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
    generation_trace: GenerationTrace
    picks: tuple[StockPick, ...]

    @field_validator("provider")
    @classmethod
    def validate_provider(cls, value: str) -> str:
        if _PROVIDER_NAME.fullmatch(value) is None:
            raise ValueError("provider must use lowercase letters, digits, and hyphens")
        return value

    @model_validator(mode="after")
    def validate_artifact(self) -> SelectionArtifact:
        self._validate_timestamps()
        self._validate_temporal_status()
        self._validate_input_assurance()
        self._validate_pick_set()
        return self

    def _validate_timestamps(self) -> None:
        for field, value in (
            ("generated_at", self.generated_at),
            ("candidate_generated_at", self.candidate_generated_at),
        ):
            if value.tzinfo is None or value.utcoffset() is None:
                raise ValueError(f"{field} must include a UTC offset")
            if value.utcoffset() != timedelta(0):
                raise ValueError(f"{field} must be normalized to UTC")
        if self.candidate_generated_at > self.generated_at:
            raise ValueError("candidate_generated_at must not follow generated_at")

    def _validate_temporal_status(self) -> None:
        if len(self.evidence_limitations) != len(set(self.evidence_limitations)):
            raise ValueError("evidence_limitations must be unique")
        if any(not limitation.strip() for limitation in self.evidence_limitations):
            raise ValueError("evidence_limitations must not contain empty strings")
        generated_market_date = self.generated_at.astimezone(
            market_timezone(self.market)
        ).date()
        if generated_market_date < self.selection_as_of:
            raise ValueError("generated_at precedes selection_as_of")
        expected: TemporalStatus = (
            "retrospective_simulation"
            if generated_market_date > self.selection_as_of
            else "contemporaneous"
        )
        if self.temporal_status != expected:
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

    def _validate_input_assurance(self) -> None:
        recognized_hot_contract = (
            self.input_contract == "hot_sector_candidate_universe_v1"
        )
        if (self.point_in_time_assurance == "signal_date_only") != (
            recognized_hot_contract
        ):
            raise ValueError(
                "signal_date_only must match the recognized hot-sector contract"
            )
        if self.candidate_observation_date > self.selection_as_of:
            raise ValueError(
                "candidate_observation_date must not follow selection_as_of"
            )
        if self.data_cutoff > self.candidate_observation_date:
            raise ValueError("data_cutoff must not follow candidate_observation_date")
        if not recognized_hot_contract:
            return
        if (
            self.data_cutoff != self.candidate_observation_date
            or self.upstream_execution_not_before != "next_trading_session"
        ):
            raise ValueError(
                "recognized hot-sector input requires complete candidate timing"
            )
        required = {
            "rotation_publisher_receipt_unavailable",
            "candidate_artifact_does_not_establish_out_of_sample_validity",
        }
        if not required.issubset(self.evidence_limitations):
            raise ValueError(
                "recognized hot-sector input requires canonical OOS limitations"
            )
        local = self.candidate_generated_at.astimezone(ZoneInfo("Asia/Shanghai"))
        if local.date() < self.candidate_observation_date or (
            local.date() == self.candidate_observation_date
            and local.timetz().replace(tzinfo=None) < time(16, 0)
        ):
            raise ValueError("candidate_generated_at precedes the completed EOD cutoff")
        if (
            local.date() > self.candidate_observation_date
            and "post_observation_reconstruction_not_oos"
            not in self.evidence_limitations
        ):
            raise ValueError(
                "post-observation candidate generation requires its OOS limitation"
            )

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
    "GenerationTrace",
    "InputContract",
    "Market",
    "ModelPick",
    "ModelSelection",
    "PROMPT_VERSION",
    "PointInTimeAssurance",
    "ResponseLanguage",
    "SCHEMA_VERSION",
    "SelectionArtifact",
    "StockPick",
    "Style",
    "TEMPERATURE",
    "TemporalStatus",
    "market_timezone",
    "validate_symbol",
]
