#!/usr/bin/env bash
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
CAMPAIGN_DIR="${1:-$ROOT/outputs/order-sensitivity-demo/campaign}"
RESULTS_DIR="${2:-$ROOT/outputs/order-sensitivity-demo/results}"
SUMMARY="$RESULTS_DIR/summary.json"
TRIALS=(canonical shuffle_101 shuffle_202 shuffle_303 opaque_404)

if [[ ! -f "$CAMPAIGN_DIR/manifest.json" ]]; then
  echo "missing campaign manifest: $CAMPAIGN_DIR/manifest.json" >&2
  echo "run experiments/order-sensitivity/prepare.sh first" >&2
  exit 2
fi

mkdir -p "$RESULTS_DIR"
failed=0
for trial_id in "${TRIALS[@]}"; do
  plan="$CAMPAIGN_DIR/trials/$trial_id/trial.json"
  output="$RESULTS_DIR/$trial_id.json"
  evidence="$RESULTS_DIR/$trial_id.evidence"

  if [[ -f "$output" || -d "$evidence" ]]; then
    echo "skip_existing=$trial_id"
    continue
  fi

  echo "running_trial=$trial_id"
  if ! uv run aipick cn trial \
    --plan "$plan" \
    --output "$output" \
    --evidence-dir "$evidence"; then
    echo "trial_failed=$trial_id" >&2
    failed=1
  fi
done

# summary.json is derived analysis, not append-only provider evidence.
rm -f "$SUMMARY"
if ! uv run aipick cn stability-summary \
  --campaign-dir "$CAMPAIGN_DIR" \
  --results-dir "$RESULTS_DIR" \
  --output "$SUMMARY"; then
  failed=1
fi

exit "$failed"
