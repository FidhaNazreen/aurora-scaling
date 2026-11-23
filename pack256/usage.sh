#!/bin/bash
# Login-node usage logger (screen -S pack256-usage on aurora-uan-0010). Read-only: starts and kills nothing.
# Every 5 min, for each RUNNING pilot of this pool, it logs:
#   logs/usage/nodes.tsv  one row per node: CPU busy % (over 2 s), load, memory, agent and Reactra process counts
#   logs/usage/pilot.tsv  one row per pilot: nodes, tickets running and nodes busy (from events.jsonl), tickets queued
# GPU use is already recorded by the pilot itself: reactra/pool/pilots/JOB/telemetry/NODE.csv (xpu-smi, per tile).
# Exits after the guard logs "guard exits".
D=/lus/flare/projects/FRAME-IDP/fkunnath/ma/pack256
PY=/lus/flare/projects/FRAME-IDP/fkunnath/ma/venv/bin/python
U=$D/logs/usage; mkdir -p $U
[ -s $U/nodes.tsv ] || echo -e "ts\tjob\tnode\tcpu_busy_pct\tload1\tncpu\tmem_used_mib\tmem_total_mib\tn_codex\tn_python" > $U/nodes.tsv
[ -s $U/pilot.tsv ] || echo -e "ts\tjob\tnodes\ttickets_running\tnodes_busy\ttickets_queued" > $U/pilot.tsv
probe='read _ a b c d e f g h _ < <(head -1 /proc/stat); sleep 2; read _ A B C D E F G H _ < <(head -1 /proc/stat);
t=$(( (A+B+C+D+E+F+G+H)-(a+b+c+d+e+f+g+h) )); i=$(( (D+E)-(d+e) ));
echo "$(awk "BEGIN{printf \"%.1f\", 100*($t-$i)/$t}") $(cut -d" " -f1 /proc/loadavg) $(nproc) $(free -m | awk "/^Mem/{print \$3, \$2}") $(pgrep -c -f codex) $(pgrep -c python)"'
export probe
while true; do
  grep -q "guard exits" $D/logs/guard.log 2>/dev/null && { echo "$(date -u +%FT%TZ) guard exited; usage logger stops" >> $U/usage.log; break; }
  ts=$(date -u +%FT%TZ)
  ids=$(qstat -u "$USER" 2>/dev/null | awk -F. '$1 ~ /^[0-9]+$/ {print $1}')
  [ -n "$ids" ] && qstat -f -F json $ids 2>/dev/null | $PY -c '
import json,sys,re
j=json.load(sys.stdin).get("Jobs",{})
for k,v in j.items():
    if "/pack256/" in json.dumps(v) and v.get("job_state")=="R":
        hosts=sorted(set(re.findall(r"(x\w+)/", v.get("exec_host",""))))
        print(k.split(".")[0], " ".join(hosts))' > $U/.running || : > $U/.running
  while read -r job hosts; do
    [ -n "$job" ] || continue
    $PY - "$D" "$job" "$ts" "$(echo $hosts | wc -w)" >> $U/pilot.tsv <<'EOF'
import json,sys,glob,os
D,job,ts,n=sys.argv[1:]; run={}
p=f"{D}/reactra/pool/pilots/{job}/events.jsonl"
for l in (open(p) if os.path.exists(p) else []):
    try: e=json.loads(l)
    except Exception: continue
    if e.get("event")=="start_ticket": run[e["ticket"]]=len(e["nodes"])
    elif e.get("event")=="end": run.pop(e["ticket"],None)
print(f"{ts}\t{job}\t{n}\t{len(run)}\t{sum(run.values())}\t{len(glob.glob(D+'/reactra/pool/queue/*.json'))}")
EOF
    printf '%s\n' $hosts | xargs -P 48 -I{} bash -c 'o=$(timeout 25 ssh -o BatchMode=yes -o StrictHostKeyChecking=no -o ConnectTimeout=8 -o LogLevel=ERROR {} "$probe" 2>/dev/null) && printf "%s\t%s\t%s\t%s\n" "'$ts'" "'$job'" {} "$(echo $o | tr " " "\t")"' >> $U/nodes.tsv
  done < $U/.running
  echo "$ts sampled: $(awk '{print $1}' $U/.running | tr '\n' ' ')" >> $U/usage.log
  sleep 300
done
