#!/usr/bin/env bash
# Resume the three-year POI sweep: runs only the arms whose shard file is
# missing, so it is safe to run repeatedly and safe to interrupt.
#
# Interrupting is cheap by construction — each shard is ONE arm and writes its
# JSON only on completion, so a killed shard leaves no partial file and no
# half-written result. The cost of a stop is the compute of whatever was
# in flight, never data.
#
#   bash scripts/resume_poi_3y.sh          # run the missing arms
#   bash scripts/resume_poi_3y.sh --dry    # just list what is missing
#
# -P defaults to 6; pass a number as the first argument to change it.
set -u
cd "$(cd "$(dirname "$0")/.." && pwd)"
PY=./.venv/Scripts/python.exe
START=2023-08-28T00:00:00Z
END=2026-08-27T00:00:00Z
BARS=52600

DRY=0
PAR=6
for a in "$@"; do
  case "$a" in
    --dry) DRY=1 ;;
    [0-9]*) PAR="$a" ;;
  esac
done

missing=""
add() {   # stage model side
  f="research/runs/30mof_stage$1_3y_$2_$3.json"
  if [ -f "$f" ]; then
    printf 'есть      %s %s %s\n' "$1" "$2" "$3"
  else
    printf 'НУЖЕН     %s %s %s\n' "$1" "$2" "$3"
    missing="$missing$1 $2 $3
"
  fi
}

for m in market poi fvg fvg_full bpr ob stb; do
  for s in long short; do add 1 "$m" "$s"; done
done
for m in poi_full bpr_full ob_full stb_full; do
  for s in long short; do add 1b "$m" "$s"; done
done

n=$(printf '%s' "$missing" | grep -c . || true)
echo
if [ "$n" -eq 0 ]; then
  echo "Всё посчитано. Мержить:"
  echo "  $PY scripts/merge_shards.py --stage 1  --prefix 3y_ --by-side"
  echo "  $PY scripts/merge_shards.py --stage 1b --prefix 3y_ --by-side"
  echo "  $PY scripts/analyse_30mof.py --prefix 3y_"
  exit 0
fi
echo "Осталось арм: $n  (~43 мин каждая, по $PAR параллельно)"
[ "$DRY" -eq 1 ] && exit 0

printf '%s' "$missing" | xargs -P "$PAR" -L1 sh -c \
  '"'"$PY"'" scripts/run_30mof.py --stage $0 --bars '"$BARS"' \
     --start '"$START"' --end '"$END"' \
     --only $1 --side $2 --tag 3y_$1_$2 --of-lookback 8000 \
     > research/runs/logs/3y_$1_$2.log 2>&1; echo "done $1 $2 rc=$?"'
