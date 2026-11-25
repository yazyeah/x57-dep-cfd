#!/usr/bin/env python3
"""One-shot partial compression of the extension stages P7-P10 (user request 2026-11-25).

The orchestrator reads the compute deadline (fasttrack_deadline.json) once at launch and only fits the
extension stages P7-P10 to it; the coursework-brief stages P2-P6 and the report stages P11/P12 always get
their full limits. This helper waits until the running orchestrator logs the start of P7 (all required
cases are then accepted), sets the compute deadline to min(current deadline, now + EXT_HOURS), stops the
orchestrator before its P7 child can launch Fluent, and relaunches the run from P7 with the new deadline.

Every extension case still ends with an accepted endpoint (best tier at its share, one grace block, else
'flagged'), so all extension figures/tables and the FSI study keep their inputs. MAPDL/FSI runs are not
deadline-bound. Acts once, then exits; gives up after MAX_WAIT_H. Log: logs/fasttrack_compress_extensions.log
"""
import datetime as dt
import json
import os
import re
import subprocess
import time
from pathlib import Path

import psutil

WS = Path(r"D:\FEA Coursework\Workspace")
LOG = WS / "logs" / "fasttrack_orchestrator.log"
DEADLINE = WS / "SUPERVISOR" / "fasttrack_deadline.json"
OUT = WS / "logs" / "fasttrack_compress_extensions.log"
EXT_HOURS = float(os.environ.get("X57_EXT_HOURS", "3.5"))
MAX_WAIT_H = 20.0
KEYS = ("run_all_fasttrack", "run_x57_stage", "run_x57_converged", "run_fluent_managed",
        "prepare_solver_case", "_launch_orchestrator")
TRIGGER = re.compile(r"\] P7 attempt \d+: ")


def note(msg):
    with OUT.open("a", encoding="utf-8") as f:
        f.write(f"[{dt.datetime.now().astimezone().isoformat(timespec='seconds')}] {msg}\n")


def fmt(epoch):
    return dt.datetime.fromtimestamp(epoch).astimezone().isoformat(timespec="minutes")


def run_tree():
    me = os.getpid()
    out = []
    for p in psutil.process_iter(["cmdline", "exe"]):
        if p.pid == me:
            continue
        cmd = " ".join(p.info.get("cmdline") or [])
        if "fasttrack_compress_extensions" in cmd:
            continue
        if any(k in cmd for k in KEYS) or str(p.info.get("exe") or "").lower().startswith(r"d:\ansys"):
            out.append(p)
    return out


def main():
    offset = LOG.stat().st_size if LOG.is_file() else 0
    note(f"armed: EXT_HOURS={EXT_HOURS}; watching {LOG.name} from byte {offset}")
    t0 = time.time()
    while time.time() - t0 < MAX_WAIT_H * 3600:
        time.sleep(3)
        data = LOG.read_bytes()
        text, offset = data[offset:].decode("utf-8", errors="replace"), len(data)
        if not TRIGGER.search(text):
            continue
        now = time.time()
        rec = json.loads(DEADLINE.read_text(encoding="utf-8"))
        old = float(rec["deadline_epoch"])
        new = min(old, now + EXT_HOURS * 3600)
        victims = run_tree()
        for p in victims:
            try:
                p.kill()
            except psutil.Error:
                pass
        psutil.wait_procs(victims, timeout=30)
        left = [p.pid for p in run_tree()]
        if left:
            note(f"P7 start seen but processes survived the stop: {left}; deadline NOT changed")
            return 1
        rec.update(deadline_epoch=new, compressed_from_epoch=old, compressed_at=dt.datetime.now().astimezone()
                   .isoformat(timespec="seconds"), compression_note=f"P7-P10 limited to {EXT_HOURS} h (user request)")
        tmp = DEADLINE.with_suffix(".tmp")
        tmp.write_text(json.dumps(rec, indent=2), encoding="utf-8")
        tmp.replace(DEADLINE)
        note(f"P7 start seen -> stopped {len(victims)} processes; compute deadline {fmt(old)} -> {fmt(new)}")
        res = subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
                              str(WS / "00_FASTTRACK_START.ps1"), "-FromStage", "P7"],
                             capture_output=True, text=True, timeout=300, cwd=str(WS))
        tail = " | ".join((res.stdout or "").strip().splitlines()[-4:])
        note(f"relaunched from P7 (rc={res.returncode}): {tail[:600]}")
        return 0
    note(f"timeout ({MAX_WAIT_H} h) without a P7 start; nothing changed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
