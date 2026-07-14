"""AI Stock Picker CLI — LLM-driven stock selection from quantitative candidate pools.

Supports:
  - US: Gemini-based quarterly selection from S&P 500 pre-screened candidates
  - A-share: DeepSeek daily selection from 同花顺 hot-sector candidates
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]
SCRIPTS_DIR = PROJECT_ROOT / "scripts"


def create_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="aipick",
        description="AI Stock Picker — LLM-driven stock selection from quantitative candidate pools",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
examples:
  aipick us ai-pick              # US: Gemini quarterly selection (S&P 500)
  aipick us backtest             # US: backtest AI picks vs benchmark

  aipick cn pick --date 20260715 # A-share: DeepSeek daily picks from 同花顺 hot pool
  aipick cn report --date 20260715 --dry-run  # A-share: generate Feishu report
  aipick cn pipeline --push      # A-share: full pipeline + push to Feishu
  aipick cn backtest --lookback 30  # A-share: backtest via portfolio-backtester
        """,
    )
    parser.add_argument("--version", action="version", version="%(prog)s 0.1.0")

    sub = parser.add_subparsers(dest="market", help="Market", metavar="MARKET")
    parser._subparsers_action = sub  # type: ignore[attr-defined]

    # --- US market (Gemini + S&P 500) ---
    us = sub.add_parser("us", help="US market (Gemini + S&P 500)")
    us_sub = us.add_subparsers(dest="us_cmd", metavar="CMD")
    us_sub.add_parser("ai-pick", help="Run Gemini quarterly AI stock selection")
    us_sub.add_parser("backtest", help="Run US AI pick backtest")

    # --- A-share market (DeepSeek + 同花顺) ---
    cn = sub.add_parser("cn", help="A-share market (DeepSeek + 同花顺 hot sectors)")
    cn_sub = cn.add_subparsers(dest="cn_cmd", metavar="CMD")

    cn_pick = cn_sub.add_parser("pick", help="Run DeepSeek daily picks")
    cn_pick.add_argument("--date", help="Trade date YYYYMMDD (default: today)")
    cn_pick.add_argument("--top-n", type=int, default=10)
    cn_pick.add_argument("--model", default=None, help="DeepSeek model")

    cn_report = cn_sub.add_parser("report", help="Generate Feishu report card")
    cn_report.add_argument("--date", help="Trade date YYYYMMDD")
    cn_report.add_argument("--top-n", type=int, default=10)
    cn_report.add_argument("--dry-run", action="store_true", default=True)
    cn_report.add_argument("--push", action="store_true")

    cn_pipe = cn_sub.add_parser(
        "pipeline", help="Full pipeline: candidates → picks → report"
    )
    cn_pipe.add_argument("--date", help="Trade date YYYYMMDD")
    cn_pipe.add_argument("--top-n", type=int, default=10)
    cn_pipe.add_argument("--dry-run", action="store_true", default=True)
    cn_pipe.add_argument("--push", action="store_true")

    cn_bt = cn_sub.add_parser("backtest", help="Run portfolio-backtester backtest")
    cn_bt.add_argument("--lookback", type=int, default=30)
    cn_bt.add_argument("--start", help="Start date YYYYMMDD")
    cn_bt.add_argument("--end", help="End date YYYYMMDD")
    cn_bt.add_argument("--top-n", type=int, default=10)

    return parser


def main() -> int:
    parser = create_parser()
    args = parser.parse_args()

    if not args.market:
        parser.print_help()
        return 0

    # US market
    if args.market == "us":
        if args.us_cmd == "ai-pick":
            return _run_module("stock_analysis.app.commands.ai_pick", "run_ai_pick")
        elif args.us_cmd == "backtest":
            return _run_module("stock_analysis.app.commands.backtest", "run_backtest")
        else:
            print("Usage: aipick us {ai-pick,backtest}", file=sys.stderr)
            return 1

    # A-share market
    if args.market == "cn":
        return _run_cn_script(args)

    return 0


def _run_module(module_name: str, func_name: str, **kwargs: object) -> int:
    """Lazily import and call a function from a module."""
    import importlib

    try:
        mod = importlib.import_module(module_name)
        func = getattr(mod, func_name)
        result = func(**kwargs)
        return int(result) if isinstance(result, int) else 0
    except ImportError as e:
        print(f"Error: cannot import {module_name}: {e}", file=sys.stderr)
        return 1


def _run_cn_script(args: argparse.Namespace) -> int:
    """Run A-share scripts from hot-sector-screener."""
    import subprocess

    script_map = {
        "pick": "deepseek_pick.py",
        "report": "feishu_report.py",
        "pipeline": "feishu_report.py",
        "backtest": "backtest_deepseek.py",
    }

    script = script_map.get(args.cn_cmd)
    if not script:
        print(f"Unknown cn command: {args.cn_cmd}", file=sys.stderr)
        return 1

    # Build CLI args for the script
    script_args = [sys.executable, str(SCRIPTS_DIR / script)]
    if hasattr(args, "date") and args.date:
        script_args.extend(["--date", args.date])
    if hasattr(args, "top_n") and args.top_n:
        script_args.extend(["--top-n", str(args.top_n)])
    if hasattr(args, "model") and args.model:
        script_args.extend(["--model", args.model])
    if hasattr(args, "lookback") and args.lookback:
        script_args.extend(["--lookback", str(args.lookback)])
    if hasattr(args, "start") and args.start:
        script_args.extend(["--start", args.start])
    if hasattr(args, "end") and args.end:
        script_args.extend(["--end", args.end])

    # Special flags
    if args.cn_cmd == "report" and not getattr(args, "push", False):
        script_args.append("--dry-run")
    if args.cn_cmd == "report" and getattr(args, "push", False):
        script_args.append("--push")
    if args.cn_cmd == "pipeline":
        script_args.append("--pipeline")
        if getattr(args, "push", False):
            script_args.append("--push")

    if args.cn_cmd == "backtest":
        script_args.extend(["--phase", "backtest"])

    result = subprocess.run(script_args, cwd=str(PROJECT_ROOT))
    return result.returncode


def app() -> None:
    sys.exit(main())


if __name__ == "__main__":
    app()
