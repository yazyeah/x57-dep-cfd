#!/usr/bin/env python3
"""
Control Gate ("开关口") for X-57 DEP Aircraft CFD Coursework.

Control files are confined to the CONTROL directory in this workspace.
Zero third-party dependencies required (uses h5py if available for deep HDF5 validation).

Exit codes for `check`:
  0  = RUN (no pending user instruction; safe to proceed)
  10 = PAUSE (user requested pause; checkpoint & stop/wait cleanly)
  20 = STOP (user requested graceful stop; checkpoint, summarize & exit)
  30 = ABORT (emergency abort requested; terminate tracked workers immediately)
  40 = INSTRUCTION_PENDING (user wrote a new instruction in CONTROL/USER_INSTRUCTION.md)
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional

WORKSPACE_ROOT = Path(__file__).resolve().parents[1]
CONTROL_DIR = WORKSPACE_ROOT / "CONTROL"
STATE_FILE = CONTROL_DIR / "STATE.txt"
INSTRUCTION_FILE = CONTROL_DIR / "USER_INSTRUCTION.md"
HISTORY_FILE = CONTROL_DIR / "INSTRUCTION_HISTORY.log"
CHECKPOINT_FILE = CONTROL_DIR / "CHECKPOINT.json"
STATUS_FILE = CONTROL_DIR / "STATUS.json"
PIDS_FILE = CONTROL_DIR / "active_pids.json"

INSTRUCTION_MARKER = "--- INSTRUCTION BELOW ---"
INSTRUCTION_TEMPLATE = (
    "# User Mid-Flight Instruction Inbox (用户实时指令收件箱)\n"
    "#\n"
    "# HOW TO USE:\n"
    "#   Write any instruction below the marker line at the bottom and save this file\n"
    "#   (or double-click 05_SEND_INSTRUCTION.bat).\n"
    "#   The AI agent and running Fluent supervisor check this file continuously.\n"
    "#   Leave everything below the marker BLANK when you have no new instruction.\n"
    "#\n"
    f"{INSTRUCTION_MARKER}\n"
)

VALID_STATES = {"RUN", "PAUSE", "STOP", "ABORT"}


def now_iso() -> str:
    return dt.datetime.now().astimezone().isoformat(timespec="seconds")


def atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=str(path.parent), prefix=".tmp_", suffix=".part")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
        os.replace(tmp_name, path)
    except Exception:
        if os.path.exists(tmp_name):
            try:
                os.remove(tmp_name)
            except OSError:
                pass
        raise


def atomic_write_json(path: Path, payload: Any) -> None:
    atomic_write_text(path, json.dumps(payload, indent=2, ensure_ascii=False) + "\n")


def get_workspace_free_gb() -> float:
    usage = shutil.disk_usage(str(WORKSPACE_ROOT))
    return round(usage.free / (1024 ** 3), 2)


def append_history(event: str, details: str) -> None:
    CONTROL_DIR.mkdir(parents=True, exist_ok=True)
    line = f"[{now_iso()}] [{event}] {details.strip()}\n"
    with open(HISTORY_FILE, "a", encoding="utf-8", newline="\n") as f:
        f.write(line)


def checked_command(command, **kwargs):
    """Preserve a managed child's control state across all controller layers."""
    kwargs["check"] = False
    result = subprocess.run(command, **kwargs)
    if result.returncode in (10, 20, 30, 40):
        raise SystemExit(result.returncode)
    result.check_returncode()
    return result


def request_fluent_exit(workdir):
    """Windows Fluent 25.2 consumes an empty trigger in the session's working directory."""
    flags = [Path(workdir) / name for name in ("exit-fluent.txt", "exit-fluent")]
    for flag in flags:
        flag.write_bytes(b"")
    return flags


class ControlGate:
    def __init__(self, workspace_root: Path = WORKSPACE_ROOT) -> None:
        self.root = workspace_root
        self.control_dir = workspace_root / "CONTROL"
        self.state_file = self.control_dir / "STATE.txt"
        self.instruction_file = self.control_dir / "USER_INSTRUCTION.md"
        self.history_file = self.control_dir / "INSTRUCTION_HISTORY.log"
        self.checkpoint_file = self.control_dir / "CHECKPOINT.json"
        self.status_file = self.control_dir / "STATUS.json"
        self.pids_file = self.control_dir / "active_pids.json"

    def read_state(self) -> str:
        if not self.state_file.exists():
            return "RUN"
        raw = self.state_file.read_text(encoding="utf-8", errors="ignore").strip().upper()
        first = raw.splitlines()[0].strip() if raw else "RUN"
        return first if first in VALID_STATES else "PAUSE"

    def set_state(self, state: str, reason: str = "") -> str:
        st = state.strip().upper()
        if st not in VALID_STATES:
            raise ValueError(f"Invalid state {st!r}; must be one of {sorted(VALID_STATES)}")
        atomic_write_text(self.state_file, st + "\n")
        append_history(f"STATE->{st}", reason or "State updated via control_gate")
        self.update_status(state=st, message=reason or f"State set to {st}")
        return st

    def read_pending_instruction(self) -> str:
        if not self.instruction_file.exists():
            return ""
        text = self.instruction_file.read_text(encoding="utf-8", errors="ignore")
        if INSTRUCTION_MARKER in text:
            body = text.rsplit(INSTRUCTION_MARKER, 1)[1]
        else:
            body = text
        lines = [ln for ln in body.splitlines() if ln.strip() and not ln.strip().startswith("#")]
        return "\n".join(lines).strip()

    def write_instruction(self, message: str) -> None:
        msg = message.strip()
        if not msg:
            return
        existing = self.read_pending_instruction()
        combined = f"{existing}\n{msg}".strip() if existing else msg
        atomic_write_text(self.instruction_file, INSTRUCTION_TEMPLATE + combined + "\n")
        append_history("USER_INSTRUCTION_QUEUED", msg)
        self.update_status(message=f"Pending user instruction: {msg[:120]}")

    def ack_instruction(self, response: str = "Acknowledged by agent") -> str:
        pending = self.read_pending_instruction()
        if pending:
            append_history("USER_INSTRUCTION_ACK", f"Instruction={pending!r} | AgentResponse={response!r}")
        atomic_write_text(self.instruction_file, INSTRUCTION_TEMPLATE)
        self.update_status(message=f"Acknowledged instruction: {response[:120]}")
        return pending

    def load_checkpoint(self) -> Dict[str, Any]:
        if not self.checkpoint_file.exists():
            return {"stages": {}, "current_stage": None}
        return json.loads(self.checkpoint_file.read_text(encoding="utf-8"))

    def update_checkpoint(
        self,
        stage: str,
        status: str,
        notes: Optional[str] = None,
        artifacts: Optional[List[str]] = None,
        active_case: Optional[str] = None,
        last_fluent_checkpoint: Optional[str] = None,
    ) -> Dict[str, Any]:
        cp = self.load_checkpoint()
        cp.setdefault("stages", {})
        st_obj = cp["stages"].setdefault(stage, {"title": stage, "status": "pending", "artifacts": [], "notes": ""})
        st_obj["status"] = status
        if notes is not None:
            st_obj["notes"] = notes
        if artifacts:
            existing = list(st_obj.get("artifacts", []))
            for a in artifacts:
                if a not in existing:
                    existing.append(a)
            st_obj["artifacts"] = existing
        cp["current_stage"] = stage
        cp["last_updated"] = now_iso()
        if active_case is not None:
            cp["active_case"] = active_case
        if last_fluent_checkpoint is not None:
            cp["last_fluent_checkpoint"] = last_fluent_checkpoint
        atomic_write_json(self.checkpoint_file, cp)
        append_history("CHECKPOINT", f"stage={stage} status={status} case={active_case or '-'} notes={notes or '-'}")
        self.update_status(current_stage=stage, active_case=cp.get("active_case"), message=notes or f"{stage}: {status}")
        return cp

    def load_pids(self) -> List[Dict[str, Any]]:
        if not self.pids_file.exists():
            return []
        try:
            data = json.loads(self.pids_file.read_text(encoding="utf-8"))
            return list(data.get("pids", []))
        except Exception:
            return []

    def save_pids(self, pids: List[Dict[str, Any]]) -> None:
        atomic_write_json(self.pids_file, {"pids": pids})

    def register_pid(self, pid: int, name: str, workdir: str = "", case: str = "") -> None:
        pids = [p for p in self.load_pids() if p.get("pid") != pid]
        pids.append({
            "pid": pid,
            "name": name,
            "workdir": workdir,
            "case": case,
            "started_at": now_iso(),
        })
        self.save_pids(pids)
        self.update_status(active_pid_count=len(pids))

    def unregister_pid(self, pid: int) -> None:
        pids = [p for p in self.load_pids() if p.get("pid") != pid]
        self.save_pids(pids)
        self.update_status(active_pid_count=len(pids))

    def trigger_fluent_exit_files(self) -> List[str]:
        dropped: List[str] = []
        for entry in self.load_pids():
            wd = entry.get("workdir")
            if wd and Path(wd).exists():
                if not entry.get("name", "").startswith("fluent_"):
                    continue
                try:
                    dropped.extend(str(flag) for flag in request_fluent_exit(wd))
                except OSError:
                    pass
        if dropped:
            append_history("FLUENT_EXIT_FLAG", f"Dropped exit-fluent in: {dropped}")
        return dropped

    def kill_tracked_pids(self) -> List[int]:
        killed: List[int] = []
        pids = self.load_pids()
        for entry in pids:
            pid = entry.get("pid")
            if not isinstance(pid, int):
                continue
            try:
                subprocess.run(
                    ["taskkill", "/PID", str(pid), "/T", "/F"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    check=False,
                )
                killed.append(pid)
            except Exception:
                pass
        self.save_pids([])
        append_history("EMERGENCY_KILL", f"Terminated tracked PIDs: {killed}")
        self.update_status(active_pid_count=0, message=f"Emergency killed PIDs: {killed}")
        return killed

    def update_status(
        self,
        state: Optional[str] = None,
        current_stage: Optional[str] = None,
        active_case: Optional[str] = None,
        message: Optional[str] = None,
        active_pid_count: Optional[int] = None,
    ) -> Dict[str, Any]:
        cur: Dict[str, Any] = {}
        if self.status_file.exists():
            try:
                cur = json.loads(self.status_file.read_text(encoding="utf-8"))
            except Exception:
                cur = {}
        cur["state"] = state if state is not None else self.read_state()
        if current_stage is not None:
            cur["current_stage"] = current_stage
        if active_case is not None:
            cur["active_case"] = active_case
        if message is not None:
            cur["message"] = message
        cur["last_heartbeat"] = now_iso()
        cur["d_drive_free_gb"] = get_workspace_free_gb()
        cur["workspace_free_gb"] = cur["d_drive_free_gb"]
        cur["active_pid_count"] = active_pid_count if active_pid_count is not None else len(self.load_pids())
        cur["has_pending_instruction"] = bool(self.read_pending_instruction())
        atomic_write_json(self.status_file, cur)
        return cur

    def check(self) -> Dict[str, Any]:
        state = self.read_state()
        instr = self.read_pending_instruction()
        if state == "ABORT":
            code = 30
            action = "ABORT_IMMEDIATELY"
        elif state == "STOP":
            code = 20
            action = "CHECKPOINT_AND_STOP"
        elif state == "PAUSE":
            code = 10
            action = "CHECKPOINT_AND_PAUSE"
        elif instr:
            code = 40
            action = "READ_AND_FOLLOW_USER_INSTRUCTION"
        else:
            code = 0
            action = "CONTINUE"
        return {
            "state": state,
            "exit_code": code,
            "action": action,
            "pending_instruction": instr,
            "d_drive_free_gb": get_workspace_free_gb(),
            "workspace_free_gb": get_workspace_free_gb(),
            "timestamp": now_iso(),
        }


def inspect_hdf5_kind(p: Path) -> Dict[str, Any]:
    from fluent_checkpoints import check_mesh_file
    surface, volume = check_mesh_file(p, deep=True)
    return {"valid_hdf5": surface, "has_volume_cells": volume}


def main() -> int:
    gate = ControlGate()
    parser = argparse.ArgumentParser(description="X-57 CFD Coursework Control Gate (workspace)")
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("check", help="Check control state and pending user instruction")

    p_set = sub.add_parser("set", help="Set state (RUN, PAUSE, STOP, ABORT)")
    p_set.add_argument("state", choices=["RUN", "PAUSE", "STOP", "ABORT"])
    p_set.add_argument("--reason", default="")
    p_set.add_argument("--signal-fluent", action="store_true")

    p_ins = sub.add_parser("instruct", help="Queue a mid-flight user instruction")
    p_ins.add_argument("message", nargs="+")

    p_ack = sub.add_parser("ack-instruction", help="Acknowledge and archive current user instruction")
    p_ack.add_argument("--response", default="Acknowledged and applied by agent")

    sub.add_parser("status", help="Display current status, checkpoint ledger, and F: disk space")
    sub.add_parser("checkpoint-show", help="Print CHECKPOINT.json")
    sub.add_parser("resume-scan", help="Scan 02_mesh and 03_cases for verified valid HDF5 checkpoints")

    p_cp = sub.add_parser("checkpoint-update", help="Update stage checkpoint")
    p_cp.add_argument("--stage", required=True)
    p_cp.add_argument("--status", required=True, choices=["pending", "in_progress", "paused", "done", "failed"])
    p_cp.add_argument("--note", default=None)
    p_cp.add_argument("--case", default=None)
    p_cp.add_argument("--fluent-ckpt", default=None)
    p_cp.add_argument("--artifacts", nargs="*", default=None)

    p_hb = sub.add_parser("heartbeat", help="Update live STATUS.json heartbeat")
    p_hb.add_argument("--stage", default=None)
    p_hb.add_argument("--case", default=None)
    p_hb.add_argument("--message", required=True)

    p_reg = sub.add_parser("register-pid", help="Register a tracked subprocess PID")
    p_reg.add_argument("--pid", type=int, required=True)
    p_reg.add_argument("--name", required=True)
    p_reg.add_argument("--workdir", default="")
    p_reg.add_argument("--case", default="")

    p_unreg = sub.add_parser("unregister-pid", help="Unregister a subprocess PID")
    p_unreg.add_argument("--pid", type=int, required=True)

    sub.add_parser("kill-tracked", help="Emergency terminate all tracked subprocess PIDs")

    args = parser.parse_args()

    if args.cmd == "check":
        res = gate.check()
        print(json.dumps(res, indent=2, ensure_ascii=False))
        return int(res["exit_code"])

    if args.cmd == "set":
        gate.set_state(args.state, args.reason)
        if args.signal_fluent or args.state in {"PAUSE", "STOP"}:
            dropped = gate.trigger_fluent_exit_files()
            if dropped:
                print(f"[ControlGate] Signaled graceful Fluent checkpoint exit: {dropped}")
        print(f"[ControlGate] State is now: {args.state}")
        return 0

    if args.cmd == "instruct":
        msg = " ".join(args.message)
        gate.write_instruction(msg)
        print(f"[ControlGate] Queued user instruction: {msg}")
        return 0

    if args.cmd == "ack-instruction":
        old = gate.ack_instruction(args.response)
        print(f"[ControlGate] Acknowledged instruction: {old!r}")
        return 0

    if args.cmd == "status":
        st = gate.update_status()
        cp = gate.load_checkpoint()
        instr = gate.read_pending_instruction()
        pids = gate.load_pids()
        print("=" * 70)
        print(f"  X-57 DEP CFD WORKSPACE CONTROL STATUS ({WORKSPACE_ROOT})")
        print("=" * 70)
        print(f"  Switch State    : {st.get('state')}")
        print(f"  Current Stage   : {cp.get('current_stage')}")
        print(f"  Active Case     : {cp.get('active_case')}")
        print(f"  Last Fluent Ckpt: {cp.get('last_fluent_checkpoint')}")
        print(f"  Last Message    : {st.get('message')}")
        print(f"  Last Heartbeat  : {st.get('last_heartbeat')}")
        print(f"  D: Free Space   : {st.get('d_drive_free_gb', st.get('workspace_free_gb'))} GB")
        print(f"  Tracked PIDs    : {len(pids)} -> {pids}")
        print(f"  Pending Instr.  : {instr if instr else '(none)'}")
        print("-" * 70)
        print("  Stage Checklist:")
        for sid, info in cp.get("stages", {}).items():
            print(f"    [{info.get('status', 'pending'):11s}] {sid}: {info.get('title', '')}")
        print("=" * 70)
        return 0

    if args.cmd == "checkpoint-show":
        print(json.dumps(gate.load_checkpoint(), indent=2, ensure_ascii=False))
        return 0

    if args.cmd == "resume-scan":
        found: Dict[str, Any] = {"meshes": [], "cases": {}}
        mesh_root = WORKSPACE_ROOT / "02_mesh"
        if mesh_root.exists():
            for p in sorted(mesh_root.rglob("*.msh.h5"), key=lambda x: x.stat().st_mtime, reverse=True):
                meta = inspect_hdf5_kind(p)
                found["meshes"].append({
                    "path": str(p),
                    "size_mb": round(p.stat().st_size / (1024 ** 2), 2),
                    "valid_hdf5": meta["valid_hdf5"],
                    "has_volume_cells": meta["has_volume_cells"],
                    "mtime": dt.datetime.fromtimestamp(p.stat().st_mtime).isoformat(timespec="seconds"),
                })
        cases_root = WORKSPACE_ROOT / "03_cases"
        if cases_root.exists():
            for case_dir in sorted(d for d in cases_root.iterdir() if d.is_dir()):
                from fluent_checkpoints import latest_pair
                case, data, errors = latest_pair(case_dir, deep=True)
                found["cases"][case_dir.name] = {
                    "latest_valid_cas": str(case) if case else None,
                    "latest_valid_dat": str(data) if data else None,
                    "corrupt_or_incomplete_files": errors,
                }
        out = {
            "workspace_root": str(WORKSPACE_ROOT),
            "state": gate.read_state(),
            "d_drive_free_gb": get_workspace_free_gb(),
            "workspace_free_gb": get_workspace_free_gb(),
            "checkpoint": gate.load_checkpoint(),
            "discovered_valid_checkpoints": found,
        }
        print(json.dumps(out, indent=2, ensure_ascii=False))
        return 0

    if args.cmd == "checkpoint-update":
        cp = gate.update_checkpoint(
            stage=args.stage,
            status=args.status,
            notes=args.note,
            artifacts=args.artifacts,
            active_case=args.case,
            last_fluent_checkpoint=args.fluent_ckpt,
        )
        print(json.dumps(cp["stages"][args.stage], indent=2, ensure_ascii=False))
        return 0

    if args.cmd == "heartbeat":
        st = gate.update_status(current_stage=args.stage, active_case=args.case, message=args.message)
        print(json.dumps(st, indent=2, ensure_ascii=False))
        return 0

    if args.cmd == "register-pid":
        gate.register_pid(args.pid, args.name, args.workdir, args.case)
        return 0

    if args.cmd == "unregister-pid":
        gate.unregister_pid(args.pid)
        return 0

    if args.cmd == "kill-tracked":
        killed = gate.kill_tracked_pids()
        print(f"[ControlGate] Killed tracked PIDs: {killed}")
        return 0

    return 0


if __name__ == "__main__":
    sys.exit(main())
