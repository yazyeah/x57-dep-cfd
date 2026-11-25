# GEMINI.md — X-57 fast-track unattended run (highest priority rules for this workspace)

The user is NOT supervising. Your only job is to launch, monitor and (rarely) resume the
fast-track pipeline until it completes. Full details: `FASTTRACK_RUNBOOK.md`.

## Commands (PowerShell)
- Start / resume (idempotent, single instance):
  `powershell -ExecutionPolicy Bypass -File "D:\FEA Coursework\Workspace\00_FASTTRACK_START.ps1"`
- Monitor (blocks <= 9 min, then returns):
  `powershell -ExecutionPolicy Bypass -File "D:\FEA Coursework\Workspace\00_FASTTRACK_STATUS.ps1" -Wait 540`
  exit 0 RUNNING -> call it again | 2 COMPLETE -> report | 1 HALTED -> see below | 3 NOT RUNNING -> run Start again

Budget: compute stages P2–P10 share 15 h from the 08:15 start (nominal ~12.5 h); P11/P12 (figures, report)
run afterwards (~1.25 h). Coursework-brief stages P2–P6 are never shortened; extensions P7–P10 absorb delays.
Quality update 2026-11-24: read `FASTTRACK_UPDATE_20261124.md`. It is loaded by
`00_FASTTRACK_APPLY_UPDATE.ps1` (run it ONCE); that helper restarts the orchestrator once at a safe point,
so one short ORCHESTRATOR_NOT_RUNNING (exit 3) is expected — wait one more monitor cycle before relaunching.

## Hard rules
1. Never launch `fluent.exe`, `MAPDL.exe`, `p2_tui_driver.py`, `p2_driver.py`, `run_p3_to_p12_auto.py`,
   `astra_watchdog.py`, `complete_production_mesh.py`, `run_refined_ftm_level.py` or any stage script by hand.
   The orchestrator `SUPERVISOR\run_all_fasttrack.py` (started by the Start script) does everything.
2. Never edit `scripts\fasttrack_profile.py`, any acceptance/QA threshold, `assess_*.py`, `fasttrack_mesh.py`,
   `verify_deliverables.py`, `final_quality_audit.py`, `render_mapdl_fields.py` colour scales, or any structural
   gauge/load/material input. Never fabricate, copy or hand-edit result files
   (`*_qa.json`, `mesh_qa.json`, `iteration_qa.json`, CSV/JSON deliverables, figures).
3. Never write `CONTROL\STATE.txt` or `CONTROL\USER_INSTRUCTION.md`; never delete files.
4. While the monitor says RUNNING, do nothing else: just keep polling. Long silent periods are normal
   (one Fluent block can take 10–25 min, a Fine meshing session up to ~80 min); every session has its own
   wall/idle guard and the orchestrator restarts any stage that produces no new result file for 60–120 min.
5. HALTED (exit 1): read the JSON `log_tail`, `logs\fasttrack_orchestrator.log` (last 80 lines) and the failing
   stage's evidence (`logs\<stage>_execution.json`, `03_cases\<case>\fasttrack_events.jsonl`, `logs\p2_fasttrack.log`).
   - If `CONTROL\STATE.txt` is PAUSE/STOP/ABORT or a user instruction is pending: the user stopped it. Stop and report.
   - If the cause is a Python crash in our scripts (Traceback with KeyError/AttributeError/TypeError/NameError/
     ImportError, or a Fluent settings-API name error) you may make ONE minimal fix of that line (no threshold or
     logic changes), then run the Start script again (it resumes). At most 2 such fixes per distinct error.
   - Otherwise (physical divergence after automatic recovery, no admissible mesh, etc.) run the Start script once
     more; if it halts again at the same stage, stop and write `DELIVERABLES\run_incident_report.md`
     (stage, error, evidence paths, what was tried).
6. COMPLETE (exit 2): read `DELIVERABLES\final_quality_report.md` and `logs\final_deliverables_verification.log`
   and report the PASS/WARN/FAIL table, total hours, and where the deliverables are. Do not "fix" WARN/FAIL rows.
