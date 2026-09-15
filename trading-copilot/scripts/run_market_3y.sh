#!/usr/bin/env bash
# 30mOF market arms over three years, sharded by side.
#
# Only the market arms: run 1 showed the POI arms measured degenerate fills,
# and those are re-run after the stop floor lands, not before. Market entries
# were unaffected (median stop $550, 6% under $150).
#
# lookback=8000 instead of the full walk — verified to reproduce it exactly on
# the research year (research/runs/of_lookback.json, 500 slices, every field
# 100%), and it is what makes three years affordable: the sweep goes from
# quadratic to linear, ~50 min per arm instead of ~2.7 h.
#
# The floor (min_stop_atr 0.5) is ON here, per the trader's decision of
# 2026-08-27, so these numbers are NOT comparable to run 1's market arms.
set -u
cd "$(cd "$(dirname "$0")/.." && pwd)"
PY=./.venv/Scripts/python.exe
printf '%s\n' long short | xargs -P 2 -I{} sh -c \
  "$PY scripts/run_30mof.py --bars 52600 \
     --start 2023-08-28T00:00:00Z --end 2026-08-27T00:00:00Z \
     --only market --side {} --tag 3y_market_{} \
     --of-lookback 8000 \
     > research/runs/logs/3y_{}.log 2>&1; echo \"done {} rc=\$?\""
