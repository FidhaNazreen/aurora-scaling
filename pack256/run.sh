#!/bin/bash
# run.sh [--finalize]: start the pack256 dispatcher on a login node (screen pack256-drive). Agents use no GPU node.
D=/lus/flare/projects/FRAME-IDP/fkunnath/ma/pack256
source /lus/flare/projects/FRAME-IDP/fkunnath/ma/ma-env.sh >/dev/null
export PATH=$HOME/codex-bench/.venv/bin:$PATH
mkdir -p $D/logs
echo "=== $(date -u +%FT%TZ) dispatcher on $(hostname -s) $*" >> $D/logs/drive.log
"$HOME/codex-bench/.venv/bin/python" "$D/drive.py" "$@" >> $D/logs/drive.log 2>&1
echo "=== $(date -u +%FT%TZ) dispatcher exit=$?" >> $D/logs/drive.log
