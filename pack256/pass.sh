#!/bin/bash
# pass.sh GROUP: one Reactra campaign pass of one pack256 group (the dispatcher's job, never an agent's).
D=/lus/flare/projects/FRAME-IDP/fkunnath/ma/pack256
G=${1:?usage: pass.sh GROUP}
[ -e $D/stop ] && { echo "stop file present: no pass"; exit 9; }
[ "${PACK256_DRIVER:-}" = 1 ] || { echo "refused in pack256: only the dispatcher runs campaign passes"; exit 3; }
mkdir -p $D/logs/passes; t0=$(date +%s)
out=$( (flock -w 600 9 || { echo "group lock busy"; exit 4; }; cd $D/groups/$G && timeout 900 $D/bin/reactra campaign campaign.yaml 2>&1) 9>$D/groups/$G/.lock ); rc=$?
dt=$(( $(date +%s) - t0 ))
echo -e "$(date -u +%FT%TZ)\t$G\t$rc\t$dt\t$(hostname -s)" >> $D/logs/passes.tsv
{ echo "=== $(date -u +%FT%TZ) rc=$rc ${dt}s"; echo "$out" | tail -10; } >> $D/logs/passes/$G.log
exit $rc
