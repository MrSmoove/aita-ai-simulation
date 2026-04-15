#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT_DIR"

export PYTHONPATH="$ROOT_DIR"

OUTPUT="$(./.venv/bin/python scripts/cli.py \
  --post-id viewer-smoke \
  --title "AITA for testing the simulation viewer?" \
  --body "This is a short smoke test to generate a local run for the frontend." \
  --num-commenters 3 \
  --max-steps 2 \
  --model gpt-4.1-mini)"

printf "%s\n" "$OUTPUT"

RUN_ID="$(printf "%s\n" "$OUTPUT" | sed -n 's/^✓ Simulation complete\. Run ID: //p' | tail -n 1)"

if [ -z "$RUN_ID" ]; then
  echo "Could not determine run ID from CLI output." >&2
  exit 1
fi

echo
echo "Viewer URL:"
echo "http://localhost:8000/frontend/?run=$RUN_ID"
