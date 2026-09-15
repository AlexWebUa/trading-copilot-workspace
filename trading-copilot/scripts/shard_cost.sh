#!/usr/bin/env bash
# Stage 1 + stage 1b with the honest cost model, 11 shards over 8 cores.
# Same pinned window as the cost-free pass, so the two are directly comparable.
set -u
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
PY=./.venv/Scripts/python.exe
START=2025-08-27T12:00:00Z
END=2026-08-27T00:00:00Z
{
  for m in market poi fvg fvg_full bpr ob stb; do echo "1 $m"; done
  for m in poi_full bpr_full ob_full stb_full; do echo "1b $m"; done
} | xargs -P 8 -L1 sh -c \
  '"'"$PY"'" scripts/run_30mof.py --stage $0 --bars 17520 \
     --start '"$START"' --end '"$END"' --only $1 --tag cost_$1 \
     --fee-bps 4 --slippage-bps 2 \
     > research/runs/logs/cost_$0_$1.log 2>&1; echo "done stage$0 $1 rc=$?"'
