#!/usr/bin/env python3
"""Realizable k-epsilon comparison rerun with first-order k/epsilon transport (user decision 2026-11-26).

The 2026-11-25 all-second-order case is archived as 03_cases/medium_rpm100_rke_secondorder_20261125 (kept for the
report). The rerun goes through the normal managed path (run_x57_converged.py -> run_fluent_managed.py) with a
90-minute per-case budget, like the other compressed extension cases. Log: logs/rke_rerun.log
"""
import datetime as dt
import os
import subprocess
import sys
import time
from pathlib import Path

WS = Path(r"D:\FEA Coursework\Workspace")
LOG = WS / "logs" / "rke_rerun.log"
PY = WS / ".venv" / "Scripts" / "python.exe"
sys.path.insert(0, str(WS / "scripts"))


def note(msg):
    with LOG.open("a", encoding="utf-8") as f:
        f.write(f"[{dt.datetime.now().astimezone().isoformat(timespec='seconds')}] {msg}\n")


def main():
    from run_x57_converged import workspace_environment
    case = WS / "03_cases" / "medium_rpm100_rke"
    archive = WS / "03_cases" / "medium_rpm100_rke_secondorder_20261125"
    if case.exists() and not archive.exists():
        case.rename(archive)
        note(f"archived second-order case -> {archive.name}")
    env = workspace_environment()
    env["X57_PYTHON"] = str(PY)
    env["X57_CASE_DEADLINE_EPOCH"] = repr(time.time() + 90 * 60)
    note("solve start: run_x57_converged.py medium_rpm100_rke --stage P9 (90 min budget)")
    t0 = time.time()
    with (WS / "logs" / "rke_rerun_console.log").open("a", encoding="utf-8") as out:
        rc = subprocess.run([str(PY), "-B", str(WS / "scripts" / "run_x57_converged.py"), "medium_rpm100_rke",
                             "--stage", "P9"], cwd=str(WS), env=env, stdout=out, stderr=subprocess.STDOUT).returncode
    note(f"solve end: rc={rc} after {(time.time() - t0) / 60:.1f} min")
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
