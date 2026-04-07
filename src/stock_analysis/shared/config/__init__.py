"""Configuration file loading module.

Provides unified configuration file loading functionality.
"""

import datetime
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..logging import get_logger

logger = get_logger(__name__)

try:
    import yaml
except ImportError:
    yaml = None

from dateutil.relativedelta import relativedelta


@dataclass(frozen=True)
class RiskFreeSettings:
    """Immutable configuration for risk-free rate management."""

    series: str = "DGS3MO"
    ttl_days: int | None = 5
    fallback_rate: float | None = None
    calendar: str | None = "US"


@dataclass(frozen=True)
class ReportSettings:
    """Immutable configuration for report rendering preferences."""

    report_mode: str = "both"
    with_underwater: bool = True
    index_to_100: bool = True
    use_log_scale: bool = False
    show_rolling: bool = True
    rolling_window: int = 252
    show_heatmap: bool = True


def load_cfg() -> dict[str, Any]:
    """Load configuration file.

    Prioritize reading config/config.yaml, then config.yaml in project root

    Returns:
        Dict[str, Any]: Configuration dictionary
    """
    # Project root directory
    root = Path(__file__).resolve().parents[3]

    # Try to load config file from multiple locations
    candidates = [
        root / "config" / "config.yaml",  # Priority: config/config.yaml
        root / "config.yaml",  # Alternative: config.yaml in project root
    ]

    config_path = None
    for p in candidates:
        if p.exists():
            config_path = p
            break

    if config_path is None:
        # Default configuration: return to dynamic mode, consistent with existing logic
        return {
            "backtest": {
                "period_mode": "dynamic",
                "buffer": {"months": 3, "days": 10},
                "initial_cash": 1000000,  # Unified initial capital
            }
        }

    if yaml is None:
        raise ImportError(
            "PyYAML is required to read config.yaml. Install it with: pip install PyYAML"
        )

    try:
        with open(config_path, encoding="utf-8") as f:
            config = yaml.safe_load(f) or {}
        return config
    except Exception as e:
        logger.warning("Failed to load config.yaml: %s. Using default configuration.", e)
        return {
            "backtest": {
                "period_mode": "dynamic",
                "buffer": {"months": 3, "days": 10},
                "initial_cash": {"ai": 1000000, "quant": 1000000, "spy": 100000},
            }
        }


_DEFAULT_PRELIMINARY_FACTOR_WEIGHTS: dict[str, float] = {
    "cfo": 1.0,
    "ceq": 1.0,
    "txt": 1.0,
    "d_txt": 1.0,
    "d_at": -1.0,
    "d_rect": -1.0,
}

_DEFAULT_PROMPT_VERSION = "v1"


def _coerce_bool(value: Any, default: bool) -> bool:
    """Best-effort conversion of configuration values to boolean."""

    if isinstance(value, bool):
        return value
    if value is None:
        return default
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"true", "yes", "1", "on"}:
            return True
        if lowered in {"false", "no", "0", "off"}:
            return False
    try:
        return bool(int(value))
    except (TypeError, ValueError):
        return default


def get_preliminary_factor_weights() -> dict[str, float]:
    """Return factor weights for the preliminary screen from configuration."""

    config = load_cfg()
    selection_cfg = config.get("selection", {}) if isinstance(config, dict) else {}
    prelim_cfg = (
        selection_cfg.get("preliminary", {})
        if isinstance(selection_cfg, dict)
        else {}
    )
    weights_cfg = (
        prelim_cfg.get("factor_weights") if isinstance(prelim_cfg, dict) else None
    )

    if not isinstance(weights_cfg, dict) or not weights_cfg:
        return _DEFAULT_PRELIMINARY_FACTOR_WEIGHTS.copy()

    merged = _DEFAULT_PRELIMINARY_FACTOR_WEIGHTS.copy()
    for factor, value in weights_cfg.items():
        try:
            merged[str(factor)] = float(value)
        except (TypeError, ValueError):
            logger.warning(
                "Invalid factor weight configured for %s=%r; falling back to defaults.",
                factor,
                value,
            )
            return _DEFAULT_PRELIMINARY_FACTOR_WEIGHTS.copy()

    return merged


def get_ai_prompt_version() -> str:
    """Return the configured AI prompt version for selection exports."""

    config = load_cfg()
    selection_cfg = config.get("selection", {}) if isinstance(config, dict) else {}
    ai_cfg = (
        selection_cfg.get("ai", {}) if isinstance(selection_cfg, dict) else {}
    )
    prompt_version = (
        ai_cfg.get("prompt_version") if isinstance(ai_cfg, dict) else None
    )

    if isinstance(prompt_version, str) and prompt_version.strip():
        return prompt_version.strip()
    return _DEFAULT_PROMPT_VERSION


def get_backtest_period(portfolios: dict = None) -> tuple[datetime.date, datetime.date]:
    """Get backtest time period.

    Args:
        portfolios: Portfolio dictionary, only used in dynamic mode

    Returns:
        Tuple[datetime.date, datetime.date]: (start_date, end_date)
    """
    config = load_cfg()
    backtest_config = config.get("backtest", {})

    period_mode = backtest_config.get("period_mode", "dynamic")

    if period_mode == "fixed":
        # Fixed time mode
        start_str = backtest_config.get("start", "2021-04-02")
        end_str = backtest_config.get("end", "2025-07-02")

        # Handle possible date formats
        if isinstance(start_str, str):
            start_date = datetime.datetime.strptime(start_str, "%Y-%m-%d").date()
        else:
            start_date = start_str  # Already a date object

        if isinstance(end_str, str):
            end_date = datetime.datetime.strptime(end_str, "%Y-%m-%d").date()
        else:
            end_date = end_str  # Already a date object

        return start_date, end_date

    else:
        # Dynamic time mode
        if not portfolios:
            raise ValueError("Dynamic mode requires portfolios data")

        # Get time range from portfolio data
        first_rebalance_date = min(portfolios.keys())
        last_rebalance_date = max(portfolios.keys())

        # Add buffer time
        buffer_config = backtest_config.get("buffer", {"months": 3, "days": 10})
        buffer_months = buffer_config.get("months", 3)
        buffer_days = buffer_config.get("days", 10)

        start_date = first_rebalance_date
        end_date = last_rebalance_date + relativedelta(
            months=buffer_months, days=buffer_days
        )

        return start_date, end_date


def get_initial_cash(strategy: str) -> float:
    """Get initial cash amount.

    Supports two configuration formats:
    1. Unified capital: initial_cash: 1000000
    2. Strategy-specific configuration: initial_cash: {ai: 1000000, quant: 1000000, spy: 1000000}

    Args:
        strategy: Strategy name ('ai', 'quant', 'spy')

    Returns:
        float: Initial cash amount
    """
    config = load_cfg()
    backtest_config = config.get("backtest", {})
    initial_cash_config = backtest_config.get("initial_cash", 1000000)

    # Support two formats: number (unified capital) or dictionary (strategy-specific configuration)
    if isinstance(initial_cash_config, dict):
        # Dictionary format: configure by strategy
        return float(initial_cash_config.get(strategy, 1000000))
    else:
        # Number format: unified capital
        return float(initial_cash_config)


def get_risk_free_settings() -> RiskFreeSettings:
    """Return sanitized risk-free configuration settings."""

    config = load_cfg()
    defaults = RiskFreeSettings()

    rf_cfg = config.get("risk_free", {}) if isinstance(config, dict) else {}
    if not isinstance(rf_cfg, dict):
        return defaults

    series = rf_cfg.get("series", defaults.series)
    if isinstance(series, str):
        series = series.strip() or defaults.series
    else:
        series = defaults.series

    ttl_raw = rf_cfg.get("ttl_days", defaults.ttl_days)
    ttl_days: int | None
    if ttl_raw is None:
        ttl_days = None
    else:
        try:
            ttl_days = int(ttl_raw)
            if ttl_days < 0:
                raise ValueError("ttl_days must be non-negative")
        except (TypeError, ValueError):
            logger.warning(
                "Invalid ttl_days=%r in risk_free config; falling back to %s.",
                ttl_raw,
                defaults.ttl_days,
            )
            ttl_days = defaults.ttl_days

    fallback_raw = rf_cfg.get("fallback_rate", defaults.fallback_rate)
    fallback_rate: float | None
    if fallback_raw is None:
        fallback_rate = None
    else:
        try:
            fallback_rate = float(fallback_raw)
        except (TypeError, ValueError):
            logger.warning(
                "Invalid fallback_rate=%r in risk_free config; falling back to %s.",
                fallback_raw,
                defaults.fallback_rate,
            )
            fallback_rate = defaults.fallback_rate

    calendar = rf_cfg.get("calendar", defaults.calendar)
    if isinstance(calendar, str):
        calendar = calendar.strip() or defaults.calendar
    else:
        calendar = defaults.calendar

    return RiskFreeSettings(
        series=series,
        ttl_days=ttl_days,
        fallback_rate=fallback_rate,
        calendar=calendar,
    )


def get_report_settings() -> ReportSettings:
    """Return report rendering preferences merged with defaults."""

    config = load_cfg()
    defaults = ReportSettings()

    report_cfg = config.get("report", {}) if isinstance(config, dict) else {}
    if not isinstance(report_cfg, dict):
        report_cfg = {}

    report_mode_raw = report_cfg.get("report_mode", defaults.report_mode)
    report_mode = (
        str(report_mode_raw).strip().lower()
        if isinstance(report_mode_raw, str)
        else str(report_mode_raw).lower()
    )
    valid_modes = {"comparison_only", "strategy_only", "both"}
    if report_mode not in valid_modes:
        if report_mode_raw not in (None, ""):
            logger.warning(
                "Invalid report_mode=%r in report config; falling back to %s.",
                report_mode_raw,
                defaults.report_mode,
            )
        report_mode = defaults.report_mode

    with_underwater = _coerce_bool(
        report_cfg.get("with_underwater"), defaults.with_underwater
    )
    index_to_100 = _coerce_bool(report_cfg.get("index_to_100"), defaults.index_to_100)
    use_log_scale = _coerce_bool(report_cfg.get("use_log_scale"), defaults.use_log_scale)
    show_rolling = _coerce_bool(report_cfg.get("show_rolling"), defaults.show_rolling)
    show_heatmap = _coerce_bool(report_cfg.get("show_heatmap"), defaults.show_heatmap)

    rolling_raw = report_cfg.get("rolling_window", defaults.rolling_window)
    try:
        rolling_window = int(rolling_raw)
        if rolling_window <= 0:
            raise ValueError
    except (TypeError, ValueError):
        logger.warning(
            "Invalid rolling_window=%r in report config; falling back to %s.",
            rolling_raw,
            defaults.rolling_window,
        )
        rolling_window = defaults.rolling_window

    return ReportSettings(
        report_mode=report_mode,
        with_underwater=with_underwater,
        index_to_100=index_to_100,
        use_log_scale=use_log_scale,
        show_rolling=show_rolling,
        rolling_window=rolling_window,
        show_heatmap=show_heatmap,
    )
