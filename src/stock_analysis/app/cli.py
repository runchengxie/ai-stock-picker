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
from stock_analysis.ai_lab.evidence import (
    load_stability_trial,
    validate_selection_evidence,
    write_rejected_selection_evidence,
    write_selection_evidence,
    write_stability_campaign,
)
from stock_analysis.ai_lab.providers import ProviderError
from stock_analysis.ai_lab.selection import (
    SelectionPlan,
    build_selection_plan,
    call_plan_provider_exchange,
    create_selection,
    validate_selection_artifact,
    write_selection,
    write_stability_selection,
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
        "--evidence-dir",
        help="Append-only evidence directory; defaults to <output>.evidence",
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
    validate.add_argument(
        "--evidence-dir",
        help="Also verify the byte-exact append-only evidence directory",
    )
    evidence = commands.add_parser(
        "validate-evidence", help="Validate an append-only provider evidence directory"
    )
    evidence.add_argument("--evidence-dir", required=True)
    stability = commands.add_parser(
        "stability-plan",
        help="Freeze the preregistered five-arm legacy-prompt stability campaign",
    )
    stability.add_argument("--candidates", required=True)
    stability.add_argument("--as-of", required=True)
    stability.add_argument("--top-n", type=int, required=True)
    stability.add_argument("--style", choices=styles)
    stability.add_argument("--model")
    stability.add_argument("--campaign-id", required=True)
    stability.add_argument("--output-dir", required=True)
    trial = commands.add_parser(
        "trial", help="Run one previously frozen stability trial"
    )
    trial.add_argument("--plan", required=True, help="Frozen trial.json path")
    trial.add_argument("--output", required=True)
    trial.add_argument("--evidence-dir")
    trial.add_argument("--timeout", type=float, default=120.0)
    trial.add_argument("--credential-file")


def main(argv: Sequence[str] | None = None) -> int:
    """Run the CLI and return a process exit code."""

    parser = create_parser()
    args = parser.parse_args(argv)
    if args.market is None:
        parser.print_help()
        return 0
    if args.command not in {
        "pick",
        "stability-plan",
        "trial",
        "validate",
        "validate-evidence",
    }:
        parser.parse_args([args.market, "--help"])
        return 0

    market = cast(Market, args.market.upper())
    try:
        if args.command == "validate":
            return _validate_selection_command(args, market)
        if args.command == "validate-evidence":
            manifest = validate_selection_evidence(args.evidence_dir)
            print(json.dumps(manifest, ensure_ascii=False, sort_keys=True))
            return 0
        if args.command == "trial":
            plan = load_stability_trial(args.plan)
            if plan.market != market:
                raise ValueError("trial market does not match CLI market")
            return _execute_live_selection(args, plan)

        style = cast(Style | None, args.style)
        if args.command == "pick" and (
            not math.isfinite(args.timeout) or args.timeout <= 0
        ):
            raise ValueError("timeout must be a positive finite number")
        plan = build_selection_plan(
            market=market,
            candidates_path=args.candidates,
            as_of=parse_date(args.as_of),
            top_n=args.top_n,
            style=style,
            model=args.model,
        )
        if args.command == "stability-plan":
            output = write_stability_campaign(
                plan,
                args.output_dir,
                campaign_id=args.campaign_id,
            )
            print(f"wrote network-free stability plan to {output}")
            print("api_calls=0")
            return 0
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
                        "evidence_dir": (
                            str(args.evidence_dir)
                            if args.evidence_dir is not None
                            else None
                        ),
                    },
                    ensure_ascii=False,
                    indent=2,
                )
            )
            return 0
        return _execute_live_selection(args, plan)
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
    response_verification = "format_only_raw_response_unavailable"
    if args.evidence_dir is not None:
        evidence_root = Path(args.evidence_dir).expanduser().resolve()
        validate_selection_evidence(evidence_root)
        if (
            evidence_root / "selection.json"
        ).read_bytes() != selection_path.read_bytes():
            raise ValueError("evidence selection differs from the supplied selection")
        response_verification = "byte_exact_evidence"
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
                "response_sha256_verification": response_verification,
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


def _execute_live_selection(args: argparse.Namespace, plan: SelectionPlan) -> int:
    if not math.isfinite(args.timeout) or args.timeout <= 0:
        raise ValueError("timeout must be a positive finite number")
    if args.output is None:
        raise ValueError("--output is required unless --dry-run is used")
    output_path = Path(args.output).expanduser().resolve()
    evidence_path = (
        Path(args.evidence_dir).expanduser().resolve()
        if args.evidence_dir is not None
        else Path(f"{output_path}.evidence")
    )
    if output_path.exists() or output_path.is_symlink():
        raise FileExistsError(
            "selection output already exists; reuse it or choose a new path: "
            f"{output_path}"
        )
    if evidence_path.exists() or evidence_path.is_symlink():
        raise FileExistsError(
            "evidence directory already exists; reuse it or choose a new path: "
            f"{evidence_path}"
        )
    exchange = call_plan_provider_exchange(
        plan,
        timeout=args.timeout,
        credential_file=args.credential_file,
    )
    if exchange.response_text is None:
        write_rejected_selection_evidence(
            plan,
            exchange,
            evidence_path,
            rejection=exchange.extraction_error,
        )
        raise ProviderError("provider returned an invalid response schema")
    try:
        artifact = create_selection(plan, exchange.response_text)
    except ValueError:
        write_rejected_selection_evidence(plan, exchange, evidence_path)
        raise
    write_selection_evidence(plan, exchange, artifact, evidence_path)
    output = (
        write_selection(artifact, output_path)
        if plan.prompt_profile == "production_v4"
        else write_stability_selection(artifact, output_path)
    )
    print(f"wrote {len(artifact.picks)} validated picks to {output}")
    print(f"evidence_dir={evidence_path}")
    print(f"temporal_status={artifact.temporal_status}")
    print(f"eligible_as_oos_evidence={str(artifact.eligible_as_oos_evidence).lower()}")
    return 0


def app() -> None:
    """Console-script entry point."""

    raise SystemExit(main())


if __name__ == "__main__":
    app()
