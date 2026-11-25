#!/usr/bin/env python3
"""
Sanctioned Intervention Bridge from Antigravity Supervisor -> GPT Astra.

Uses Astra's own ControlGate API (D:/FEA Coursework/Workspace/scripts/control_gate.py)
to queue structured mid-flight guidance into CONTROL/USER_INSTRUCTION.md so
running managed Fluent sessions cleanly stop (exit code 40) and deliver the
instruction directly to GPT Astra without user intervention.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from pathlib import Path

WS_ROOT = Path(r"D:\FEA Coursework\Workspace")
SCRIPTS_DIR = WS_ROOT / "scripts"
SUP_DIR = WS_ROOT / "SUPERVISOR"
INTERVENTIONS_LOG = SUP_DIR / "interventions.log"

sys.path.insert(0, str(SCRIPTS_DIR))
from control_gate import ControlGate  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Send sanctioned intervention instruction to GPT Astra")
    parser.add_argument("--reason", required=True, help="Short alert code / root cause")
    parser.add_argument("--message", required=True, help="Exact actionable instruction for GPT Astra")
    parser.add_argument("--force-run-state", action="store_true", help="Ensure STATE.txt is RUN if currently PAUSE")
    args = parser.parse_args()

    gate = ControlGate(WS_ROOT)
    before = gate.check()

    ts = dt.datetime.now().astimezone().isoformat(timespec="seconds")
    formatted = (
        f"[ANTIGRAVITY SUPERVISOR INTERVENTION @ {ts} | Reason: {args.reason}]\n"
        f"{args.message.strip()}\n"
        f"(After applying this fix, run control_gate.py ack-instruction and continue P2->P12 automatically without ending your turn.)"
    )
    gate.write_instruction(formatted)
    if args.force_run_state and before.get("state") == "PAUSE":
        gate.set_state("RUN", f"Resumed by Antigravity Supervisor after intervention ({args.reason})")

    SUP_DIR.mkdir(parents=True, exist_ok=True)
    with INTERVENTIONS_LOG.open("a", encoding="utf-8") as f:
        f.write(json.dumps({
            "timestamp": ts,
            "reason": args.reason,
            "before_state": before.get("state"),
            "message": args.message.strip(),
        }, ensure_ascii=False) + "\n")

    print(f"[SupervisorBridge] Delivered intervention ({args.reason}) to CONTROL/USER_INSTRUCTION.md")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
