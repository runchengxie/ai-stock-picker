# Selection validation receipt

English · [简体中文](zh-CN/validation-receipt.md)

For downstream developers: validate a selection with the owner CLI, then save a receipt binding the consumed result to its inputs. Ordinary command-line use does not require constructing these fields.

`aipick cn validate` retains its backward-compatible output by default. Add `--validation-receipt` when you need a machine-readable receipt bound to the specific selection file:

```bash
uv run aipick cn validate \
  --selection /absolute/path/selection.json \
  --candidates /absolute/path/candidates.json \
  --validation-receipt
```

Include the append-only archive when available:

```bash
uv run aipick cn validate \
  --selection /absolute/path/selection.json \
  --candidates /absolute/path/candidates.json \
  --evidence-dir /absolute/path/selection.json.evidence \
  --validation-receipt
```

## Receipt contract

Current shape:

```json
{
  "schema_version": "1.0.0",
  "artifact_type": "ai_stock_selection_validation_receipt",
  "valid": true,
  "market": "CN",
  "selection_sha256": "<64 lowercase hex>",
  "selection_as_of": "2026-07-15",
  "prompt_version": "2026-07-29.1",
  "picks": 1,
  "validation_profile": "current_full",
  "prompt_hash_revalidated": true,
  "commentary_policy_revalidated": true,
  "response_sha256_verification": "format_only_raw_response_unavailable",
  "evidence_manifest_sha256": null
}
```

`selection_sha256` hashes the exact selection bytes passed to the owner validator, so consumers can reject a receipt paired with a different file.

When `--evidence-dir` is supplied and evidence validation passes:

- `response_sha256_verification` is `byte_exact_evidence`.
- `evidence_manifest_sha256` is the archive's `manifest.json` SHA-256.
- The validator first checks that archived `selection.json` and the supplied file are byte-identical.

Without evidence, `evidence_manifest_sha256` is `null`: selection, candidate, and Prompt contracts were revalidated, but the raw provider response was not rebound through byte-exact evidence.

## Trust boundary

The receipt proves only that the owner validator passed the declared checks on **these selection bytes**. It does not:

- Upgrade `strict_point_in_time=false` to strict point-in-time proof.
- Upgrade `eligible_as_oos_evidence=false` to qualified out-of-sample evidence.
- Prove that model training data contains no future information.
- Replace an external trusted timestamp.
- Turn customer commentary into independent fact-checking.

Downstream adapters must recompute the selection SHA-256 and compare it with the receipt. Checking only `valid=true` is insufficient.

## Compatibility

Without `--validation-receipt`, existing validation JSON output is unchanged. Breaking receipt-contract changes require a new `schema_version`; do not reinterpret `1.0.0` in place.
