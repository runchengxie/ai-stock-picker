"""Provider-neutral ``aipick`` command-line interface."""

from __future__ import annotations

import argparse
import json
import math
import sys
from collections.abc import Sequence
from hashlib import sha256
from pathlib import Path
from typing import cast

from . import __version__
from .contracts import Market, ResponseLanguage, Style
from .csv_migration import migrate_csv
from .providers import ProviderError, ProviderKind
from .selection import build_selection_plan, run_selection
from .storage import write_selection
from .time_utils import parse_date, parse_timestamp


def create_parser() -> argparse.ArgumentParser:
    """Create the complete CLI parser."""

    parser = argparse.ArgumentParser(
        prog="aipick",
        description=(
            "Provider-neutral reranking of a versioned stock candidate manifest"
        ),
    )
    parser.add_argument(
        "--version", action="version", version=f"%(prog)s {__version__}"
    )
    commands = parser.add_subparsers(dest="command", metavar="COMMAND")
    _add_pick_parser(commands)
    _add_migrate_parser(commands)
    return parser


def _add_pick_parser(
    commands: argparse._SubParsersAction[argparse.ArgumentParser],
) -> None:
    pick = commands.add_parser("pick", help="Rerank a candidate manifest")
    pick.add_argument("--candidates", required=True, help="Versioned candidate JSON")
    pick.add_argument(
        "--output",
        help="Destination selection JSON; required unless --dry-run is used",
    )
    pick.add_argument("--as-of", required=True, help="Selection signal date")
    pick.add_argument("--top-n", type=int, required=True)
    pick.add_argument(
        "--style", choices=("momentum", "quality", "growth"), required=True
    )
    pick.add_argument(
        "--response-language", choices=("zh-CN", "en"), required=True
    )
    pick.add_argument(
        "--provider",
        choices=("deepseek", "gemini", "openai-compatible"),
        required=True,
    )
    pick.add_argument("--model", help="Provider model name")
    pick.add_argument(
        "--base-url", help="Full HTTPS chat-completions endpoint for custom provider"
    )
    pick.add_argument(
        "--api-key-env", help="API-key environment variable for custom provider"
    )
    pick.add_argument("--temperature", type=float, default=0.2)
    pick.add_argument("--timeout", type=float, default=120.0)
    pick.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate input and build the prompt without calling a provider",
    )


def _add_migrate_parser(
    commands: argparse._SubParsersAction[argparse.ArgumentParser],
) -> None:
    migrate = commands.add_parser(
        "migrate-csv", help="Convert legacy CSV to a versioned candidate manifest"
    )
    migrate.add_argument("--input", required=True)
    migrate.add_argument("--output", required=True)
    migrate.add_argument("--market", choices=("CN", "US"), required=True)
    migrate.add_argument("--observation-date", required=True)
    migrate.add_argument("--generated-at", required=True)
    migrate.add_argument("--data-cutoff", required=True)


def main(argv: Sequence[str] | None = None) -> int:
    """Run the CLI and return a process exit code."""

    parser = create_parser()
    args = parser.parse_args(argv)
    if args.command is None:
        parser.print_help()
        return 0
    try:
        if args.command == "migrate-csv":
            output = migrate_csv(
                args.input,
                args.output,
                market=cast(Market, args.market),
                observation_date=parse_date(args.observation_date),
                generated_at=parse_timestamp(args.generated_at, "generated_at"),
                data_cutoff=parse_date(args.data_cutoff),
            )
            print(f"wrote versioned candidate manifest to {output}")
            return 0
        return _run_pick(args)
    except (OSError, ProviderError, ValueError) as exc:
        print(f"aipick: error: {exc}", file=sys.stderr)
        return 2


def _run_pick(args: argparse.Namespace) -> int:
    if not math.isfinite(args.timeout) or args.timeout <= 0:
        raise ValueError("timeout must be a positive finite number")
    if not math.isfinite(args.temperature) or not 0.0 <= args.temperature <= 2.0:
        raise ValueError("temperature must be finite in [0, 2]")
    if not args.dry_run and args.output is None:
        raise ValueError("--output is required unless --dry-run is used")
    if args.output is not None and not args.dry_run:
        output_path = Path(args.output).expanduser().resolve()
        if output_path.exists() or output_path.is_symlink():
            raise FileExistsError(
                f"output already exists; reuse it or choose a new path: {output_path}"
            )
    plan = build_selection_plan(
        candidates_path=args.candidates,
        as_of=parse_date(args.as_of),
        top_n=args.top_n,
        style=cast(Style, args.style),
        response_language=cast(ResponseLanguage, args.response_language),
        provider=cast(ProviderKind, args.provider),
        model=args.model,
        base_url=args.base_url,
        api_key_env=args.api_key_env,
        temperature=args.temperature,
    )
    if args.dry_run:
        print(
            json.dumps(
                {
                    "dry_run": True,
                    "market": plan.universe.market,
                    "provider": plan.provider.name,
                    "provider_api": plan.provider.provider_api,
                    "model": plan.provider.model,
                    "style": plan.style,
                    "response_language": plan.response_language,
                    "as_of": plan.universe.selection_as_of.isoformat(),
                    "candidate_observation_date": (
                        plan.universe.observation_date.isoformat()
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
    artifact = run_selection(plan, timeout=args.timeout)
    output = write_selection(artifact, cast(str, args.output))
    print(f"wrote {len(artifact.picks)} validated picks to {output}")
    print(f"temporal_status={artifact.temporal_status}")
    print(
        f"eligible_as_oos_evidence={str(artifact.eligible_as_oos_evidence).lower()}"
    )
    return 0


def app() -> None:
    """Console-script entry point."""

    raise SystemExit(main())


if __name__ == "__main__":
    app()
