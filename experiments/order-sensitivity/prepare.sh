#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
CAMPAIGN_DIR="${1:-$ROOT/outputs/order-sensitivity-demo/campaign}"
CANDIDATES="$ROOT/experiments/order-sensitivity/candidates.json"

if [[ -e "$CAMPAIGN_DIR" ]]; then
  echo "campaign directory already exists: $CAMPAIGN_DIR" >&2
  echo "choose a new path or remove the old derived demo output" >&2
  exit 2
fi

uv run aipick cn stability-plan \
  --candidates "$CANDIDATES" \
  --as-of 2026-06-30 \
  --top-n 3 \
  --style momentum \
  --campaign-id order-sensitivity-demo-v1 \
  --output-dir "$CAMPAIGN_DIR"

echo "campaign_dir=$CAMPAIGN_DIR"
echo "api_calls=0"
