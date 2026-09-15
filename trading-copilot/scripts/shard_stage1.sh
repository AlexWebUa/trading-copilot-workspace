#!/usr/bin/env bash
# Stage 1 sharded across processes — one shard per entry model, 2 arms each.
# The window is PINNED so every arm is scored on byte-identical data; the
# default "most recent N bars" path would give shard 1 and shard 7 windows that
# differ by however long the sweep ran.
set -u
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
PY=./.venv/Scripts/python.exe
START=2025-08-27T12:00:00Z
END=2026-08-27T00:00:00Z
MODELS="market poi fvg fvg_full bpr ob stb"
printf '%s\n' $MODELS | xargs -P 7 -I{} sh -c \
  "$PY scripts/run_30mof.py --bars 17520 --start $START --end $END --only {} --tag {} \
   > research/runs/logs/{}.log 2>&1; echo \"done {} rc=\$?\""
