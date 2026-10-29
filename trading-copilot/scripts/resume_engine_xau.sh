#!/usr/bin/env bash
# What was left of the gold engine runs when they were paused on 2026-10-06.
#
#   bash scripts/resume_engine_xau.sh
#
# Eight arms whose processes never started in the first batch (rc=127: too many
# launched at once), then the random-entry control for everything that kept its
# trades. Four processes at a time, not seven-plus-four: that overload is what
# the failures came from. About 30 minutes.
#
# An arm that already has a result file is skipped, so this is safe to re-run.
set -u
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
PY=./.venv/Scripts/python.exe
START=2023-09-14T00:00:00Z
END=2025-09-14T00:00:00Z
COST="--fee-bps 0.4 --slippage-bps 0.2"
LOGS=research/runs/logs
RUNS=research/runs
mkdir -p "$LOGS"

# 30mOF shards: stage, entry model, side.
printf '%s\n' "1 bpr short" "1 stb long" "1 stb short" "1b poi_full short" "2 market short" |
  while read -r stage model side; do
    [ -s "$RUNS/30mof_stage${stage}_xau_${model}_${side}.json" ] || echo "$stage $model $side"
  done |
  xargs -P 4 -L 1 sh -c \
    "$PY scripts/run_30mof.py --symbol XAUUSD --tf 30m --stage \$0 --only \$1 --side \$2 \
       --start $START --end $END $COST --of-lookback 8000 --dump-trades --tag xau_\$1_\$2 \
       > $LOGS/xau_30mof_s\$0_\$1_\$2.log 2>&1; echo \"done \$0 \$1 \$2 rc=\$?\""

# Bellissimo arms re-run with their trades kept, for the control.
printf '%s\n' bellissimo_1h3m_long_softfta bellissimo_1h3m_short bellissimo_1h3m_short_softfta |
  while read -r arm; do
    [ -s "$RUNS/costs_recheck_xau_ctl_${arm}.json" ] || echo "$arm"
  done |
  xargs -P 3 -I{} sh -c \
    "$PY scripts/run_costs_recheck.py --symbol XAUUSD --arms {} --tf 1h --start $START --end $END \
       $COST --dump-trades --tag xau_ctl_{} > $LOGS/xau_ctl_{}.log 2>&1; echo \"done {} rc=\$?\""

# Every arm against a same-side random entry (RESEARCH_PROTOCOL 2.5).
$PY scripts/engine_control.py --symbol XAUUSD --tf 3m --tag xau_bellissimo \
    --files "$RUNS/costs_recheck_xau_ctl_bellissimo_*.json"
for timing in "nyam 10,11" "nypm 14,15"; do
  set -- $timing
  $PY scripts/engine_control.py --symbol XAUUSD --tf 3m --tag "xau_sb_$1" --hours-ny "$2" \
      --files "$RUNS/costs_recheck_xau_ctl_sb_$1_*.json"
done
$PY scripts/engine_control.py --symbol XAUUSD --tf 30m --tag xau_30mof \
    --files "$RUNS/30mof_stage*_xau_*.json"
