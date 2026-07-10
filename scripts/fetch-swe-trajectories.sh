#!/usr/bin/env bash
# Stream a BOUNDED number of real mini-swe-agent trajectories for the agentic
# real-trajectory benchmark (app/benchmark/agentic_trace_bench.py). These are real
# agent runs on SWE-smith tasks — each a sequence of (assistant action, tool
# observation with <returncode>) turns that include genuinely failed commands.
#
# Disk-safe: it STREAMS the parquet dataset and writes only N small per-trajectory
# .traj.json files to /tmp (override with MEMTRACE_SWE_DIR); the full 66k-trajectory
# dataset is never downloaded. Tune the count with MEMTRACE_SWE_N (default 250 ->
# a few thousand real memory steps). `--clean` deletes the files.
#
#   ./scripts/fetch-swe-trajectories.sh              # stream MEMTRACE_SWE_N trajectories
#   MEMTRACE_SWE_N=400 ./scripts/fetch-swe-trajectories.sh
#   ./scripts/fetch-swe-trajectories.sh --clean
#
# Source: https://huggingface.co/datasets/Kwai-Klear/SWE-smith-mini_swe_agent_plus-trajectories-66k
set -euo pipefail

DEST="${MEMTRACE_SWE_DIR:-/tmp/swe_trajs}"
N="${MEMTRACE_SWE_N:-250}"
REPO="${MEMTRACE_SWE_REPO:-Kwai-Klear/SWE-smith-mini_swe_agent_plus-trajectories-66k}"

if [[ "${1:-}" == "--clean" ]]; then
  rm -rf "$DEST" && echo "removed SWE trajectories from $DEST"; exit 0
fi

mkdir -p "$DEST"
uv run --with datasets python - "$DEST" "$N" "$REPO" <<'PY'
import json, os, sys
from datasets import load_dataset

dest, n, repo = sys.argv[1], int(sys.argv[2]), sys.argv[3]
ds = load_dataset(repo, split="train", streaming=True)
count = 0
for row in ds:
    if count >= n:
        break
    inst = str(row.get("instance_id") or f"traj_{count}").replace("/", "_")
    with open(os.path.join(dest, f"{inst}.traj.json"), "w", encoding="utf-8") as fh:
        json.dump({"instance_id": inst, "messages": row["messages"], "trajectory_format": "mini-swe-agent"}, fh)
    count += 1
    if count % 50 == 0:
        print(f"  streamed {count}/{n} …", file=sys.stderr)
print(f"wrote {count} trajectories to {dest}", file=sys.stderr)
PY
echo "$DEST"
