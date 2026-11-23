#!/bin/bash
# Agent environment on a compute node (proxy, node-local CODEX_HOME) or a login node (test). Usage: run.sh ACC
D=/lus/flare/projects/FRAME-IDP/fkunnath/ma/prod300
source /lus/flare/projects/FRAME-IDP/fkunnath/ma/ma-env.sh >/dev/null
export MA_SITES=$D/sites.yaml MECHAGENT_REACTRA_SITES=$D/sites.yaml
case "$(hostname -s)" in
  aurora-uan-*) ;;
  *) export http_proxy=http://proxy.alcf.anl.gov:3128 https_proxy=http://proxy.alcf.anl.gov:3128
     export HTTP_PROXY=$http_proxy HTTPS_PROXY=$https_proxy no_proxy=localhost,127.0.0.1 NO_PROXY=localhost,127.0.0.1
     export CODEX_HOME=/tmp/codex-home-$USER-p300-$1; mkdir -p "$CODEX_HOME"; cp ~/.codex/*.toml "$CODEX_HOME"/ 2>/dev/null ;;
esac
export PATH=$HOME/codex-bench/.venv/bin:$PATH
unset ZE_AFFINITY_MASK
echo "=== $(date -u +%FT%TZ) driver $1 on $(hostname -s) job_end=${REACTRA_JOB_END:-none} qsub=$(command -v qsub || echo missing)"
"$HOME/codex-bench/.venv/bin/python" "$D/drive.py" "$@"
echo "=== $(date -u +%FT%TZ) driver exit=$?"
