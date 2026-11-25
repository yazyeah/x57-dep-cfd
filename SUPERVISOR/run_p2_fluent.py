#!/usr/bin/env python3
"""
Antigravity P2 Dedicated Fluent Runner (keeps CONTROL/STATE.txt=PAUSE so Astra
cannot collide while Antigravity completes P2 Coarse/Medium/Fine meshes).

Uses the exact same D:-drive workspace isolation, Win32 Kill-On-Close Job Object,
visible Fluent GUI (-wait), -t4 MPI ranks, live transcript mirroring, and
30-minute silent-stall guard.
"""

from __future__ import annotations

import argparse
import ctypes
import ctypes.wintypes as wt
import datetime as dt
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import psutil

WS_ROOT = Path(r"D:\FEA Coursework\Workspace")
SCRIPTS_DIR = WS_ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

from run_fluent_managed import (  # noqa: E402
    FLUENT_EXE,
    LOGS_DIR,
    attach_kill_on_close_job,
    build_f_only_env,
    close_job_handle,
    set_prevent_sleep,
)


def wait_no_fluent(timeout_s: int = 240) -> None:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        alive = []
        for p in psutil.process_iter(["pid", "name"]):
            n = (p.info["name"] or "").lower()
            if any(k in n for k in ("fl_mpi", "fl2520", "cx2520", "fluent")):
                alive.append((p.info["pid"], p.info["name"]))
        if not alive:
            return
        print(f"[P2Runner] Waiting for prior Fluent processes to exit: {alive}", flush=True)
        time.sleep(5)
    raise RuntimeError("Prior Fluent processes did not exit within timeout")


def terminate_job(job_handle, proc) -> None:
    if job_handle and os.name == "nt":
        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        k32.TerminateJobObject.argtypes = [wt.HANDLE, wt.UINT]
        k32.TerminateJobObject(wt.HANDLE(job_handle), 1)
    if proc.poll() is None:
        subprocess.run(
            ["taskkill", "/PID", str(proc.pid), "/T", "/F"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )


def run_fluent(
    workdir: Path,
    journal: Path,
    mode: str,
    case_label: str,
    procs: int = 4,
    gui: bool = True,
    silent_stall_min: float = 25.0,
    max_wall_min: float = 95.0,
) -> tuple[int, Path | None]:
    workdir = workdir.resolve()
    journal = journal.resolve()
    workdir.mkdir(parents=True, exist_ok=True)
    LOGS_DIR.mkdir(parents=True, exist_ok=True)

    wait_no_fluent(timeout_s=240)

    for stale in ("exit-fluent", "check-fluent", "exit-fluent.txt", "check-fluent.txt"):
        (workdir / stale).unlink(missing_ok=True)
    prev_trns = set(workdir.glob("fluent-*.trn"))

    ts = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    log_path = LOGS_DIR / f"{ts}_agy_{case_label}_{mode}.log"
    cmd = [str(FLUENT_EXE), "3ddp", f"-t{procs}", "-wait"]
    if not gui:
        cmd.append("-g")
    if mode == "meshing":
        cmd.append("-meshing")
    cmd.extend(["-i", str(journal)])

    env = build_f_only_env()
    print(f"[P2Runner] Launching {case_label}: {' '.join(cmd)}", flush=True)
    set_prevent_sleep(True)

    proc = subprocess.Popen(
        cmd,
        creationflags=0x00000004,  # CREATE_SUSPENDED
        cwd=str(workdir),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    job = attach_kill_on_close_job(proc)
    if not job:
        proc.kill()
        proc.wait()
        set_prevent_sleep(False)
        raise RuntimeError("Could not attach Win32 Job Object")

    psutil.Process(proc.pid).resume()
    start = time.time()
    last_growth = start
    last_size = -1
    active_trn: Path | None = None
    abort_reason: str | None = None

    try:
        while proc.poll() is None:
            now = time.time()
            new_trns = sorted(set(workdir.glob("fluent-*.trn")) - prev_trns, key=lambda p: p.stat().st_mtime)
            if new_trns:
                active_trn = new_trns[-1]
                sz = active_trn.stat().st_size
                if sz != last_size:
                    last_size = sz
                    last_growth = now
                    tail = active_trn.read_bytes()[-2048:].decode("utf-8", errors="replace").lower()
                    if ("error or interrupt occurred while reading the journal" in tail
                            or "sigsegv(segmentation violation)" in tail):
                        abort_reason = f"Journal error or SIGSEGV detected in {active_trn.name}"
                        break
            elapsed_min = (now - start) / 60.0
            silent_min = (now - last_growth) / 60.0
            if silent_min >= silent_stall_min:
                abort_reason = f"Silent stall ({silent_min:.1f} min >= {silent_stall_min} min) in {active_trn}"
                break
            if elapsed_min >= max_wall_min:
                abort_reason = f"Wall-clock limit ({elapsed_min:.1f} min >= {max_wall_min} min) exceeded"
                break
            time.sleep(3.0)

        if abort_reason:
            print(f"[P2Runner] ABORTING {case_label}: {abort_reason}", flush=True)
            terminate_job(job, proc)
            proc.wait(timeout=30)
            rc = 2
        else:
            rc = proc.wait()
    finally:
        terminate_job(job, proc)
        close_job_handle(job)
        set_prevent_sleep(False)

    # Final capture of new transcript
    new_trns = sorted(set(workdir.glob("fluent-*.trn")) - prev_trns, key=lambda p: p.stat().st_mtime)
    if new_trns:
        active_trn = new_trns[-1]
        dest = log_path.with_name(log_path.stem + "_" + active_trn.name)
        dest.write_bytes(active_trn.read_bytes())

    elapsed_min = (time.time() - start) / 60.0
    print(f"[P2Runner] Finished {case_label}: rc={rc}, elapsed={elapsed_min:.1f} min, trn={active_trn}", flush=True)
    return rc, active_trn


def main() -> int:
    p = argparse.ArgumentParser(description="Antigravity P2 Fluent Runner")
    p.add_argument("--workdir", type=Path, required=True)
    p.add_argument("--journal", type=Path, required=True)
    p.add_argument("--mode", choices=["meshing", "solver"], required=True)
    p.add_argument("--case", required=True)
    p.add_argument("--procs", type=int, default=4)
    p.add_argument("--headless", action="store_true")
    p.add_argument("--silent-stall-min", type=float, default=25.0)
    p.add_argument("--max-wall-min", type=float, default=95.0)
    args = p.parse_args()

    rc, trn = run_fluent(
        workdir=args.workdir,
        journal=args.journal,
        mode=args.mode,
        case_label=args.case,
        procs=args.procs,
        gui=not args.headless,
        silent_stall_min=args.silent_stall_min,
        max_wall_min=args.max_wall_min,
    )
    print(json.dumps({"rc": rc, "transcript": str(trn) if trn else None}))
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
