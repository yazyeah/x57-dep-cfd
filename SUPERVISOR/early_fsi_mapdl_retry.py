#!/usr/bin/env python3
"""Re-run the early MAPDL structural pairs after the 2026-11-25 pitch-moment unit fix (12:16 failures).

The first early pass stopped every pair at map_cfd_shell_loads' pitch check: the native Fluent report is the
moment coefficient, the mapped wall moment is in N m. compare_x57_cases.pitch_report_to_Nm now converts it.
Runs the same pairs and the same stress metric as early_fsi_postproc (whose own process keeps doing the
Fluent-free slices). Log: logs/early_fsi_postproc.log; metric: logs/early_stress_check.json
"""
import sys
import time
from pathlib import Path

import psutil

sys.path.insert(0, str(Path(__file__).resolve().parent))
import early_fsi_postproc as E  # noqa: E402


def main():
    try:
        psutil.Process().cpu_affinity([c for c in range(psutil.cpu_count()) if c >= 16] or None)
    except (psutil.Error, ValueError):
        pass
    E.log("retry after pitch-moment unit fix: MAPDL pairs + stress metric")
    try:
        from compare_x57_cases import accepted
        pairs = [("fine", "fine_rpm100"), ("coarse", "fine_rpm100"), ("medium", "fine_rpm100"),
                 ("fine", "coarse_rpm100"), ("fine", "medium_rpm100")]
        for grid, name in pairs:
            _, cas, _ = accepted(name)
            rc = E.step("run_mapdl_structural", grid, cas, minutes=45)
            if (grid, name) == ("fine", "fine_rpm100"):
                if rc != 0:
                    E.log("  fine/fine_rpm100 MAPDL failed; see logs/early_fsi_postproc_console.log")
                try:
                    E.stress_metric()
                except Exception as exc:
                    E.log(f"  stress metric unavailable: {exc.__class__.__name__}: {exc}")
        E.log("retry done")
    except Exception as exc:
        E.log(f"retry stopped: {exc.__class__.__name__}: {exc}")
    return 0


if __name__ == "__main__":
    t = time.time()
    raise SystemExit(main())
