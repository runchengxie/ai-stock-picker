# Research: repeated runs and controlled experiments

English · [简体中文](zh-CN/shadow-research.md)

To select stocks from a pool, start with the [Usage guide](usage.md). This page is for experiments that test ranking stability and sensitivity to stock identity or input order. Research outputs are separate from official selections and do not prove future returns.

## Terms in plain language

| Term | Meaning |
| --- | --- |
| Shadow | An experiment isolated from official publication; freeze inputs and options, repeat model calls, and validate archives offline |
| Bounded arm | Constrained ranking of boundary stocks; each of the final three needs at least two votes to complete |
| Risk-veto arm | A single `veto_symbol/risk_code` decision requiring at least two identical votes |
| Prospective shadow | Freeze before publishing for a future trading session, rather than replaying history |
| Decision plan | Immutable `ai_shadow_decision_plan` binding campaign/date/arm, Prompt, candidates, and numeric evidence |
| Launch receipt | `ai_shadow_launch_receipt` authorizing provider, model, and full inference options for the decision |
| Tombstone | A recorded failed terminal state, rather than a complete result |
| Consensus | A true majority result from repeated runs, fully staged before atomic publication |
| Borda consensus | Rank aggregation retained read-only for historical `.7` archives |
| Numeric | Ranking by numeric score; replacement order comes only from this ranking |
| Manifest | Metadata describing a bundle, including status such as `legacy_unbound` |
| Artifact | A saved, validated JSON result or append-only evidence bundle |

## Current `.8` workflow

`bounded_ranking_v3 / 2026-07-18.8` and `risk_veto_v1 / 2026-07-18.8` implement strict parsing, three repetitions, true-majority consensus, and tombstones.

The bounded arm completes only when each final boundary stock has at least two votes. The risk-veto arm requires two identical `veto_symbol/risk_code` votes; only Numeric order supplies the replacement. Repetitions and consensus are fully written into isolated staging, then atomically published as complete or tombstone. Existing directories are preserved. Artifacts embed a relative candidate snapshot rather than the original absolute path.

Two immutable artifacts remove the old `ai_pick_plan` binding to DeepSeek identity. `ai_shadow_decision_plan` freezes campaign/date/arm, Prompt, candidates, and numeric evidence. `ai_shadow_launch_receipt` then freezes provider, model, and inference options. Both use canonical JSON content hashes; the receipt binds the decision digest, and the runner derives its model partition only from the receipt.

Replace the example paths and model snapshot with your frozen materials:

```bash
uv run aipick cn shadow-decision-plan \
  --plan /absolute/path/frozen/plan.json \
  --campaign-id prompt-8-prospective \
  --signal-date 2026-07-18 \
  --output-dir /absolute/path/lineage/decision

uv run aipick cn shadow-launch-receipt \
  --decision-plan /absolute/path/lineage/decision/decision-plan.json \
  --provider openai \
  --model gpt-model-snapshot \
  --output-dir /absolute/path/lineage/openai-receipt

uv run aipick cn shadow-day \
  --plan /absolute/path/frozen/plan.json \
  --decision-plan /absolute/path/lineage/decision/decision-plan.json \
  --launch-receipt /absolute/path/lineage/openai-receipt/launch-receipt.json \
  --campaign-id prompt-8-prospective \
  --signal-date 2026-07-18 \
  --output-root /absolute/path/shadow
```

If either artifact is missing, standard `.8 shadow-day` fails before calling a provider. Historical rehearsals with an explicitly injected caller can still be replayed, but manifest and validator mark them only `legacy_unbound`, never `prospective_bound`.

If an interrupted historical `.7` process leaves missing repetitions, the network-free watchdog can record tombstones:

```bash
uv run aipick cn shadow-watchdog \
  --plan /absolute/path/frozen/plan.json \
  --campaign-id legacy-bounded-v2 \
  --signal-date 2026-07-17 \
  --output-root /absolute/path/shadow \
  --provider deepseek \
  --model deepseek-v4-flash
```

Downstream systems should not copy the owner's schemas. Obtain machine contracts and digests with `contract-info`, and validate artifacts offline with the owner CLI. Day validation returns verified `plan_sha256`, `decision_plan_sha256`, `launch_receipt_sha256`, `evidence_status`, `numeric_ranking_sha256`, and candidate hashes to bind the full lineage:

```bash
uv run aipick cn contract-info
uv run aipick cn contract-info --json-schema
uv run aipick cn validate-shadow-day --day-dir /absolute/path/shadow/day
uv run aipick cn validate-shadow-campaign --campaign-root /absolute/path/shadow/campaign
```

New partitions use `campaign/arm/provider--model/date/repetition`. Frozen `.7` plans, old directories, and Borda consensus remain rebuilt and validated read-only under their original contract; `.8` does not overwrite them.

For archive contents and anonymous controls, see [Evidence and stability](evidence-and-stability.md).
