#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

OUT_DIR="${1:-reports}"

if [[ "$OUT_DIR" = /* || "$OUT_DIR" == *".."* || ( "$OUT_DIR" != "reports" && "$OUT_DIR" != reports/* ) ]]; then
  echo "error: output directory must be reports or a relative path under reports/" >&2
  exit 2
fi

echo "==> Generating MemTrace demo report"
uv run python -m app.demo.run_demo --out "$OUT_DIR"

echo "==> Generating multi-hop retrieval demo report"
uv run python -m app.demo.run_multi_hop_demo --out "$OUT_DIR"

echo "==> Running deterministic benchmark"
uv run python -m app.benchmark.runner --output-dir "$OUT_DIR"

echo "==> Generating observability report fixture"
uv run python -m app.observability.reports --output-dir "$OUT_DIR"

echo "==> Checking benchmark acceptance"
uv run python - "$OUT_DIR/benchmark_results.json" <<'PY'
import json
import sys
from pathlib import Path

path = Path(sys.argv[1])
payload = json.loads(path.read_text(encoding="utf-8"))
checks = payload.get("acceptance", {}).get("checks", {})
passed = payload.get("acceptance", {}).get("passed") is True
if not passed:
    raise SystemExit(f"benchmark acceptance failed in {path}")
print(f"acceptance.passed=true ({sum(1 for ok in checks.values() if ok)}/{len(checks)} checks true)")
PY

cat <<EOF

MemTrace reproducibility baseline generated under: $OUT_DIR

Read these files next:
  - $OUT_DIR/demo_report.md
  - $OUT_DIR/multi_hop_demo_report.md
  - $OUT_DIR/benchmark_report.md
  - $OUT_DIR/benchmark_results.json
  - $OUT_DIR/observability_report.md
  - $OUT_DIR/observability_report.html

EOF
