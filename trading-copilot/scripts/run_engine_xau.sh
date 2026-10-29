#!/usr/bin/env bash
# The SetupRule setups on spot gold: Bellissimo, Silver Bullet, 30mOF.
#
#   bash scripts/run_engine_xau.sh bellissimo
#   bash scripts/run_engine_xau.sh silver_bullet
#   bash scripts/run_engine_xau.sh 30mof
#
# In-sample only: the window is the first two years of the research window and
# the source is capped at its end, so the held-out year is never loaded.
#
# Costs are the trader's forex.com account, 0.20 spread + 0.10 commission per
# round trip, as 0.6 bps a side — the engine only knows basis points. That is
# 0.30 on a price between 1900 and 3650: slightly generous late in the window,
# slightly harsh early. Limit entries would in fact fill a spread later than the
# engine assumes; at these stop sizes that is under 0.05R.
set -u
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
PY=./.venv/Scripts/python.exe
START=2023-09-14T00:00:00Z
END=2025-09-14T00:00:00Z
COST="--fee-bps 0.4 --slippage-bps 0.2"
LOGS=research/runs/logs
mkdir -p "$LOGS"

case "${1:-}" in
  bellissimo)
    printf '%s\n' bellissimo_1h3m_long bellissimo_1h3m_short \
                  bellissimo_1h3m_long_softfta bellissimo_1h3m_short_softfta |
      xargs -P 4 -I{} sh -c \
        "$PY scripts/run_costs_recheck.py --symbol XAUUSD --arms {} --tf 1h \
           --start $START --end $END $COST --tag xau_{} > $LOGS/xau_{}.log 2>&1; echo \"done {} rc=\$?\""
    ;;
  silver_bullet)
    for timing in london nyam nypm; do for mode in mkt test; do
      echo "sb_${timing}_${mode}_long,sb_${timing}_${mode}_short xau_sb_${timing}_${mode}"
    done; done |
      xargs -P 6 -L 1 sh -c \
        "$PY scripts/run_costs_recheck.py --symbol XAUUSD --arms \$0 --tf 15m \
           --start $START --end $END $COST --tag \$1 > $LOGS/\$1.log 2>&1; echo \"done \$1 rc=\$?\""
    ;;
  30mof)
    # Stage 1 (14 arms), stage 1b (8 full-fill arms) and the two market arms of
    # stage 2 against a flat 1.8R target — the same 24 arms BTC was scored on,
    # one process per entry model and side.
    for model in market poi fvg fvg_full bpr ob stb; do for side in long short; do
      echo "1 $model $side"
    done; done > "$LOGS/xau_30mof_shards.txt"
    for model in poi_full bpr_full ob_full stb_full; do for side in long short; do
      echo "1b $model $side"
    done; done >> "$LOGS/xau_30mof_shards.txt"
    for side in long short; do echo "2 market $side"; done >> "$LOGS/xau_30mof_shards.txt"
    xargs -P 7 -L 1 sh -c \
      "$PY scripts/run_30mof.py --symbol XAUUSD --tf 30m --stage \$0 --only \$1 --side \$2 \
         --start $START --end $END $COST --of-lookback 8000 --dump-trades --tag xau_\$1_\$2 \
         > $LOGS/xau_30mof_s\$0_\$1_\$2.log 2>&1; echo \"done \$0 \$1 \$2 rc=\$?\"" < "$LOGS/xau_30mof_shards.txt"
    ;;
  *)
    echo "usage: $0 bellissimo | silver_bullet | 30mof" >&2
    exit 2
    ;;
esac
