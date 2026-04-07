"""Targets JSON utilities.

Defines a canonical, market-aware schema for live rebalance targets while
providing a controlled migration path from the older ticker-list format.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import json


SCHEMA_VERSION = 2
KNOWN_MARKETS = {"US", "HK", "CN", "SG"}


def _split_symbol_market(
    symbol: str, market: str | None = None, *, default_market: str = "US"
) -> tuple[str, str]:
    raw_symbol = str(symbol or "").upper().strip()
    raw_market = str(market or "").upper().strip()

    if raw_market:
        if raw_symbol.rsplit(".", 1)[-1] in KNOWN_MARKETS and "." in raw_symbol:
            raw_symbol = raw_symbol.rsplit(".", 1)[0]
        return raw_symbol, raw_market

    if "." in raw_symbol:
        base, suffix = raw_symbol.rsplit(".", 1)
        if suffix in KNOWN_MARKETS:
            return base, suffix

    return raw_symbol, str(default_market or "US").upper().strip() or "US"


@dataclass(slots=True)
class TargetEntry:
    """Canonical target entry."""

    symbol: str
    market: str
    target_weight: float | None = None
    target_quantity: float | None = None
    notes: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.symbol, self.market = _split_symbol_market(self.symbol, self.market)
        if not self.symbol:
            raise ValueError("target symbol cannot be empty")
        if self.market not in KNOWN_MARKETS:
            raise ValueError(f"unsupported market: {self.market}")

        has_weight = self.target_weight is not None
        has_quantity = self.target_quantity is not None
        if has_weight == has_quantity:
            raise ValueError(
                "each target entry must define exactly one of "
                "target_weight or target_quantity"
            )

        if self.target_weight is not None:
            self.target_weight = float(self.target_weight)
            if self.target_weight < 0:
                raise ValueError("target_weight cannot be negative")

        if self.target_quantity is not None:
            self.target_quantity = float(self.target_quantity)
            if self.target_quantity < 0:
                raise ValueError("target_quantity cannot be negative")

        self.notes = self.notes or None
        self.metadata = dict(self.metadata or {})

    @property
    def key(self) -> str:
        return f"{self.symbol}.{self.market}"

    def to_payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "symbol": self.symbol,
            "market": self.market,
        }
        if self.target_weight is not None:
            payload["target_weight"] = self.target_weight
        if self.target_quantity is not None:
            payload["target_quantity"] = self.target_quantity
        if self.notes:
            payload["notes"] = self.notes
        if self.metadata:
            payload["metadata"] = self.metadata
        return payload


@dataclass(slots=True)
class Targets:
    """Canonical targets document."""

    targets: list[TargetEntry]
    asof: str | None = None
    source: str | None = None
    target_gross_exposure: float = 1.0
    notes: str | None = None
    schema_version: int = SCHEMA_VERSION

    def __post_init__(self) -> None:
        self.targets = list(self.targets or [])
        if not self.targets:
            raise ValueError("targets document must contain at least one target")
        self.target_gross_exposure = float(self.target_gross_exposure or 0.0)
        if self.target_gross_exposure < 0:
            raise ValueError("target_gross_exposure cannot be negative")
        self.notes = self.notes or None
        self.source = self.source or None
        self.asof = self.asof or None

    @property
    def tickers(self) -> list[str]:
        """Compatibility accessor returning base symbols."""

        return [target.symbol for target in self.targets]

    @property
    def weights(self) -> dict[str, float] | None:
        """Compatibility accessor for weight-based targets."""

        weighted = {
            target.key: float(target.target_weight)
            for target in self.targets
            if target.target_weight is not None
        }
        return weighted or None


def _entry_from_obj(
    obj: TargetEntry | dict[str, Any],
    *,
    default_market: str = "US",
) -> TargetEntry:
    if isinstance(obj, TargetEntry):
        return obj
    if not isinstance(obj, dict):
        raise TypeError(f"unsupported target entry type: {type(obj)!r}")
    symbol, market = _split_symbol_market(
        str(obj.get("symbol") or obj.get("ticker") or ""),
        obj.get("market"),
        default_market=default_market,
    )
    return TargetEntry(
        symbol=symbol,
        market=market,
        target_weight=obj.get("target_weight"),
        target_quantity=obj.get("target_quantity"),
        notes=obj.get("notes"),
        metadata=dict(obj.get("metadata") or {}),
    )


def _entries_from_legacy(
    tickers: list[str],
    *,
    weights: dict[str, float] | None = None,
    default_market: str = "US",
) -> list[TargetEntry]:
    cleaned: list[tuple[str, str, str]] = []
    for raw in tickers:
        symbol, market = _split_symbol_market(str(raw), default_market=default_market)
        if symbol:
            cleaned.append((str(raw), symbol, market))
    if not cleaned:
        raise ValueError("legacy targets document contained no valid tickers")

    if weights:
        entries: list[TargetEntry] = []
        for raw, symbol, market in cleaned:
            weight = None
            for key in (raw, symbol, f"{symbol}.{market}"):
                if key in weights:
                    weight = weights[key]
                    break
            if weight is None:
                raise ValueError(
                    "legacy targets weights must define each target explicitly"
                )
            entries.append(
                TargetEntry(
                    symbol=symbol,
                    market=market,
                    target_weight=float(weight),
                )
            )
        return entries

    equal_weight = 1.0 / len(cleaned)
    return [
        TargetEntry(symbol=symbol, market=market, target_weight=equal_weight)
        for _, symbol, market in cleaned
    ]


def write_targets_json(
    out_path: Path,
    tickers: list[str] | None = None,
    *,
    asof: str | None = None,
    source: str | None = "manual",
    weights: dict[str, float] | None = None,
    notes: str | None = None,
    targets: list[TargetEntry | dict[str, Any]] | None = None,
    target_gross_exposure: float = 1.0,
    default_market: str = "US",
) -> Path:
    """Write canonical targets JSON in schema v2.

    Callers may either provide explicit ``targets`` entries or a legacy-style
    ticker list plus optional weights, which will be normalized into schema v2.
    """

    if targets is not None:
        entries = [
            _entry_from_obj(target, default_market=default_market) for target in targets
        ]
    else:
        entries = _entries_from_legacy(
            list(tickers or []),
            weights=weights,
            default_market=default_market,
        )

    payload: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "asof": asof,
        "source": source,
        "target_gross_exposure": float(target_gross_exposure or 0.0),
        "targets": [entry.to_payload() for entry in entries],
        "notes": notes or None,
    }

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    return out_path


def read_targets_json(
    path: Path,
    *,
    require_schema_v2: bool = False,
    default_market: str = "US",
) -> Targets:
    """Read targets JSON and return structured data.

    When ``require_schema_v2`` is true, legacy ticker-list inputs are rejected
    with a migration-oriented error message.
    """

    if not path.exists():
        raise FileNotFoundError(f"文件不存在: {path}")

    raw = json.loads(path.read_text(encoding="utf-8"))
    schema_version = int(raw.get("schema_version") or 1)
    asof = raw.get("asof") or None
    source = raw.get("source") or None
    notes = raw.get("notes") or None
    target_gross_exposure = float(raw.get("target_gross_exposure", 1.0))

    if schema_version >= SCHEMA_VERSION and isinstance(raw.get("targets"), list):
        entries = [
            _entry_from_obj(item, default_market=default_market)
            for item in (raw.get("targets") or [])
        ]
        return Targets(
            targets=entries,
            asof=asof,
            source=source,
            target_gross_exposure=target_gross_exposure,
            notes=notes,
            schema_version=schema_version,
        )

    if require_schema_v2:
        raise ValueError(
            "legacy ticker-list targets are no longer canonical execution inputs; "
            "regenerate the file with 'stockq targets gen' to produce schema v2"
        )

    tickers = [str(t).upper().strip() for t in (raw.get("tickers") or []) if t]
    weights = raw.get("weights") or None
    entries = _entries_from_legacy(
        tickers,
        weights=weights,
        default_market=default_market,
    )
    return Targets(
        targets=entries,
        asof=asof,
        source=source,
        target_gross_exposure=target_gross_exposure,
        notes=notes,
        schema_version=schema_version,
    )
