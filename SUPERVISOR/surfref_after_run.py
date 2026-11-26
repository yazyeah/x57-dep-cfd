#!/usr/bin/env python3
"""Run the surface-refinement study (SUPERVISOR/surfref_study.py) once the fast-track run has finished.

The 14:08 attempt at the P6->P7 hand-over found no inflatable refined CAD shell (see surfref_study.SHELLS);
the study now uses the subdivided coarse shell (scripts/build_subdivided_shell.py). One Student Fluent seat:
the study must not overlap P7-P11 (P11 renders through Fluent), and nothing in P11/P12 consumes its result,
so this helper waits until the orchestrator logs its final "FAST-TRACK <STATE> in ... h" line (after P12),
checks that no Ansys process is alive, and then runs the study. On "FAST-TRACK HALTED" it only logs and exits
(the halt is handled by hand first). Log: logs/surfref_after_run.log
"""
import datetime as dt
import re
import subprocess
import time
from pathlib import Path

import psutil

WS = Path(r"D:\FEA Coursework\Workspace")
ORCH = WS / "logs" / "fasttrack_orchestrator.log"
OUT = WS / "logs" / "surfref_after_run.log"
PY = WS / ".venv" / "Scripts" / "python.exe"
DONE = re.compile(r"FAST-TRACK (?!START|HALTED)[A-Z_]+ in [\d.]+ h")
HALT = re.compile(r"FAST-TRACK HALTED at (P\d+)")
MAX_WAIT_H, STUDY_MAX_H = 14.0, 6.5


def note(msg):
    with OUT.open("a", encoding="utf-8") as f:
        f.write(f"[{dt.datetime.now().astimezone().isoformat(timespec='seconds')}] {msg}\n")


def ansys_alive():
    alive = []
    for p in psutil.process_iter(["exe", "name"]):
        try:
            if str(p.info.get("exe") or "").lower().startswith(r"d:\ansys"):
                alive.append(f"{p.info['name']}:{p.pid}")
        except psutil.Error:
            continue
    return alive


def main():
    import sys
    offset = ORCH.stat().st_size if ORCH.is_file() else 0
    now = "--now" in sys.argv[1:]   # run finished already and the native renders were redone by hand (2026-11-26)
    note("started with --now: not waiting for the orchestrator" if now else
         f"armed: waiting for the end of the fast-track run ({ORCH.name} from byte {offset})")
    t0 = time.time()
    while not now and time.time() - t0 < MAX_WAIT_H * 3600:
        time.sleep(60)
        with ORCH.open("rb") as f:
            f.seek(offset)
            text = f.read().decode("utf-8", "replace")
        halt = HALT.search(text)
        if halt:
            note(f"run halted at {halt.group(1)}; surface study NOT started (handle the halt first)")
            return 2
        if DONE.search(text):
            break
    else:
        if not now:
            note("gave up waiting")
            return 3
    note("run finished; waiting for Ansys processes to exit")
    for _ in range(60):
        alive = ansys_alive()
        if not alive:
            break
        time.sleep(30)
    else:
        note(f"Ansys processes still alive after 30 min: {alive}; not starting")
        return 4
    note("surface-refinement study: start (SUPERVISOR/surfref_study.py; log logs/surfref_study.log)")
    t1 = time.time()
    with (WS / "logs" / "surfref_study_console.log").open("a", encoding="utf-8") as out:
        proc = subprocess.Popen([str(PY), "-B", str(WS / "SUPERVISOR" / "surfref_study.py")], cwd=str(WS),
                                stdout=out, stderr=subprocess.STDOUT)
        try:
            rc = proc.wait(timeout=STUDY_MAX_H * 3600)
        except subprocess.TimeoutExpired:
            proc.kill()
            rc = "timeout"
    note(f"surface-refinement study: rc={rc} after {(time.time() - t1) / 60:.0f} min; Ansys left: {ansys_alive()}")
    if rc != 0:
        note("study did not complete; fig02 keeps the volume-ladder layout")
        return 0
    # User request (2026-11-25): show the surface-refinement result in fig02 (panel e + points in a/b). P11/P12
    # ran before the study, so redraw fig02, rebuild the hashed deliverables manifest + verify_deliverables
    # (package_x57_submission verify; no Fluent) and refresh the final quality report.
    import sys
    sys.path.insert(0, str(WS / "scripts"))
    from run_fluent_managed import build_f_only_env
    env = build_f_only_env()
    for args in (["plot_x57_baseline.py", "--figures", "2"], ["package_x57_submission.py", "verify"],
                 ["final_quality_audit.py"]):
        with (WS / "logs" / "surfref_followup_console.log").open("a", encoding="utf-8") as out:
            step_rc = subprocess.run([str(PY), "-B", str(WS / "scripts" / args[0]), *args[1:]], cwd=str(WS), env=env,
                                     stdout=out, stderr=subprocess.STDOUT).returncode
        note(f"follow-up {' '.join(args)}: rc={step_rc}")
        if step_rc != 0 and args[0] != "final_quality_audit.py":   # the audit returns non-zero for quality failures
            note("follow-up stopped; see logs/surfref_followup_console.log")
            break
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
