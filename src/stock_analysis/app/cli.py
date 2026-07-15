"""The deliberately small, wheel-safe ``aipick`` command surface."""

from __future__ import annotations

import argparse
import json
import math
import sys
from collections.abc import Sequence
from hashlib import sha256
from pathlib import Path
from typing import cast

from stock_analysis import __version__
from stock_analysis.ai_lab.candidates import parse_date
from stock_analysis.ai_lab.contracts import Market, SelectionArtifact, Style
from stock_analysis.ai_lab.credentials import CredentialFileError
from stock_analysis.ai_lab.providers import ProviderError
from stock_analysis.ai_lab.selection import (
    build_selection_plan,
    run_selection,
    validate_selection_artifact,
    write_selection,
)


def create_parser() -> argparse.ArgumentParser:
    """Create the complete CLI parser."""

    parser = argparse.ArgumentParser(
        prog="aipick",
        description=(
            "Strict LLM reranking of an explicit, precomputed candidate universe"
        ),
    )
    parser.add_argument(
        "--version", action="version", version=f"%(prog)s {__version__}"
    )
    markets = parser.add_subparsers(dest="market")
    _add_market_parser(markets, "us")
    _add_market_parser(markets, "cn")
    return parser


def _add_market_parser(
    markets: argparse._SubParsersAction[argparse.ArgumentParser], market: str
) -> None:
    label = "US / Gemini" if market == "us" else "A-share / DeepSeek"
    market_parser = markets.add_parser(market, help=label)
    commands = market_parser.add_subparsers(dest="command", metavar="COMMAND")
    pick = commands.add_parser("pick", help="Rerank a candidate snapshot")
    pick.add_argument(
        "--candidates",
        required=True,
        help="Candidate JSON manifest or exploratory legacy CSV",
    )
    pick.add_argument(
        "--output",
        help="Destination selection JSON; required unless --dry-run is used",
    )
    pick.add_argument(
        "--as-of",
        required=True,
        help="Selection signal date in YYYY-MM-DD or YYYYMMDD format",
    )
    pick.add_argument("--top-n", type=int, required=True)
    styles = ("quality", "growth") if market == "us" else ("momentum", "quality")
    pick.add_argument("--style", choices=styles)
    pick.add_argument("--model", help="Provider model name")
    pick.add_argument("--timeout", type=float, default=120.0)
    pick.add_argument(
        "--credential-file",
        help="Owner credential file with exact mode 0600 (optional env alternative)",
    )
    pick.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate input and build the prompt without calling a provider",
    )
    validate = commands.add_parser(
        "validate",
        help=(
            "Revalidate an owner selection against candidates; response hash is "
            "format-only because the raw provider response is not persisted"
        ),
    )
    validate.add_argument("--selection", required=True, help="Selection JSON artifact")
    validate.add_argument(
        "--candidates",
        required=True,
        help="Canonical candidate snapshot used to revalidate artifact lineage",
    )


def main(argv: Sequence[str] | None = None) -> int:
    """Run the CLI and return a process exit code."""

    parser = create_parser()
    args = parser.parse_args(argv)
    if args.market is None:
        parser.print_help()
        return 0
    if args.command not in {"pick", "validate"}:
        parser.parse_args([args.market, "--help"])
        return 0

    market = cast(Market, args.market.upper())
    try:
        if args.command == "validate":
            return _validate_selection_command(args, market)

        style = cast(Style | None, args.style)
        if not math.isfinite(args.timeout) or args.timeout <= 0:
            raise ValueError("timeout must be a positive finite number")
        plan = build_selection_plan(
            market=market,
            candidates_path=args.candidates,
            as_of=parse_date(args.as_of),
            top_n=args.top_n,
            style=style,
            model=args.model,
        )
        if args.dry_run:
            print(
                json.dumps(
                    {
                        "dry_run": True,
                        "market": plan.market,
                        "provider": plan.provider,
                        "model": plan.model,
                        "style": plan.style,
                        "as_of": plan.universe.selection_as_of.isoformat(),
                        "candidate_observation_date": (
                            plan.universe.observation_date.isoformat()
                            if plan.universe.observation_date is not None
                            else None
                        ),
                        "input_count": len(plan.universe.candidates),
                        "requested_top_n": plan.top_n,
                        "input_sha256": plan.universe.input_sha256,
                        "prompt_sha256": sha256(plan.prompt.encode()).hexdigest(),
                        "point_in_time_assurance": (
                            plan.universe.point_in_time_assurance
                        ),
                        "eligible_as_oos_evidence": False,
                        "output": str(args.output) if args.output is not None else None,
                    },
                    ensure_ascii=False,
                    indent=2,
                )
            )
            return 0
        if args.output is None:
            raise ValueError("--output is required unless --dry-run is used")
        output_path = Path(args.output).expanduser().resolve()
        if output_path.exists() or output_path.is_symlink():
            raise FileExistsError(
                "selection output already exists; reuse it or choose a new path: "
                f"{output_path}"
            )
        artifact = run_selection(
            plan,
            timeout=args.timeout,
            credential_file=args.credential_file,
        )
        output = write_selection(artifact, output_path)
        print(f"wrote {len(artifact.picks)} validated picks to {output}")
        print(f"temporal_status={artifact.temporal_status}")
        print(
            f"eligible_as_oos_evidence={str(artifact.eligible_as_oos_evidence).lower()}"
        )
        return 0
    except (CredentialFileError, OSError, ProviderError, ValueError) as exc:
        print(f"aipick: error: {exc}", file=sys.stderr)
        return 2


def _validate_selection_command(args: argparse.Namespace, market: Market) -> int:
    selection_path = Path(args.selection).expanduser()
    artifact = SelectionArtifact.model_validate_json(
        selection_path.read_text(encoding="utf-8"),
        strict=True,
    )
    if artifact.market != market:
        raise ValueError(
            f"selection market {artifact.market} does not match CLI market {market}"
        )
    validation = validate_selection_artifact(artifact, args.candidates)
    print(
        json.dumps(
            {
                "valid": True,
                "market": artifact.market,
                "prompt_version": artifact.prompt_version,
                "validation_profile": validation.validation_profile,
                "prompt_hash_revalidated": validation.prompt_hash_revalidated,
                "commentary_policy_revalidated": (
                    validation.commentary_policy_revalidated
                ),
                "selection_as_of": artifact.selection_as_of.isoformat(),
                "picks": len(artifact.picks),
                "response_sha256_verification": "format_only_raw_response_unavailable",
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


def app() -> None:
    """Console-script entry point."""

    raise SystemExit(main())


if __name__ == "__main__":
    app()
