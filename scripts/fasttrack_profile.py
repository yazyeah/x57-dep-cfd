"""Fast-track execution profile for the unattended X-57 P2..P12 run.

Every loop in the pipeline reads its iteration cap, wall-clock budget and
acceptance tier from this single file, so no stage can spin forever and every
relaxed criterion is written down in one auditable place.

Acceptance tiers (all tiers are recorded in each QA JSON next to the strict
result, nothing is hidden):
  strict       original project redlines (QUALITY_AND_MILESTONES.md)
  engineering  industry-standard RANS convergence (force plateau, mass closure,
               residual drop, exact actuator integrals) -- the normal acceptance
  budget       used only when the case's time/iteration budget is exhausted:
               forces still on a plateau within 2 %, conservative but honest
Deterministic invariants (actuator-disk integrals, report/monitor consistency,
positive cell volumes, licence cell cap, boundary zones) are never relaxed.
"""
from __future__ import annotations

import json
import math
import os
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ENABLED = os.environ.get("X57_FASTTRACK", "1") != "0"

# --------------------------------------------------------------------------- P2
LICENSE_CELL_CAP = 1_048_575                       # Student solver hard cap (< 1,048,576)
TARGET_WINDOWS = {"coarse": (280_000, 380_000), "medium": (560_000, 680_000), "fine": (940_000, 1_044_000)}
HARD_WINDOWS = {"coarse": (250_000, 400_000), "medium": (480_000, 720_000), "fine": (840_000, 1_045_000)}
COUNT_TARGET = {"coarse": 315_000, "medium": 570_000, "fine": 945_000}   # centred in the hard windows; r32~1.22, r21~1.18
RATIO_TARGET = {"r32": 1.18, "r21": 1.15}           # h_coarse/h_medium, h_medium/h_fine (project target)
RATIO_HARD = {"r32": 1.10, "r21": 1.10}             # Celik (2008): r > 1.1 is the admissible minimum
MESH_OQ_TARGET = 0.10                               # project preference
MESH_OQ_ACCEPT = 0.01                               # Ansys Fluent documented minimum orthogonal quality
MESH_POOR_FRACTION_MAX = 0.01                       # cells with inverse OQ > 0.95 (OQ < 0.05) / all cells
MESH_POOR_FRACTION_LASTRESORT = 0.02
CAD_GAP_TOL_M = {"coarse": 0.008, "medium": 0.008, "fine": 0.008}   # ~1 % of the 0.7785 m sponson clearance
P2_LEVEL_BUDGET_MIN = {"coarse": 100, "medium": 150, "fine": 190}  # room for quality-driven re-attempts
P2_MAX_ATTEMPTS = {"coarse": 3, "medium": 3, "fine": 3}
P2_FLUENT_WALL_MIN = {"coarse": 45, "medium": 60, "fine": 80}      # one volume-meshing session
P2_SILENT_STALL_MIN = 35        # QUALITY_AND_MILESTONES.md: abort a volume-mesh log silent for 35 min

# ----------------------------------------------------------------------- solver
FORCE_TIERS = {                                     # (relative std, relative drift) over last 200 iterations
    "strict": (0.005, 0.005),
    "engineering": (0.0075, 0.003),       # drift: QUALITY_AND_MILESTONES.md preferred 0.3 %
    "budget": (0.015, 0.0075),
}
FORCE_NEAR_ZERO_ABS = {"strict": (1.0, 0.5), "engineering": (1.5, 0.75), "budget": (3.0, 1.5)}  # (std N, drift N)
MASS_TIERS = {"strict": 0.005, "engineering": 0.005, "budget": 0.010}   # 0.5 % = project redline
REDUCTION_ORDERS = {"strict": 4.0, "engineering": 3.0, "budget": 2.0}  # cold starts; warm starts: from post-perturbation peak, one order less
RESIDUAL_TIERS = {
    "strict": {"continuity": 1e-3, "velocity": 1e-4, "energy": 1e-6, "turbulence": 1e-4},
    "engineering": {"continuity": 2e-3, "velocity": 5e-4, "energy": 5e-6, "turbulence": 5e-4},
    "budget": {"continuity": 5e-3, "velocity": 1e-3, "energy": 1e-5, "turbulence": 1e-3},
}
SECTION_RESIDUAL_TIERS = {
    "strict": {"continuity": 1e-6, "other": 1e-6},
    "engineering": {"continuity": 5e-5, "other": 5e-6},
    "budget": {"continuity": 1e-4, "other": 1e-5},
}
SECTION_YPLUS_MAX = {"strict": 0.5, "engineering": 1.0, "budget": 2.0}
TIER_ORDER = ("strict", "engineering", "budget")

CASE_PLAN = {
    # block = iterations per Fluent launch, min/max = total case iterations.
    # REQUIRED cases answer the coursework brief (mesh-convergence study, lift/thrust, lift vs RPM):
    #   only strict/engineering acceptance, never the 'budget' tier, and NOT shortened by stage deadlines.
    # EXTENSION cases (swirl, decomposition, ground effect, roll, RKE, vectoring, 2D) are deadline-bound and
    #   may stop at the 'budget' tier to save time.
    "coarse_rpm100": dict(block=300, min_iter=900, max_iter=2400, initial_scale=0.6, warmup=150, grace_blocks=3,
                          allow_budget=False, deadline_binding=False),
    "medium_rpm100": dict(block=300, min_iter=900, max_iter=2400, initial_scale=0.6, warmup=100, grace_blocks=3,
                          allow_budget=False, deadline_binding=False),
    "fine_rpm100": dict(block=300, min_iter=600, max_iter=2100, initial_scale=0.8, warmup=60, grace_blocks=3,
                        allow_budget=False, deadline_binding=False),
    "medium_rpm050": dict(block=300, min_iter=600, max_iter=1800, initial_scale=1.0, warmup=0, grace_blocks=3,
                          allow_budget=False, deadline_binding=False),
    "medium_rpm075": dict(block=300, min_iter=600, max_iter=1800, initial_scale=1.0, warmup=0, grace_blocks=3,
                          allow_budget=False, deadline_binding=False),
    "_branch": dict(block=300, min_iter=300, max_iter=900, initial_scale=1.0, warmup=0, grace_blocks=1,
                    allow_budget=True, deadline_binding=True),
    "_section": dict(block=600, min_iter=600, max_iter=3000, initial_scale=1.0, warmup=0, grace_blocks=1,
                     allow_budget=True, deadline_binding=True),
}
REQUIRED_CASES = ("coarse_rpm100", "medium_rpm100", "fine_rpm100", "medium_rpm050", "medium_rpm075")
CORE_CASES = ("coarse_rpm100", "medium_rpm100", "fine_rpm100")
MAX_DIVERGENCE_RECOVERIES = 2
FIELD_EXPORT_CASES = ("medium_rpm100", "fine_rpm100", "medium_rpm100_noswirl")   # consumers of native cell CSV
INTERPOLATION_EXPORT_CASES = ("coarse_rpm100", "medium_rpm100")                  # coarse->medium->fine init

# ------------------------------------------------------------------ wall clock
# The global budget covers the COMPUTE stages P2-P10 only. P11 (figures/renders) and P12 (packaging,
# report) run afterwards with their own fixed limits and are not compressed by the deadline.
# Required stages P2-P6 use generous hard limits; extensions P7-P10 absorb any compression.
GLOBAL_HOURS = float(os.environ.get("X57_GLOBAL_HOURS", "15.0"))
STAGES = ("P2", "P3", "P4", "P5", "P6", "P7", "P8", "P9", "P10", "P11", "P12")
COMPUTE_STAGES = ("P2", "P3", "P4", "P5", "P6", "P7", "P8", "P9", "P10")
REPORT_STAGES = ("P11", "P12")
REQUIRED_STAGES = ("P2", "P3", "P4", "P5", "P6")
STAGE_NOMINAL_MIN = {"P2": 190, "P3": 45, "P4": 70, "P5": 95, "P6": 75, "P7": 25, "P8": 75,
                     "P9": 80, "P10": 95, "P11": 60, "P12": 15}
STAGE_HARD_MIN = {"P2": 360, "P3": 120, "P4": 180, "P5": 240, "P6": 160, "P7": 45, "P8": 110,
                  "P9": 120, "P10": 150, "P11": 150, "P12": 45}
STAGE_FLOOR_MIN = {"P2": 60, "P3": 30, "P4": 45, "P5": 60, "P6": 45, "P7": 15, "P8": 40,
                   "P9": 40, "P10": 55, "P11": 45, "P12": 12}
FLUENT_DEFAULT_WALL_MIN = float(os.environ.get("X57_FLUENT_MAX_WALL_MIN", "90"))    # one solver block/export/render session
FLUENT_DEFAULT_IDLE_MIN = float(os.environ.get("X57_FLUENT_IDLE_MIN", "20"))
MAPDL_WALL_MIN = float(os.environ.get("X57_MAPDL_MAX_WALL_MIN", "40"))
# Steady-progress watchdog: a stage child is restarted (resume from checkpoints) when no new result
# file (block QA, case/data, mesh, figure, render, MAPDL result, stage record) appears for this long.
PROGRESS_STALL_MIN = {"P2": 100, "P11": 120, "_default": 60}
STAGE_ATTEMPTS = 3              # resume-retries per stage (progress-stall kills and crashes)
PROGRESS_SUFFIXES = (".json", ".jsonl", ".cas.h5", ".dat.h5", ".msh.h5", ".ip", ".png", ".pdf", ".csv", ".rst", ".npz", ".sf", ".h5")
PROGRESS_DIRS = ("02_mesh", "03_cases", "04_postproc", "DELIVERABLES", "logs")
# Acceptance-defining files: hashed at the first launch; any later change is reported as FAIL.
PROTECTED_FILES = ("scripts/fasttrack_profile.py", "scripts/assess_fluent_case.py", "scripts/assess_section_case.py",
                   "scripts/fasttrack_mesh.py", "scripts/cfd_verification.py", "scripts/verify_deliverables.py",
                   "scripts/final_quality_audit.py", "scripts/verify_fsi_mesh_study.py")

# --------------------------------------------------------------- final quality
# Global structural contour = von Mises stress on a fixed, pre-declared ALLOWABLE scale
# 0 .. sigma_allow, sigma_allow = 503 MPa (7075-T6 yield) / 1.5 (FAR 25.303 ultimate factor) = 335.3 MPa,
# drawn in 9 equal ENGINEERING bands. Requirement: >= 95 % of the exterior skin area in the LOWEST
# (darkest blue) band, i.e. below sigma_allow / 9 = 37.3 MPa (utilisation < 11 %). The local zoom
# (render19) keeps its own adaptive range so concentrations are never hidden.
STRESS_YIELD_MPA = 503.0
STRESS_DESIGN_FACTOR = 1.5
STRESS_SCALE_MAX_MPA = STRESS_YIELD_MPA / STRESS_DESIGN_FACTOR
STRESS_BLUE_BINS = 1            # the lowest of the 9 colour bands
STRESS_BLUE_AREA_MIN = 0.95     # >= 95 % of the exterior skin area must render in that band
STRESS_MIN_YIELD_FOS = 1.5      # hard minimum yield factor anywhere in the modelled skin
GCI_TARGET_PCT, GCI_REDLINE_PCT = 3.0, 5.0


def case_plan(case: str) -> dict:
    if case in CASE_PLAN:
        return dict(CASE_PLAN[case])
    return dict(CASE_PLAN["_section" if case.startswith("opt2d_") else "_branch"])


def now() -> float:
    return time.time()


def env_deadline(name: str) -> float | None:
    raw = os.environ.get(name)
    try:
        value = float(raw) if raw else None
    except ValueError:
        return None
    return value if value and math.isfinite(value) else None


def minutes_left(deadline: float | None) -> float:
    return float("inf") if deadline is None else (deadline - now()) / 60.0


def tier_rank(tier: str | None) -> int:
    return TIER_ORDER.index(tier) if tier in TIER_ORDER else len(TIER_ORDER)


def ratio_hard_pass(r32: float | None, r21: float | None) -> bool:
    return bool(r32 is not None and r21 is not None and r32 >= RATIO_HARD["r32"] and r21 >= RATIO_HARD["r21"])


def ratio_target_pass(r32: float | None, r21: float | None) -> bool:
    return bool(r32 is not None and r21 is not None and r32 >= RATIO_TARGET["r32"] and r21 >= RATIO_TARGET["r21"])


def in_hard_window(level: str, cells: int) -> bool:
    lo, hi = HARD_WINDOWS[level]
    return lo <= int(cells) <= hi and int(cells) <= LICENSE_CELL_CAP


def snapshot() -> dict:
    """Machine-readable copy of every threshold, embedded in QA reports."""
    keys = [k for k, v in globals().items() if k.isupper() and isinstance(v, (int, float, str, dict, tuple, bool))]
    return json.loads(json.dumps({k: globals()[k] for k in keys}, default=list))
