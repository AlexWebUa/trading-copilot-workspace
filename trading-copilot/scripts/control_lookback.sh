#!/usr/bin/env bash
# Control: does lookback=8000 reproduce run 1's market arms exactly?
# Floor OFF (--min-stop-atr 0) so this isolates the lookback change; run 1 had
# no floor. Must match n=48 / E=+0.123 and n=59 / E=-0.311 to the digit.
set -u
cd "$(cd "$(dirname "$0")/.." && pwd)"
PY=./.venv/Scripts/python.exe
printf '%s\n' long short | xargs -P 2 -I{} sh -c \
  "$PY scripts/run_30mof.py --bars 17520 \
     --start 2025-08-27T12:00:00Z --end 2026-08-27T00:00:00Z \
     --only market --side {} --tag ctl8000_{} \
     --of-lookback 8000 --min-stop-atr 0 \
     > research/runs/logs/ctl8000_{}.log 2>&1; echo \"done {} rc=\$?\""
