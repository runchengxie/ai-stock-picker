# Input formats

English · [简体中文](zh-CN/input-formats.md)

Prepare a candidate file before running a selection. Start from the structure of the [bundled examples](../examples/README.md) and replace the data. This page describes validation requirements, not market data collection.

`aipick` accepts JSON manifests and legacy UTF-8 CSV. Prefer JSON: it can record generation time, observation date, and data cutoff. CSV lacks this context and is intended for exploration or migration.

## Shared limits

Every input is checked:

- The file must exist and be no larger than 10 MB.
- The pool must contain 1–1,000 candidates.
- Symbols must match the market format and be unique.
- Scores must be finite numbers.
- Names, themes, and feature strings must stay within their length limits.

`--as-of` is the selection signal date. The candidate observation date may be earlier, but must not be later.

## A-share JSON

A-shares support `hot_sector_candidate_universe` v1 and v2. v1 is retained for old frozen artifacts; new campaigns should use v2. The [bundled A-share file](../examples/cn_candidates.json) is a v1 example.

### Contract identity

For v1 these values must match exactly:

```json
{
  "schema_version": "1.0.0",
  "artifact_type": "hot_sector_candidate_universe",
  "market": "CN"
}
```

### Dates and timing

`date`, `date_int`, `observation_date`, and `data_cutoff` must refer to the same observation day. `generated_at` must be ISO 8601 with an explicit UTC offset.

When generated on the observation day, Shanghai market time must be at least 16:00. Pools generated later carry corresponding evidence limitations. These values are also required:

```json
{
  "data_cutoff_semantics": "end_of_day",
  "execution_not_before": "next_trading_session",
  "future_data_included": false
}
```

The tool records `execution_not_before`. It has no exchange calendar and does not verify the actual next trading session.

### Candidate fields

Each candidate needs `ts_code`, `name`, `score`, `relevance`, `source_topics`, and `source_concepts`:

```json
{
  "ts_code": "002371.SZ",
  "name": "北方华创",
  "score": 1.25,
  "relevance": 0.92,
  "source_topics": ["半导体国产替代"],
  "source_concepts": ["半导体设备"]
}
```

`score` must be finite. `relevance` must be between 0 and 1. `source_topics` and `source_concepts` must be string arrays with no empty strings. Chinese names and themes above are input data and remain unchanged across documentation languages.

### Provenance and evidence

The v1 contract also validates:

- `provenance.timezone`, `provenance.observation_date`, and `provenance.data_cutoff`
- `provenance.rotation`
- `evidence.temporal_context` and `evidence.limitations`
- `quality_report` and `outcome_report`

At generation time, `quality_report` and `outcome_report` must remain deferred. Future performance must not be inserted into candidate-generation data. Refer to the bundled A-share example for the full structure.

### v2 concept-source isolation

v2 uses `schema_version=2.0.0` and requires canonical top-level `source_concepts_policy` and `model_identity`. `source_concepts` may come only from theme, concept, or related_concepts. Sources tag, lu_desc, status, rank_reason, and limit_type are excluded.

The policy's canonical JSON SHA-256 must be:

```text
d14282e8047367ba61ea762cd3c3de56162329c12f1778c9681246ec7f0f0b40
```

Each v2 candidate must separately provide `source_event_tags`, `source_event_statuses`, and `source_event_reasons` as string arrays. Empty arrays are allowed; blank elements are not. These event fields are retained as explanatory lineage, are outside the Prompt feature allowlist, and do not participate in AI ranking.

## US JSON

US stocks currently use a generic JSON manifest; see the [US sample](../examples/us_candidates.json).

Required top-level fields:

- `generated_at`
- One of `date`, `observation_date`, or `as_of`
- `universe_size`
- `candidates`

Each candidate requires `ticker` or `symbol`, `company_name` or `name`, and `score`. A theme may come from `sector`, `industry`, or `topic`.

```json
{
  "date": "2026-07-14",
  "generated_at": "2026-07-15T08:30:00-04:00",
  "data_cutoff": "2026-07-14",
  "universe_size": 1,
  "candidates": [
    {
      "ticker": "AAPL",
      "company_name": "Apple Inc.",
      "score": 7.5,
      "sector": "Technology"
    }
  ]
}
```

Generic JSON has no supported versioned timing contract, so `point_in_time_assurance` is `unverified`.

## Legacy CSV

CSV must be UTF-8. Required columns:

| Market | Symbol | Name | Score |
| --- | --- | --- | --- |
| A-shares | `ts_code` or `symbol` | `name` | `score` or numeric-convertible `relevance` |
| US | `ticker` or `symbol` | `company_name` or `name` | `score` or numeric-convertible `relevance` |

Optional date columns are `trade_date`, `date`, or `as_of`. Themes may be encoded as JSON arrays or Python list text; this compatibility is intended for old files, not new workflows.

CSV lacks a manifest generation time and trusted cutoff, so its results always carry `unverified` assurance.

## Common errors

| Error | Meaning / action |
| --- | --- |
| `top_n exceeds candidate count` | Reduce `--top-n` or provide more candidates |
| `manifest observation date is after selection --as-of` | Check the signal date and input dates |
| `candidate symbols must be unique` | Remove duplicate symbols |
| `manifest generated_at must include an explicit UTC offset` | Use a timestamp such as `2026-07-15T08:30:00+08:00` |
