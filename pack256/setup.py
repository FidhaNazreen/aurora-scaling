"""pack256 setup: the 300 prod300 cases in 25 shared Reactra campaigns of 12, on one packed 256-node pool.

Why 25 x 12: Reactra packs light-stage runs onto shared nodes (one tile each, 12 per node) only within
one campaign's job. 12 cases per campaign fill one node per light job; 25 small campaigns keep each
controller pass short and let passes run in parallel. Heavy (reaction sampling) runs get their own
tickets, as wide as their ensemble, from the shared pool.

Run inputs are copied from each prod300 case's original run folder (run.yaml + MECH + structures),
never its store, so every run starts fresh on release ed519bc.
Usage (on Aurora): python3 setup.py [--force]
"""
import json, shutil, sys
from pathlib import Path

MA = Path("/lus/flare/projects/FRAME-IDP/fkunnath/ma")
SRC = MA / "prod300"
D = MA / "pack256"
DK = Path("/lus/flare/projects/FRAME-IDP/dkastner/Projects")
REL = "ed519bc"
GROUP = 12

SITE = f"""sites:
  aurora-pack256:
    kind: aurora
    account: FRAME-IDP
    queue: prod                 # routes to prod small: 256-1024 nodes, <=12 h
    walltime: "12:00:00"
    max_jobs: 1                 # one pilot for the whole pool
    pilot_nodes: 256
    nodes_per_job: 1            # a light job is one node: up to 12 light runs, one tile each
    slots_per_node: 12
    root: {D}/reactra
    python: {DK}/reactra-sweep/venv-{REL}/bin/python
    node_setup:
      - module load frameworks/2026.1.0
      - export ZE_FLAT_DEVICE_HIERARCHY=FLAT TMPDIR=/tmp
    environment: {{OMP_NUM_THREADS: "8", HF_HUB_OFFLINE: "1", HF_HUB_DISABLE_TELEMETRY: "1"}}
    execution_profiles:
      cofold: {DK}/Reactra/deployments/release-1e9ac19/mol1.yaml
      boltz: {DK}/Reactra/candidates/mean-force-lab/engine-string/candidate-campaign-2f2bf76/boltz/profile.yaml
      unfolded: {DK}/Reactra/deployments/release-1e9ac19/unfolded.yaml
      solution: {DK}/Reactra/deployments/release-1e9ac19/solution.yaml
      prepared: {DK}/Reactra/deployments/release-1e9ac19/prepared.yaml
    assets:
      - {DK}/Reactra/assets
      - {DK}/Reactra-Boltz-Aurora-qualification-20261004-v1/.reactra/assets/boltz-2/boltz2_conf.ckpt
      - {DK}/Reactra-Boltz-Aurora-qualification-20261004-v1/.reactra/assets/boltz-2/mols.tar
      - {DK}/Reactra-Aurora-stack-20261004-v1/reactra/.reactra/assets/espaloma-0.3.2.pt
      - {DK}/Reactra-Aurora-stack-20261004-v1/reactra/.pixi/envs/parameterization/lib/python3.11/site-packages/propka/propka.cfg
      - {DK}/reactra-sweep/reactra-{REL}/src/reactra/data
    deployment_assets:
      hydration-assets.json: {DK}/Reactra-AroQ-from-start-20261009-v2/hydration-assets.aurora.json
"""


def main():
    force = "--force" in sys.argv
    cases = (SRC / "cases.txt").read_text().split()
    assert len(cases) == 300, len(cases)
    groups = [cases[i:i + GROUP] for i in range(0, len(cases), GROUP)]
    index = {}
    for g, accs in enumerate(groups, 1):
        gd = D / "groups" / f"g{g:02d}"
        if (gd / "campaign.yaml").exists() and not force:
            sys.exit(f"{gd} exists; pass --force to rebuild")
        runs = []
        for acc in accs:
            src = SRC / "cases" / acc / "reactra" / "runs" / "kept-structure"
            name = acc.lower()
            dst = gd / "runs" / name
            if dst.exists():
                shutil.rmtree(dst)
            dst.mkdir(parents=True)
            for f in src.iterdir():
                if f.is_file() and (f.suffix in (".yaml", ".mech", ".cif")):
                    shutil.copy2(f, dst / f.name)
            runs.append(f"- file: runs/{name}/run.yaml\n  variant_of: {acc}\n"
                        f"  hypothesis: as declared, from the kept cofold seed\n")
            index[acc] = {"group": f"g{g:02d}", "run": name}
            (D / "agents" / acc).mkdir(parents=True, exist_ok=True)
        (gd / "campaign.yaml").write_text(
            "# pack256 shared campaign: 12 CM cases packed on one node per light job. Agents add variants via act.\n"
            "schema_version: reactra.campaign/1\n"
            f"name: pack256-g{g:02d}\nruns:\n" + "".join(runs) +
            "archive: null\nretries: 2\n" + SITE)
    (D / "index.json").write_text(json.dumps(index, indent=1))
    (D / "cases.txt").write_text("\n".join(cases) + "\n")
    print(f"{len(groups)} campaigns, {len(index)} runs under {D}/groups")


if __name__ == "__main__":
    main()
