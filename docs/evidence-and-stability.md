# Evidence archives and stability experiments

English · [简体中文](zh-CN/evidence-and-stability.md)

The first part explains what a model call records. The rest explains frozen inputs, repeated runs, and anonymous controls. For normal use, start with the [Usage guide](usage.md). Evidence helps inspect a process; it does not establish future returns.

## What a call records

After a model call, `pick` and `trial` write a dedicated archive. Its default location is `<output>.evidence` unless `--evidence-dir` is supplied. Archives and results are append-only and reject existing targets.

| File | Contents |
| --- | --- |
| `candidate_input.json` or `candidate_input.csv` | Original candidate pool |
| `numeric_ranking.json` | Full numeric ranking |
| `prompt.txt` | Exact Prompt sent to the model |
| `http_request_envelope.json` | Sanitized HTTP request information |
| `provider_request_body.json` | Request body without credentials |
| `provider_response_body.bin` | Raw response bytes |
| `model_response.txt` | Successfully extracted model text |
| `selection.json` | Validated selection |
| `ranking_diagnostic.json` | Stock order when ranking passes but publication fails |
| `manifest.json` | Status, timing, model information, and file hashes |

New evidence v2 archives save full inference options in `provider_parameters`. With DeepSeek thinking disabled, these include `thinking=disabled`, `max_tokens`, `temperature`, and JSON output format. With thinking enabled, they include `thinking=enabled`, `reasoning_effort`, `max_tokens`, and JSON format, omitting `temperature`. The validator compares them with `provider_request_body.json`.

Anonymous production archives also retain `symbol_aliases`, `name_aliases`, and `alias_maps_sha256`. The combined hash covers canonical JSON containing those two mappings: sorted keys, two-space indentation, UTF-8, and one trailing newline. The validator rebuilds the full Prompt from archived candidates and recomputes the mapping hash.

The manifest records both the requested model alias and actual response model: top-level `model` for DeepSeek, `modelVersion` for Gemini. If absent, the identity is empty and should be treated as unconfirmed.

An HTTP success can still contain invalid JSON, the wrong top-level type, or no extractable model text. Such runs retain the raw response with status `rejected` and create neither `model_response.txt` nor a selection file. Errors exclude credentials and raw response text.

## Three separate checks

- `transport_contract`: can the response be extracted as model text?
- `ranking_contract`: does it satisfy structure, count, uniqueness, and pool membership?
- `publication_contract`: does commentary satisfy grounding, safety, and the full publication contract?

When ranking passes but publication fails, status remains `rejected`. `ranking_diagnostic.json` contains only the ordered stock symbols as business data, allowing research on ranking performance. A delivery system still requires the official `selection.json` before publication.

Validate an archive:

```bash
uv run aipick cn validate-evidence \
  --evidence-dir /absolute/path/selection.evidence
```

Missing manifests, hash mismatches, and unregistered files cause failure.

## Prospective shadow experiments (`.8`)

A shadow experiment is a research run kept separate from official selections; see the [Research guide](shadow-research.md) for terminology and launch commands.

`bounded_ranking_v3 / 2026-07-18.8` and `risk_veto_v1 / 2026-07-18.8` require a provider-neutral `ai_shadow_decision_plan`, followed by a provider-specific `ai_shadow_launch_receipt`. The decision binds campaign/date/arm, Prompt, candidates, numeric ranking, and policy. The receipt binds its digest, provider, model, and inference options.

The runner derives the model partition only from the receipt and requires execution after 16:00 on the Shanghai market signal date. Every model has exactly three repetitions:

```text
campaign/arm/provider--model/YYYY-MM-DD/repetition-01
campaign/arm/provider--model/YYYY-MM-DD/repetition-02
campaign/arm/provider--model/YYYY-MM-DD/repetition-03
campaign/arm/provider--model/YYYY-MM-DD/consensus
```

A repetition is complete when ranking passes. Commentary failure still preserves hash-indexed `ranking.json` for consensus. Ranking failure, refusal, or call failure produces a tombstone: a recorded failed terminal state.

Consensus needs at least two valid results. The bounded arm fixes the Numeric Top7; each of the final three boundary stocks needs at least two votes. The risk-veto arm needs at least two votes for the identical single veto decision, and the program replaces the vetoed stock from the Numeric reserve. With too few valid results or no true majority, consensus is a tombstone. Validation also returns the frozen Numeric Top10 fallback, retaining failed dates in the sample.

Historical `bounded_ranking_v2 / 2026-07-17.7`, old model/date directories, and Borda consensus remain validated under their original `1.0.0` contract. New runners do not reinterpret historical artifacts.

Each terminal bundle is written into isolated staging under the output root, fsynced, then atomically renamed into its final partition. An interrupted publication leaves staging fragments excluded from campaign validation; the watchdog can still mark missing repetitions as tombstones.

Archives use relative `candidate_snapshot_path` and content digests rather than copying the original machine's absolute candidate path. Campaign validation fixes model parameters, style, top_n, Prompt version, and input contract across days for each model, and requires all models on one trading day to use the same frozen input.

The OpenAI adapter uses Responses API `text.format` strict JSON Schema and `store=false`, saving requested and actual model identities, refusal, usage, and raw responses. Each prospective repetition embeds identical decision-plan and launch-receipt bytes. Manifest and validation summaries expose `decision_plan_sha256`, `launch_receipt_sha256`, and `evidence_status=prospective_bound`.

Any mismatch in hashes, provider/model, campaign/date/arm, Prompt, or candidates fails validation. Old injected-caller rehearsals without receipts are `legacy_unbound`. Standard `.8` execution fails before networking if either artifact is missing. Trading-day registries and whole-day watchdog scheduling belong to the external control plane.

Historical `1.1.0` manifests missing all three lineage fields are read-only `legacy_unbound`; partially present fields are corruption and are rejected. `prospective_bound` proves launch lineage only. With upstream `strict_point_in_time=false`, artifacts remain `research_only`, not qualified out-of-sample alpha evidence.

## Freeze a production selection plan

`pick-plan` freezes a production v4 request for repeatable batches. It reads no credentials and makes no model call. A presentation-order file must be a JSON string array containing every candidate symbol exactly once.

```bash
uv run aipick cn pick-plan \
  --candidates /absolute/path/candidates/20260715/candidate_universe.json \
  --as-of 2026-07-15 \
  --top-n 10 \
  --style momentum \
  --model deepseek-v4-pro \
  --prompt-profile production_v4 \
  --presentation-order-file /absolute/path/orders/20260715_shuffle.json \
  --symbol-aliases-file /absolute/path/aliases/20260715_symbols.json \
  --name-aliases-file /absolute/path/aliases/20260715_names.json \
  --thinking enabled \
  --reasoning-effort max \
  --max-tokens 32768 \
  --campaign-id deepseek_v4_pro_month_v1_20260716 \
  --trial-id 20260715_pro_shuffle \
  --output-dir /absolute/path/plans/20260715_pro_shuffle
```

The directory contains `candidate_input.json` or `.csv`, `numeric_ranking.json`, `prompt.txt`, `plan.json`, and `receipt.json`. Anonymous plans also contain `symbol_aliases.json` and `name_aliases.json`.

`plan.json` saves campaign and trial IDs, model, `provider_parameters`, candidate and Prompt hashes, and order. Anonymous plans save both mappings, their individual file hashes, and the combined hash. Both mappings must be supplied together, cover the entire pool, and use unique aliases.

`receipt.json` binds the plan's core fields excluding the file index; that index binds every input file's exact bytes. Execution hashes the full `plan.json` into the evidence manifest:

```bash
uv run aipick cn trial \
  --plan /absolute/path/plans/20260715_pro_shuffle/plan.json \
  --output /absolute/path/results/20260715_pro_shuffle.json \
  --evidence-dir /absolute/path/results/20260715_pro_shuffle.evidence
```

`trial` reloads the candidate snapshot, rebuilds the Prompt, and checks files and hashes before calling the model. There are no runtime overrides for model, thinking, or token budget. Anonymous execution also rejects any real symbol or name left anywhere in the full Prompt.

## Five-arm stability plan

`stability-plan` prepares materials without credentials or network calls. For each date, it creates these arms in order:

1. `canonical`: standard rendered order.
2. `shuffle_101`: final rendered order shuffled with seed 101.
3. `shuffle_202`: shuffled with seed 202.
4. `shuffle_303`: shuffled with seed 303.
5. `opaque_404`: standard order with anonymous symbols and names.

The three shuffled orders must differ from each other and from canonical. Planning fails if a small pool cannot meet this constraint with the fixed seeds.

Anonymous identifiers are assigned by:

1. Hashing the compact JSON array `[campaign_id, selection_as_of, symbol, 404]` with SHA-256 for each candidate.
2. Sorting by hash and symbol.
3. Assigning symbols `C001`, `C002`, … and names `候选001`, `候选002`, ….
4. Saving real identity, anonymous identity, and identity hash in `identity_mapping`.

The full Prompt is checked for real symbols and names. Identity references in themes or other text are also replaced; all numeric fields stay unchanged. Model output is validated in anonymous space before mapping back.

## Isolated Prompt versions

Official `pick` uses production v4 version `2026-07-29.1`. Providers receive symbols, top-level `score`, and numeric features. Names, themes, and concepts are filled from canonical candidates after validation. Commentary must reference exact `field_key=value` numbers.

The five-arm stability experiment uses frozen legacy v3 version `2026-07-15.3`, preserving the first-row example and duplicate top-level/feature `score` for preregistered reproducibility. Builders validate separately. Production `plan.json` uses the official writer; legacy `trial.json` uses a research-only writer and remains `eligible_as_oos_evidence=false`.

A one-day example:

```bash
uv run aipick cn stability-plan \
  --candidates /absolute/path/candidates/20260715/candidate_universe.json \
  --as-of 2026-07-15 \
  --top-n 10 \
  --style momentum \
  --campaign-id deepseek_stability_v1_20260716 \
  --output-dir /absolute/path/stability/20260715
```

The same pool, campaign ID, and parameters generate byte-identical `trial.json` and `prompt.txt`. The top-level manifest separately records generation time, fixed seeds, and all file hashes.

## Batch the preregistered 20 dates

This example does not call DeepSeek. It assumes files under `$candidate_root/<YYYYMMDD>/candidate_universe.json`. The historical registration assumes 116 valid dates; verify that count and freeze the complete date list and candidate hashes before using it.

```bash
candidate_root=/absolute/path/candidates
output_root=/absolute/path/stability-plans
campaign_id=deepseek_stability_v1_20260716

for date in \
  20260115 20260123 20260202 20260210 20260226 \
  20260306 20260316 20260324 20260401 20260410 \
  20260421 20260429 20260512 20260520 20260528 \
  20260605 20260615 20260624 20260707 20260715
do
  iso_date="${date:0:4}-${date:4:2}-${date:6:2}"
  uv run aipick cn stability-plan \
    --candidates "$candidate_root/$date/candidate_universe.json" \
    --as-of "$iso_date" \
    --top-n 10 \
    --style momentum \
    --campaign-id "$campaign_id" \
    --output-dir "$output_root/$date"
done
```

If the count changes, select 20 dates again with the preregistered formula `round(i * (n - 1) / 19)` and record the difference separately from the plans.

## Execute one arm

```bash
uv run aipick cn trial \
  --plan /absolute/path/stability/20260715/trials/shuffle_101/trial.json \
  --output /absolute/path/results/20260715_shuffle_101.json \
  --evidence-dir /absolute/path/results/20260715_shuffle_101.evidence
```

`trial` rebuilds the Prompt using the version in `trial.json`, requires byte equality with the frozen file, then calls the model.

## Interpretation limits

An archive identifies the local materials used and detects later modification. Historical existence still requires external publication receipts or continuous append-only time records. Replayed results remain research evidence without qualified out-of-sample status.
