#!/usr/bin/env python3
"""Unattended fast-track orchestrator for the whole X-57 P2 -> P12 pipeline.

One command, no agent decisions needed while healthy:
  * single-instance lock (a second launch exits immediately),
  * preflight: orphan Fluent/MAPDL cleanup, control-gate RUN + inbox acknowledgement, disk space,
  * a persistent compute deadline for P2-P10 (default 14 h; P11/P12 excluded) split into per-stage deadlines that every
    case driver honours (iteration caps, budget-tier acceptance, no infinite loops),
  * every stage runs in a child process with a hard wall-clock kill (deadline + grace),
  * one automatic resume-retry per stage (all drivers resume from native checkpoints),
  * heartbeat status file SUPERVISOR/fasttrack_status.json and log logs/fasttrack_orchestrator.log,
  * final independent quality audit (DELIVERABLES/final_quality_report.md).
Exit: 0 complete + no quality FAIL, 5 complete with quality FAIL rows, 4 a stage failed twice,
      3 P2 found no admissible mesh, 10/20/30/40 user control gate.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import msvcrt
import os
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path

WS = Path(r"D:\FEA Coursework\Workspace")
SCRIPTS, SUP = WS / "scripts", WS / "SUPERVISOR"
sys.path.insert(0, str(SCRIPTS))
sys.path.insert(0, str(SUP))

import fasttrack_profile as FP  # noqa: E402
from control_gate import ControlGate, atomic_write_json  # noqa: E402
from run_fluent_managed import build_f_only_env, set_prevent_sleep  # noqa: E402

PY = sys.executable
STATUS = SUP / "fasttrack_status.json"
DEADLINE_FILE = SUP / "fasttrack_deadline.json"
LOG = WS / "logs" / "fasttrack_orchestrator.log"
LOCK = SUP / "fasttrack.lock"
STAGE_GRACE_MIN = 45          # extra time after a stage deadline before the hard kill
ANSYS_PROCS = ("fluent", "fl_mpi", "fl2520", "cx2520", "mapdl")
ANSYS_ROOT = Path(r"D:\Ansys")          # only processes started from the project's Ansys install are touched


def now_iso():
    return dt.datetime.now().astimezone().isoformat(timespec="seconds")


def log(msg):
    LOG.parent.mkdir(parents=True, exist_ok=True)
    line = f"[{now_iso()}] {msg}"
    print(line, flush=True)
    with LOG.open("a", encoding="utf-8") as f:
        f.write(line + "\n")


def status(**kw):
    cur = {}
    if STATUS.is_file():
        try:
            cur = json.loads(STATUS.read_text(encoding="utf-8"))
        except ValueError:
            cur = {}
    cur.update(kw, updated_at=now_iso(), orchestrator_pid=os.getpid())
    atomic_write_json(STATUS, cur)


def stage_done(stage):
    if stage == "P2":
        path = WS / "02_mesh" / "grid_ladder_qa.json"
        try:
            return path.is_file() and json.loads(path.read_text(encoding="utf-8-sig")).get("passed") is True
        except ValueError:
            return False
    path = WS / "logs" / f"{stage}_execution.json"
    try:
        return path.is_file() and json.loads(path.read_text(encoding="utf-8-sig")).get("status") == "completed"
    except ValueError:
        return False


def kill_orphans():
    import psutil
    victims = []
    for p in psutil.process_iter(["pid", "name"]):
        name = (p.info["name"] or "").lower()
        if any(k in name for k in ANSYS_PROCS):
            try:
                exe = Path(p.exe()).resolve()
            except Exception:
                continue
            if exe.is_relative_to(ANSYS_ROOT):
                victims.append(p)
    for p in victims:
        try:
            log(f"preflight: terminating orphan {p.info['name']} pid={p.pid}")
            subprocess.run(["taskkill", "/PID", str(p.pid), "/T", "/F"], capture_output=True, check=False)
        except Exception:
            pass
    return len(victims)


def preflight(gate, kill):
    if kill:
        n = kill_orphans()
        if n:
            time.sleep(5)
    for name in ("active_pids.json",):
        path = WS / "CONTROL" / name
        atomic_write_json(path, {"pids": []})
    pending = gate.read_pending_instruction()
    if pending:
        gate.ack_instruction("Fast-track orchestrator: the user authorised an unattended P2-P12 run "
                             "(prior handoff instruction superseded).")
        log(f"preflight: acknowledged pending instruction: {pending[:160]!r}")
    if gate.read_state() != "RUN":
        gate.set_state("RUN", "Fast-track orchestrator start (user-authorised unattended run)")
        log("preflight: control state set to RUN")
    free = shutil.disk_usage(WS).free / 2 ** 30
    log(f"preflight: workspace free space {free:.1f} GB")
    if free < 15:
        raise SystemExit("Less than 15 GB free on the workspace drive; free space before running")
    for stale in WS.glob("03_cases/*/exit-fluent*"):
        stale.unlink(missing_ok=True)


def global_deadline(hours, renew):
    if DEADLINE_FILE.is_file() and not renew:
        rec = json.loads(DEADLINE_FILE.read_text(encoding="utf-8"))
        if rec.get("deadline_epoch", 0) > time.time() + 600:
            return rec["deadline_epoch"], rec["started_epoch"]
    start = time.time()
    rec = dict(started_epoch=start, deadline_epoch=start + hours * 3600, hours=hours, started=now_iso())
    atomic_write_json(DEADLINE_FILE, rec)
    return rec["deadline_epoch"], start


def stage_deadline(stage, gdl):
    """Compute stages share the global budget; report stages (P11, P12) only use their own hard limit."""
    t = time.time()
    if stage in FP.REPORT_STAGES or stage in getattr(FP, "REQUIRED_STAGES", ()):
        # Report stages and coursework-brief stages always get their full hard limit; only the
        # extension stages are compressed when the run is behind schedule.
        return t + 60 * FP.STAGE_HARD_MIN[stage]
    later = FP.COMPUTE_STAGES[FP.COMPUTE_STAGES.index(stage) + 1:]
    reserve = 60 * sum(FP.STAGE_FLOOR_MIN[s] for s in later if not stage_done(s))
    return max(t + 60 * FP.STAGE_FLOOR_MIN[stage], min(t + 60 * FP.STAGE_HARD_MIN[stage], gdl - reserve))


def eta(gdl):
    t = time.time()
    remaining = [s for s in FP.STAGES if not stage_done(s)]
    compute = sum(FP.STAGE_NOMINAL_MIN[s] for s in remaining if s in FP.COMPUTE_STAGES)
    report = sum(FP.STAGE_NOMINAL_MIN[s] for s in remaining if s in FP.REPORT_STAGES)
    fmt = lambda x: dt.datetime.fromtimestamp(x).astimezone().isoformat(timespec="minutes")
    return dict(remaining_stages=remaining, nominal_compute_remaining_min=compute, nominal_report_min=report,
                nominal_compute_finish=fmt(t + 60 * compute), nominal_all_finish=fmt(t + 60 * (compute + report)),
                compute_deadline_P2_to_P10=fmt(gdl))


SUFFIXES = tuple(FP.PROGRESS_SUFFIXES) + (".npy", ".inp")


def newest_progress():
    """Newest mtime of any result-type file (QA, case/data, mesh, figure, render, MAPDL output, stage record)."""
    newest = 0.0
    for d in FP.PROGRESS_DIRS:
        for dirpath, dirnames, filenames in os.walk(WS / d):
            dirnames[:] = [x for x in dirnames if not x.startswith(("FM_", "__pycache__")) and not x.endswith("_workflow_files")]
            for name in filenames:
                if name.endswith(SUFFIXES):
                    try:
                        newest = max(newest, os.stat(os.path.join(dirpath, name)).st_mtime)
                    except OSError:
                        continue
    return newest


def kill_tree(proc):
    subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"], capture_output=True, check=False)
    try:
        proc.wait(timeout=120)
    except subprocess.TimeoutExpired:
        pass


def run_child(cmd, env, hard_deadline, label, stall_min):
    """Run one stage process. Kill its tree at the hard deadline (rc 124) or when no new result
    file has appeared for stall_min minutes (rc 125); the next attempt resumes from checkpoints."""
    log(f"{label}: {' '.join(str(c) for c in cmd)}")
    proc = subprocess.Popen([str(c) for c in cmd], cwd=str(WS), env=env)
    t0 = last_scan = time.time()
    last_progress, last_change = newest_progress(), time.time()
    try:
        while proc.poll() is None:
            now = time.time()
            if now > hard_deadline:
                log(f"{label}: stage hard wall-clock limit reached -> terminating process tree")
                kill_tree(proc)
                return 124
            if now - last_scan >= 120:
                last_scan = now
                newest = newest_progress()
                if newest > last_progress:
                    last_progress, last_change = newest, now
                idle = (now - last_change) / 60
                status(heartbeat=now_iso(), stage_elapsed_min=round((now - t0) / 60, 1),
                       minutes_since_new_result=round(idle, 1), progress_stall_limit_min=stall_min,
                       stage_hard_deadline=dt.datetime.fromtimestamp(hard_deadline).astimezone().isoformat(timespec="minutes"))
                if idle >= stall_min:
                    log(f"{label}: no new result file for {idle:.0f} min (limit {stall_min}) -> restart from checkpoints")
                    kill_tree(proc)
                    return 125
            time.sleep(5)
        return proc.returncode
    finally:
        if proc.poll() is None:
            kill_tree(proc)


def integrity(record_if_missing=True):
    """SHA-256 of the acceptance-defining files; baseline written at the first launch."""
    import hashlib
    path = SUP / "fasttrack_integrity.json"
    current = {}
    for rel in FP.PROTECTED_FILES:
        f = WS / rel
        current[rel] = hashlib.sha256(f.read_bytes()).hexdigest() if f.is_file() else None
    if not path.is_file():
        if record_if_missing:
            atomic_write_json(path, dict(recorded=now_iso(), sha256=current))
        return []
    base = json.loads(path.read_text(encoding="utf-8")).get("sha256", {})
    return [rel for rel in FP.PROTECTED_FILES if base.get(rel) != current.get(rel)]


def run_stage(stage, gdl, env):
    stalled_without_progress = 0
    for attempt in range(1, FP.STAGE_ATTEMPTS + 1):
        gate_code = int(ControlGate(WS).check()["exit_code"])
        if gate_code:
            log(f"{stage}: control gate {gate_code} -> stopping orchestrator")
            return gate_code
        sdl = stage_deadline(stage, gdl)
        env = dict(env, X57_STAGE_DEADLINE_EPOCH=repr(sdl))
        if stage == "P11":   # one native session renders all 16 Fluent views
            env["X57_FLUENT_MAX_WALL_MIN"] = "120"
        status(current_stage=stage, attempt=attempt, stage_deadline=dt.datetime.fromtimestamp(sdl).astimezone()
               .isoformat(timespec="minutes"), eta=eta(gdl), state="running")
        t0 = time.time()
        before = newest_progress()
        if stage == "P2":
            cmd = [PY, "-B", SUP / "p2_fasttrack.py", "--deadline-epoch", repr(sdl)]
        else:
            cmd = [PY, "-B", SCRIPTS / "run_x57_stage.py", stage]
        stall = FP.PROGRESS_STALL_MIN.get(stage, FP.PROGRESS_STALL_MIN["_default"])
        rc = run_child(cmd, env, sdl + 60 * STAGE_GRACE_MIN, f"{stage} attempt {attempt}", stall)
        minutes = (time.time() - t0) / 60
        progressed = newest_progress() > before
        hist = json.loads(STATUS.read_text(encoding="utf-8")).get("history", []) if STATUS.is_file() else []
        hist.append(dict(stage=stage, attempt=attempt, rc=rc, minutes=round(minutes, 1), new_results=progressed, at=now_iso()))
        status(history=hist)
        if rc == 0 and stage_done(stage):
            log(f"{stage}: DONE in {minutes:.1f} min")
            return 0
        if rc in (10, 20, 30, 40):
            log(f"{stage}: stopped by control gate ({rc})")
            return rc
        stalled_without_progress = 0 if progressed else stalled_without_progress + 1
        last = attempt == FP.STAGE_ATTEMPTS or stalled_without_progress >= 2
        log(f"{stage}: attempt {attempt} ended rc={rc} after {minutes:.1f} min (new results: {progressed}); "
            f"{'giving up' if last else 'resuming from native checkpoints'}")
        if last:
            break
    return 3 if stage == "P2" else 4


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--hours", type=float, default=FP.GLOBAL_HOURS, help="Wall-clock budget for the compute stages P2-P10")
    p.add_argument("--renew-deadline", action="store_true", help="Restart the global clock (default: resume it)")
    p.add_argument("--from-stage", choices=FP.STAGES, default="P2")
    p.add_argument("--to-stage", choices=FP.STAGES, default="P12")
    p.add_argument("--no-kill-orphans", action="store_true")
    p.add_argument("--plan", action="store_true", help="Print the time plan and exit (no Fluent)")
    a = p.parse_args()
    LOCK.parent.mkdir(parents=True, exist_ok=True)
    lock_fp = LOCK.open("a+b")
    try:
        lock_fp.seek(0)
        msvcrt.locking(lock_fp.fileno(), msvcrt.LK_NBLCK, 1)
    except OSError:
        print("Another fast-track orchestrator is already running (SUPERVISOR/fasttrack.lock). Monitor it instead.")
        return 0
    stages = FP.STAGES[FP.STAGES.index(a.from_stage):FP.STAGES.index(a.to_stage) + 1]
    if a.plan:
        t = time.time()
        for s in stages:
            mark = "done" if stage_done(s) else f"nominal {FP.STAGE_NOMINAL_MIN[s]:>3d} min, hard {FP.STAGE_HARD_MIN[s]:>3d} min"
            print(f"{s:>4}: {mark}")
        comp = sum(FP.STAGE_NOMINAL_MIN[s] for s in stages if not stage_done(s) and s in FP.COMPUTE_STAGES)
        rep = sum(FP.STAGE_NOMINAL_MIN[s] for s in stages if not stage_done(s) and s in FP.REPORT_STAGES)
        print(f"Compute P2-P10: nominal {comp} min = {comp/60:.1f} h (budget {a.hours} h). "
              f"Report P11-P12 (not budgeted): nominal {rep} min = {rep/60:.1f} h. "
              f"Nominal finish {dt.datetime.fromtimestamp(t + 60*(comp+rep)):%Y-%m-%d %H:%M}")
        return 0
    gate = ControlGate(WS)
    preflight(gate, not a.no_kill_orphans)
    changed = integrity()
    if changed:
        log(f"INTEGRITY WARNING: acceptance-defining files changed since the first launch: {changed} "
            f"(reported as FAIL in the final quality report)")
    status(integrity_changed_files=changed)
    gdl, started = global_deadline(a.hours, a.renew_deadline)
    env = build_f_only_env()
    env.update(X57_FASTTRACK="1", X57_ALLOW_FLAGGED="1", PYTHONUNBUFFERED="1", PYTHONUTF8="1")
    # Same variables scripts/env_d_only.ps1 sets, in case the launcher shell did not dot-source it.
    ansys = r"D:\Ansys\ANSYS Inc\ANSYS Student\v252"
    for key, value in dict(X57_WORKSPACE=str(WS), X57_PYTHON=sys.executable,
                           X57_FLUENT=ansys + r"\fluent\ntbin\win64\fluent.exe",
                           X57_MAPDL=ansys + r"\ansys\bin\winx64\MAPDL.exe",
                           X57_ANSYS_PY=ansys + r"\commonfiles\CPython\3_10\winx64\Release\python\python.exe",
                           PYVISTA_USERDATA_PATH=str(WS / "_cache" / "pyvista"),
                           NUMBA_CACHE_DIR=str(WS / "_cache" / "numba"),
                           NATURE_FIGURE_CONFIG=str(WS / "_cache" / "nature-figure.json")).items():
        env.setdefault(key, value)
    set_prevent_sleep(True)
    status(state="running", started=now_iso(), stages=list(stages), eta=eta(gdl), history=[])
    log(f"FAST-TRACK START stages={stages} compute (P2-P10) deadline "
        f"{dt.datetime.fromtimestamp(gdl):%Y-%m-%d %H:%M} ({(gdl - time.time())/3600:.1f} h left); "
        f"P11/P12 run afterwards with their own limits")
    try:
        for stage in stages:
            if stage_done(stage):
                log(f"{stage}: already complete -> skip")
                continue
            rc = run_stage(stage, gdl, env)
            if rc:
                status(state="failed" if rc in (3, 4) else "stopped", failed_stage=stage, rc=rc)
                log(f"FAST-TRACK HALTED at {stage} rc={rc}. Diagnostics: logs/fasttrack_orchestrator.log, "
                    f"logs/{stage}_execution.json, 03_cases/*/fasttrack_events.jsonl, logs/p2_fasttrack.log")
                print(f"=== FASTTRACK_HALTED stage={stage} rc={rc} ===", flush=True)
                return rc
        audit = subprocess.run([PY, "-B", str(SCRIPTS / "final_quality_audit.py")], cwd=str(WS), env=env)
        total_h = (time.time() - started) / 3600
        state = "complete" if audit.returncode == 0 else "complete_with_quality_failures"
        status(state=state, finished=now_iso(), total_hours=round(total_h, 2), quality_audit_rc=audit.returncode)
        log(f"FAST-TRACK {state.upper()} in {total_h:.2f} h -> DELIVERABLES/final_quality_report.md")
        print(f"=== FASTTRACK_{state.upper()} ===", flush=True)
        return 0 if audit.returncode == 0 else 5
    finally:
        set_prevent_sleep(False)


if __name__ == "__main__":
    raise SystemExit(main())
