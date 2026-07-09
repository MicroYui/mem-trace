#!/usr/bin/env bash
# Opt-in horizontal-scaling measurement: proves the production scaling claim in
# docs/deployment.md — retrieval is CPU-bound and stateless over a shared Postgres,
# so adding API worker processes multiplies throughput ~linearly. It runs the REAL
# HTTP app (app.main:app) at several `uvicorn --workers` counts against the shared
# Postgres and drives concurrent /v1/context/retrieve load, reporting req/s per
# worker count and the measured speedup.
#
# `--workers K` (K processes behind one socket, kernel load-balances accept()) is
# the single-host form of the same stateless-replica + shared-Postgres property
# that docker-compose.scale.yml scales across containers behind nginx; the numbers
# transfer. Skips cleanly if Postgres is unreachable. NOT part of default CI.
#
# Requires Postgres up + migrated:
#   docker-compose up -d && uv run alembic upgrade head
# then:
#   ./scripts/perf-scale.sh
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

PORT="${MEMTRACE_SCALE_PORT:-8080}"
BASE="http://127.0.0.1:${PORT}"
N="${MEMTRACE_SCALE_N:-3000}"                 # memories seeded (heavier -> more CPU per retrieve)
WORKERS="${MEMTRACE_SCALE_WORKERS:-1 4}"      # worker counts to compare
CONC="${MEMTRACE_SCALE_CONC:-24}"             # concurrent in-flight requests
REQS="${MEMTRACE_SCALE_REQS:-360}"            # total requests per worker count
IDS_FILE="$(mktemp -t memtrace_scale_ids.XXXXXX)"
SERVER_PID=""

cleanup() {
  [[ -n "$SERVER_PID" ]] && kill "$SERVER_PID" 2>/dev/null || true
  pkill -f "uvicorn app.main:app .*--port ${PORT}" 2>/dev/null || true
  rm -f "$IDS_FILE"
}
trap cleanup EXIT

echo "==> horizontal-scaling measurement (N=${N} memories, workers=[${WORKERS}], conc=${CONC}, reqs=${REQS}/config)"

# 1) Seed the workspace + create a run/step directly in the shared Postgres. Skips
#    the whole measurement (exit 0) if the DB is unreachable.
if ! PYTHONPATH=apps/api uv run python scripts/_perf_scale_seed.py "$N" >"$IDS_FILE" 2>"${IDS_FILE}.err"; then
  if grep -q "SKIP_NO_DB" "${IDS_FILE}.err" 2>/dev/null; then
    echo "  ⏭️  skip: no reachable database"
    rm -f "${IDS_FILE}.err"
    echo "perf-scale skipped"
    exit 0
  fi
  echo "  ✗ seed failed:"; cat "${IDS_FILE}.err"; rm -f "${IDS_FILE}.err"; exit 1
fi
rm -f "${IDS_FILE}.err"
RUN_ID="$(grep '^RUNID ' "$IDS_FILE" | awk '{print $2}')"
STEP_ID="$(grep '^STEPID ' "$IDS_FILE" | awk '{print $2}')"
echo "  ✅ seeded ${N} memories; run=${RUN_ID:0:14}… step=${STEP_ID:0:14}…"

declare -a RESULTS=()
for K in $WORKERS; do
  echo "  -- workers=${K} --"
  # Heavy (unbounded) retrieval so each request is CPU-bound and scaling is visible.
  MEMTRACE_RETRIEVAL_CANDIDATE_LIMIT=0 \
    uv run uvicorn app.main:app --app-dir apps/api --host 127.0.0.1 --port "$PORT" \
      --workers "$K" --log-level warning >/dev/null 2>&1 &
  SERVER_PID=$!

  # health-wait (up to ~40s for K workers to import + connect)
  ok=""
  for _ in $(seq 1 80); do
    if curl -fsS "${BASE}/health" >/dev/null 2>&1; then ok=1; break; fi
    sleep 0.5
  done
  if [[ -z "$ok" ]]; then echo "  ✗ server did not become healthy for workers=${K}"; kill "$SERVER_PID" 2>/dev/null || true; SERVER_PID=""; exit 1; fi

  rps="$(MEMTRACE_SCALE_RUN_ID="$RUN_ID" MEMTRACE_SCALE_STEP_ID="$STEP_ID" \
         uv run python scripts/_perf_scale_load.py "$BASE" "$CONC" "$REQS")"
  echo "     ${rps}"
  RESULTS+=("$K:$(echo "$rps" | sed -n 's/.*rps=\([0-9.]*\).*/\1/p')")

  kill "$SERVER_PID" 2>/dev/null || true
  pkill -f "uvicorn app.main:app .*--port ${PORT}" 2>/dev/null || true
  SERVER_PID=""
  sleep 1
done

echo
echo "==> scaling summary"
base_rps=""; base_k=""; top_rps=""; top_k=""
for r in "${RESULTS[@]}"; do
  k="${r%%:*}"; v="${r##*:}"
  printf "   workers=%-3s  %s req/s\n" "$k" "$v"
  if [[ -z "$base_rps" ]]; then base_rps="$v"; base_k="$k"; fi
  top_rps="$v"; top_k="$k"
done
if [[ -n "$base_rps" && "$base_rps" != "0" && "$base_k" != "$top_k" ]]; then
  speedup="$(uv run python -c "import sys; print(f'{float(sys.argv[1])/float(sys.argv[2]):.2f}')" "$top_rps" "$base_rps")"
  echo "   speedup workers ${base_k}->${top_k}: ${speedup}x (ideal ~$(( top_k / base_k ))x)"
  # Conservative gate: more workers must give a real throughput win (>1.5x for >=2x workers).
  pass="$(uv run python -c "import sys; print('1' if float(sys.argv[1])>1.5 else '0')" "$speedup")"
  if [[ "$pass" == "1" ]]; then
    echo "perf-scale passed: horizontal scaling confirmed"
  else
    echo "perf-scale WARN: speedup ${speedup}x below expected — check host load/core count"
  fi
fi
