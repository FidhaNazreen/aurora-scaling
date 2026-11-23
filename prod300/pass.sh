#!/bin/bash
# pass.sh ACC [driver|finalize]: one Reactra campaign pass for one prod300 case (the driver's job, never the agent's).
D=/lus/flare/projects/FRAME-IDP/fkunnath/ma/prod300
ACC=${1:?usage: pass.sh ACC}; BY=${2:-driver}
[ -e $D/stop ] && { echo "stop file present: no pass"; exit 9; }
[ "${PROD300_DRIVER:-}" = 1 ] || { echo "refused in prod300: only the driver runs campaign passes"; exit 3; }
source /lus/flare/projects/FRAME-IDP/fkunnath/ma/ma-env.sh >/dev/null
export MA_SITES=$D/sites.yaml MECHAGENT_REACTRA_SITES=$D/sites.yaml
t0=$(date +%s)
out=$(timeout 600 /lus/flare/projects/FRAME-IDP/fkunnath/ma/venv/bin/reactra campaign "$D/cases/$ACC/reactra/campaign.yaml" 2>&1); rc=$?
dt=$(( $(date +%s) - t0 )); mkdir -p $D/logs/passes
echo -e "$(date -u +%FT%TZ)\t$ACC\t$rc\t$dt\t$(hostname -s)\t$BY" >> $D/logs/passes.tsv
{ echo "=== $(date -u +%FT%TZ) $(hostname -s) rc=$rc ${dt}s"; echo "$out" | tail -8; } >> $D/logs/passes/$ACC.log
echo "$out" | tail -8 > $D/cases/$ACC/last-pass.txt
echo "$out" | tail -15; exit $rc
