#!/usr/bin/env bash
# The POI arms re-measured: three years, stop floor ON.
#
# Run 1 could not answer "which POI has edge" for two independent reasons — the
# arms measured degenerate fills (median stop $33 on ob_full_long), and none of
# them reached 30 trades on a year. This run fixes both: `min_stop_atr=0.5`
# from `rules_30mof.py` widens a stop that landed on the structural key, and
# three years is what the POI entry frequency needs.
#
# 20 arms = 10 entry models x 2 sides, one shard each, 6 wide so the two market
# shards keep their cores.
set -u
cd "$(cd "$(dirname "$0")/.." && pwd)"
PY=./.venv/Scripts/python.exe
{
  for m in poi fvg fvg_full bpr ob stb; do for s in long short; do echo "1 $m $s"; done; done
  for m in poi_full bpr_full ob_full stb_full; do for s in long short; do echo "1b $m $s"; done; done
} | xargs -P 6 -L1 sh -c \
  '"'"$PY"'" scripts/run_30mof.py --stage $0 --bars 52600 \
     --start 2023-08-28T00:00:00Z --end 2026-08-27T00:00:00Z \
     --only $1 --side $2 --tag 3y_$1_$2 --of-lookback 8000 \
     > research/runs/logs/3y_$1_$2.log 2>&1; echo "done $1 $2 rc=$?"'
