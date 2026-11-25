#!/usr/bin/env python3
"""
Managed ANSYS Fluent v252 Launcher (F: Drive NTFS Isolation):
  1. Workspace-local logs, temporary files, and user profile
  2. Visible Desktop GUI Mode (default, with -wait so launcher blocks cleanly until GUI exits!)
  3. Codex One-Click Stop Protection (Windows Win32 Job Object JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
     + SIGINT/SIGTERM/SIGBREAK handlers -> clicking Codex Stop kills fluent.exe + MPI tree cleanly)
  4. Overnight Sleep Lock (SetThreadExecutionState) + 15s live valid-HDF5 checkpoint sync
  5. Control Gate Watchdog (supports PAUSE/STOP/ABORT switches too)
"""

from __future__ import annotations

import argparse
import ctypes
import ctypes.wintypes as wt
import datetime as dt
import json
import os
import re
import psutil
import msvcrt
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Optional

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

from control_gate import ControlGate, WORKSPACE_ROOT, append_history, request_fluent_exit, atomic_write_json  # noqa: E402

FLUENT_EXE = Path(r"D:\Ansys\ANSYS Inc\ANSYS Student\v252\fluent\ntbin\win64\fluent.exe")
LOGS_DIR = WORKSPACE_ROOT / "logs"
TMP_DIR = WORKSPACE_ROOT / "_tmp"
CACHE_DIR = WORKSPACE_ROOT / "_cache"

ITER_RE = re.compile(r"^\s*(\d+)\s+[0-9.eE+-]+\s+[0-9.eE+-]+")


class _JOBOBJECT_BASIC_LIMIT_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("PerProcessUserTimeLimit", ctypes.c_int64),
        ("PerJobUserTimeLimit", ctypes.c_int64),
        ("LimitFlags", wt.DWORD),
        ("MinimumWorkingSetSize", ctypes.c_size_t),
        ("MaximumWorkingSetSize", ctypes.c_size_t),
        ("ActiveProcessLimit", wt.DWORD),
        ("Affinity", ctypes.c_size_t),
        ("PriorityClass", wt.DWORD),
        ("SchedulingClass", wt.DWORD),
    ]


class _IO_COUNTERS(ctypes.Structure):
    _fields_ = [
        (n, ctypes.c_uint64)
        for n in (
            "ReadOperationCount",
            "WriteOperationCount",
            "OtherOperationCount",
            "ReadTransferCount",
            "WriteTransferCount",
            "OtherTransferCount",
        )
    ]


class _JOBOBJECT_EXTENDED_LIMIT_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("BasicLimitInformation", _JOBOBJECT_BASIC_LIMIT_INFORMATION),
        ("IoInfo", _IO_COUNTERS),
        ("ProcessMemoryLimit", ctypes.c_size_t),
        ("JobMemoryLimit", ctypes.c_size_t),
        ("PeakProcessMemoryUsed", ctypes.c_size_t),
        ("PeakJobMemoryUsed", ctypes.c_size_t),
    ]


def attach_kill_on_close_job(proc: subprocess.Popen) -> Optional[int]:
    if os.name != "nt":
        return None
    try:
        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        k32.CreateJobObjectW.argtypes = [ctypes.c_void_p, wt.LPCWSTR]
        k32.CloseHandle.argtypes = [wt.HANDLE]
        k32.CreateJobObjectW.restype = wt.HANDLE
        k32.SetInformationJobObject.argtypes = [wt.HANDLE, ctypes.c_int, ctypes.c_void_p, wt.DWORD]
        k32.AssignProcessToJobObject.argtypes = [wt.HANDLE, wt.HANDLE]

        job = k32.CreateJobObjectW(None, None)
        if not job:
            return None
        info = _JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
        info.BasicLimitInformation.LimitFlags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        if not k32.SetInformationJobObject(job, 9, ctypes.byref(info), ctypes.sizeof(info)):
            k32.CloseHandle(job)
            return None
        if not k32.AssignProcessToJobObject(job, int(proc._handle)):
            k32.CloseHandle(job)
            return None
        return int(job)
    except Exception:
        return None


def confirm_job_ranks(job, workdir, earliest):
    """Verify MPI rank containment despite transient Hydra launch processes."""
    k32 = ctypes.WinDLL("kernel32",use_last_error=True)
    k32.OpenProcess.argtypes = [wt.DWORD,wt.BOOL,wt.DWORD]
    k32.OpenProcess.restype = wt.HANDLE
    k32.CloseHandle.argtypes = [wt.HANDLE]
    k32.IsProcessInJob.argtypes = [wt.HANDLE,wt.HANDLE,ctypes.POINTER(wt.BOOL)]
    k32.AssignProcessToJobObject.argtypes = [wt.HANDLE,wt.HANDLE]
    members = []
    install = FLUENT_EXE.resolve().parents[2]
    for proc in psutil.process_iter(["name","create_time"]):
        if (proc.info["name"] or "").lower() not in {"fl_mpi2520.exe","mpiexec.exe","hydra_pmi_proxy.exe"} or proc.info["create_time"] < earliest-1:
            continue
        try:
            if Path(proc.cwd()).resolve() != workdir or not Path(proc.exe()).resolve().is_relative_to(install):
                continue
            handle = k32.OpenProcess(0x0100 | 0x0001 | 0x1000,False,proc.pid)
            if not handle:
                if proc.is_running():raise ctypes.WinError(ctypes.get_last_error())
                continue
            try:
                state=wt.BOOL()
                if not k32.IsProcessInJob(handle,job,ctypes.byref(state)):
                    raise ctypes.WinError(ctypes.get_last_error())
                if not state.value:
                    if not k32.AssignProcessToJobObject(job,handle):
                        raise ctypes.WinError(ctypes.get_last_error())
                    if not k32.IsProcessInJob(handle,job,ctypes.byref(state)) or not state.value:
                        raise RuntimeError("Uncontained Fluent MPI rank")
                if (proc.info["name"] or "").lower()=="fl_mpi2520.exe":
                    members.append(proc.pid)
            finally:
                k32.CloseHandle(handle)
        except psutil.NoSuchProcess:
            continue
    return sorted(members)


def close_job_handle(job: Optional[int]) -> None:
    if job and os.name == "nt":
        try:
            ctypes.WinDLL("kernel32", use_last_error=True).CloseHandle(wt.HANDLE(job))
        except Exception:
            pass


def set_prevent_sleep(enable: bool) -> None:
    if os.name != "nt":
        return
    try:
        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        flags = 0x80000001 if enable else 0x80000000
        k32.SetThreadExecutionState(wt.DWORD(flags))
    except Exception:
        pass


def is_pid_alive(pid: int) -> bool:
    return psutil.pid_exists(pid)


def prune_dead_pids(gate: ControlGate) -> None:
    pids = gate.load_pids()
    alive = [p for p in pids if isinstance(p.get("pid"), int) and is_pid_alive(p["pid"])]
    if len(alive) != len(pids):
        gate.save_pids(alive)
        gate.update_status(active_pid_count=len(alive))


def build_f_only_env() -> dict:
    TMP_DIR.mkdir(parents=True, exist_ok=True)
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    env.update({
        "X57_WORKSPACE": str(WORKSPACE_ROOT),
        "TEMP": str(TMP_DIR),
        "TMP": str(TMP_DIR),
        "TMPDIR": str(TMP_DIR),
        "FLUENT_TMPDIR": str(TMP_DIR),
        "AWP_TEMP_DIR": str(TMP_DIR),
        "ANSYS_TEMP_DIR": str(TMP_DIR),
        "ANSYS_SCRATCH_DIR": str(TMP_DIR),
        "AWP_LOCALE252": "en-us",
        "FLUENT_NO_WEB_BROWSER": "1",
        "PYTHONDONTWRITEBYTECODE": "1",
        "MPLCONFIGDIR": str(CACHE_DIR / "matplotlib"),
    })
    profile = CACHE_DIR / "ansys_profile"
    for key, directory in {
        "USERPROFILE": profile, "HOME": profile,
        "APPDATA": profile / "AppData" / "Roaming", "LOCALAPPDATA": profile / "AppData" / "Local",
        "ANSYS_USER_PATH": profile / "ansys", "XDG_CACHE_HOME": CACHE_DIR / "xdg",
        "CUDA_CACHE_PATH": CACHE_DIR / "cuda", "QTWEBENGINE_DATA_PATH": CACHE_DIR / "qt",
        "PYTHONPYCACHEPREFIX": CACHE_DIR / "pycache",
    }.items():
        directory.mkdir(parents=True, exist_ok=True)
        env[key] = str(directory)
    env["HOMEDRIVE"], env["HOMEPATH"] = os.path.splitdrive(str(profile))
    return env


def checkpoint_info(workdir, mode, deep=False):
    """Return a validated pair, volume mesh, or retained meshing surface."""
    from fluent_checkpoints import check_mesh_file, latest_pair
    case, data, _ = latest_pair(workdir, deep)
    if data is not None:
        return {"kind": "case_data", "path": str(data), "case": str(case)}
    if mode == "meshing":
        surfaces = []
        for mesh in sorted(workdir.glob("*.msh.h5"),key=lambda p:p.stat().st_mtime_ns,reverse=True):
            surface, volume = check_mesh_file(mesh, deep)
            if volume:
                return {"kind": "volume_mesh", "path": str(mesh)}
            if surface:
                surfaces.append(mesh)
        if surfaces:
            return {"kind": "surface_mesh", "path": str(surfaces[0])}
    return {}


def file_state(path):
    stat = path.stat()
    return stat.st_size, stat.st_mtime_ns


def output_state(workdir):
    files = {}
    for pattern in ("*.cas.h5","*.dat.h5","*.msh.h5"):
        for path in workdir.glob(pattern):
            try:
                files[str(path)] = file_state(path)
            except FileNotFoundError:
                continue
    return files


class AuditPauseGate(ControlGate):
    """Allow a fixture to add a PAUSE while every real project stop retains priority."""
    def __init__(self,workdir,project):
        super().__init__(workdir)
        self.project=project

    def check(self):
        live=self.project.check()
        if live["exit_code"]:
            return dict(live,audit_local_control=False)
        return dict(super().check(),audit_local_control=True)

    def register_pid(self,*args):
        return self.project.register_pid(*args)

    def unregister_pid(self,*args):
        return self.project.unregister_pid(*args)


def main() -> int:
    parser = argparse.ArgumentParser(description="Managed ANSYS Fluent runner (workspace-local, visible GUI, Codex stop-safe)")
    parser.add_argument("--mode", choices=["solver", "meshing"], required=True)
    parser.add_argument("--dim", default="3ddp", choices=["3d", "3ddp", "2d", "2ddp"])
    parser.add_argument("--procs", type=int, default=4, help="Parallel processes (ANSYS Student max = 4)")
    parser.add_argument("--workdir", required=True, help="Working directory strictly inside the project workspace")
    parser.add_argument("--journal", required=True, help="Path to Fluent .jou / .py journal file")
    parser.add_argument("--stage", required=True, help="Stage ID in CONTROL/CHECKPOINT.json")
    parser.add_argument("--case", required=True, help="Case name for logging and status")
    parser.add_argument("--gui", action="store_true", default=True, help="Launch visible Ansys Fluent GUI (DEFAULT)")
    parser.add_argument("--headless", action="store_true", default=False, help="Force headless -g mode (only for quick probes / OpenGL fallback)")
    parser.add_argument("--extra-args", nargs="*", default=[], help="Optional extra Fluent CLI arguments")
    parser.add_argument("--grace-seconds", type=int, default=180, help="Graceful wait for Control Gate PAUSE exit")
    parser.add_argument("--interrupt-grace-seconds", type=int, default=180, help="Idle time allowed for checkpointing after an OS interrupt")
    parser.add_argument("--poll-seconds", type=float, default=2.0, help="Control gate polling interval")
    parser.add_argument("--audit-local-pause",action="store_true",help="Also honor an isolated 12-cell pause-test gate")
    # Fast-track unattended guards: no Fluent session may run forever or sit silent.
    parser.add_argument("--max-wall-min", type=float, default=float(os.environ.get("X57_FLUENT_MAX_WALL_MIN", "90")),
                        help="Request a native checkpoint exit after this many minutes (0 disables)")
    parser.add_argument("--idle-min", type=float, default=float(os.environ.get("X57_FLUENT_IDLE_MIN", "20")),
                        help="Request exit when no file in the work directory changes for this many minutes (0 disables)")
    args = parser.parse_args()

    if not 1 <= args.procs <= 4:
        parser.error("--procs must be between 1 and 4 for this installation")
    use_gui = not args.headless
    workdir = Path(args.workdir).resolve()
    journal = Path(args.journal).resolve()

    ws_resolved = WORKSPACE_ROOT.resolve()
    try:
        workdir.relative_to(ws_resolved)
        journal.relative_to(ws_resolved)
    except ValueError:
        print(f"[ERROR] Storage violation: workdir ({workdir}) and journal ({journal}) MUST be inside {ws_resolved}!", file=sys.stderr)
        return 2

    if not (args.poll_seconds > 0 and args.grace_seconds >= 1 and args.interrupt_grace_seconds >= 1):
        parser.error("Polling and checkpoint grace intervals must be positive")

    if not FLUENT_EXE.exists():
        print(f"[ERROR] Fluent executable not found: {FLUENT_EXE}", file=sys.stderr)
        return 2
    if not journal.exists():
        print(f"[ERROR] Journal file not found: {journal}", file=sys.stderr)
        return 2

    from volume_native_lines import is_volume_generation,VolumeLines
    volume_generation=is_volume_generation(args.mode,workdir,journal,ws_resolved)
    workdir.mkdir(parents=True, exist_ok=True)
    LOGS_DIR.mkdir(parents=True, exist_ok=True)

    gate = ControlGate()
    prune_dead_pids(gate)
    if args.audit_local_pause:
        if (not workdir.is_relative_to((WORKSPACE_ROOT/"00_env_audit/native_pause_probe").resolve())
                or args.stage not in ("S0","P2_CONTROL_CHECK") or args.mode!="solver" or not args.case.startswith("s0_native_pause_")
                or journal.parent!=workdir or not (workdir/"CONTROL/STATE.txt").is_file()):
            parser.error("The local pause gate is restricted to the S0 native pause fixture")
        args.stage="P2_CONTROL_CHECK"
        gate=AuditPauseGate(workdir,gate)

    pre = gate.check()
    if pre["exit_code"] != 0:
        print(f"[ControlGate] Blocked launch before start: state={pre['state']} action={pre['action']} instr={pre['pending_instruction']!r}")
        return int(pre["exit_code"])

    for stale in ("exit-fluent", "check-fluent", "exit-fluent.txt", "check-fluent.txt"):
        (workdir / stale).unlink(missing_ok=True)
    initial_files = output_state(workdir)
    previous_transcripts = set(workdir.glob("fluent-*.trn"))

    ts = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    log_path = LOGS_DIR / f"{ts}_{args.case}_{args.mode}.log"

    # Use -wait so fluent.exe blocks cleanly until GUI/solver finishes!
    cmd = [str(FLUENT_EXE), args.dim, f"-t{args.procs}", "-wait"]
    if not use_gui:
        cmd.append("-g")
    if args.mode == "meshing":
        cmd.append("-meshing")
    cmd.extend(["-i", str(journal)])
    if args.extra_args:
        cmd.extend(args.extra_args)

    env = build_f_only_env()
    ui_tag = "GUI" if use_gui else "HEADLESS"
    append_history("FLUENT_START", f"stage={args.stage} case={args.case} mode={args.mode} ui={ui_tag} procs={args.procs} log={log_path.name}")
    gate.update_status(
        current_stage=args.stage,
        active_case=args.case,
        message=f"Running Fluent {ui_tag} ({args.mode}, -t{args.procs}) for {args.case}",
    )

    print(f"[FluentManaged] Launching ({ui_tag}): {' '.join(cmd)}")
    print(f"[FluentManaged] Workdir  : {workdir}")
    print(f"[FluentManaged] Log      : {log_path}")

    set_prevent_sleep(True)
    proc = subprocess.Popen(
        cmd,
        creationflags=0x00000004,  # CREATE_SUSPENDED until the entire process tree is contained
        cwd=str(workdir),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        bufsize=1,
    )
    job_handle = attach_kill_on_close_job(proc)
    if not job_handle:
        proc.kill()
        proc.wait()
        set_prevent_sleep(False)
        raise RuntimeError("Windows could not contain the suspended Fluent launcher")
    registered = False
    try:
        gate.register_pid(proc.pid, f"fluent_{args.mode}_{ui_tag.lower()}", str(workdir), args.case)
        registered = True
        ready = gate.check()["exit_code"]
        if ready:
            close_job_handle(job_handle)
            proc.wait()
            gate.unregister_pid(proc.pid)
            set_prevent_sleep(False)
            return ready
        psutil.Process(proc.pid).resume()
    except BaseException:
        close_job_handle(job_handle)
        proc.wait()
        if registered:
            gate.unregister_pid(proc.pid)
        set_prevent_sleep(False)
        raise

    run_id=f"{ts}_{proc.pid}"
    volume_lines=VolumeLines(run_id,journal,args.case,time.monotonic(),time.time()) if volume_generation else None
    line_record=workdir/"volume_generation_log_progress.json"
    if volume_lines is not None:
        atomic_write_json(line_record,volume_lines.evidence(time.monotonic(),time.time()))
    stop_watchdog = threading.Event()
    control_trigger = {"code": 0, "reason": "", "interrupt_count": 0, "forced": False,
                       "requested_ns": None, "grace": args.grace_seconds}
    progress_state = {"last_iter": None, "start_time": time.time(), "last_synced_ckpt": None}

    def terminate_tree() -> None:
        if job_handle and os.name=="nt":
            kernel=ctypes.WinDLL("kernel32",use_last_error=True)
            kernel.TerminateJobObject.argtypes=[wt.HANDLE,wt.UINT]
            kernel.TerminateJobObject(wt.HANDLE(job_handle),1)
        if proc.poll() is None:
            subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)

    def begin_stop(code, reason, grace):
        if control_trigger["requested_ns"] is not None:
            return
        control_trigger.update(code=code, reason=reason, requested_ns=time.time_ns(), grace=grace)
        try:
            request_fluent_exit(workdir)
        except OSError as exc:
            print(f"[FluentManaged] Could not write exit trigger: {exc}", flush=True)
        print(f"[FluentManaged] {reason}. Waiting for native checkpoint exit.", flush=True)
        gate.update_status(current_stage=args.stage, active_case=args.case,
                           message=f"{reason}. Native checkpoint exit requested.")

    def handle_signal(signum, _frame):
        control_trigger["interrupt_count"] += 1
        if control_trigger["interrupt_count"] == 1:
            begin_stop(10, f"OS interrupt signal {signum}", args.interrupt_grace_seconds)
        else:
            control_trigger["forced"] = True
            terminate_tree()

    for sig_name in ("SIGINT", "SIGTERM", "SIGBREAK"):
        sig = getattr(signal, sig_name, None)
        if sig is not None:
            try:
                signal.signal(sig, handle_signal)
            except Exception:
                pass

    # In desktop mode the transcript receives output even when the launcher pipe is silent.
    from mesh_quality_guard import MeshQualityGuard
    quality_guard=MeshQualityGuard() if args.mode=="meshing" else None
    transcript_offsets = {}
    launch_time = progress_state["start_time"] - 3
    def capture_transcripts() -> bool:
        failed = False
        for src in workdir.glob("fluent-*.trn"):
            if src in previous_transcripts:
                continue
            offset = transcript_offsets.get(src, 0)
            dest = log_path.with_name(log_path.stem + "_" + src.name)
            with src.open("rb") as inp:
                inp.seek(offset)
                chunk = inp.read()
                transcript_offsets[src] = inp.tell()
            if chunk:
                if volume_lines is not None:
                    tick,wall=time.monotonic(),time.time()
                    if volume_lines.feed(src,chunk,tick,wall):
                        atomic_write_json(line_record,volume_lines.evidence(tick,wall))
                if quality_guard is not None:
                    quality_guard.feed(str(src),chunk)
                with dest.open("ab") as out:
                    out.write(chunk)
                for line in chunk.decode("utf-8", errors="replace").splitlines():
                    m = ITER_RE.match(line)
                    if m and args.mode == "solver":
                        progress_state["last_iter"] = int(m.group(1))
                # Search across consecutive reads as Fluent flushes its transcript incrementally.
                with dest.open("rb") as copied:
                    copied.seek(max(0, offset - 256))
                    recent = copied.read().lower()
                    failed |= (b"error or interrupt occurred while reading the journal" in recent
                               or b"sigsegv(segmentation violation)" in recent)
        return failed

    activity = {"sig": None, "last": time.monotonic(), "start": time.monotonic()}

    def activity_signature():
        """Newest mtime and total size of files in the work dir plus the launcher log."""
        newest, total = 0, 0
        try:
            with os.scandir(workdir) as entries:
                for entry in entries:
                    try:
                        if entry.is_file(follow_symlinks=False):
                            st = entry.stat(follow_symlinks=False)
                            newest = max(newest, st.st_mtime_ns)
                            total += st.st_size
                    except OSError:
                        continue
        except OSError:
            pass
        try:
            total += log_path.stat().st_size
        except OSError:
            pass
        return newest, total

    def unattended_guard() -> bool:
        """Return True when a fast-track wall/idle stop was requested in this poll."""
        tick = time.monotonic()
        if args.max_wall_min > 0 and tick - activity["start"] >= args.max_wall_min * 60.0:
            reason = f"Fast-track wall-clock limit of {args.max_wall_min:g} min reached"
            atomic_write_json(workdir / "managed_timeout.json",
                              dict(case=args.case, reason=reason, elapsed_min=(tick - activity["start"]) / 60.0))
            begin_stop(2, reason, 240)
            control_trigger["absolute_deadline"] = tick + 300
            return True
        sig = activity_signature()
        if sig != activity["sig"]:
            activity["sig"] = sig
            activity["last"] = tick
        elif args.idle_min > 0 and tick - activity["last"] >= args.idle_min * 60.0:
            reason = f"Fast-track idle guard: no file activity for {args.idle_min:g} min"
            atomic_write_json(workdir / "managed_timeout.json",
                              dict(case=args.case, reason=reason, idle_min=(tick - activity["last"]) / 60.0))
            begin_stop(2, reason, 60)
            control_trigger["absolute_deadline"] = tick + 120
            return True
        return False

    def watchdog() -> None:
        last_hb = 0.0
        last_write_state = None
        last_change = time.monotonic()
        while not stop_watchdog.is_set():
            if proc.poll() is not None:
                return
            chk = gate.check()
            code = chk["exit_code"]
            if code and control_trigger["requested_ns"] is not None and (control_trigger["code"]==2 or chk.get("audit_local_control") is False):
                control_trigger.update(code=code,reason=f"Project Control Gate {chk['state']}")
            if code == 30:
                control_trigger.update(code=30, reason="User set ABORT", forced=True)
                terminate_tree()
                return
            if code in (10, 20, 40):
                begin_stop(code, f"Control Gate {chk['state']}", args.grace_seconds)
            if control_trigger["requested_ns"] is not None:
                if (control_trigger["code"]==2 and "absolute_deadline" in control_trigger
                        and time.monotonic()>=control_trigger["absolute_deadline"]):
                    control_trigger["forced"]=True
                    terminate_tree()
                    return
                state = output_state(workdir)
                if state != last_write_state:
                    last_change = time.monotonic()
                    last_write_state = state
                if time.monotonic() - last_change >= max(1,control_trigger["grace"]):
                    control_trigger["forced"] = True
                    print("[FluentManaged] Grace expired without further checkpoint I/O.",flush=True)
                    terminate_tree()
                    return
                stop_watchdog.wait(args.poll_seconds)
                continue
            try:
                if capture_transcripts():
                    if gate.check()["exit_code"] or control_trigger["requested_ns"] is not None:
                        continue
                    begin_stop(2, "Native Fluent journal interrupted or a compute rank crashed", 45)
                    continue
            except OSError:
                pass
            if volume_lines is not None and volume_lines.expired(time.monotonic()):
                if gate.check()["exit_code"] or control_trigger["requested_ns"] is not None:
                    continue
                tick,wall=time.monotonic(),time.time()
                evidence=volume_lines.evidence(tick,wall)
                reason="35 minutes without a new complete native volume-generation transcript line"
                evidence.update(reason=reason,grace_seconds=45)
                begin_stop(2,reason,45)
                control_trigger["absolute_deadline"]=tick+45
                atomic_write_json(workdir/f"volume_generation_no_output_{run_id}.json",evidence)
                continue
            if unattended_guard():
                continue
            if quality_guard is not None and quality_guard.check():
                if gate.check()["exit_code"]:
                    continue
                atomic_write_json(workdir/"mesh_quality_early_stop.json",
                    dict(case=args.case,reason=quality_guard.reason,evidence=quality_guard.measurement,
                         native_transcripts={str(k):v for k,v in transcript_offsets.items()}))
                begin_stop(2,quality_guard.reason,45)
                continue
            now = time.time()
            if now - last_hb >= 15.0:
                last_hb = now
                try:
                    attached = confirm_job_ranks(job_handle,workdir,launch_time)
                    if attached and attached != progress_state.get("contained_ranks"):
                        progress_state["contained_ranks"] = attached
                        append_history("FLUENT_RANKS_CONTAINED", f"case={args.case} ranks={attached}")
                except (OSError,RuntimeError,psutil.AccessDenied) as exc:
                    if gate.check()["exit_code"] or control_trigger["requested_ns"] is not None:
                        continue
                    control_trigger.update(code=2,reason=f"Rank containment verification failed: {exc}")
                    print(control_trigger["reason"],flush=True)
                    terminate_tree()
                    return
                elapsed_min = (now - progress_state["start_time"]) / 60.0
                msg = f"Fluent {ui_tag} {args.mode} active ({args.case}) | elapsed {elapsed_min:.1f} min"
                if progress_state["last_iter"] is not None:
                    msg += f" | iter ~{progress_state['last_iter']}"
                gate.update_status(current_stage=args.stage, active_case=args.case, message=msg)
                ckpt = checkpoint_info(workdir,args.mode).get("path")
                if ckpt and ckpt != progress_state["last_synced_ckpt"]:
                    progress_state["last_synced_ckpt"] = ckpt
                    gate.update_checkpoint(
                        stage=args.stage,
                        status="in_progress",
                        active_case=args.case,
                        last_fluent_checkpoint=ckpt,
                        notes=f"Readable native restart artifact ({args.case}, iter~{progress_state['last_iter']}, elapsed={elapsed_min:.1f}m)",
                    )

            stop_watchdog.wait(args.poll_seconds)

    wd_thread = threading.Thread(target=watchdog, daemon=True)
    wd_thread.start()

    rc = 0
    try:
        with open(log_path, "w", encoding="utf-8", newline="\n") as lf:
            assert proc.stdout is not None
            for line in proc.stdout:
                lf.write(line)
                lf.flush()
                m = ITER_RE.match(line)
                if m and args.mode == "solver":
                    progress_state["last_iter"] = int(m.group(1))
        rc = proc.wait()
    except KeyboardInterrupt:
        begin_stop(10, "KeyboardInterrupt", args.interrupt_grace_seconds)
        rc = proc.wait()
    finally:
        stop_watchdog.set()
        wd_thread.join(timeout=5.0)
        terminate_tree()
        close_job_handle(job_handle)
        set_prevent_sleep(False)
        gate.unregister_pid(proc.pid)

    final_gate = gate.check()
    if final_gate["exit_code"] in (10,20,30,40) and (control_trigger["code"] not in (10,20,30,40)
            or (final_gate.get("audit_local_control") is False and control_trigger["code"]!=30)):
        control_trigger.update(code=final_gate["exit_code"],reason=f"Control Gate {final_gate['state']} at exit")
    stopped = control_trigger["code"] in (10,20,30,40)
    artifact = checkpoint_info(workdir,args.mode,deep=stopped)
    latest_ckpt = artifact.get("path")
    elapsed_min = (time.time() - progress_state["start_time"]) / 60.0

    if stopped:
        c = control_trigger["code"]
        if latest_ckpt is None:
            provenance = "no_readable_restart_in_workdir"
        elif initial_files.get(latest_ckpt) == file_state(Path(latest_ckpt)):
            provenance = "retained_before_launch"
        else:
            provenance = "written_during_launch"
        evidence = dict(control_code=c, reason=control_trigger["reason"], forced=control_trigger["forced"],
                        returncode=rc, requested_ns=control_trigger["requested_ns"], elapsed_minutes=elapsed_min,
                        last_observed_iteration=progress_state["last_iter"], checkpoint=artifact, provenance=provenance)
        atomic_write_json(workdir/"managed_stop.json",evidence)
        gate.update_checkpoint(stage=args.stage,status="failed" if c==30 else "paused",active_case=args.case,
                               last_fluent_checkpoint=latest_ckpt,notes=json.dumps(evidence,ensure_ascii=False))
        print(f"[FluentManaged] Stop code {c}, forced={evidence['forced']}, {provenance}: {latest_ckpt}")
        return c

    journal_failed = capture_transcripts()
    quality_failure = quality_guard is not None and bool(quality_guard.check())
    if quality_failure:
        atomic_write_json(workdir/"mesh_quality_early_stop.json", dict(
            case=args.case, reason=quality_guard.reason, evidence=quality_guard.measurement,
            native_transcripts={str(k): v for k, v in transcript_offsets.items()}))
    managed_rc = 2 if journal_failed or quality_failure or control_trigger["code"] == 2 else rc
    message = f"Fluent {ui_tag} {args.mode} finished ({args.case}) managed_rc={managed_rc} native_rc={rc} in {elapsed_min:.1f} min"
    # A successful final write can occur between the last heartbeat and native exit.
    if (managed_rc == 0 and latest_ckpt and
            initial_files.get(latest_ckpt) != file_state(Path(latest_ckpt))):
        gate.update_checkpoint(stage=args.stage, status="in_progress", active_case=args.case,
                               last_fluent_checkpoint=latest_ckpt,
                               notes=f"Native {artifact['kind']} saved on exit ({args.case}, elapsed={elapsed_min:.1f}m)")
    append_history("FLUENT_EXIT", f"stage={args.stage} {message} latest_file={latest_ckpt}")
    gate.update_status(current_stage=args.stage, active_case=args.case, message=message)
    print(f"[FluentManaged] {message}. Latest artifact: {latest_ckpt}")
    return managed_rc


if __name__ == "__main__":
    # One Student licence seat. The OS releases the lock if the supervisor is interrupted.
    with (WORKSPACE_ROOT / "CONTROL" / "fluent_seat.lock").open("a+b") as seat:
        seat.seek(0)
        try:
            msvcrt.locking(seat.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError:
            sys.exit("Another managed Fluent process holds the Student seat")
        sys.exit(main())
