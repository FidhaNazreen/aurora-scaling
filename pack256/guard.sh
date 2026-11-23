#!/bin/bash
# Login-node guard (screen -S pack256): runs NO passes. Every 2 min logs the pool's pilot(s).
# Whichever starts runs; if the other also starts while it runs, it claims the tickets still waiting.
# Once ANY pilot has run and ended, every still-queued pilot of this pool is deleted (no second 12 h round).
# When no pilot of this pool is running any more, it creates the stop file and runs the post-pilot decisions
# (drive.py --finalize) on this node. Pilots of this pool are found by their job script path (.../pack256/...).
D=/lus/flare/projects/FRAME-IDP/fkunnath/ma/pack256
PY=/lus/flare/projects/FRAME-IDP/fkunnath/ma/venv/bin/python
mkdir -p $D/logs; seen=" "
pilots() { ids=$(qstat -u "$USER" 2>/dev/null | awk -F. '$1 ~ /^[0-9]+$/ {print $1}'); [ -n "$ids" ] || return; qstat -f -F json $ids 2>/dev/null | $PY -c '
import json,sys
try: j=json.load(sys.stdin).get("Jobs",{})
except Exception: print("ERR"); j={}
for k,v in j.items():
    if "/pack256/" in json.dumps(v): print(k.split(".")[0], v.get("job_state"), v.get("queue"))'; }
while true; do
  # PBS unreachable: never read an empty answer as "pilot ended"
  qstat -u "$USER" >/dev/null 2>&1 || { echo "$(date -u +%FT%TZ) qstat failed" >> $D/logs/guard.log; sleep 120; continue; }
  p=$(pilots); echo "$(date -u +%FT%TZ) ${p:-none}" | tr '\n' ' ' >> $D/logs/guard.log; echo >> $D/logs/guard.log
  echo "$p" | grep -q ERR && { sleep 120; continue; }
  running=$(echo "$p" | awk '$2=="R"{print $1}')
  for j in $running; do case "$seen" in *" $j "*) ;; *) seen="$seen$j "; echo "$(date -u +%FT%TZ) pilot $j running" >> $D/logs/guard.log;; esac; done
  ended=""; for j in $seen; do echo "$running" | grep -qx "$j" || ended="$ended $j"; done
  if [ -n "$ended" ]; then
    for j in $(echo "$p" | awk '$2=="Q" || $2=="H"{print $1}'); do
      echo "$(date -u +%FT%TZ) pilot(s)$ended ended; deleting queued pilot $j" >> $D/logs/guard.log; qdel "$j"
    done
    if [ -z "$running" ]; then
      touch $D/stop
      echo "$(date -u +%FT%TZ) no pilot running ($seen); stop file set; finalizing open cases" >> $D/logs/guard.log
      # Decisions the pilot ended before: decide each open case on its last outcome, actions disabled (no pass, no pilot).
      $D/run.sh --finalize
      echo "$(date -u +%FT%TZ) finalize done ($(ls $D/agents/*/DONE 2>/dev/null | wc -l) cases decided); guard exits" >> $D/logs/guard.log; break
    fi
  fi
  sleep 120
done
