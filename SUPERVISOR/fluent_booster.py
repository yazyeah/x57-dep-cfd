#!/usr/bin/env python3
"""Keep Ansys processes (Fluent solver/mesher, MAPDL) on the performance cores (2026-11-25).

Measured: with the Fluent window in the background, Windows ran all four fl_mpi ranks on the E-cores
(logical CPUs 16-23 busy, P-cores idle, 1.5 GHz) and coarse iterations took 6.3 s instead of 1.7 s;
restricting them to the P-cores gave 1.9 s, with two ranks still sharing hyper-threads of one core.
For every process whose executable lives under D:\\Ansys this daemon
  * gives each Fluent MPI rank (fl_mpi*) an exclusive physical P-core (both hyper-threads),
    preferring cores 2,4,6,... and leaving core 0 to the OS / GUI,
  * restricts every other Ansys process to all P-core logical processors,
  * sets ABOVE_NORMAL priority and disables EcoQoS execution-speed throttling.
Topology from GetSystemCpuSetInformation (EfficiencyClass, CoreIndex); on a non-hybrid CPU affinity is
left alone. Per-process runtime settings of our own solver processes only; no system setting is changed.
Runs until MAX_HOURS. Log: logs/fluent_booster.log
"""
import ctypes
import datetime as dt
import time
from ctypes import wintypes
from pathlib import Path

import psutil

WS = Path(r"D:\FEA Coursework\Workspace")
OUT = WS / "logs" / "fluent_booster.log"
MAX_HOURS = 30.0
k32 = ctypes.WinDLL("kernel32", use_last_error=True)


def note(msg):
    with OUT.open("a", encoding="utf-8") as f:
        f.write(f"[{dt.datetime.now().astimezone().isoformat(timespec='seconds')}] {msg}\n")


def topology():
    """{physical P-core index: [logical CPUs]} or None on a non-hybrid CPU."""
    need = wintypes.ULONG(0)
    k32.GetSystemCpuSetInformation(None, 0, ctypes.byref(need), None, 0)
    buf = ctypes.create_string_buffer(need.value)
    if not k32.GetSystemCpuSetInformation(buf, need, ctypes.byref(need), None, 0):
        return None
    raw, off, sets = buf.raw, 0, []
    while off < need.value:
        size = int.from_bytes(raw[off:off + 4], "little")
        if size == 0:
            break
        sets.append((raw[off + 14], raw[off + 15], raw[off + 18]))   # logical, core, efficiency class
        off += size
    classes = {e for _, _, e in sets}
    if len(classes) < 2:
        return None
    lo = min(classes)
    cores = {}
    for lp, core, eff in sets:
        if eff > lo:
            cores.setdefault(core, []).append(lp)
    return {c: sorted(v) for c, v in sorted(cores.items())}


class THROTTLE(ctypes.Structure):
    _fields_ = [("Version", wintypes.ULONG), ("ControlMask", wintypes.ULONG), ("StateMask", wintypes.ULONG)]


def no_throttle(pid):
    h = k32.OpenProcess(0x0200 | 0x1000, False, pid)   # PROCESS_SET_INFORMATION | QUERY_LIMITED_INFORMATION
    if not h:
        return False
    try:
        st = THROTTLE(1, 0x1, 0x0)                      # EXECUTION_SPEED controlled, state off = never throttle
        return bool(k32.SetProcessInformation(h, 4, ctypes.byref(st), ctypes.sizeof(st)))
    finally:
        k32.CloseHandle(h)


def main():
    cores = topology()
    all_p = sorted(lp for v in (cores or {}).values() for lp in v)
    order = [c for c in (cores or {}) if c != min(cores or {0: 0})] + ([min(cores)] if cores else [])
    note(f"start (v2): P-cores {cores}; rank core order {order}")
    seen, ranks = set(), {}                              # ranks: pid -> physical core
    t0 = time.time()
    while time.time() - t0 < MAX_HOURS * 3600:
        ranks = {pid: c for pid, c in ranks.items() if psutil.pid_exists(pid)}
        procs = sorted(psutil.process_iter(["pid", "name", "exe"]), key=lambda p: p.pid)
        for p in procs:
            exe = str(p.info.get("exe") or "")
            if p.pid in seen or not exe.lower().startswith("d:\\ansys"):
                continue
            seen.add(p.pid)
            done = []
            try:
                is_rank = (p.info.get("name") or "").lower().startswith("fl_mpi")
                if cores and is_rank:
                    free = [c for c in order if c not in ranks.values()]
                    if free:
                        ranks[p.pid] = free[0]
                        p.cpu_affinity(cores[free[0]])
                        done.append(f"exclusive P-core {free[0]} {cores[free[0]]}")
                    else:
                        p.cpu_affinity(all_p)
                        done.append("P-cores (all exclusive cores taken)")
                elif cores:
                    p.cpu_affinity(all_p)
                    done.append("P-cores")
                p.nice(psutil.ABOVE_NORMAL_PRIORITY_CLASS)
                done.append("above-normal")
                if no_throttle(p.pid):
                    done.append("no-EcoQoS")
            except psutil.Error as exc:
                done.append(f"error {exc.__class__.__name__}")
            note(f"{p.info['name']} pid={p.pid}: {', '.join(done)}")
        if len(seen) > 5000:
            seen = {pid for pid in seen if psutil.pid_exists(pid)}
        time.sleep(5)
    note("stop (max hours)")


if __name__ == "__main__":
    main()
