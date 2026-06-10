#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

echo "==> Running full pytest suite"
uv run pytest -q

echo "==> Running reproducibility baseline"
./scripts/reproduce.sh reports

echo "==> Re-running deterministic benchmark for explicit acceptance check"
uv run python -m app.benchmark.runner --output-dir reports

echo "smoke passed"
