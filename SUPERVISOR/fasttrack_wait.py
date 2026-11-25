#!/usr/bin/env python3
"""Silent waiter: returns only when the fast-track run reaches a terminal state (or stays dead).

Exit 0 complete | 1 halted/failed/stopped | 3 orchestrator gone for > 15 min | 4 waited max hours.
Prints one compact summary on exit (no output while healthy).
"""
import json
import sys
import time
from pathlib import Path

import psutil

WS = Path(r"D:\FEA Coursework\Workspace")
STATUS = WS / "SUPERVISOR" / "fasttrack_status.json"


def alive():
    for p in psutil.process_iter(["cmdline"]):
        if "run_all_fasttrack" in " ".join(p.info.get("cmdline") or []):
            return True
    return False


def main():
    max_h = float(sys.argv[1]) if len(sys.argv) > 1 else 20.0
    t0, dead_since = time.time(), None
    while time.time() - t0 < max_h * 3600:
        try:
            st = json.loads(STATUS.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            st = {}
        state = st.get("state")
        if state in ("complete", "complete_with_quality_failures", "failed", "stopped") and not alive():
            break
        if alive():
            dead_since = None
        else:
            dead_since = dead_since or time.time()
            if time.time() - dead_since > 900:
                state = "orchestrator_gone"
                break
        time.sleep(120)
    else:
        state = "max_wait"
    log = (WS / "logs" / "fasttrack_orchestrator.log").read_text(encoding="utf-8", errors="replace").splitlines()[-15:]
    print(json.dumps(dict(state=state, failed_stage=st.get("failed_stage"), rc=st.get("rc"),
                          history=st.get("history", [])[-8:], log_tail=log), indent=1, ensure_ascii=False))
    return {"complete": 0, "complete_with_quality_failures": 0, "orchestrator_gone": 3, "max_wait": 4}.get(state, 1)


if __name__ == "__main__":
    raise SystemExit(main())
