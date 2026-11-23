# How the prod300 PBS job was launched

There is no hand-written PBS script. Reactra generates the pilot job and submits it with `qsub` the first time a campaign pass finds work waiting. In this run that first pass came from `setup.sh` running `newcase.sh --submit`.

## Files

| File | What it is |
|---|---|
| `sites.yaml` | The site file Reactra read. It sets the account, queue, walltime and node count, plus the steps to run on each node (`node_setup`, which includes `hook.sh`). |
| `job.sh` | The pilot script Reactra actually generated and submitted, copied unchanged from `reactra/pool/pilots/20261119T214312/job.sh`. |
| `pilot-equivalent.pbs` | The same job written as one ordinary PBS script, with `#PBS` lines, for reading. It was not submitted. |

## What Reactra ran

Reactra (release 64b98b4, `adapters/clusters.py`) submitted `job.sh` with the PBS settings on the command line:

```bash
qsub -A FRAME-IDP -q prod \
  -l select=300 -l walltime=12:00:00 \
  -l filesystems=home:flare -l place=scatter \
  -N <pilot name> -j oe -o <pilot folder>/pbs.log \
  <pilot folder>/job.sh
```

| Setting | Comes from |
|---|---|
| `-A`, `-q`, `walltime` | `account`, `queue`, `walltime` in `sites.yaml` |
| `select` | `pilot_nodes` in `sites.yaml` |
| `filesystems`, `place=scatter` | Reactra's built-in Aurora defaults |

## What happens inside the job

1. `job.sh` starts `campaign_pilot.py`, Reactra's pilot loop, for 43,200 s (12 h).
2. The pilot holds all 300 nodes. It takes tickets from the pool's queue and gives each one whole free nodes:
   - one node for a preprocessing step;
   - about 4 nodes for reaction sampling, one tile per ensemble member.
3. On a ticket's nodes, it runs the `node_setup` steps from `sites.yaml` through `mpiexec`, then the ticket's own `job.sh` (under `reactra/<campaign>/jobs/jNNNN/`).
4. `node_setup` includes `hook.sh`, which starts the case's agent on the ticket's first node.
5. The pilot stops claiming tickets 30 min before the walltime. It releases nodes that sit idle for 10 min.
6. At the end it writes a summary to `pbs.log`: busy fraction, tickets, exits and GPU telemetry.

