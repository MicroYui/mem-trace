#!/usr/bin/env bash
# Fetch a few real SWE-agent (mini-swe-agent) trajectories for the opt-in agentic
# real-trajectory benchmark (app/benchmark/agentic_trace_bench.py). Disk-safe:
# downloads small .traj.json files to /tmp (override with MEMTRACE_SWE_DIR), and
# `--clean` deletes them. These are real agent runs on SWE-bench issues, each a
# sequence of (assistant action, tool observation with <returncode>) turns that
# include genuinely failed commands.
#
#   ./scripts/fetch-swe-trajectories.sh          # download the sample set
#   ./scripts/fetch-swe-trajectories.sh --clean  # delete them
#
# Source: https://huggingface.co/datasets/Yi30/deepseek-v4-swebench-trajectories
set -euo pipefail

REPO="Yi30/deepseek-v4-swebench-trajectories"
DEST="${MEMTRACE_SWE_DIR:-/tmp/swe_trajs}"
INSTANCES=(
  astropy__astropy-12907 astropy__astropy-13033 astropy__astropy-13236
  astropy__astropy-13398 astropy__astropy-13453 astropy__astropy-13579
  astropy__astropy-13977 astropy__astropy-14096 astropy__astropy-14182
  astropy__astropy-14309
)

if [[ "${1:-}" == "--clean" ]]; then
  rm -rf "$DEST" && echo "removed SWE trajectories from $DEST"; exit 0
fi

mkdir -p "$DEST"
for inst in "${INSTANCES[@]}"; do
  out="$DEST/${inst}.traj.json"
  [[ -f "$out" ]] && continue
  url="https://huggingface.co/datasets/$REPO/resolve/main/data/no_think/${inst}.traj.json"
  curl -fSL --max-time 120 -o "$out" "$url" && echo "  ${inst}.traj.json" >&2
done
echo "$DEST"
