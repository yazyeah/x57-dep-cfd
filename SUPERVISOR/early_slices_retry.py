#!/usr/bin/env python3
"""Re-run the early Fluent-free Fine native volume + P11 slice intersections after the 2026-11-25 fix of the
vorticity/curl labelling check in scripts/native_flow_data.py. Log: logs/early_fsi_postproc.log"""
import sys
import traceback
from pathlib import Path

import psutil

sys.path.insert(0, str(Path(__file__).resolve().parent))
import early_fsi_postproc as E  # noqa: E402

if __name__ == "__main__":
    try:
        psutil.Process().cpu_affinity([c for c in range(psutil.cpu_count()) if c >= 16] or None)
    except (psutil.Error, ValueError):
        pass
    E.log("slices retry after vorticity-check fix")
    try:
        E.slices()
        E.log("slices retry done")
    except Exception as exc:
        E.log(f"slices retry stopped: {exc.__class__.__name__}: {exc}\n{traceback.format_exc()[-1200:]}")
