#!/usr/bin/env python3
"""One-shot: load the 2026-11-24 quality update into the RUNNING fast-track job at a safe point.

What it does (bounded, idempotent, logs to logs/fasttrack_update.log):
  1. byte-compiles every fast-track script; aborts without touching the run if anything fails,
  2. extends the P2-P10 compute deadline to the new budget (never shortens it),
  3. waits (max 60 min) for a SAFE POINT = a freshly written mesh candidate / published mesh /
     solver-block QA / stage record, i.e. the moment between two native Fluent steps,
  4. stops the orchestrator process tree (native checkpoints stay on disk),
  5. relaunches it detached; it resumes from the checkpoints with the new code.
The run keeps its single-instance lock semantics: if anybody else relaunched first, nothing doubles.
"""
from __future__ import annotations

import datetime as dt
import json
import msvcrt
import py_compile
import subprocess
import sys
import time
from pathlib import Path

WS = Path(r"D:\FEA Coursework\Workspace")
SUP = WS / "SUPERVISOR"
sys.path.insert(0, str(WS / "scripts"))
import fasttrack_profile as FP  # noqa: E402

LOG = WS / "logs" / "fasttrack_update.log"
DONE = SUP / "fasttrack_update_applied.json"
LOCK = SUP / "fasttrack_update.lock"
SAFE_PATTERNS = ("02_mesh/*/mesh_qa.json", "02_mesh/*/*/fasttrack_candidate_*.json", "02_mesh/grid_ladder_qa.json",
                 "03_cases/*/block_*_qa.json", "logs/P*_execution.json", "03_cases/*/static_equilibrium_audit.json")


def log(msg):
    line = f"[{dt.datetime.now().astimezone().isoformat(timespec='seconds')}] {msg}"
    print(line, flush=True)
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a", encoding="utf-8") as f:
        f.write(line + "\n")


def orchestrator_pid():
    import psutil
    try:
        st = json.loads((SUP / "fasttrack_status.json").read_text(encoding="utf-8"))
        proc = psutil.Process(int(st.get("orchestrator_pid")))
        if proc.is_running() and "run_all_fasttrack" in " ".join(proc.cmdline()):
            return proc.pid
    except Exception:
        pass
    for proc in psutil.process_iter(["pid", "cmdline"]):
        if "run_all_fasttrack" in " ".join(proc.info.get("cmdline") or []):
            return proc.info["pid"]
    return None


def newest_safe_point():
    newest = 0.0
    for pattern in SAFE_PATTERNS:
        for path in WS.glob(pattern):
            try:
                newest = max(newest, path.stat().st_mtime)
            except OSError:
                continue
    return newest


def launch():
    stamp = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    launcher = SUP / "_launch_orchestrator.cmd"
    args = f'/c start "X57 fast-track" /min "{launcher}" {stamp} --from-stage P2 --hours {FP.GLOBAL_HOURS}'
    subprocess.run("cmd.exe " + args, cwd=str(WS), check=False)
    log(f"relaunch requested (console log logs/fasttrack_console_{stamp}.log)")


def main():
    lock = LOCK.open("a+b")
    try:
        lock.seek(0)
        msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
    except OSError:
        print("Update already in progress.")
        return 0
    if DONE.is_file():
        print(f"Update already applied: {DONE.read_text(encoding='utf-8')}")
        return 0
    files = list((WS / "scripts").glob("*.py")) + list(SUP.glob("*.py"))
    for f in files:
        try:
            py_compile.compile(str(f), doraise=True, cfile=str(WS / "_cache" / "pycache" / (f.stem + ".pyc")))
        except py_compile.PyCompileError as exc:
            log(f"ABORT: {f.name} does not compile; the running job was not touched: {exc}")
            return 2
    log(f"compile check OK ({len(files)} files)")
    dl = SUP / "fasttrack_deadline.json"
    if dl.is_file():
        rec = json.loads(dl.read_text(encoding="utf-8"))
        new = rec["started_epoch"] + FP.GLOBAL_HOURS * 3600
        if new > rec["deadline_epoch"]:
            rec.update(deadline_epoch=new, hours=FP.GLOBAL_HOURS, extended_by_update=dt.datetime.now().isoformat())
            dl.write_text(json.dumps(rec, indent=2), encoding="utf-8")
            log(f"compute deadline extended to {dt.datetime.fromtimestamp(new):%Y-%m-%d %H:%M} ({FP.GLOBAL_HOURS} h)")
    pid = orchestrator_pid()
    if pid is None:
        log("no orchestrator running -> launching with the new code")
        launch()
    else:
        start, base = time.time(), newest_safe_point()
        log(f"orchestrator pid {pid}; waiting (<= 60 min) for the next safe point between native steps")
        while time.time() - start < 3600:
            if orchestrator_pid() is None:
                log("orchestrator stopped by itself -> launching with the new code")
                break
            if newest_safe_point() > base:
                log("safe point reached (new mesh candidate / block QA / stage record)")
                break
            time.sleep(15)
        else:
            log("no safe point within 60 min -> restarting now (the step resumes from its last checkpoint)")
        pid = orchestrator_pid()
        if pid is not None:
            subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True, check=False)
            for _ in range(60):
                if orchestrator_pid() is None:
                    break
                time.sleep(2)
            log(f"orchestrator tree {pid} stopped")
        time.sleep(10)
        if orchestrator_pid() is None:
            launch()
        else:
            log("another launcher already restarted the orchestrator (single-instance lock) -> nothing to do")
    for _ in range(30):
        time.sleep(4)
        new_pid = orchestrator_pid()
        if new_pid:
            DONE.write_text(json.dumps(dict(applied=dt.datetime.now().astimezone().isoformat(timespec="seconds"),
                                            orchestrator_pid=new_pid)), encoding="utf-8")
            log(f"UPDATE APPLIED: orchestrator running as pid {new_pid}")
            return 0
    log("WARNING: orchestrator not visible after relaunch; run 00_FASTTRACK_START.ps1")
    return 3


if __name__ == "__main__":
    raise SystemExit(main())
