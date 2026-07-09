#!/usr/bin/env bash
# Fetch a LongMemEval-cleaned dataset file from HuggingFace for the opt-in
# longmemeval_bench (app/benchmark/longmemeval_bench.py). Disk-safe: downloads to
# /tmp (override with MEMTRACE_LME_DIR), and `--clean` deletes the files again.
#
#   ./scripts/fetch-longmemeval.sh s_cleaned   # 264MB full histories (scale + distractors)
#   ./scripts/fetch-longmemeval.sh oracle      # 14MB gold-only sessions (fast smoke)
#   ./scripts/fetch-longmemeval.sh --clean     # delete downloaded longmemeval_*.json
#
# Dataset: xiaowu0162/longmemeval-cleaned. NOT committed; only aggregate report
# JSON + charts derived from it are kept.
set -euo pipefail

REPO="xiaowu0162/longmemeval-cleaned"
DEST_DIR="${MEMTRACE_LME_DIR:-/tmp}"

case "${1:-s_cleaned}" in
  --clean) rm -f "$DEST_DIR"/longmemeval_*.json && echo "removed LongMemEval files from $DEST_DIR"; exit 0 ;;
  oracle)     file="longmemeval_oracle.json" ;;
  s_cleaned)  file="longmemeval_s_cleaned.json" ;;
  m_cleaned)  file="longmemeval_m_cleaned.json" ;;
  *) echo "unknown variant '$1' (oracle|s_cleaned|m_cleaned|--clean)" >&2; exit 2 ;;
esac

out="$DEST_DIR/$file"
if [[ -f "$out" ]]; then echo "$out"; exit 0; fi
echo "downloading $file -> $out (this may take a while for s_cleaned/264MB)" >&2
curl -fSL --max-time 1800 -o "$out" "https://huggingface.co/datasets/$REPO/resolve/main/$file"
echo "$out"
