# Output format

English · [简体中文](zh-CN/output-artifact.md)

After a successful run, inspect the selected stocks and commentary. For integration, use the field reference below. An invalid model response does not produce an official selection.

Real runs create an `ai_stock_selection` v1 JSON file. The file is revalidated with Pydantic strict rules before writing. An existing target causes failure rather than an overwrite.

## Top-level fields

### Identity

`schema_version`, `artifact_type`, and `market`:

```json
{
  "schema_version": "1.0.0",
  "artifact_type": "ai_stock_selection",
  "market": "CN"
}
```

### Time

`selection_as_of`, `candidate_observation_date`, `candidate_generated_at`, `data_cutoff`, `upstream_execution_not_before`, `generated_at`, and `temporal_status`.

`generated_at` is converted to UTC. `temporal_status` is either `contemporaneous` or `retrospective_simulation`; see [Time and evidence boundaries](trust-boundaries.md).

### Model

`provider`, `model`, `prompt_version`, `style`, and `selection_method`.

Official A-share selections use `deepseek`; US selections use `gemini`. `selection_method` is currently `llm_candidate_rerank`.

### Input and evidence

`input_contract`, `point_in_time_assurance`, `strict_point_in_time`, `eligible_as_oos_evidence`, `evidence_limitations`, `input_count`, and `requested_top_n`.

All current selections include:

```json
{
  "strict_point_in_time": false,
  "eligible_as_oos_evidence": false
}
```

These values prevent a run from being presented as strict historical timing proof or qualified out-of-sample evidence.

## Lineage and validation

`lineage` records `candidate_path` and the SHA-256 values `input_sha256`, `candidate_symbols_sha256`, `prompt_sha256`, and `response_sha256`. Hashes detect content changes; they do not prove historical existence or replace trusted external timestamps.

Revalidate an artifact against the same candidate snapshot:

```bash
uv run aipick cn validate \
  --selection "$HOME/data/ai-stock-picker/cn-selection.json" \
  --candidates /absolute/path/candidates.json
```

The validator reloads the snapshot and checks its path, input and symbol-set hashes, dates, counts, metadata, evidence limitations, selected members, names, themes, and every commentary field. The current Prompt is rebuilt deterministically and checked against `prompt_sha256`, yielding `validation_profile=current_full`.

Versions `2026-07-15.2` and `2026-07-15.3` use `legacy_read_only`: input, membership, and commentary safety are checked, but changed Prompts are not recomputed and old results are not rewritten.

With `--evidence-dir`, validation also checks the raw response, exact Prompt, selection, and file hashes, reporting `response_sha256_verification=byte_exact_evidence`. Without the archive, only the response hash format can be checked. See [Validation receipt](validation-receipt.md) for downstream binding.

## Picks

The number of `picks` must equal `requested_top_n`. Each pick has `rank`, `symbol`, `name`, `topic`, `confidence_score`, `reasoning`, and `risk_note`.

The model returns only `symbol`, `confidence_score`, `reasoning`, and `risk_note`; the program fills `name` and `topic` from the candidate pool.

Checks include:

- Symbols are unique and belong to the input pool.
- Ranks are consecutive starting at 1.
- `confidence_score` is an integer from 1 to 10.
- Extra model fields are rejected.
- A-share reasoning and risk notes contain Chinese; US commentary uses English.
- Each sentence references an actual candidate field using its key or an approved English/Chinese label.
- Commentary does not expose provider/model identity or structured system metadata, URLs, secrets, trading or holding instructions, target prices, or guaranteed returns.

Documentation language does not change the market-specific output language requirements.

## Commentary boundaries

`reasoning` and `risk_note` are AI interpretations of candidate fields, not independently fact-checked statements. The persisted schema adds no field for this label; customer-facing consumers must display it consistently and must not present commentary as verified facts or investment advice.

The production Prompt provides only symbols, the top-level `score`, and numeric features. Names, themes, concepts, and other free text stay out of provider requests and are filled deterministically from the canonical pool after validation.

Upstream `risk_score` is projected to `intraday_stability_score`, with fixed meaning **higher = more stable**. A high value must never be interpreted as higher risk. Current Prompt version `2026-07-29.1` requires one sentence each for `reasoning` and `risk_note`, grounded in exact `field_key=value` numeric references. This avoids provider-like tokens in candidate concepts conflicting with publication checks. Readers accept historical versions; official writers publish only the current version. Preregistered stability trials use a separate legacy v3 builder retaining old examples and duplicate `score` fields.

Artifact creation rejects the result if any of these requirements fail:

- Every sentence references at least one real candidate field or its approved natural-language label.
- References to `source_topics`, `source_concepts`, `topic`, `name`, `symbol`, `sector`, `industry`, or `confidence_label` contain the exact candidate value.
- Values from `source_topics` and `source_concepts` are not relabeled across fields or grouped under a single label; explicit field/value references are required.
- A provider/model-like token in candidate data is treated as data only inside `<approved field label>：[<exact candidate value>]`. The same token elsewhere is still rejected as system metadata.
- Explicit references outside the candidate-field allowlist are rejected.
- After Unicode normalization, Cyrillic/Greek confusables, domains, emails, IP addresses, provider/model metadata, credentials, and secrets are rejected.
- Trading instructions, target prices, guaranteed returns, `风险分`, reversed stability semantics, and common external or future factual claims are rejected.

## Structural illustration

The following historical-style illustration shows the JSON shape. It is not a current-version validation fixture: its hashes are omitted and current production commentary requires exact numeric references.

```json
{
  "schema_version": "1.0.0",
  "artifact_type": "ai_stock_selection",
  "market": "CN",
  "selection_as_of": "2026-07-15",
  "candidate_observation_date": "2026-07-14",
  "candidate_generated_at": "2026-07-14T22:00:00Z",
  "data_cutoff": "2026-07-14",
  "upstream_execution_not_before": "next_trading_session",
  "generated_at": "2026-07-15T02:00:00Z",
  "provider": "deepseek",
  "model": "deepseek-v4-flash",
  "prompt_version": "2026-07-29.1",
  "style": "momentum",
  "input_contract": "hot_sector_candidate_universe_v1",
  "temporal_status": "contemporaneous",
  "point_in_time_assurance": "signal_date_only",
  "strict_point_in_time": false,
  "eligible_as_oos_evidence": false,
  "evidence_limitations": [
    "rotation_publisher_receipt_unavailable",
    "candidate_artifact_does_not_establish_out_of_sample_validity"
  ],
  "input_count": 20,
  "requested_top_n": 1,
  "selection_method": "llm_candidate_rerank",
  "lineage": {
    "candidate_path": "/path/to/candidates.json",
    "input_sha256": "omitted",
    "candidate_symbols_sha256": "omitted",
    "prompt_sha256": "omitted",
    "response_sha256": "omitted"
  },
  "picks": [
    {
      "rank": 1,
      "symbol": "002371.SZ",
      "name": "北方华创",
      "topic": "半导体国产替代",
      "confidence_score": 8,
      "reasoning": "综合候选评分与热点主题中的半导体国产替代支持相对排序。",
      "risk_note": "仅依据综合候选评分与热点主题中的半导体国产替代，风险解读仍有信息边界。"
    }
  ]
}
```

Real hashes use 64 lowercase hexadecimal SHA-256 characters. Chinese candidate values and A-share commentary are intentionally preserved as market data, not translated protocol values.
