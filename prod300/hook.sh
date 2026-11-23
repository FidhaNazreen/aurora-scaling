#!/bin/bash
# node_setup hook (every node of every ticket): start the case agent on this node (rank 0 only).
# agent.py waits up to 15 min for the per-case lock, so a newer ticket can take over from an older one.
[ "${PALS_RANKID:-${PMI_RANK:-0}}" = 0 ] || exit 0
D=/lus/flare/projects/FRAME-IDP/fkunnath/ma/prod300
[ -e $D/agents-off ] && exit 0
# The pilot points PBS_NODEFILE at <campaign>/jobs/<job>/nodes-<pilot>; the campaign is mech-xxxx-xxxx-xxx-<digest>.
camp=$(basename "$(dirname "$(dirname "$(dirname "${PBS_NODEFILE:-x/x/x/x}")")")")
ACC=$(echo "$camp" | awk -F- '{print toupper($1"-"$2"-"$3"-"$4)}')
[ -d "$D/cases/$ACC" ] || { echo "$(date -u +%T) $(hostname -s) no case for '$camp'" >> $D/logs/hook-miss.log; exit 0; }
[ -e "$D/cases/$ACC/agent/DONE" ] && exit 0
mkdir -p $D/logs/agents
REACTRA_JOB_END=${REACTRA_JOB_END:-} setsid nohup $D/run.sh "$ACC" >> "$D/logs/agents/$ACC.log" 2>&1 < /dev/null &
exit 0
