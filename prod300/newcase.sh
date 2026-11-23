#!/bin/bash
# newcase.sh ACCESSION [--submit]   (prod300 variant of bin/ma-newcase)
# Cases live in $MA/prod300/cases; site file prod300/sites.yaml (prod, 300 nodes, 12 h, driver hook).
# No .loop-active: the ma-ctl loop never sees these; the agent on each node drives them.
set -euo pipefail
export MA_SITES=/lus/flare/projects/FRAME-IDP/fkunnath/ma/prod300/sites.yaml
source /lus/flare/projects/FRAME-IDP/fkunnath/ma/ma-env.sh >/dev/null
S=$MA/prod300
ACC=${1:?usage: newcase.sh ACCESSION [--submit]}; MODE=${2:-}
M=$(ls "$MECH_DATASET"/collections/enzymes/entries/*/"$ACC"/"$ACC".mech 2>/dev/null | head -1)
[ -n "$M" ] || { echo "no MECH for $ACC"; exit 1; }
C=$S/cases/$ACC; RUN=kept-structure
if [ ! -e "$C/task.json" ]; then
  mechagent case start "$C" --mech "$M" \
    --objective 'Prod run: 300 CM cases, each driven by its own Codex SDK agent on its compute node' >/dev/null
fi
if [ ! -e "$C/reactra/runs/$RUN/run.yaml" ]; then
  T=$(mechagent "case" status "$C" --select /task/sha256 | tr -d "\"")
  mechagent reactra init "$C" --name "$RUN" --hypothesis 'as declared, from the kept cofold seed' --expect-sha256 "$T" >/dev/null
  R=$C/reactra/runs/$RUN/run.yaml
  ( cd "$MA/repos/reactra-golden-2026-11-17j" && "$MA/venv/bin/python" "$MA/bin/ma-aroq-block.py" "$R" . ) >/dev/null
  reactra validate --offline "$R" >/dev/null
fi
if [ "$MODE" = "--submit" ]; then
  mechagent reactra submit "$C" > "$C/submit.log" 2>&1
  date -u +%FT%TZ > "$C/.submitted"
else
  mechagent reactra submit "$C" --dry-run > "$C/dryrun.log" 2>&1
  grep -q "ready: a pass would find everything" "$C/dryrun.log"
fi
