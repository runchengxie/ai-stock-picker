from __future__ import annotations

"""
Export and validation helpers for per-period JSON and Excel workbooks.

Provides utilities to:
- Export from Excel (multi-sheet) to per-date JSON files
- Export from per-date JSON files to Excel (multi-sheet)
- Validate consistency between Excel and JSON exports
"""

from pathlib import Path
from typing import Any, Literal

import pandas as pd

from ..utils.paths import AI_PORTFOLIO_FILE, OUTPUTS_DIR, QUANT_PORTFOLIO_FILE
from ..logging import get_logger


LOGGER = get_logger(__name__)


def _emit(level: str, message: str, *, asof: Any | None = None, **context: Any) -> None:
    base_context: dict[str, Any] = {"component": "exports", "asof": asof}
    base_context.update({k: v for k, v in context.items() if v is not None})
    context_parts = [f"{key}={value}" for key, value in base_context.items() if value is not None]
    if context_parts:
        message = f"{message} [{' '.join(context_parts)}]"
    getattr(LOGGER, level)(message)


def _info(message: str, *, asof: Any | None = None, **context: Any) -> None:
    _emit("info", message, asof=asof, **context)


def _warning(message: str, *, asof: Any | None = None, **context: Any) -> None:
    _emit("warning", message, asof=asof, **context)


def _error(message: str, *, asof: Any | None = None, **context: Any) -> None:
    _emit("error", message, asof=asof, **context)


def _prelim_json_dir(root: Path | None = None) -> Path:
    base = root or OUTPUTS_DIR
    return (base / "preliminary").resolve()


def _ai_json_dir(root: Path | None = None) -> Path:
    base = root or OUTPUTS_DIR
    return (base / "ai_pick").resolve()


def export_excel_to_json(
    source: Literal["preliminary", "ai"],
    excel_path: Path | None = None,
    json_root: Path | None = None,
    overwrite: bool = True,
) -> int:
    """Export all sheets from Excel to per-date JSON files.

    Returns the number of JSON files written.
    """
    if source == "preliminary":
        excel = Path(excel_path) if excel_path else QUANT_PORTFOLIO_FILE
        out_root = _prelim_json_dir(json_root)
    else:
        excel = Path(excel_path) if excel_path else AI_PORTFOLIO_FILE
        out_root = _ai_json_dir(json_root)

    if not excel.exists():
        _error("[export] Excel not found", source=source, path=excel)
        return 0

    xls = pd.ExcelFile(excel)
    written = 0
    for sheet in xls.sheet_names:
        try:
            trade_date = pd.to_datetime(sheet).date()
        except Exception:
            _warning(
                "[export] Skip non-date sheet",
                source=source,
                sheet=sheet,
            )
            continue

        df = pd.read_excel(xls, sheet_name=sheet)
        year_dir = out_root / f"{trade_date.year}"
        year_dir.mkdir(parents=True, exist_ok=True)
        out_path = year_dir / f"{trade_date}.json"
        if out_path.exists() and not overwrite:
            continue

        if source == "preliminary":
            rows = []
            df_iter = df.reset_index(drop=True)
            for i, row in df_iter.iterrows():
                rows.append(
                    {
                        "ticker": str(row.get("Ticker", "")).upper().strip(),
                        "rank": int(i + 1),
                        "avg_factor_score": float(row.get("avg_factor_score", 0.0)),
                        "num_reports": int(row.get("num_reports", 0)),
                    }
                )
            payload = {
                "schema_version": 1,
                "source": "preliminary",
                "trade_date": str(trade_date),
                "data_cutoff_date": str(
                    (pd.Timestamp(trade_date) - pd.offsets.BDay(2)).date()
                ),
                "universe": "sp500",
                "method": "preliminary_v1",
                "params": {
                    "rolling_years": 5,
                    "min_reports": 5,
                    "top_n": int(len(df_iter)),
                    "rank_metric": "avg_factor_score",
                },
                "rows": rows,
            }
        else:  # ai
            # Expect columns: ticker, company_name, confidence_score, reasoning
            picks = []
            df_iter = df.reset_index(drop=True)
            for i, row in df_iter.iterrows():
                score = int(row.get("confidence_score", 0))
                picks.append(
                    {
                        "ticker": str(row.get("ticker", "")).upper().strip(),
                        "rank": int(i + 1),
                        "confidence": round(score / 10.0, 2),
                        "rationale": str(row.get("reasoning", "")),
                    }
                )
            payload = {
                "schema_version": 1,
                "source": "ai_pick",
                "trade_date": str(trade_date),
                "data_cutoff_date": str(
                    (pd.Timestamp(trade_date) - pd.offsets.BDay(2)).date()
                ),
                "universe": "sp500",
                "model": "gemini-2.5-pro",
                "prompt_version": "v1",
                "params": {"top_n": int(len(df_iter))},
                "picks": picks,
            }

        import json as _json

        out_path.write_text(
            _json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        written += 1

    _info(
        f"[export] Wrote {written} JSON files under {out_root}",
        source=source,
    )
    return written


def export_json_to_excel(
    source: Literal["preliminary", "ai"],
    json_root: Path | None = None,
    excel_out: Path | None = None,
) -> int:
    """Export per-date JSON files to a single Excel workbook (sheets per date).

    Returns the number of sheets written.
    """
    if source == "preliminary":
        root = _prelim_json_dir(json_root)
        excel = Path(excel_out) if excel_out else QUANT_PORTFOLIO_FILE
    else:
        root = _ai_json_dir(json_root)
        excel = Path(excel_out) if excel_out else AI_PORTFOLIO_FILE

    if not root.exists():
        _error("[export] JSON root not found", source=source, path=root)
        return 0

    files = sorted(root.rglob("*.json"))
    if not files:
        _warning("[export] No JSON files found", source=source, path=root)
        return 0

    written = 0
    with pd.ExcelWriter(excel) as writer:
        for fp in files:
            try:
                data = pd.read_json(fp)
            except ValueError:
                # read_json on an object file returns Series; use raw json
                import json as _json

                data = _json.loads(fp.read_text(encoding="utf-8"))

            if isinstance(data, pd.DataFrame):
                payload = data.to_dict(orient="records")[0]  # should not happen
            else:
                payload = data

            trade_date = payload.get("trade_date")
            if not trade_date:
                continue

            if source == "preliminary":
                rows = payload.get("rows", [])
                df = pd.DataFrame(rows)
                # Normalize column names
                if "ticker" in df.columns:
                    df.rename(columns={"ticker": "Ticker"}, inplace=True)
            else:
                picks = payload.get("picks", [])
                # Map back to Excel schema: ticker, confidence_score, reasoning
                for p in picks:
                    if "confidence" in p and "confidence_score" not in p:
                        try:
                            p["confidence_score"] = int(
                                round(float(p["confidence"]) * 10)
                            )
                        except Exception:
                            p["confidence_score"] = 0
                    if "rationale" in p and "reasoning" not in p:
                        p["reasoning"] = p.get("rationale", "")
                df = pd.DataFrame(picks)

            df.to_excel(writer, sheet_name=str(trade_date), index=False)
            written += 1

    _info(
        f"[export] Wrote {written} sheets to {excel}",
        source=source,
        path=excel,
    )
    return written


def validate_exports(
    source: Literal["preliminary", "ai"],
    excel_path: Path | None = None,
    json_root: Path | None = None,
) -> bool:
    """Validate tickers between Excel sheets and JSON files.

    Returns True if all matched; otherwise False.
    """
    if source == "preliminary":
        excel = Path(excel_path) if excel_path else QUANT_PORTFOLIO_FILE
        root = _prelim_json_dir(json_root)
    else:
        excel = Path(excel_path) if excel_path else AI_PORTFOLIO_FILE
        root = _ai_json_dir(json_root)

    if not excel.exists():
        _error("[validate] Excel not found", source=source, path=excel)
        return False
    if not root.exists():
        _error("[validate] JSON root not found", source=source, path=root)
        return False

    xls = pd.ExcelFile(excel)
    ok = True
    for sheet in xls.sheet_names:
        try:
            trade_date = pd.to_datetime(sheet).date()
        except Exception:
            continue
        df = pd.read_excel(xls, sheet_name=sheet)
        year_dir = root / f"{trade_date.year}"
        fp = year_dir / f"{trade_date}.json"
        if not fp.exists():
            _error(
                "[validate] Missing JSON file",
                source=source,
                asof=trade_date,
                path=fp,
            )
            ok = False
            continue
        payload = pd.read_json(fp)
        if isinstance(payload, pd.DataFrame):
            payload = payload.to_dict(orient="records")[0]

        if source == "preliminary":
            json_tickers = [
                str(r.get("ticker", "")).upper().strip()
                for r in payload.get("rows", [])
            ]
            excel_tickers = [
                str(x).upper().strip()
                for x in df.get("Ticker", pd.Series(dtype=str)).tolist()
            ]
        else:
            json_tickers = [
                str(r.get("ticker", "")).upper().strip()
                for r in payload.get("picks", [])
            ]
            col = (
                "ticker"
                if "ticker" in df.columns
                else ("Ticker" if "Ticker" in df.columns else None)
            )
            excel_tickers = [
                str(x).upper().strip() for x in (df[col].tolist() if col else [])
            ]

        if set(json_tickers) != set(excel_tickers) or len(json_tickers) != len(
            excel_tickers
        ):
            ok = False
            only_in_json = sorted(set(json_tickers) - set(excel_tickers))
            only_in_excel = sorted(set(excel_tickers) - set(json_tickers))
            _error(
                (
                    f"[validate] MISMATCH json={len(json_tickers)} "
                    f"excel={len(excel_tickers)} only_in_json={only_in_json} "
                    f"only_in_excel={only_in_excel}"
                ),
                source=source,
                asof=trade_date,
            )

    if ok:
        _info("[validate] Excel and JSON exports are consistent.", source=source)
    return ok
