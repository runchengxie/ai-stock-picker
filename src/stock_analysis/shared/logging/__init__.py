# src/stock_analysis/utils/logging.py
"""Logging configuration module.

Provides unified logging configuration functionality.
"""

from __future__ import annotations

import logging
import sys
import uuid
from contextvars import ContextVar
from pathlib import Path

# This module is already being used elsewhere
try:
    from .paths import OUTPUTS_DIR
except Exception:
    # Fallback, don't crash again due to path module issues
    OUTPUTS_DIR = Path.cwd() / "outputs"

__all__ = [
    "setup_logging",
    "get_logger",
    "StrategyLogger",
    "set_run_id",
    "get_run_id",
]

_DEFAULT_FMT = "[%(asctime)s] %(levelname)s %(name)s [run=%(run_id)s]: %(message)s"
_DEFAULT_DATEFMT = "%Y-%m-%d %H:%M:%S"

_RUN_ID: ContextVar[str | None] = ContextVar("stock_analysis_run_id", default=None)


def get_run_id() -> str:
    """Return the current run identifier, generating one if missing."""

    run_id = _RUN_ID.get()
    if not run_id:
        run_id = uuid.uuid4().hex[:12]
        _RUN_ID.set(run_id)
    return run_id


def set_run_id(run_id: str) -> None:
    """Set the current run identifier for log records."""

    _RUN_ID.set(run_id)


class _RunIdFilter(logging.Filter):
    """Ensure each log record carries the active ``run_id`` field."""

    def filter(self, record: logging.LogRecord) -> bool:  # pragma: no cover - trivial
        record.run_id = get_run_id()
        return True


_RUN_ID_FILTER = _RunIdFilter()


def _ensure_outputs_dir() -> Path:
    try:
        OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)
    except Exception:
        # Worst case fallback to current directory
        return Path.cwd()
    return OUTPUTS_DIR


def setup_logging(
    name: str,
    filename: str | None = None,
    *,
    log_file: str | None = None,
    level: int = logging.INFO,
    use_console: bool = True,
) -> logging.Logger:
    """Set up logging configuration.

    ``setup_logging`` historically accepted ``filename`` for the log file.  The
    tests (and public API) use ``log_file`` instead, so we accept both.  If both
    are provided, ``log_file`` takes precedence.

    Args:
        name: Logger name.
        filename: Deprecated log file name, kept for backward compatibility.
        log_file: Optional log file name.
        level: Log level, defaults to ``logging.INFO``.
        use_console: If ``True`` (default) attach a ``StreamHandler``.

    Returns:
        Configured ``logging.Logger`` instance.
    """

    if log_file is None:
        log_file = filename

    logger = logging.getLogger(name)
    logger.setLevel(level)

    formatter = logging.Formatter(_DEFAULT_FMT, datefmt=_DEFAULT_DATEFMT)

    # ------------------------------------------------------------------
    # Prevent duplicate handlers but allow adding a file handler later if
    # one wasn't configured initially.  This mirrors typical ``logging``
    # usage where you might first create a console logger and later attach a
    # file.
    # ------------------------------------------------------------------
    if getattr(logger, "_configured", False):
        if log_file:
            out_dir = _ensure_outputs_dir()
            fh_path = out_dir / log_file
            if not any(
                isinstance(h, logging.FileHandler) and Path(h.baseFilename) == fh_path
                for h in logger.handlers
            ):
                fh = logging.FileHandler(fh_path, encoding="utf-8")
                fh.setLevel(level)
                fh.setFormatter(formatter)
                fh.addFilter(_RUN_ID_FILTER)
                logger.addHandler(fh)
        return logger

    if use_console:
        sh = logging.StreamHandler(stream=sys.stderr)
        sh.setLevel(level)
        sh.setFormatter(formatter)
        sh.addFilter(_RUN_ID_FILTER)
        logger.addHandler(sh)

    if log_file:
        out_dir = _ensure_outputs_dir()
        fh_path = out_dir / log_file
        fh = logging.FileHandler(fh_path, encoding="utf-8")
        fh.setLevel(level)
        fh.setFormatter(formatter)
        fh.addFilter(_RUN_ID_FILTER)
        logger.addHandler(fh)

    logger.addFilter(_RUN_ID_FILTER)
    logger._configured = True  # type: ignore[attr-defined]
    return logger


def get_logger(name: str) -> logging.Logger:
    """Get logger for backward compatibility.

    Only configures console output if no filename provided.
    For file output, call setup_logging(name, 'xxx.log') first.

    Args:
        name: Logger name

    Returns:
        Logger instance
    """
    return setup_logging(name, filename=None)


class StrategyLogger:
    """
    Small wrapper for backtest strategies: can use logging or fallback to print.
    """

    logger: logging.Logger | None

    def __init__(
        self,
        use_logging: bool = True,
        logger_name: str = "strategy",
        level: int | None = None,
    ):
        self.use_logging = use_logging
        if use_logging:
            # Ensure at least console output; let upper layer decide file output
            self.logger = setup_logging(
                logger_name, level=level if level is not None else logging.INFO
            )
        else:
            self.logger = None

    def log(self, txt: str, dt=None) -> None:
        if self.use_logging and self.logger:
            if dt is not None:
                self.logger.info(f"{dt} - {txt}")
            else:
                self.logger.info(txt)
        else:
            prefix = f"{dt} - " if dt is not None else ""
            print(prefix + txt)

    # ------------------------------------------------------------------
    # Convenience wrappers that mirror ``logging.Logger``'s API.  When
    # ``use_logging`` is ``False`` they fall back to printing to stdout/stderr
    # to keep the tests and simple scripts working without a logging setup.
    # ------------------------------------------------------------------
    def info(self, msg: str) -> None:
        if self.use_logging and self.logger:
            self.logger.info(msg)
        else:
            print(msg)

    def warning(self, msg: str) -> None:
        if self.use_logging and self.logger:
            self.logger.warning(msg)
        else:
            print(f"WARNING: {msg}")

    def error(self, msg: str) -> None:
        if self.use_logging and self.logger:
            self.logger.error(msg)
        else:
            print(f"ERROR: {msg}", file=sys.stderr)
