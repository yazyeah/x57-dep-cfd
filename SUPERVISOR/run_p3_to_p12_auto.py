#!/usr/bin/env python3
"""
Unattended End-to-End Orchestrator for P3 -> P12 (X-57 DEP CFD + 1-Way FSI).

Runs strictly locally (0 LLM tokens while healthy), chaining the verified
workspace pipeline scripts/run_x57_stage.py P3..P12 sequentially with:
  - Per-stage wall-clock logging & resume skip for already-completed stages
  - Windows sleep prevention (SetThreadExecutionState)
  - Immediate structured error exit so Antigravity wakes up automatically
    ONLY if a stage fails or when P12 completes cleanly.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import subprocess
import sys
import time
from pathlib import Path

WS_ROOT = Path(r"D:\FEA Coursework\Workspace")
SCRIPTS_DIR = WS_ROOT / "scripts"
SUP_DIR = WS_ROOT / "SUPERVISOR"
STATUS_OUT = SUP_DIR / "p3_p12_auto_status.json"
LOG_OUT = SUP_DIR / "p3_p12_auto.log"

sys.path.insert(0, str(SCRIPTS_DIR))
from control_gate import ControlGate, atomic_write_json  # noqa: E402
from run_fluent_managed import build_f_only_env, set_prevent_sleep  # noqa: E402

ALL_STAGES = ["P3", "P4", "P5", "P6", "P7", "P8", "P9", "P10", "P11", "P12"]


def now_iso() -> str:
    return dt.datetime.now().astimezone().isoformat(timespec="seconds")


def log(msg: str) -> None:
    SUP_DIR.mkdir(parents=True, exist_ok=True)
    line = f"[{now_iso()}] {msg}"
    print(line, flush=True)
    with LOG_OUT.open("a", encoding="utf-8") as f:
        f.write(line + "\n")


def stage_already_completed(stage: str) -> bool:
    exec_file = WS_ROOT / "logs" / f"{stage}_execution.json"
    if not exec_file.is_file():
        return False
    try:
        data = json.loads(exec_file.read_text(encoding="utf-8-sig"))
        return data.get("status") == "completed"
    except Exception:
        return False


def main() -> int:
    parser = argparse.ArgumentParser(description="Unattended P3..P12 pipeline orchestrator")
    parser.add_argument("--from-stage", choices=ALL_STAGES, default="P3")
    parser.add_argument("--to-stage", choices=ALL_STAGES, default="P12")
    args = parser.parse_args()

    start_i = ALL_STAGES.index(args.from_stage)
    end_i = ALL_STAGES.index(args.to_stage)
    stages = ALL_STAGES[start_i : end_i + 1]

    gate = ControlGate(WS_ROOT)
    chk = gate.check()
    if chk["exit_code"] != 0:
        raise RuntimeError(f"ControlGate not ready for RUN: {chk}")

    set_prevent_sleep(True)
    env = build_f_only_env()
    history = []

    try:
        for stage in stages:
            if stage_already_completed(stage):
                log(f"SKIP {stage} (already completed)")
                history.append({"stage": stage, "status": "skipped_already_done", "at": now_iso()})
                continue

            t0 = time.time()
            log(f"START {stage}")
            atomic_write_json(STATUS_OUT, {
                "updated_at": now_iso(),
                "current_stage": stage,
                "status": "running",
                "history": history,
            })

            cmd = [sys.executable, "-B", str(SCRIPTS_DIR / "run_x57_stage.py"), stage]
            proc = subprocess.run(cmd, cwd=str(WS_ROOT), env=env)
            elapsed_min = round((time.time() - t0) / 60.0, 2)

            if proc.returncode != 0:
                err_payload = {
                    "updated_at": now_iso(),
                    "failed_stage": stage,
                    "returncode": proc.returncode,
                    "elapsed_min": elapsed_min,
                    "status": "failed",
                    "history": history,
                }
                atomic_write_json(STATUS_OUT, err_payload)
                log(f"FAIL {stage} rc={proc.returncode} in {elapsed_min} min")
                print("=== P3_P12_AUTO_FAILED ===")
                print(json.dumps(err_payload, indent=2, ensure_ascii=False))
                return proc.returncode

            log(f"DONE {stage} in {elapsed_min} min")
            history.append({"stage": stage, "status": "completed", "elapsed_min": elapsed_min, "at": now_iso()})
            atomic_write_json(STATUS_OUT, {
                "updated_at": now_iso(),
                "last_completed_stage": stage,
                "status": "running",
                "history": history,
            })

        done_payload = {
            "updated_at": now_iso(),
            "status": "ALL_COMPLETED",
            "stages_run": stages,
            "history": history,
        }
        atomic_write_json(STATUS_OUT, done_payload)
        log("ALL STAGES COMPLETED SUCCESSFULLY!")
        print("=== P3_P12_ALL_COMPLETED ===")
        print(json.dumps(done_payload, indent=2, ensure_ascii=False))
        return 0
    finally:
        set_prevent_sleep(False)


if __name__ == "__main__":
    raise SystemExit(main())
