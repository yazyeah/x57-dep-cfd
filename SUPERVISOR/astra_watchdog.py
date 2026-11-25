#!/usr/bin/env python3
"""
Zero-Quota Event-Driven Watchdog for GPT Astra (X-57 DEP CFD Coursework).

Runs locally in Python (0 LLM tokens while healthy). Polls workspace telemetry,
transcripts, process liveness, and mesh/solver/FSI quality artifacts every 20s.
Exits immediately with a structured JSON alert ONLY when:
  - Fluent stalls silently (hang/deadlock) or exceeds wall-clock bounds
  - Repeated Fluent failures / spin-loops occur
  - Unsafe meshing config (e.g., OrthogonalQuality >= 0.12) is detected
  - Mesh / Solver / FSI / Deliverables quality gate fails or solver diverges
  - Astra becomes idle/stopped before P12 completion
  - A major stage milestone (P2/S2, S3, S5, S7/P12) completes

Strictly read-only on Astra's active directories; persists its own state only
inside D:/FEA Coursework/Workspace/SUPERVISOR/.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import psutil

WS_ROOT = Path(r"D:\FEA Coursework\Workspace")
CONTROL_DIR = WS_ROOT / "CONTROL"
SUP_DIR = WS_ROOT / "SUPERVISOR"
CURSOR_FILE = SUP_DIR / "watchdog_cursor.json"
STATE_FILE = SUP_DIR / "watchdog_state.json"
ALERT_FILE = SUP_DIR / "latest_alert.json"
LOG_FILE = SUP_DIR / "watchdog.log"

STATUS_FILE = CONTROL_DIR / "STATUS.json"
CHECKPOINT_FILE = CONTROL_DIR / "CHECKPOINT.json"
HISTORY_FILE = CONTROL_DIR / "INSTRUCTION_HISTORY.log"
PIDS_FILE = CONTROL_DIR / "active_pids.json"

# --- Configurable Safety & Quality Thresholds ---
POLL_SECONDS = 20.0
MESH_SILENT_STALL_S = 22 * 60       # 22 min without new .trn bytes during meshing
SOLVER_SILENT_STALL_S = 15 * 60     # 15 min without new .trn / force output during solver
ASTRA_IDLE_S = 10 * 60              # 10 min with zero active workers & no telemetry update
MAX_CONSECUTIVE_FAILS = 3           # >=3 consecutive non-zero Fluent exits
MAX_SAME_ERROR_REPEATS = 2          # >=2 consecutive identical fatal error signatures

WALLCLOCK_CAPS_MIN = {
    "coarse_mesh": 50.0,
    "medium_mesh": 75.0,
    "fine_mesh": 115.0,
    "solver": 160.0,
}

CELL_WINDOWS = {
    "coarse": (280_000, 380_000),
    "medium": (560_000, 680_000),
    "fine": (940_000, 1_044_000),
}
STUDENT_CELL_CAP = 1_048_576

DIVERGENCE_PATTERNS = [
    re.compile(r"floating point exception", re.I),
    re.compile(r"divergence detected in amg solver", re.I),
    re.compile(r"sigsegv|segmentation violation", re.I),
    re.compile(r"turbulent viscosity limited to viscosity ratio of 1\.000000e\+05 in [5-9]\d{4,} cells", re.I),
    re.compile(r"exceeds the student license|cell limit exceeded", re.I),
]

FATAL_MESH_ERRORS = [
    ("hexcore_mixed_quad", re.compile(r"Hexcore cannot mesh mixed/quad boundary faces", re.I)),
    ("negative_volume", re.compile(r"negative cell volume|minimum volume:\s*-", re.I)),
    ("journal_error", re.compile(r"An error or interrupt occurred while reading the journal", re.I)),
    ("prism_failed", re.compile(r"Error:.*prism|Failed in auto-meshing", re.I)),
    ("student_cap", re.compile(r"cell limit|student.*limit|license.*exceeded", re.I)),
]


def now_iso() -> str:
    return dt.datetime.now().astimezone().isoformat(timespec="seconds")


def atomic_write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def log_line(msg: str) -> None:
    SUP_DIR.mkdir(parents=True, exist_ok=True)
    line = f"[{now_iso()}] {msg}\n"
    with LOG_FILE.open("a", encoding="utf-8") as f:
        f.write(line)


def safe_read_json(path: Path) -> Optional[Dict[str, Any]]:
    try:
        if not path.is_file():
            return None
        return json.loads(path.read_text(encoding="utf-8-sig", errors="replace"))
    except Exception:
        return None


def tail_text(path: Path, max_bytes: int = 8192) -> str:
    try:
        size = path.stat().st_size
        with path.open("rb") as f:
            if size > max_bytes:
                f.seek(size - max_bytes)
            return f.read().decode("utf-8", errors="replace")
    except Exception:
        return ""


def active_workspace_processes() -> List[Dict[str, Any]]:
    procs: List[Dict[str, Any]] = []
    ws_str = str(WS_ROOT).lower()
    for p in psutil.process_iter(["pid", "name", "cmdline", "create_time"]):
        try:
            name = (p.info["name"] or "").lower()
            cmd = " ".join(p.info["cmdline"] or []).lower()
            is_ansys = any(k in name for k in ("fl_mpi", "fl2520", "cx2520", "fluent", "mapdl", "ansys"))
            is_ws_py = ("python" in name) and (ws_str in cmd or "run_fluent_managed" in cmd or "run_x57" in cmd) and ("astra_watchdog" not in cmd)
            if is_ansys or is_ws_py:
                procs.append({
                    "pid": p.info["pid"],
                    "name": p.info["name"],
                    "age_min": round((time.time() - p.info["create_time"]) / 60.0, 1),
                })
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    return procs


def find_active_workdir(status: Dict[str, Any]) -> Optional[Path]:
    pids_doc = safe_read_json(PIDS_FILE) or {}
    for entry in pids_doc.get("pids", []):
        wd = entry.get("workdir")
        if wd and Path(wd).is_dir():
            return Path(wd)
    # Fallback: latest fluent-*.trn in 02_mesh or 03_cases modified within 2 hours
    newest: Optional[Tuple[float, Path]] = None
    cutoff = time.time() - 7200
    for sub in ("02_mesh", "03_cases"):
        root = WS_ROOT / sub
        if not root.is_dir():
            continue
        for trn in root.rglob("fluent-*.trn"):
            try:
                mt = trn.stat().st_mtime
                if mt >= cutoff and (newest is None or mt > newest[0]):
                    newest = (mt, trn.parent)
            except OSError:
                continue
    return newest[1] if newest else None


def latest_trn_in(workdir: Path) -> Optional[Path]:
    trns = list(workdir.glob("fluent-*.trn"))
    if not trns:
        return None
    return max(trns, key=lambda p: p.stat().st_mtime)


def scan_qa_files() -> Dict[str, float]:
    mtimes: Dict[str, float] = {}
    patterns = [
        ("02_mesh", "mesh_qa.json"),
        ("02_mesh", "volume_readback.json"),
        ("02_mesh", "mesh_config.json"),
        ("03_cases", "iteration_qa.json"),
        ("DELIVERABLES", "*.json"),
    ]
    for sub, pat in patterns:
        base = WS_ROOT / sub
        if not base.is_dir():
            continue
        for p in base.rglob(pat):
            try:
                mtimes[str(p)] = p.stat().st_mtime
            except OSError:
                continue
    return mtimes


def init_cursor() -> Dict[str, Any]:
    cp = safe_read_json(CHECKPOINT_FILE) or {}
    stages = {k: v.get("status") for k, v in (cp.get("stages") or {}).items() if isinstance(v, dict)}
    hist_size = HISTORY_FILE.stat().st_size if HISTORY_FILE.is_file() else 0
    return {
        "initialized_at": now_iso(),
        "history_offset": hist_size,
        "stage_statuses": stages,
        "qa_mtimes": scan_qa_files(),
        "consecutive_failures": 0,
        "recent_error_sigs": [],
        "alerted_keys": [],
    }


def load_or_create_cursor(reset: bool = False) -> Dict[str, Any]:
    if not reset:
        existing = safe_read_json(CURSOR_FILE)
        if existing and "history_offset" in existing:
            return existing
    cur = init_cursor()
    atomic_write_json(CURSOR_FILE, cur)
    return cur


def extract_error_sig(text: str) -> Optional[str]:
    for tag, rx in FATAL_MESH_ERRORS:
        if rx.search(text):
            return tag
    for rx in DIVERGENCE_PATTERNS:
        if rx.search(text):
            return rx.pattern[:40]
    return None


def audit_mesh_qa(path: Path) -> List[str]:
    issues: List[str] = []
    data = safe_read_json(path)
    if not data:
        return [f"Unreadable mesh_qa.json: {path}"]
    level = (data.get("level") or "").lower()
    cells = data.get("cells")
    min_oq = data.get("min_orthogonal_quality")
    min_vol = data.get("min_volume_m3")
    passed = data.get("passed")
    solver_oq = (data.get("independent_solver_quality") or {}).get("standard")

    if passed is not True:
        failed_checks = [k for k, v in (data.get("checks") or {}).items() if not v]
        issues.append(f"mesh_qa passed=False ({level}); failed_checks={failed_checks}")
    if isinstance(cells, int):
        if cells >= STUDENT_CELL_CAP:
            issues.append(f"{level} cells={cells} >= Student hard cap {STUDENT_CELL_CAP}")
        if level in CELL_WINDOWS:
            lo, hi = CELL_WINDOWS[level]
            if not (lo <= cells <= hi):
                issues.append(f"{level} cells={cells} outside recommended window [{lo}, {hi}]")
    if isinstance(min_oq, (int, float)) and min_oq <= 0.10:
        issues.append(f"{level} mesher min_orthogonal_quality={min_oq:.4f} <= 0.10")
    if isinstance(solver_oq, (int, float)) and solver_oq <= 0.10:
        issues.append(f"{level} solver reload standard OQ={solver_oq:.4f} <= 0.10")
    if isinstance(min_vol, (int, float)) and min_vol <= 0:
        issues.append(f"{level} non-positive min_volume_m3={min_vol}")
    return issues


def audit_iteration_qa(path: Path) -> List[str]:
    issues: List[str] = []
    data = safe_read_json(path)
    if not data:
        return [f"Unreadable iteration_qa.json: {path}"]
    if data.get("passed") is not True:
        failed = [k for k, v in (data.get("checks") or {}).items() if not v]
        issues.append(f"Solver iteration_qa failed for {path.parent.name}: failed_checks={failed}")
    return issues


def check_once(cursor: Dict[str, Any], runtime: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    now = time.time()
    status = safe_read_json(STATUS_FILE) or {}
    cp = safe_read_json(CHECKPOINT_FILE) or {}
    procs = active_workspace_processes()
    has_fluent = any(any(k in p["name"].lower() for k in ("fl_mpi", "fl2520", "cx2520", "fluent")) for p in procs)
    active_case = str(status.get("active_case") or "")
    current_stage = str(status.get("current_stage") or cp.get("current_stage") or "")
    state_str = str(status.get("state") or "RUN").upper()
    workdir = find_active_workdir(status)

    # Update live heartbeat state file (zero LLM cost)
    live_state = {
        "checked_at": now_iso(),
        "astra_state": state_str,
        "current_stage": current_stage,
        "active_case": active_case,
        "status_message": status.get("message", ""),
        "active_process_count": len(procs),
        "has_fluent": has_fluent,
        "active_workdir": str(workdir) if workdir else None,
        "consecutive_failures": cursor.get("consecutive_failures", 0),
        "d_drive_free_gb": status.get("d_drive_free_gb"),
    }

    # --- 1. Check INSTRUCTION_HISTORY.log for new FLUENT_EXIT failures ---
    if HISTORY_FILE.is_file():
        size = HISTORY_FILE.stat().st_size
        offset = int(cursor.get("history_offset", 0))
        if size < offset:
            offset = 0
        if size > offset:
            with HISTORY_FILE.open("rb") as f:
                f.seek(offset)
                new_text = f.read().decode("utf-8", errors="replace")
            cursor["history_offset"] = size
            for line in new_text.splitlines():
                if "[FLUENT_EXIT]" in line:
                    m_rc = re.search(r"managed_rc=(\d+)\s+native_rc=(\d+)", line)
                    m_case = re.search(r"finished \(([^)]+)\)", line)
                    case_lbl = m_case.group(1) if m_case else active_case
                    if m_rc:
                        mrc, nrc = int(m_rc.group(1)), int(m_rc.group(2))
                        if mrc == 0 and nrc == 0:
                            cursor["consecutive_failures"] = 0
                            cursor["recent_error_sigs"] = []
                            log_line(f"OK FLUENT_EXIT rc=0 case={case_lbl}")
                        elif mrc not in (10, 20, 40):
                            cursor["consecutive_failures"] = int(cursor.get("consecutive_failures", 0)) + 1
                            trn_tail = ""
                            err_sig = f"rc_{mrc}_{nrc}"
                            if workdir:
                                trn = latest_trn_in(workdir)
                                if trn:
                                    trn_tail = tail_text(trn, 4096)
                                    found_sig = extract_error_sig(trn_tail)
                                    if found_sig:
                                        err_sig = found_sig
                            sigs = list(cursor.get("recent_error_sigs", []))
                            sigs.append(err_sig)
                            cursor["recent_error_sigs"] = sigs[-6:]
                            log_line(f"FAIL FLUENT_EXIT case={case_lbl} rc={mrc}/{nrc} sig={err_sig} streak={cursor['consecutive_failures']}")
                            same_repeat = len(sigs) >= MAX_SAME_ERROR_REPEATS and len(set(sigs[-MAX_SAME_ERROR_REPEATS:])) == 1
                            if cursor["consecutive_failures"] >= MAX_CONSECUTIVE_FAILS or same_repeat:
                                atomic_write_json(CURSOR_FILE, cursor)
                                return {
                                    "alert_type": "REPEATED_FAILURE_LOOP",
                                    "severity": "HIGH",
                                    "timestamp": now_iso(),
                                    "stage": current_stage,
                                    "case": case_lbl,
                                    "consecutive_failures": cursor["consecutive_failures"],
                                    "recent_error_sigs": cursor["recent_error_sigs"],
                                    "history_line": line,
                                    "workdir": str(workdir) if workdir else None,
                                    "transcript_tail": trn_tail[-2000:],
                                }

    # --- 2. Check active Fluent silent stall, live divergence & wall-clock limit ---
    if has_fluent and workdir:
        trn = latest_trn_in(workdir)
        if trn and trn.is_file():
            st = trn.stat()
            trn_key = str(trn)
            prev_key = runtime.get("trn_key")
            prev_size = runtime.get("trn_size", -1)
            if trn_key != prev_key or st.st_size != prev_size:
                runtime["trn_key"] = trn_key
                runtime["trn_size"] = st.st_size
                runtime["trn_last_growth"] = st.st_mtime
            silent_s = now - float(runtime.get("trn_last_growth", st.st_mtime))
            live_state["active_trn"] = trn.name
            live_state["active_trn_bytes"] = st.st_size
            live_state["trn_silent_min"] = round(silent_s / 60.0, 1)

            tail = tail_text(trn, 6144)
            is_meshing = ("meshing" in str(status.get("message", "")).lower()) or ("02_mesh" in str(workdir).lower())

            # Check live divergence / crash signatures in solver or mesher
            for rx in DIVERGENCE_PATTERNS:
                if rx.search(tail):
                    key = f"div:{trn.name}:{rx.pattern[:20]}"
                    if key not in cursor.get("alerted_keys", []):
                        cursor.setdefault("alerted_keys", []).append(key)
                        atomic_write_json(CURSOR_FILE, cursor)
                        return {
                            "alert_type": "LIVE_DIVERGENCE_OR_CRASH",
                            "severity": "CRITICAL",
                            "timestamp": now_iso(),
                            "stage": current_stage,
                            "case": active_case,
                            "matched_pattern": rx.pattern,
                            "transcript": str(trn),
                            "transcript_tail": tail[-2000:],
                        }

            # Check silent stall
            stall_limit = MESH_SILENT_STALL_S if is_meshing else SOLVER_SILENT_STALL_S
            if silent_s >= stall_limit:
                # For solver, also check if force_history.out is actively growing
                force_file = workdir / "force_history.out"
                if (not is_meshing) and force_file.is_file() and (now - force_file.stat().st_mtime) < stall_limit:
                    pass
                else:
                    key = f"stall:{trn.name}:{st.st_size}"
                    if key not in cursor.get("alerted_keys", []):
                        cursor.setdefault("alerted_keys", []).append(key)
                        atomic_write_json(CURSOR_FILE, cursor)
                        return {
                            "alert_type": "FLUENT_SILENT_STALL",
                            "severity": "HIGH",
                            "timestamp": now_iso(),
                            "stage": current_stage,
                            "case": active_case,
                            "is_meshing": is_meshing,
                            "silent_minutes": round(silent_s / 60.0, 1),
                            "transcript": str(trn),
                            "transcript_bytes": st.st_size,
                            "transcript_tail": tail[-2000:],
                        }

        # Check wall-clock cap from STATUS.json message ("elapsed XX.X min")
        m_el = re.search(r"elapsed\s+([0-9.]+)\s+min", str(status.get("message", "")))
        if m_el:
            elapsed_min = float(m_el.group(1))
            live_state["fluent_elapsed_min"] = elapsed_min
            case_l = active_case.lower()
            is_meshing = ("meshing" in str(status.get("message", "")).lower()) or ("02_mesh" in str(workdir).lower())
            if is_meshing:
                cap = (WALLCLOCK_CAPS_MIN["fine_mesh"] if "fine" in case_l else
                       WALLCLOCK_CAPS_MIN["medium_mesh"] if "medium" in case_l else
                       WALLCLOCK_CAPS_MIN["coarse_mesh"])
                if "serial" in case_l:
                    cap *= 1.6  # Serial 1-rank prism extrusion legitimately takes ~1.5x longer than 4-rank MPI
            else:
                cap = WALLCLOCK_CAPS_MIN["solver"]
            if elapsed_min >= cap:
                key = f"wallcap:{active_case}:{int(cap)}"
                if key not in cursor.get("alerted_keys", []):
                    cursor.setdefault("alerted_keys", []).append(key)
                    atomic_write_json(CURSOR_FILE, cursor)
                    return {
                        "alert_type": "WALLCLOCK_LIMIT_EXCEEDED",
                        "severity": "HIGH",
                        "timestamp": now_iso(),
                        "stage": current_stage,
                        "case": active_case,
                        "elapsed_min": elapsed_min,
                        "cap_min": cap,
                        "workdir": str(workdir),
                        "transcript_tail": tail_text(trn, 2048) if (trn and trn.is_file()) else "",
                    }

    # --- 3. Check newly written QA / config / deliverables files ---
    prev_mtimes = cursor.get("qa_mtimes", {})
    curr_mtimes = scan_qa_files()
    changed_paths = [Path(p) for p, mt in curr_mtimes.items() if mt > float(prev_mtimes.get(p, 0.0)) + 1e-6]
    if changed_paths:
        cursor["qa_mtimes"] = curr_mtimes
        for p in changed_paths:
            name = p.name.lower()
            if name in ("volume_readback.json", "mesh_config.json"):
                cfg = safe_read_json(p) or {}
                oq = cfg.get("OrthogonalQuality", cfg.get("orthogonal_quality"))
                if isinstance(oq, (int, float)) and oq >= 0.12:
                    atomic_write_json(CURSOR_FILE, cursor)
                    return {
                        "alert_type": "UNSAFE_MESH_CONFIG",
                        "severity": "HIGH",
                        "timestamp": now_iso(),
                        "stage": current_stage,
                        "case": active_case,
                        "file": str(p),
                        "orthogonal_quality": oq,
                        "message": f"Detected unsafe native OrthogonalQuality={oq} (>=0.12) which risks Fluent meshing hang.",
                    }
            elif name == "mesh_qa.json":
                issues = audit_mesh_qa(p)
                if issues:
                    atomic_write_json(CURSOR_FILE, cursor)
                    return {
                        "alert_type": "MESH_QUALITY_FAILED",
                        "severity": "HIGH",
                        "timestamp": now_iso(),
                        "stage": current_stage,
                        "file": str(p),
                        "issues": issues,
                    }
                else:
                    # Canonical level passed (e.g. 02_mesh/coarse/mesh_qa.json)
                    if p.parent.name in ("coarse", "medium", "fine") and p.parent.parent.name == "02_mesh":
                        data = safe_read_json(p) or {}
                        log_line(f"PASS MESH LEVEL {p.parent.name}: cells={data.get('cells')} OQ={data.get('min_orthogonal_quality')}")
            elif name == "iteration_qa.json":
                issues = audit_iteration_qa(p)
                if issues:
                    atomic_write_json(CURSOR_FILE, cursor)
                    return {
                        "alert_type": "SOLVER_QUALITY_FAILED",
                        "severity": "HIGH",
                        "timestamp": now_iso(),
                        "stage": current_stage,
                        "file": str(p),
                        "issues": issues,
                    }

    # --- 4. Check Checkpoint Stage Milestones & Full Completion ---
    stages = {k: v.get("status") for k, v in (cp.get("stages") or {}).items() if isinstance(v, dict)}
    prev_stages = cursor.get("stage_statuses", {})
    newly_done = [k for k, v in stages.items() if v == "done" and prev_stages.get(k) != "done"]
    if newly_done:
        cursor["stage_statuses"] = stages
        atomic_write_json(CURSOR_FILE, cursor)
        if "S7_DELIVERABLES_PACK" in newly_done or "P12" in newly_done:
            return {
                "alert_type": "ALL_WORK_COMPLETED",
                "severity": "INFO",
                "timestamp": now_iso(),
                "newly_done_stages": newly_done,
                "stage_statuses": stages,
            }
        # Wake on key review gates (P2 mesh complete, S3 mesh convergence complete, S5 FSI/postproc complete)
        review_gates = {"S2_MESH_STUDY", "P2", "S3_SOLVER_MESH_CONVERGENCE", "S5_POSTPROC_EXTRACTION"}
        if any(s in review_gates for s in newly_done):
            return {
                "alert_type": "MILESTONE_COMPLETED",
                "severity": "INFO",
                "timestamp": now_iso(),
                "newly_done_stages": newly_done,
                "stage_statuses": stages,
            }
    else:
        cursor["stage_statuses"] = stages

    # --- 5. Check Astra Idle / Stopped Early ---
    all_done = stages.get("S7_DELIVERABLES_PACK") == "done"
    if (not all_done) and (not procs):
        latest_activity = 0.0
        for fpath in (STATUS_FILE, CHECKPOINT_FILE, HISTORY_FILE):
            if fpath.is_file():
                latest_activity = max(latest_activity, fpath.stat().st_mtime)
        idle_s = now - latest_activity if latest_activity > 0 else 0.0
        live_state["idle_min"] = round(idle_s / 60.0, 1)
        if idle_s >= ASTRA_IDLE_S:
            key = f"idle:{int(latest_activity)}"
            if key not in cursor.get("alerted_keys", []):
                cursor.setdefault("alerted_keys", []).append(key)
                atomic_write_json(CURSOR_FILE, cursor)
                return {
                    "alert_type": "ASTRA_IDLE_OR_STOPPED",
                    "severity": "MEDIUM",
                    "timestamp": now_iso(),
                    "stage": current_stage,
                    "case": active_case,
                    "astra_state": state_str,
                    "idle_minutes": round(idle_s / 60.0, 1),
                    "last_status_message": status.get("message", ""),
                }

    # Persist live heartbeat + cursor
    atomic_write_json(STATE_FILE, live_state)
    atomic_write_json(CURSOR_FILE, cursor)
    return None


def main() -> int:
    parser = argparse.ArgumentParser(description="Zero-quota event-driven Astra supervisor watchdog")
    parser.add_argument("--once", action="store_true", help="Run a single diagnostic check and exit")
    parser.add_argument("--reset-cursor", action="store_true", help="Reset baseline cursor to current workspace state")
    parser.add_argument("--poll-seconds", type=float, default=POLL_SECONDS)
    args = parser.parse_args()

    SUP_DIR.mkdir(parents=True, exist_ok=True)
    cursor = load_or_create_cursor(reset=args.reset_cursor)
    runtime: Dict[str, Any] = {}
    log_line(f"Watchdog started (once={args.once}, reset={args.reset_cursor}, poll={args.poll_seconds}s)")

    while True:
        alert = check_once(cursor, runtime)
        if alert is not None:
            atomic_write_json(ALERT_FILE, alert)
            log_line(f"ALERT FIRED: {alert['alert_type']} | {alert.get('stage')} | {alert.get('case', '')}")
            print("=== ASTRA_WATCHDOG_ALERT ===")
            print(json.dumps(alert, indent=2, ensure_ascii=False))
            return 0 if alert["alert_type"] in ("MILESTONE_COMPLETED", "ALL_WORK_COMPLETED") else 10
        if args.once:
            state = safe_read_json(STATE_FILE) or {}
            print("=== ASTRA_WATCHDOG_HEALTHY ===")
            print(json.dumps(state, indent=2, ensure_ascii=False))
            return 0
        time.sleep(args.poll_seconds)


if __name__ == "__main__":
    raise SystemExit(main())
