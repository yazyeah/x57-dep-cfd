#!/usr/bin/env python3
"""Silent per-stage waiter: returns when the fast-track run leaves the given stage (or ends / dies).

Usage: fasttrack_wait_stage.py P2 [max_hours]
Exit 0 stage advanced | 1 halted/failed/stopped | 2 complete | 3 orchestrator gone > 15 min | 4 max wait.
Prints one compact summary on exit (no output while the stage is running).
"""
import json
import sys
import time
from pathlib import Path

import psutil

WS = Path(r"D:\FEA Coursework\Workspace")
STATUS = WS / "SUPERVISOR" / "fasttrack_status.json"
TERMINAL = ("complete", "complete_with_quality_failures", "failed", "stopped", "halted")


def alive():
    for p in psutil.process_iter(["cmdline"]):
        if "run_all_fasttrack" in " ".join(p.info.get("cmdline") or []):
            return True
    return False


def read():
    try:
        return json.loads(STATUS.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def main():
    stage = sys.argv[1]
    max_h = float(sys.argv[2]) if len(sys.argv) > 2 else 12.0
    t0, dead_since, outcome = time.time(), None, "max_wait"
    while time.time() - t0 < max_h * 3600:
        st = read()
        if st.get("state") in TERMINAL and not alive():
            outcome = st.get("state")
            break
        cur = st.get("current_stage") or st.get("stage")
        if cur and cur != stage and alive():
            outcome = "advanced"
            break
        if alive():
            dead_since = None
        else:
            dead_since = dead_since or time.time()
            if time.time() - dead_since > 900:
                outcome = "orchestrator_gone"
                break
        time.sleep(60)
    st = read()
    log = (WS / "logs" / "fasttrack_orchestrator.log").read_text(encoding="utf-8", errors="replace").splitlines()[-10:]
    print(json.dumps(dict(outcome=outcome, waited_stage=stage, now_stage=st.get("current_stage") or st.get("stage"),
                          state=st.get("state"),
                          failed_stage=st.get("failed_stage"), history=st.get("history", [])[-6:], log_tail=log),
                     indent=1, ensure_ascii=False))
    return {"advanced": 0, "complete": 2, "complete_with_quality_failures": 2,
            "orchestrator_gone": 3, "max_wait": 4}.get(outcome, 1)


if __name__ == "__main__":
    raise SystemExit(main())
