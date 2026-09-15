#!/usr/bin/env bash
set -u
cd "$(cd "$(dirname "$0")/.." && pwd)"
printf '%s\n' long short | xargs -P 2 -I{} sh -c \
  "./.venv/Scripts/python.exe scripts/run_costs_recheck.py \
     --arms bellissimo_1h3m_{} --tag bellissimo_{} \
     > research/runs/logs/bellissimo_costs_{}.log 2>&1; echo \"done {} rc=\$?\""
