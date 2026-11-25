#!/usr/bin/env python3
"""Early, Fluent-free post-processing that overlaps the P6 / surface-study Fluent solves (2026-11-25).

Once fine_rpm100 is accepted and P5 is completed, this runs, through the pipeline's own scripts, the P10/P11
steps that only need the accepted Coarse/Medium/Fine endpoints; P10/P11 later verify and reuse them
("Verified existing structural model / MAPDL result", cached slices):
  1. prepare_mapdl_shell coarse|medium|fine                      (pure Python shell models)
  2. run_mapdl_structural (grid, fine_rpm100) x3, (fine, coarse_rpm100), (fine, medium_rpm100)
  3. the final-audit structural metric on (fine shell, fine_rpm100): exterior-skin area fraction in the
     LOWEST of 9 bands of the fixed 0-335 MPa allowable scale, and the minimum yield FoS (early warning)
  4. native_volume() and the P11 Fine slice intersections
Wall loads are read from the native HDF5 files (no Fluent session). Nothing starts once the orchestrator is in
P10 or later. This process runs on the E-cores; MAPDL is placed by fluent_booster on the P-cores left free by
the Fluent ranks. Log: logs/early_fsi_postproc.log; metric: logs/early_stress_check.json
"""
import datetime as dt
import json
import subprocess
import sys
import time
import traceback
from pathlib import Path

import numpy as np
import psutil

WS = Path(r"D:\FEA Coursework\Workspace")
SCRIPTS = WS / "scripts"
sys.path.insert(0, str(SCRIPTS))
LOG = WS / "logs" / "early_fsi_postproc.log"
STATUS = WS / "SUPERVISOR" / "fasttrack_status.json"
LATE = ("P10", "P11", "P12")


def log(msg):
    line = f"[{dt.datetime.now().astimezone().isoformat(timespec='seconds')}] {msg}"
    print(line, flush=True)
    with LOG.open("a", encoding="utf-8") as f:
        f.write(line + "\n")


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def stage():
    try:
        st = read(STATUS)
        return st.get("current_stage") or st.get("stage")
    except (OSError, ValueError):
        return None


def too_late():
    s = stage()
    p10 = WS / "logs" / "P10_execution.json"
    return s in LATE or p10.is_file()


def ready():
    try:
        if read(WS / "logs" / "P5_execution.json").get("status") != "completed":
            return False
        from compare_x57_cases import accepted
        accepted("fine_rpm100")
        return True
    except Exception:
        return False


def step(*args, minutes=60):
    from run_fluent_managed import build_f_only_env
    if too_late():
        raise RuntimeError(f"orchestrator reached {stage()}; leaving the remaining steps to P10/P11")
    t = time.time()
    with (WS / "logs" / "early_fsi_postproc_console.log").open("a", encoding="utf-8") as out:
        rc = subprocess.run([sys.executable, "-B", str(SCRIPTS / (args[0] + ".py")), *map(str, args[1:])], cwd=str(WS),
                            env=build_f_only_env(), stdout=out, stderr=subprocess.STDOUT, timeout=minutes * 60).returncode
    log(f"  {' '.join(map(str, args))}: rc={rc} in {(time.time() - t) / 60:.1f} min")
    return rc


def stress_metric():
    from fasttrack_profile import STRESS_BLUE_AREA_MIN, STRESS_BLUE_BINS, STRESS_MIN_YIELD_FOS, STRESS_SCALE_MAX_MPA
    from native_mapdl_deck import fields_for_comparison
    struct = WS / "03_cases" / "fsi_structural"
    with np.load(struct / "models" / "fine" / "shell_mesh.npz") as m:
        sect, area = m["element_section"], m["area_m2"]
    with np.load(struct / "fine_struct__fine_rpm100" / "shell_fields.npz") as d:
        fields = {k: d[k] for k in d.files}
    vm = fields_for_comparison(fields)["VMMPA"]
    skin = np.isin(sect, np.arange(5))
    band = STRESS_SCALE_MAX_MPA / 9.0 * STRESS_BLUE_BINS
    frac = float(area[skin & (vm < band)].sum() / area[skin].sum())
    fos = float(np.min(fields["safety_factor"][skin]))
    rec = dict(case="fine shell / fine_rpm100", lowest_band_upper_MPa=band, skin_area_fraction_in_lowest_band=frac,
               required_fraction=STRESS_BLUE_AREA_MIN, band_pass=frac >= STRESS_BLUE_AREA_MIN,
               min_yield_fos=fos, required_fos=STRESS_MIN_YIELD_FOS, fos_pass=fos >= STRESS_MIN_YIELD_FOS,
               peak_vm_MPa=float(vm[skin].max()), p95_vm_MPa=float(np.quantile(vm[skin], .95)),
               p99_vm_MPa=float(np.quantile(vm[skin], .99)), computed=dt.datetime.now().astimezone().isoformat(timespec="seconds"),
               note="Same formula as final_quality_audit.stress_audit (exterior skin sections 0-4, VMMPA, area-weighted).")
    (WS / "logs" / "early_stress_check.json").write_text(json.dumps(rec, indent=2), encoding="utf-8")
    log(f"STRESS CHECK: lowest-band skin area {100 * frac:.2f} % (need >= {100 * STRESS_BLUE_AREA_MIN:.0f} %), "
        f"min FoS {fos:.2f} (need >= {STRESS_MIN_YIELD_FOS}), peak {rec['peak_vm_MPa']:.1f} MPa, p99 {rec['p99_vm_MPa']:.1f} MPa")
    return rec


def slices():
    from x57_stress_profiles import native_volume
    from native_flow_data import intersect
    vol, _, _ = native_volume()
    props = read(WS / "01_geometry" / "geometry_audit.json")["starboard_propellers_detected"]
    cuts = [(2, props[i]["z_axis_m"], props[i]["name"]) for i in (0, 2, 6)]
    cuts += [(1, props[0]["y_axis_m"], "hlp_axis"), (1, .225, "above_wing")]
    for axis, station, label in cuts:
        if too_late():
            return
        output = vol.parent / (label + "_slice.npz")
        if not output.is_file() or output.stat().st_mtime_ns < vol.stat().st_mtime_ns:
            intersect("fine_rpm100", axis, station, label)
            log(f"  slice {label} written")


def main():
    try:
        psutil.Process().cpu_affinity([c for c in range(psutil.cpu_count()) if c >= 16] or None)
    except (psutil.Error, ValueError):
        pass
    log("armed: waiting for P5 completed + accepted fine_rpm100")
    t0 = time.time()
    while not ready():
        if too_late() or time.time() - t0 > 20 * 3600:
            log("not started (too late or timeout); P10/P11 will do everything")
            return 0
        time.sleep(60)
    log("start (fine_rpm100 accepted)")
    try:
        from compare_x57_cases import accepted
        for grid in ("coarse", "medium", "fine"):
            step("prepare_mapdl_shell", grid, minutes=40)
        pairs = [("fine", "fine_rpm100"), ("coarse", "fine_rpm100"), ("medium", "fine_rpm100"),
                 ("fine", "coarse_rpm100"), ("fine", "medium_rpm100")]
        for grid, name in pairs:
            _, cas, _ = accepted(name)
            step("run_mapdl_structural", grid, cas, minutes=45)
            if (grid, name) == ("fine", "fine_rpm100"):
                try:
                    stress_metric()
                except Exception as exc:
                    log(f"  stress metric unavailable: {exc.__class__.__name__}: {exc}")
        slices()
        log("done")
    except Exception as exc:
        log(f"stopped: {exc.__class__.__name__}: {exc}\n{traceback.format_exc()[-1200:]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
