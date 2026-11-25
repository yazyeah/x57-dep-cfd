#!/usr/bin/env python3
"""Bounded status poll for the fast-track run (safe for an agent loop).

  python SUPERVISOR/fasttrack_monitor.py --wait 900
blocks at most --wait seconds (returns early when the run finishes or halts) and prints
one compact summary. Exit codes:
  0 RUNNING (poll again)          2 COMPLETE (read DELIVERABLES/final_quality_report.md)
  1 HALTED/FAILED (read the tail) 3 ORCHESTRATOR NOT RUNNING (relaunch 00_FASTTRACK_START.ps1; it resumes)
"""
import argparse
import json
import time
from pathlib import Path

import psutil

WS = Path(r"D:\FEA Coursework\Workspace")
STATUS = WS / "SUPERVISOR" / "fasttrack_status.json"
LOG = WS / "logs" / "fasttrack_orchestrator.log"


def snapshot():
    st = json.loads(STATUS.read_text(encoding="utf-8")) if STATUS.is_file() else {}
    pid = st.get("orchestrator_pid")
    alive = False
    if pid:
        try:
            proc = psutil.Process(int(pid))
            alive = proc.is_running() and "run_all_fasttrack" in " ".join(proc.cmdline())
        except (psutil.Error, ValueError):
            alive = False
    return st, alive


def code(st, alive):
    state = st.get("state")
    if state in ("complete", "complete_with_quality_failures"):
        return 2
    if state in ("failed", "stopped"):
        return 1
    return 0 if alive else 3


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--wait", type=int, default=600)
    a = p.parse_args()
    deadline = time.time() + max(0, a.wait)
    st, alive = snapshot()
    while code(st, alive) == 0 and time.time() < deadline:
        time.sleep(min(30, max(1, deadline - time.time())))
        st, alive = snapshot()
    rc = code(st, alive)
    tail = LOG.read_text(encoding="utf-8", errors="replace").splitlines()[-12:] if LOG.is_file() else []
    print(json.dumps(dict(result=["RUNNING", "HALTED", "COMPLETE", "ORCHESTRATOR_NOT_RUNNING"][rc],
                          state=st.get("state"), stage=st.get("current_stage"), attempt=st.get("attempt"),
                          stage_deadline=st.get("stage_deadline"), eta=st.get("eta"), heartbeat=st.get("heartbeat"),
                          stage_elapsed_min=st.get("stage_elapsed_min"),
                          minutes_since_new_result=st.get("minutes_since_new_result"),
                          progress_stall_limit_min=st.get("progress_stall_limit_min"),
                          integrity_changed_files=st.get("integrity_changed_files"),
                          history=st.get("history", [])[-6:], failed_stage=st.get("failed_stage"),
                          log_tail=tail), indent=1, ensure_ascii=False))
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
