# Aurora chorismate-mutase scaling runs

Scripts for two runs on Aurora, each pushing 300 chorismate mutase (CM) cases through the full MECHA + Reactra pipeline in one 12-hour prod job. Each case gets its own Codex agent that judges results and retries or relaunches its runs.

These are the exact scripts that were run. Paths are hard-coded to the Aurora project space (`/lus/flare/projects/FRAME-IDP/...`), so treat them as a record and reference, not a portable package.

## prod300/ (300-node pilot, Nov 2026)

One Reactra campaign per case, with agents on the GPU nodes through `hook.sh`.

- `cases.txt`: the 300 cases.
- `newcase.sh` and `setup.sh`: build each case's run folder and campaign.
- `drive.py` and `agent.md`: the dispatcher that wakes each case's agent, and the agent prompt.
- `act`: the only way an agent can change its case (retry or relaunch, with caps).
- `pass.sh`: runs one Reactra campaign pass.
- `guard.sh`: ends the run cleanly when the pilot finishes.
- `usage.sh`: logs CPU and memory on the pilot's nodes every 5 min.
- `shims/`: block agents from `qsub`/`qdel`, `reactra campaign`, and similar commands.
- `report/`: the results report, its data, and the plot scripts.

Results: 87 converged, 83 rough estimates, 73 still running, 57 failed. GPU about 45% busy, CPU about 4%. The main inefficiency was one campaign per case: Reactra only packs light stages onto shared nodes within one campaign.

## pack256/ (256-node packed pilot)

The same 300 cases in 25 shared campaigns of 12, so Reactra packs 12 light runs onto each node. Agents run CPU-only on a login node.

- `setup.py`: builds the 25 campaigns and the site config (prod queue, 256 nodes, 12 h).
- `bin/reactra`: wrapper for Reactra release ed519bc.
- The other files play the same roles as in prod300/. The dispatcher also runs the campaign passes, and an agent is woken only when a decision is needed.

## Notes

- GPU utilization comes from Reactra's pilot itself, which runs `xpu-smi dump` on every node every 60 s into `pool/pilots/<JOB>/telemetry/<node>.csv`.
- Agents use `muse-spark-bf16` through the ALCF inference endpoint, driven by the Codex SDK.
