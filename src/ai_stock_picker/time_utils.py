"""Unambiguous date and timestamp parsing."""

from __future__ import annotations

from datetime import date, datetime


def parse_date(value: str) -> date:
    """Parse YYYY-MM-DD or YYYYMMDD without accepting ambiguous formats."""

    stripped = value.strip()
    fmt = "%Y%m%d" if len(stripped) == 8 and stripped.isdigit() else "%Y-%m-%d"
    try:
        return datetime.strptime(stripped, fmt).date()
    except ValueError as exc:
        raise ValueError(f"invalid date {value!r}; use YYYY-MM-DD or YYYYMMDD") from exc


def parse_timestamp(value: object, field: str) -> datetime:
    """Parse an ISO-8601 timestamp that includes an explicit offset."""

    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"manifest {field} must be an ISO-8601 timestamp")
    text = value.strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as exc:
        raise ValueError(f"manifest {field} is not ISO-8601") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"manifest {field} must include an explicit UTC offset")
    return parsed


def parse_cutoff_date(value: object) -> date:
    """Parse an ISO date or timestamp and return its date component."""

    if not isinstance(value, str) or not value.strip():
        raise ValueError("manifest data_cutoff must be an ISO date or timestamp")
    text = value.strip()
    try:
        return parse_date(text)
    except ValueError:
        return parse_timestamp(text, "data_cutoff").date()


__all__ = ["parse_cutoff_date", "parse_date", "parse_timestamp"]
