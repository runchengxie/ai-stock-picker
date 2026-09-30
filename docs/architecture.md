# Architecture

English · [简体中文](zh-CN/architecture.md)

For maintainers: follow the execution flow to locate a change. Candidate validation handles input issues, providers handle model calls, and selection/evidence modules handle saved results. Normal users do not need these internals.

## Product boundary

The project ranks candidates after an external system has generated the pool. Inputs are an A-share or US pool, signal date, requested count, and ranking style. The official output is a strictly validated `ai_stock_selection` JSON file. Market data collection, candidate generation, backtesting, notifications, and order execution are outside scope.

## Execution flow

```text
CLI options
  ↓
Read and validate candidates
  ↓
Normalize fields
  ↓
Build deterministic Prompt
  ↓
Call the market-bound provider
  ↓
Validate model JSON
  ↓
Fill names and themes from the pool
  ↓
Build SelectionArtifact
  ↓
Write append-only evidence
  ↓
Write the result atomically, rejecting existing files
```

## Module responsibilities

All names below are under `stock_analysis`.

| Module | Responsibility |
| --- | --- |
| `app.cli` | Arguments, readable errors, dry-run summaries, and core dispatch; keep candidate contracts and provider parsing out of CLI |
| `ai_lab.candidates` | JSON/CSV reading, size limits, manifest validation, CN v1/v2 contracts, normalization, and Prompt feature allowlists; v2 requires canonical `source_concepts_policy` |
| `ai_lab.contracts` | Market/provider/style types, model and artifact schemas, cross-field checks for time, lineage, and picks |
| `ai_lab.credentials` | Securely read an explicit owner credential file and return only the plan's provider key |
| `ai_lab.providers` | DeepSeek/Gemini HTTPS and OpenAI research Responses API calls, parsing, actual model identity, raw invalid-response retention, size limits, credential isolation, sanitized errors |
| `ai_lab.selection` | Plans, provider dispatch, output validation, artifact construction, and isolated official/research persistence |
| `ai_lab.prompting` | Separate production v4 and frozen legacy v3 rendering, presentation order, aliases, and anonymous text replacement |
| `ai_lab.evidence` | Original input and numeric ranking, exact Prompt and sanitized requests/raw responses, identities/times/hashes/selections, five fixed stability arms, archive integrity and overwrite rejection |
| `ai_lab.evidence_consistency` | Reconstruct archived plans and cross-check requests, responses, parameters, hashes, and results; read v1 under its original request contract, write v2 |
| `ai_lab.evidence_contracts` | Separate transport/ranking/publication checks; retain order-only research diagnostics on publication failure |
| `ai_lab.frozen_plan` | Write and rebuild network-free production plans including inputs, ranking, Prompt/order/model/inference options; bind anonymous mappings and verify identity removal |
| `ai_lab.stability_support` | Hash-based anonymous IDs, reversible identity mappings, removal of real identities, and numeric consistency |
| `ai_lab.shadow_campaign` | `.8` bounded-ranking/risk-veto day execution, three repetitions, strict local schemas, true 2/3 majority, Numeric fallback, complete/tombstone states, and network-free watchdog |
| `ai_lab.shadow_validation` | Offline repetitions/consensus/hash/lineage validation and deterministic consensus reconstruction |
| `ai_lab.shadow_exchange_validation` | Rebuild provider requests and cross-check Prompt, request body, raw response, extracted text, actual model, refusal, and usage |

`candidates` still has a broad responsibility. Extracting CN contract validation while retaining one loading entry point is a possible follow-up, rather than adding more public loaders now.

Pydantic models use strict, extra-forbid, and frozen configuration to prevent implicit coercion and accidental mutation.

## Providers and credentials

Official A-share selections use only `DEEPSEEK_API_KEY`; US selections use only `GEMINI_API_KEY`. `.8` research first freezes a provider-neutral `ai_shadow_decision_plan`, then authorizes provider/model/inference parameters through `ai_shadow_launch_receipt`. The runner derives its model partition from the receipt and rejects missing or drifting bindings. Old explicit injected-caller rehearsals without receipts can produce only `legacy_unbound` evidence.

Credentials use non-forwardable headers and are not carried across provider redirects. An explicit `--credential-file` is read through a safe file descriptor and must be a regular, current-user-owned file with permissions exactly `0600`, at most 128 KiB, and no symlink.

Prefer strict JSON `ai_stock_picker.<deepseek|gemini>.api_key`; literal UTF-8 `KEY=value` remains supported. Neither executes shell code or expands `$()`. Only the plan's provider key is returned. Duplicate JSON fields, invalid types, and empty keys fail. Process environment keys are used only without an explicit file.

Device/inode/size/mtime/ctime snapshots are compared before and after reading; even an in-place rewrite on the same inode fails.

## Prompt and research isolation

Production v4 renders `score` once and omits a first-row real candidate example. Frozen legacy v3 retains the duplicate score and example exclusively for preregistered stability trials.

New research partitions use `campaign/arm/provider--model/date/repetition`. Historical `.7` directories and Borda consensus remain read-only under their frozen contracts. Cross-repository consumers call `validate-shadow-day` or `validate-shadow-campaign` rather than copying schemas or Prompt constants.

## Dependency direction

```text
cli
├── selection
│   └── prompting + candidates + contracts + credentials + providers
└── evidence
    └── selection + stability_support
```

- `contracts` does not depend on CLI.
- `providers` does not depend on candidate file formats.
- `candidates` does not call providers.
- Tests isolate networking with injected callers or transports.

## Names and examples

The distribution is `ai-stock-picker`, the command is `aipick`, and the Python namespace is `stock_analysis`. The namespace predates the current narrower product. A rename to `ai_stock_picker` would change imports, packaging, and external callers and belongs in a separate compatibility-reviewed change.

`examples/` contains runnable input fixtures used to verify documentation commands, not generated outputs. Keep them there rather than under an ambiguous `artifacts/` directory.

## Possible follow-ups

Use independent PRs for public-interface or persisted-format changes:

1. Migrate the Python namespace to `ai_stock_picker`.
2. Separate generic candidate loading from CN contract validation.
3. Define a versioned US input contract.
4. Move legacy CSV to an explicit migration command and gradually deprecate it in core execution.
5. Avoid local absolute paths in persisted lineage.

Do not bundle these compatibility changes with website or documentation work.
