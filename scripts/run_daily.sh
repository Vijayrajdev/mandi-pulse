#!/bin/bash
# Daily collection: pull today's mandi prices, then upload them to the Databricks Volume.
# Run by macOS launchd (see scripts/com.mandipulse.collect.plist), or by hand:
#   ./scripts/run_daily.sh
#
# Output is appended to logs/collect_daily.log (gitignored).

set -euo pipefail   # stop at the first failing command; treat unset variables as errors

# Always run from the project root, whatever folder launchd starts us in.
# (Needed for `python -m ingestion...` imports and for finding .env.)
PROJECT_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$PROJECT_ROOT"

PYTHON="$PROJECT_ROOT/.venv/bin/python"
mkdir -p logs

echo "===== $(date '+%Y-%m-%d %H:%M:%S %Z') run started ====="
"$PYTHON" -m ingestion.collect_daily
"$PYTHON" -m ingestion.upload_to_volume
echo "===== $(date '+%Y-%m-%d %H:%M:%S %Z') run finished OK ====="
