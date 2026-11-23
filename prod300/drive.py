"""prod300 driver: one per case, on the compute node holding the case's Reactra ticket.

Lessons from drive250 built in:
- The SCRIPT runs the campaign pass every 5 min (pass.sh, by=driver) and hands its output to the agent.
  Agents never run passes, so they can't double them or cut them short with their own timeouts.
- The AGENT reasons and acts, through `act` only (status / relaunch / submit / retry / checkpoint), with caps
  enforced in `act` (2 relaunches, 3 retries per case). Shims first on PATH refuse the dangerous commands
  (`mechagent reactra status|watch|adopt|submit`, `reactra campaign`, qsub/qdel).
- Each turn is a fresh Codex thread; the previous decision file is its memory.
- A "deferred" or "analyzed" decision ends the case only after a real outcome (pass exit 0 / 4, or 3 pass
  errors in a row seen by the driver). Deferring a run that is still active is overridden and logged.

When the agent is woken (trigger):
  succeeded    pass exit 0: every run succeeded        -> analyze, checkpoint
  needs-agent  pass exit 4: runs ended, some need one   -> read summary next_action; relaunch / retry / defer
  pass-error   3 failed passes in a row                 -> diagnose; retry or defer
  check        every 30 min while the run is active     -> health check; may retry a stalled run
Modes: default = drive until 5 min before the ticket's REACTRA_JOB_END; --finalize = after the pilot, no pass,
decide on the last recorded outcome with actions disabled (no pilot to run them).
"""
import argparse, asyncio, csv, json, os, shutil, socket, sys, time
from pathlib import Path

MA = Path("/lus/flare/projects/FRAME-IDP/fkunnath/ma")
D = MA / "prod300"
SKILL = MA / "repos/mecha/skills/mechagent/SKILL.md"
sys.path.insert(0, str(MA / "agents"))
from cmagent import codex_config  # noqa: E402

EVERY, CHECK, STOP_BEFORE_END, ERR_STREAK, ACT_MIN_LEFT = 300, 1800, 300, 3, 2700
OUTCOME = ("succeeded", "needs-agent", "pass-error")
FINAL = ("analyzed", "deferred")
FIELDS = ["case", "turn", "trigger", "pass_rc", "host", "t_submit", "latency_s", "status", "error", "input_tokens",
          "cached_input_tokens", "output_tokens", "n_commands", "can_act", "action", "final_response"]


def log(acc, msg):
    print(f"[{time.strftime('%FT%T')}] {acc} {msg}", flush=True)


def take_lock(lock, wait_s):
    lock.parent.mkdir(parents=True, exist_ok=True)
    t_end = time.time() + wait_s
    while True:
        try:
            if time.time() - lock.stat().st_mtime > 180:
                shutil.rmtree(lock, ignore_errors=True)
        except FileNotFoundError:
            pass
        try:
            lock.mkdir()
            (lock / "owner").write_text(f"{socket.gethostname()} {os.getpid()} {time.strftime('%FT%T')}\n")
            return True
        except FileExistsError:
            if time.time() >= t_end:
                return False
            time.sleep(30)


async def beat(lock):
    while True:
        try:
            os.utime(lock)
        except FileNotFoundError:
            pass
        await asyncio.sleep(30)


async def run_pass(acc):
    p = await asyncio.create_subprocess_exec(str(D / "pass.sh"), acc, "driver", env={**os.environ, "PROD300_DRIVER": "1"},
                                             stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT)
    out = (await p.communicate())[0].decode(errors="replace")
    return p.returncode, "\n".join(out.strip().splitlines()[-15:])


def last_logged_rc(acc):
    rc, p = None, D / "logs" / "passes.tsv"
    for line in (p.read_text().splitlines() if p.exists() else []):
        f = line.split("\t")
        if len(f) > 2 and f[1] == acc:
            rc = int(f[2])
    return rc


def summaries(acc):
    """Reactra's per-run records, trimmed to what a decision needs."""
    out = []
    for p in sorted((D / "cases" / acc / "reactra" / "summary").glob("*.json")):
        try:
            j = json.loads(p.read_text())
        except Exception:
            continue
        out.append({k: j.get(k) for k in ("run", "state", "next_stage", "site", "variant_of", "hypothesis",
                                          "outcome", "result", "next_action")} | {"file": str(p)})
    return json.dumps(out, indent=1)[:6000] if out else "(no run summaries yet)"


def count(acc, pattern):
    return len(list((D / "cases" / acc / "agent").glob(pattern)))


def runs_count(acc):
    return len(list((D / "cases" / acc / "reactra" / "runs").glob("*/run.yaml")))


async def turn(codex, acc, k, trigger, rc, tail, can_act, minutes_left, w, args):
    from openai_codex import ApprovalMode, Sandbox
    case = D / "cases" / acc
    ag = case / "agent"
    out = ag / f"turn-{k}.json"
    prev = sorted(ag.glob("turn-*.json"), key=lambda p: p.stat().st_mtime)
    flag = ag / ".can-act"
    flag.touch() if can_act else flag.unlink(missing_ok=True)
    prompt = (D / "agent.md").read_text().format(
        acc=acc, case=case, k=k, trigger=trigger, rc=rc, tail=tail or "(no pass this turn)", out=out,
        prev=prev[-1].read_text()[:2500] if prev else "(none: first turn)", summaries=summaries(acc),
        relaunches=count(acc, "relaunch-*"), retries=count(acc, "retry-*"), skill=SKILL,
        can_act="yes" if can_act else "NO (actions are disabled: decide analyzed, deferred or wait)",
        minutes_left=minutes_left)
    t1 = time.time()
    row = dict(case=acc, turn=k, trigger=trigger, pass_rc=rc, host=socket.gethostname(), t_submit=round(t1),
               status="", error="", input_tokens=0, cached_input_tokens=0, output_tokens=0, n_commands=0,
               can_act=int(can_act), action="", final_response="")
    try:
        th = await codex.thread_start(model=args.model, model_provider=args.provider, cwd=str(case),
                                      sandbox=Sandbox("full-access"), approval_mode=ApprovalMode.deny_all)
        r = await asyncio.wait_for(th.run(prompt), timeout=args.turn_timeout)
        row["status"] = r.status.value
        row["error"] = repr(r.error)[:300] if r.error else ""
        if r.usage:
            u = r.usage.total
            row.update(input_tokens=u.input_tokens, cached_input_tokens=u.cached_input_tokens,
                       output_tokens=u.output_tokens)
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
    w.writerow(row)
    log(acc, f"turn {k} [{trigger} rc={rc}] {row['status']} {row['latency_s']}s action={row['action']} "
             f":: {row['final_response'][:80]}")
    return row["action"]


async def main_async(acc, args):
    case = D / "cases" / acc
    ag = case / "agent"; ag.mkdir(parents=True, exist_ok=True)
    lock = D / "state" / "locks" / acc
    if not take_lock(lock, 0 if args.finalize else args.wait_lock):
        log(acc, "live driver holds the lock"); return
    os.environ["PATH"] = f"{D}/shims:{D}:{MA}/venv/bin:" + os.environ["PATH"]
    hb = asyncio.create_task(beat(lock))
    (D / "logs" / "turns").mkdir(parents=True, exist_ok=True)
    fh = (D / "logs" / "turns" / f"{acc}.csv").open("a", newline="")
    w = csv.DictWriter(fh, FIELDS, extrasaction="ignore")
    if fh.tell() == 0:
        w.writeheader()
    job_end = float(os.environ.get("REACTRA_JOB_END") or time.time() + 3600)
    end = job_end - STOP_BEFORE_END
    log(acc, f"driver start host={socket.gethostname()} finalize={args.finalize} end_in={int(end - time.time())}s")
    try:
        from openai_codex import AsyncCodex
        async with AsyncCodex(config=codex_config()) as codex:
            k = count(acc, "turn-*.json")
            handled = ag / "handled.txt"
            if args.finalize:
                rc = last_logged_rc(acc)
                trig = {0: "succeeded", 4: "needs-agent"}.get(rc)
                key = f"{rc}-r{runs_count(acc)}-t{count(acc, 'retry-*')}"
                if trig and key not in (handled.read_text() if handled.exists() else ""):
                    act = await turn(codex, acc, k, trig, rc, (case / "last-pass.txt").read_text()
                                     if (case / "last-pass.txt").exists() else "", False, 0, w, args)
                    handled.open("a").write(f"{key} {act} finalize\n")
                    if act in FINAL:
                        (ag / "DONE").write_text(f"{act} turn {k} (finalize)\n")
                elif rc == 3 or rc is None:
                    (ag / "final.json").write_text(json.dumps(dict(case=acc, state="unfinished at pilot end",
                                                                   last_pass_rc=rc, summaries=summaries(acc))))
                return
            await asyncio.sleep(__import__("random").uniform(0, 60))      # spread the first passes
            errors, last_check = 0, 0.0
            while time.time() < end and not (ag / "DONE").exists() and not (D / "stop").exists():
                t1 = time.time()
                rc, tail = await run_pass(acc)
                trig = None
                if rc in (0, 4):
                    errors = 0
                    key = f"{rc}-r{runs_count(acc)}-t{count(acc, 'retry-*')}"
                    seen = handled.read_text() if handled.exists() else ""
                    if key in seen:          # same outcome, nothing changed since the last decision
                        (ag / "DONE").write_text(f"unresolved: outcome {key} repeated after a decision\n")
                        log(acc, f"outcome {key} repeated; marked unresolved"); break
                    trig = "succeeded" if rc == 0 else "needs-agent"
                elif rc == 3:
                    errors = 0
                    if time.time() - last_check >= CHECK:
                        trig = "check"
                else:
                    errors += 1
                    if errors >= ERR_STREAK:
                        trig, errors = "pass-error", 0
                if trig:
                    left = end - time.time()
                    act = await turn(codex, acc, k, trig, rc, tail, left > ACT_MIN_LEFT, int(left / 60), w, args)
                    fh.flush(); k += 1; last_check = time.time()
                    if trig in ("succeeded", "needs-agent"):
                        handled.open("a").write(f"{key} {act}\n")
                    if act in FINAL:
                        if trig in OUTCOME:
                            (ag / "DONE").write_text(f"{act} turn {k - 1} ({trig})\n"); break
                        log(acc, f"{act} on a '{trig}' turn overridden: the run is still active")
                    if act in ("relaunched", "retried"):
                        continue                                     # pass again now
                await asyncio.sleep(max(0, min(EVERY - (time.time() - t1), end - time.time())))
    finally:
        hb.cancel(); fh.close(); shutil.rmtree(lock, ignore_errors=True)
        log(acc, "driver exit")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("acc")
    ap.add_argument("--finalize", action="store_true")
    ap.add_argument("--wait-lock", type=float, default=900)
    ap.add_argument("--turn-timeout", type=float, default=1500)
    ap.add_argument("--model", default="muse-spark-bf16")
    ap.add_argument("--provider", default="alcf-inference-service-tara-api")
    args = ap.parse_args()
    asyncio.run(main_async(args.acc, args))


if __name__ == "__main__":
    main()
