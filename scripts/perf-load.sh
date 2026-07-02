#!/usr/bin/env bash
# Resource-limited retrieval load test.
#
# Runs the load bench INSIDE a CPU/memory-capped container so it never hogs the
# host, and measures sustained retrieval throughput + tail latency achievable
# within that fixed quota. Self-contained: in-memory repo, no Postgres/ES, no data
# volumes, so disk use is negligible and nothing persists after `--rm`.
#
# Tune the quota + pressure via env (defaults model one small production pod):
#   PERF_CPUS=1 PERF_MEM=1g PERF_CONCURRENCY=16 PERF_DURATION=15 PERF_WORKSPACE=2000 \
#     ./scripts/perf-load.sh
#
# The container is capped to PERF_CPUS cores, so the single-process asyncio load
# saturates exactly that budget — the reported throughput is the per-quota ceiling.
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

CPUS="${PERF_CPUS:-1}"
MEM="${PERF_MEM:-1g}"
CONCURRENCY="${PERF_CONCURRENCY:-16}"
DURATION="${PERF_DURATION:-15}"
WORKSPACE="${PERF_WORKSPACE:-2000}"
IMAGE="${PERF_IMAGE:-ghcr.io/astral-sh/uv:python3.12-bookworm}"

CMD="uv run python -m app.benchmark.perf_bench --load \
  --concurrency ${CONCURRENCY} --duration ${DURATION} --workspace-size ${WORKSPACE} \
  --output-dir reports"

if ! command -v docker >/dev/null 2>&1; then
  echo "docker not found — running directly on the host (NO CPU/memory cap):"
  echo "  ${CMD}"
  eval "${CMD}"
  exit 0
fi

echo "==> Load test capped at --cpus=${CPUS} --memory=${MEM}"
echo "    concurrency=${CONCURRENCY} duration=${DURATION}s workspace=${WORKSPACE} memories"
exec docker run --rm \
  --cpus="${CPUS}" --memory="${MEM}" --memory-swap="${MEM}" \
  --pids-limit=512 \
  -v "${ROOT_DIR}:/app" -w /app \
  "${IMAGE}" \
  ${CMD}
