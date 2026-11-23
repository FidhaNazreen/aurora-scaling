"""pack256 dispatcher: one CPU-only agent per enzyme, all driving runs in 25 shared, packed Reactra campaigns.

Runs on a login node (screen pack256-drive), not on GPU nodes: agents use no compute-node resources.
- Every 5 min the SCRIPT runs one pass of each group campaign (pass.sh, flock per group, 8 at a time).
- After the passes it reads every run summary and wakes an enzyme's agent only when there is
  something to decide (fresh Codex thread, at most CONC turns at once):
    succeeded    every run of the enzyme ended and one succeeded      -> analyze, checkpoint
    needs-agent  every run of the enzyme ended, none succeeded        -> relaunch / retry / defer
    check        a run is stalled or waits on its site (by "site"),   -> retry or wait
                 at most every 30 min per enzyme
  Healthy active runs wake no agent (that was 91% of prod300's turns).
- An agent acts only through `act` (caps: 2 relaunches, 3 retries per enzyme); shims block passes,
  campaign edits and PBS commands.
- Passes stop 10 min before the pilot's end, so no pass asks for a replacement pilot.
Modes: default = drive; --finalize = after the pilot (from guard.sh): decide open enzymes on their
last outcome with actions disabled, or record them unfinished.
"""
import argparse, asyncio, csv, json, os, socket, subprocess, sys, time
from pathlib import Path

MA = Path("/lus/flare/projects/FRAME-IDP/fkunnath/ma")
D = MA / "pack256"
SKILL = MA / "repos/mecha/skills/mechagent/SKILL.md"
sys.path.insert(0, str(MA / "agents"))
from cmagent import codex_config  # noqa: E402

EVERY, CHECK, CONC, PASS_CONC, ACT_MIN_LEFT, NO_PASS_BEFORE_END = 300, 1800, 8, 8, 2700, 600
WALL = 12 * 3600
TERMINAL = ("succeeded", "failed", "withdrawn")
FIELDS = ["case", "turn", "trigger", "t_submit", "latency_s", "status", "error", "input_tokens",
          "cached_input_tokens", "output_tokens", "n_commands", "can_act", "action", "final_response"]
INDEX = json.loads((D / "index.json").read_text())


def log(msg):
    print(f"[{time.strftime('%FT%T')}] {msg}", flush=True)


def pilot():
    """(job, state, start_epoch) of this pool's pilot, or None."""
    try:
        ids = [l.split(".")[0] for l in subprocess.run(["qstat", "-u", os.environ["USER"]], capture_output=True,
               text=True, timeout=60).stdout.splitlines() if l.split(".")[0].isdigit()]
        if not ids:
            return None
        j = json.loads(subprocess.run(["qstat", "-f", "-F", "json", *ids], capture_output=True, text=True,
                                      timeout=60).stdout).get("Jobs", {})
    except Exception:
        return "unknown"
    best = None
    for k, v in j.items():
        if "/pack256/" in json.dumps(v):
            st = v.get("stime")
            t = time.mktime(time.strptime(st, "%a %b %d %H:%M:%S %Y")) if st else None
            cand = (k.split(".")[0], v.get("job_state"), t)
            if best is None or cand[1] == "R":
                best = cand
    return best


def runs_of(acc):
    g = D / "groups" / INDEX[acc]["group"]
    out = []
    for p in sorted((g / "summary").glob("*.json")):
        try:
            j = json.loads(p.read_text())
        except Exception:
            continue
        if j.get("variant_of") == acc or p.stem.startswith(INDEX[acc]["run"]):
            out.append({k: j.get(k) for k in ("run", "state", "next_stage", "variant_of", "hypothesis", "outcome",
                                               "result", "next_action")} | {"file": str(p)})
    return out


def trigger_for(acc, runs, last_check):
    if not runs:
        return None
    states = [r["state"] for r in runs]
    if all(s in TERMINAL for s in states):
        return "succeeded" if any(r["state"] == "succeeded" and r["result"] for r in runs) else "needs-agent"
    wants = any(r["state"] == "stalled" or (r["next_action"] or {}).get("by") == "site" for r in runs)
    if wants and time.time() - last_check.get(acc, 0) >= CHECK:
        return "check"
    return None


def count(acc, pattern):
    return len(list((D / "agents" / acc).glob(pattern)))


async def run_pass(group, sem):
    async with sem:
        p = await asyncio.create_subprocess_exec(str(D / "pass.sh"), group, env={**os.environ, "PACK256_DRIVER": "1"},
                                                 stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT)
        await p.communicate()
        return group, p.returncode


async def turn(codex, acc, trigger, runs, can_act, minutes_left, args, sem):
    from openai_codex import ApprovalMode, Sandbox
    async with sem:
        ag = D / "agents" / acc
        k = count(acc, "turn-*.json")
        out = ag / f"turn-{k}.json"
        prev = sorted(ag.glob("turn-*.json"), key=lambda p: p.stat().st_mtime)
        flag = ag / ".can-act"
        flag.touch() if can_act else flag.unlink(missing_ok=True)
        g = D / "groups" / INDEX[acc]["group"]
        prompt = (D / "agent.md").read_text().format(
            acc=acc, case=ag, group=g, run=INDEX[acc]["run"], trigger=trigger, out=out,
            summaries=json.dumps(runs, indent=1)[:7000], prev=prev[-1].read_text()[:2500] if prev else "(none: first turn)",
            relaunches=count(acc, "relaunch-*"), retries=count(acc, "retry-*"), skill=SKILL, minutes_left=minutes_left,
            can_act="yes" if can_act else "NO (actions are disabled: decide analyzed, deferred or wait)")
        t1 = time.time()
        row = dict(case=acc, turn=k, trigger=trigger, t_submit=round(t1), status="", error="", input_tokens=0,
                   cached_input_tokens=0, output_tokens=0, n_commands=0, can_act=int(can_act), action="", final_response="")
        try:
            th = await codex.thread_start(model=args.model, model_provider=args.provider, cwd=str(ag),
                                          sandbox=Sandbox("full-access"), approval_mode=ApprovalMode.deny_all)
            r = await asyncio.wait_for(th.run(prompt), timeout=args.turn_timeout)
            row["status"] = r.status.value
            row["error"] = repr(r.error)[:300] if r.error else ""
            if r.usage:
                u = r.usage.total
                row.update(input_tokens=u.input_tokens, cached_input_tokens=u.cached_input_tokens, output_tokens=u.output_tokens)
            row["n_commands"] = sum(getattr(i.root, "type", "") == "commandExecution" for i in r.items or [])
            row["final_response"] = (r.final_response or "")[:160].replace("\n", " ")
        except Exception as e:
            row["status"], row["error"] = "exception", repr(e)[:300]
        finally:
            flag.unlink(missing_ok=True)
        row["latency_s"] = round(time.time() - t1, 1)
        try:
            row["action"] = json.loads(out.read_text()).get("action", "")
        except Exception:
            row["action"] = "no-file"
        p = D / "logs" / "turns" / f"{acc}.csv"
        p.parent.mkdir(parents=True, exist_ok=True)
        new = not p.exists()
        with p.open("a", newline="") as fh:
            w = csv.DictWriter(fh, FIELDS, extrasaction="ignore")
            if new:
                w.writeheader()
            w.writerow(row)
        log(f"{acc} turn {k} [{trigger}] {row['status']} {row['latency_s']}s action={row['action']} :: {row['final_response'][:70]}")
        return acc, trigger, row["action"]


def key_of(acc, trigger, runs):
    return f"{trigger}-r{len(runs)}-t{count(acc, 'retry-*')}-" + ",".join(f"{r['run']}:{r['state']}" for r in runs)


async def main_async(args):
    from openai_codex import AsyncCodex
    (D / "logs" / "turns").mkdir(parents=True, exist_ok=True)
    os.environ["PATH"] = f"{D}/shims:{D}:{MA}/venv/bin:" + os.environ["PATH"]
    accs = (D / "cases.txt").read_text().split()
    groups = sorted(p.name for p in (D / "groups").iterdir() if (p / "campaign.yaml").exists())
    last_check, seen_running = {}, False
    tsem, psem = asyncio.Semaphore(CONC), asyncio.Semaphore(PASS_CONC)
    async with AsyncCodex(config=codex_config()) as codex:
        while not (D / "stop").exists():
            t1 = time.time()
            pl = pilot()
            running = isinstance(pl, tuple) and pl[1] == "R" and pl[2]
            if running:
                seen_running = True
            elif seen_running and pl != "unknown":
                log("pilot no longer running: dispatcher stops (guard.sh finalizes)"); break
            end = (pl[2] + WALL) if running else None
            if end and time.time() > end - NO_PASS_BEFORE_END:
                log("within 10 min of the pilot's end: no more passes"); await asyncio.sleep(60); continue
            res = await asyncio.gather(*(run_pass(g, psem) for g in groups))
            bad = [g for g, rc in res if rc not in (0, 3, 4)]
            log(f"passes done in {time.time() - t1:.0f}s; pilot={pl}; non-ok groups={bad}")
            left = (end - time.time()) if end else WALL
            jobs = []
            for acc in accs:
                ag = D / "agents" / acc
                if (ag / "DONE").exists():
                    continue
                runs = runs_of(acc)
                trig = trigger_for(acc, runs, last_check)
                if not trig:
                    continue
                key = key_of(acc, trig, runs)
                handled = (ag / "handled.txt").read_text() if (ag / "handled.txt").exists() else ""
                if trig != "check" and key in handled:
                    (ag / "DONE").write_text(f"unresolved: outcome {key} repeated after a decision\n"); continue
                last_check[acc] = time.time()
                jobs.append((acc, trig, runs, key))
            if jobs:
                log(f"waking {len(jobs)} agents: " + ", ".join(f"{a}:{t}" for a, t, _, _ in jobs[:12]))
                done = await asyncio.gather(*(turn(codex, a, t, r, left > ACT_MIN_LEFT, int(left / 60), args, tsem)
                                              for a, t, r, _ in jobs))
                for (acc, trig, runs, key), (_, _, act) in zip(jobs, done):
                    ag = D / "agents" / acc
                    if trig != "check":
                        with (ag / "handled.txt").open("a") as fh:
                            fh.write(f"{key} {act}\n")
                        if act in ("analyzed", "deferred"):
                            (ag / "DONE").write_text(f"{act} ({trig})\n")
            await asyncio.sleep(max(0, EVERY - (time.time() - t1)))


async def finalize_async(args):
    from openai_codex import AsyncCodex
    os.environ["PATH"] = f"{D}/shims:{D}:{MA}/venv/bin:" + os.environ["PATH"]
    tsem = asyncio.Semaphore(CONC)
    jobs = []
    for acc in (D / "cases.txt").read_text().split():
        ag = D / "agents" / acc
        if (ag / "DONE").exists():
            continue
        runs = runs_of(acc)
        trig = trigger_for(acc, runs, {acc: time.time()})
        handled = (ag / "handled.txt").read_text() if (ag / "handled.txt").exists() else ""
        if trig in ("succeeded", "needs-agent") and key_of(acc, trig, runs) not in handled:
            jobs.append((acc, trig, runs))
        else:
            (ag / "final.json").write_text(json.dumps({"case": acc, "state": "unfinished at pilot end", "runs": runs}))
    async with AsyncCodex(config=codex_config()) as codex:
        done = await asyncio.gather(*(turn(codex, a, t, r, False, 0, args, tsem) for a, t, r in jobs))
    for (acc, trig, runs), (_, _, act) in zip(jobs, done):
        if act in ("analyzed", "deferred"):
            (D / "agents" / acc / "DONE").write_text(f"{act} ({trig}, finalize)\n")
    log(f"finalize: {len(jobs)} decided, others recorded unfinished")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--finalize", action="store_true")
    ap.add_argument("--turn-timeout", type=float, default=1500)
    ap.add_argument("--model", default="muse-spark-bf16")
    ap.add_argument("--provider", default="alcf-inference-service-tara-api")
    ap.add_argument("--smoke", metavar="ACC", help="one test turn (actions disabled) for ACC, then exit")
    args = ap.parse_args()
    log(f"dispatcher start host={socket.gethostname()} finalize={args.finalize} smoke={args.smoke}")
    if args.smoke:
        async def smoke():
            from openai_codex import AsyncCodex
            os.environ["PATH"] = f"{D}/shims:{D}:{MA}/venv/bin:" + os.environ["PATH"]
            async with AsyncCodex(config=codex_config()) as codex:
                print(await turn(codex, args.smoke, "check", runs_of(args.smoke), False, 720, args, asyncio.Semaphore(1)))
        asyncio.run(smoke()); return
    asyncio.run(finalize_async(args) if args.finalize else main_async(args))


if __name__ == "__main__":
    main()
