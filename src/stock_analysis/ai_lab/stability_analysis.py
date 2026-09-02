"""Network-free analysis for frozen LLM stability campaigns."""

from __future__ import annotations

import json
from pathlib import Path
from statistics import fmean
from typing import cast

SUMMARY_SCHEMA_VERSION = "1.0.0"


def summarize_stability_results(
    campaign_dir: str | Path,
    results_dir: str | Path,
) -> dict[str, object]:
    """Summarize completed, ranking-only, rejected, and missing stability arms."""

    campaign_root = Path(campaign_dir).expanduser().resolve()
    results_root = Path(results_dir).expanduser().resolve()
    manifest = _read_object(campaign_root / "manifest.json", "campaign manifest")
    if manifest.get("artifact_type") != "ai_stability_campaign":
        raise ValueError("campaign manifest artifact_type is invalid")
    if manifest.get("status") != "planned":
        raise ValueError("campaign manifest status must be planned")
    campaign_id = manifest.get("campaign_id")
    if not isinstance(campaign_id, str) or not campaign_id:
        raise ValueError("campaign manifest campaign_id is invalid")
    variants = manifest.get("variants")
    if not isinstance(variants, list) or not variants:
        raise ValueError("campaign manifest variants are invalid")
    top_n = manifest.get("top_n")
    if isinstance(top_n, bool) or not isinstance(top_n, int) or top_n < 1:
        raise ValueError("campaign manifest top_n must be a positive integer")

    trial_ids = [_trial_id(variant) for variant in variants]
    if len(set(trial_ids)) != len(trial_ids):
        raise ValueError("campaign manifest contains duplicate trial ids")
    if "canonical" not in trial_ids:
        raise ValueError("campaign manifest must contain canonical trial")

    raw_arms = [
        _load_arm(
            results_root,
            trial_id,
            top_n=top_n,
            campaign_id=campaign_id,
        )
        for trial_id in trial_ids
    ]
    canonical = next(arm for arm in raw_arms if arm["trial_id"] == "canonical")
    canonical_ranking = canonical.get("ranking")
    if not _is_ranking(canonical_ranking):
        raise ValueError("canonical trial must have a usable ranking")
    canonical_symbols = cast(list[str], canonical_ranking)

    arms = [_with_comparison(arm, canonical_symbols) for arm in raw_arms]
    completed_trials = [
        cast(str, arm["trial_id"])
        for arm in arms
        if arm["status"] in {"complete", "ranking_only"}
    ]
    rejected_trials = [
        cast(str, arm["trial_id"])
        for arm in arms
        if arm["status"] == "rejected"
    ]
    missing_trials = [
        cast(str, arm["trial_id"])
        for arm in arms
        if arm["status"] == "missing"
    ]

    noncanonical = [
        arm
        for arm in arms
        if arm["trial_id"] != "canonical"
        and arm["status"] in {"complete", "ranking_only"}
    ]
    shuffle = [
        arm for arm in noncanonical if str(arm["trial_id"]).startswith("shuffle_")
    ]
    opaque = [arm for arm in noncanonical if str(arm["trial_id"]).startswith("opaque_")]

    return {
        "schema_version": SUMMARY_SCHEMA_VERSION,
        "artifact_type": "ai_stability_summary",
        "status": (
            "complete" if not rejected_trials and not missing_trials else "partial"
        ),
        "campaign_id": campaign_id,
        "reference_trial": "canonical",
        "expected_trials": trial_ids,
        "completed_trials": completed_trials,
        "rejected_trials": rejected_trials,
        "missing_trials": missing_trials,
        "canonical_ranking": canonical_symbols,
        "arms": arms,
        "aggregate": {
            "completed_noncanonical_arms": len(noncanonical),
            **_aggregate(noncanonical),
            "shuffle": {"completed_arms": len(shuffle), **_aggregate(shuffle)},
            "opaque": {"completed_arms": len(opaque), **_aggregate(opaque)},
        },
    }


def write_stability_summary(
    summary: dict[str, object], output_path: str | Path
) -> Path:
    """Write one deterministic derived summary and refuse to overwrite it."""

    destination = Path(output_path).expanduser().resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    try:
        with destination.open("x", encoding="utf-8") as handle:
            handle.write(payload)
    except FileExistsError as exc:
        raise FileExistsError(
            f"stability summary already exists: {destination}"
        ) from exc
    return destination


def render_stability_summary(summary: dict[str, object]) -> str:
    """Render the few metrics a human needs before opening the JSON artifact."""

    aggregate = summary.get("aggregate")
    if not isinstance(aggregate, dict):
        raise ValueError("stability summary aggregate is invalid")
    expected = summary.get("expected_trials")
    if not isinstance(expected, list) or "canonical" not in expected:
        raise ValueError("stability summary expected_trials is invalid")
    expected_noncanonical = len(expected) - 1
    completed = aggregate.get("completed_noncanonical_arms")
    if not isinstance(completed, int):
        raise ValueError("stability summary completed arm count is invalid")

    lines = [
        f"campaign={summary.get('campaign_id')}",
        f"status={summary.get('status')}",
        f"completed_noncanonical_arms={completed}/{expected_noncanonical}",
        "top1_agreement_vs_canonical="
        + _percent(aggregate.get("top1_agreement_rate_vs_canonical")),
        "exact_ranking_agreement_vs_canonical="
        + _percent(aggregate.get("exact_ranking_agreement_rate_vs_canonical")),
        "mean_top_n_jaccard_vs_canonical="
        + _decimal(aggregate.get("mean_top_n_jaccard_vs_canonical")),
        "mean_absolute_rank_shift_vs_canonical="
        + _decimal(aggregate.get("mean_absolute_rank_shift_vs_canonical")),
    ]
    rejected = summary.get("rejected_trials")
    missing = summary.get("missing_trials")
    if isinstance(rejected, list) and rejected:
        lines.append("rejected_trials=" + ",".join(cast(list[str], rejected)))
    if isinstance(missing, list) and missing:
        lines.append("missing_trials=" + ",".join(cast(list[str], missing)))
    return "\n".join(lines)


def _percent(value: object) -> str:
    if value is None:
        return "n/a"
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise ValueError("stability summary rate is invalid")
    return f"{float(value) * 100:.1f}%"


def _decimal(value: object) -> str:
    if value is None:
        return "n/a"
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise ValueError("stability summary metric is invalid")
    return f"{float(value):.3f}"


def _trial_id(raw_variant: object) -> str:
    if not isinstance(raw_variant, dict):
        raise ValueError("campaign variant must be an object")
    trial_id = raw_variant.get("trial_id")
    if not isinstance(trial_id, str) or not trial_id:
        raise ValueError("campaign variant trial_id is invalid")
    return trial_id


def _load_arm(
    results_root: Path,
    trial_id: str,
    *,
    top_n: int,
    campaign_id: str,
) -> dict[str, object]:
    selection_path = results_root / f"{trial_id}.json"
    evidence_root = results_root / f"{trial_id}.evidence"
    manifest_path = evidence_root / "manifest.json"
    if selection_path.is_file():
        return _load_complete_selection_arm(
            results_root,
            selection_path,
            evidence_root,
            trial_id=trial_id,
            top_n=top_n,
            campaign_id=campaign_id,
        )

    diagnostic_path = evidence_root / "ranking_diagnostic.json"
    if diagnostic_path.is_file():
        return _load_ranking_diagnostic_arm(
            results_root,
            diagnostic_path,
            manifest_path,
            trial_id=trial_id,
            top_n=top_n,
            campaign_id=campaign_id,
        )
    if manifest_path.is_file():
        return _load_evidence_only_arm(
            results_root,
            evidence_root,
            manifest_path,
            trial_id=trial_id,
            top_n=top_n,
            campaign_id=campaign_id,
        )
    return {
        "trial_id": trial_id,
        "status": "missing",
        "ranking_source": None,
        "ranking": None,
    }


def _load_complete_selection_arm(
    results_root: Path,
    selection_path: Path,
    evidence_root: Path,
    *,
    trial_id: str,
    top_n: int,
    campaign_id: str,
) -> dict[str, object]:
    ranking = _selection_ranking(selection_path)
    _require_top_n(ranking, top_n, selection_path)
    manifest_path = evidence_root / "manifest.json"
    mirrored_selection = evidence_root / "selection.json"
    if not manifest_path.is_file() or not mirrored_selection.is_file():
        raise ValueError(
            "complete selection requires matching evidence bundle: "
            f"{selection_path}"
        )
    evidence = _read_object(manifest_path, f"{trial_id} evidence manifest")
    if not _matches_evidence_identity(
        evidence,
        status="complete",
        campaign_id=campaign_id,
        trial_id=trial_id,
        top_n=top_n,
    ):
        raise ValueError(
            "complete selection requires matching evidence bundle: "
            f"{selection_path}"
        )
    if evidence.get("selection_path") != "selection.json":
        raise ValueError(
            "complete selection requires matching evidence bundle: "
            f"{selection_path}"
        )
    if mirrored_selection.read_bytes() != selection_path.read_bytes():
        raise ValueError(
            "complete selection requires matching evidence bundle: "
            f"{selection_path}"
        )
    return {
        "trial_id": trial_id,
        "status": "complete",
        "ranking_source": selection_path.relative_to(results_root).as_posix(),
        "ranking": ranking,
    }


def _load_ranking_diagnostic_arm(
    results_root: Path,
    diagnostic_path: Path,
    manifest_path: Path,
    *,
    trial_id: str,
    top_n: int,
    campaign_id: str,
) -> dict[str, object]:
    if not manifest_path.is_file():
        raise ValueError(
            "ranking diagnostic requires rejected evidence manifest: "
            f"{diagnostic_path}"
        )
    evidence = _read_object(manifest_path, f"{trial_id} evidence manifest")
    identity_matches = _matches_evidence_identity(
        evidence,
        status="rejected",
        campaign_id=campaign_id,
        trial_id=trial_id,
        top_n=top_n,
    )
    diagnostic_is_authorized = (
        evidence.get("ranking_contract") == "passed"
        and evidence.get("publication_contract") == "failed"
        and evidence.get("ranking_diagnostic_path") == "ranking_diagnostic.json"
    )
    if not identity_matches or not diagnostic_is_authorized:
        raise ValueError(
            "ranking diagnostic requires rejected evidence manifest: "
            f"{diagnostic_path}"
        )
    ranking = _diagnostic_ranking(diagnostic_path)
    _require_top_n(ranking, top_n, diagnostic_path)
    return {
        "trial_id": trial_id,
        "status": "ranking_only",
        "ranking_source": diagnostic_path.relative_to(results_root).as_posix(),
        "ranking": ranking,
    }


def _load_evidence_only_arm(
    results_root: Path,
    evidence_root: Path,
    manifest_path: Path,
    *,
    trial_id: str,
    top_n: int,
    campaign_id: str,
) -> dict[str, object]:
    evidence = _read_object(manifest_path, f"{trial_id} evidence manifest")
    evidence_selection = evidence_root / "selection.json"
    if _matches_evidence_identity(
        evidence,
        status="complete",
        campaign_id=campaign_id,
        trial_id=trial_id,
        top_n=top_n,
    ):
        return _load_complete_evidence_arm(
            results_root,
            evidence_selection,
            evidence,
            trial_id=trial_id,
            top_n=top_n,
        )
    if not _matches_evidence_identity(
        evidence,
        status="rejected",
        campaign_id=campaign_id,
        trial_id=trial_id,
        top_n=top_n,
    ):
        raise ValueError(
            f"{trial_id} evidence exists without selection or ranking diagnostic"
        )
    return {
        "trial_id": trial_id,
        "status": "rejected",
        "ranking_source": None,
        "ranking": None,
    }


def _load_complete_evidence_arm(
    results_root: Path,
    evidence_selection: Path,
    evidence: dict[str, object],
    *,
    trial_id: str,
    top_n: int,
) -> dict[str, object]:
    if (
        evidence.get("selection_path") != "selection.json"
        or not evidence_selection.is_file()
    ):
        raise ValueError(f"{trial_id} complete evidence is missing selection.json")
    ranking = _selection_ranking(evidence_selection)
    _require_top_n(ranking, top_n, evidence_selection)
    return {
        "trial_id": trial_id,
        "status": "complete",
        "ranking_source": evidence_selection.relative_to(results_root).as_posix(),
        "ranking": ranking,
    }


def _matches_evidence_identity(
    evidence: dict[str, object],
    *,
    status: str,
    campaign_id: str,
    trial_id: str,
    top_n: int,
) -> bool:
    return (
        evidence.get("artifact_type") == "ai_selection_evidence"
        and evidence.get("status") == status
        and evidence.get("campaign_id") == campaign_id
        and evidence.get("trial_id") == trial_id
        and evidence.get("top_n") == top_n
    )


def _selection_ranking(path: Path) -> list[str]:
    selection = _read_object(path, "selection result")
    if selection.get("artifact_type") != "ai_stock_selection":
        raise ValueError(f"selection artifact_type is invalid: {path}")
    picks = selection.get("picks")
    if not isinstance(picks, list) or not picks:
        raise ValueError(f"selection result has no picks: {path}")
    symbols: list[str] = []
    for pick in picks:
        if not isinstance(pick, dict):
            raise ValueError(f"selection pick is not an object: {path}")
        symbol = pick.get("symbol")
        if not isinstance(symbol, str) or not symbol:
            raise ValueError(f"selection pick symbol is invalid: {path}")
        symbols.append(symbol)
    _require_unique(symbols, path)
    return symbols


def _diagnostic_ranking(path: Path) -> list[str]:
    diagnostic = _read_object(path, "ranking diagnostic")
    if diagnostic.get("artifact_type") != "ai_ranking_diagnostic":
        raise ValueError(f"ranking diagnostic artifact_type is invalid: {path}")
    symbols = diagnostic.get("symbols")
    if not isinstance(symbols, list) or not symbols or any(
        not isinstance(symbol, str) or not symbol for symbol in symbols
    ):
        raise ValueError(f"ranking diagnostic is invalid: {path}")
    ranking = cast(list[str], symbols)
    _require_unique(ranking, path)
    return ranking


def _with_comparison(arm: dict[str, object], canonical: list[str]) -> dict[str, object]:
    ranking = arm.get("ranking")
    if not _is_ranking(ranking):
        return {
            **arm,
            "top1_matches_canonical": None,
            "exact_ranking_matches_canonical": None,
            "top_n_jaccard_vs_canonical": None,
            "mean_absolute_rank_shift_vs_canonical": None,
        }
    observed = cast(list[str], ranking)
    canonical_set = set(canonical)
    observed_set = set(observed)
    union = canonical_set | observed_set
    overlap = canonical_set & observed_set
    rank_by_symbol = {symbol: index for index, symbol in enumerate(observed, 1)}
    canonical_rank = {symbol: index for index, symbol in enumerate(canonical, 1)}
    shifts = [
        abs(canonical_rank[symbol] - rank_by_symbol[symbol])
        for symbol in canonical
        if symbol in rank_by_symbol
    ]
    return {
        **arm,
        "top1_matches_canonical": observed[0] == canonical[0],
        "exact_ranking_matches_canonical": observed == canonical,
        "top_n_jaccard_vs_canonical": len(overlap) / len(union),
        "mean_absolute_rank_shift_vs_canonical": fmean(shifts) if shifts else None,
    }


def _aggregate(arms: list[dict[str, object]]) -> dict[str, float | None]:
    if not arms:
        return {
            "top1_agreement_rate_vs_canonical": None,
            "exact_ranking_agreement_rate_vs_canonical": None,
            "mean_top_n_jaccard_vs_canonical": None,
            "mean_absolute_rank_shift_vs_canonical": None,
        }
    rank_shifts = [
        cast(float, arm["mean_absolute_rank_shift_vs_canonical"])
        for arm in arms
        if arm["mean_absolute_rank_shift_vs_canonical"] is not None
    ]
    return {
        "top1_agreement_rate_vs_canonical": fmean(
            1.0 if arm["top1_matches_canonical"] else 0.0 for arm in arms
        ),
        "exact_ranking_agreement_rate_vs_canonical": fmean(
            1.0 if arm["exact_ranking_matches_canonical"] else 0.0 for arm in arms
        ),
        "mean_top_n_jaccard_vs_canonical": fmean(
            cast(float, arm["top_n_jaccard_vs_canonical"]) for arm in arms
        ),
        "mean_absolute_rank_shift_vs_canonical": (
            fmean(rank_shifts) if rank_shifts else None
        ),
    }


def _read_object(path: Path, label: str) -> dict[str, object]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"{label} is unreadable: {path}") from exc
    if not isinstance(raw, dict):
        raise ValueError(f"{label} must be a JSON object: {path}")
    return cast(dict[str, object], raw)


def _is_ranking(value: object) -> bool:
    return isinstance(value, list) and bool(value) and all(
        isinstance(symbol, str) and bool(symbol) for symbol in value
    )


def _require_unique(symbols: list[str], path: Path) -> None:
    if len(set(symbols)) != len(symbols):
        raise ValueError(f"ranking contains duplicate symbols: {path}")


def _require_top_n(symbols: list[str], top_n: int, path: Path) -> None:
    if len(symbols) != top_n:
        raise ValueError(
            f"ranking length must equal campaign top_n={top_n}: {path}"
        )
