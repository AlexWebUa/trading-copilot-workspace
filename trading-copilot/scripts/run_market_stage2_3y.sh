#!/usr/bin/env bash
# Stage 2 on the market arms: flat 1.8R target instead of the nearest fractal.
#
# Labelled DESCRIPTIVE, not confirmatory. Stage 2 was designed to run only on
# entry models that survived stage 1, so that it would be a semi-independent
# confirmation. Nothing survived. These two arms answer a different and still
# useful question — does this setup do better taking a fixed 1.8R than reaching
# for the next unswept fractal — and they must not be read as a fresh shot at
# finding edge.
set -u
cd "$(cd "$(dirname "$0")/.." && pwd)"
PY=./.venv/Scripts/python.exe
printf '%s\n' long short | xargs -P 2 -I{} sh -c \
  "$PY scripts/run_30mof.py --stage 2 --bars 52600 \
     --start 2023-08-28T00:00:00Z --end 2026-08-27T00:00:00Z \
     --only market --side {} --tag 3y_market_{} --of-lookback 8000 \
     > research/runs/logs/3y_s2_market_{}.log 2>&1; echo \"done {} rc=\$?\""
