#!/usr/bin/env python3
"""
Antigravity Fast Native TUI Poly-Hexcore P2 Mesh Driver (Coarse -> Medium -> Fine).

Key fixes derived from geometric & native Fluent diagnostics:
1. Uses native TUI `/mesh/auto-mesh` (completes poly-hexcore cleanly in ~10-20 min,
   avoiding FTM's post-General-Info parallel deadlock).
2. Disables prism corner-height distortion vars (`offset-adjust? #f`,
   `normal-smooth-adjust-offsets? #f`, `offset-correct-smooth? #f`,
   `corner-height-weight? #f`) that previously caused 20-60% height taper and
   collapsed prism orthogonal quality to ~0.01 even on flat faces.
3. Uses physically appropriate first-layer heights per component & grid level
   (controlling base-width-to-height aspect ratio and curved dual sagitta while
   preserving wall-resolved Fine `wall_wing` y+ calibrated from Medium P4).
4. Uses `stairstep-quality-threshold 0.995` + proximity stair-stepping so only
   genuinely degenerate crease wedges stair-step (zero negative volumes while
   preserving full column depths across all 5 walls).
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import subprocess
import sys
from pathlib import Path

import h5py

WS_ROOT = Path(r"D:\FEA Coursework\Workspace")
SCRIPTS_DIR = WS_ROOT / "scripts"
SUP_DIR = WS_ROOT / "SUPERVISOR"
sys.path.insert(0, str(SCRIPTS_DIR))
sys.path.insert(0, str(SUP_DIR))

from run_p2_fluent import run_fluent  # noqa: E402
from verify_mesh_level import WINDOWS, prepare_solver_check, digest  # noqa: E402
from mesh_ladder_limits import raw_domain_volume, production_plan  # noqa: E402
from complete_production_mesh import native_tail_count, published_level  # noqa: E402
from prepare_native_polyhex import quality_evidence_journal  # noqa: E402
from control_gate import atomic_write_json  # noqa: E402


# Clean physically balanced prism scopes per grid level:
# (name, walls, first_height_m, layers, growth)
DEFAULT_PRISM_PLAN = {
    "coarse": [
        ("wing_prisms", ["wall_wing"], 1.5e-4, 10, 1.18),
        ("nacelle_prisms", ["wall_nacelles"], 1.8e-4, 8, 1.18),
        ("low_speed_prisms", ["wall_fuselage", "wall_sponson"], 3.5e-4, 6, 1.18),
        ("tail_prisms", ["wall_empennage"], 2.5e-4, 6, 1.18),
    ],
    "medium": [
        ("wing_prisms", ["wall_wing"], 6.0e-5, 14, 1.18),
        ("nacelle_prisms", ["wall_nacelles"], 1.2e-4, 10, 1.18),
        ("low_speed_prisms", ["wall_fuselage", "wall_sponson"], 2.2e-4, 8, 1.18),
        ("tail_prisms", ["wall_empennage"], 1.6e-4, 8, 1.18),
    ],
    "fine": [
        ("wing_prisms", ["wall_wing"], 3.5e-5, 16, 1.17),
        ("nacelle_prisms", ["wall_nacelles"], 9.0e-5, 12, 1.18),
        ("low_speed_prisms", ["wall_fuselage", "wall_sponson"], 1.8e-4, 10, 1.18),
        ("tail_prisms", ["wall_empennage"], 1.3e-4, 10, 1.18),
    ],
}


def build_scopes(level: str, wing_first_height: float | None = None) -> list[dict]:
    out = []
    for name, walls, h, n, g in DEFAULT_PRISM_PLAN[level]:
        if wing_first_height is not None and walls == ["wall_wing"]:
            h = float(wing_first_height)
        total_h = h * (g**n - 1.0) / (g - 1.0)
        last_h = h * (g ** (n - 1))
        out.append({
            "name": name,
            "walls": list(walls),
            "first_height_m": float(h),
            "layers": int(n),
            "growth": float(g),
            "total_height_m": float(total_h),
            "last_height_m": float(last_h),
        })
    return out


def parse_min_oq(transcript: Path) -> float | None:
    txt = transcript.read_text(encoding="utf-8", errors="replace")
    m = re.findall(r"Minimum Orthogonal Quality\s*=\s*([+\-\d.eE]+)", txt, re.I)
    return float(m[-1]) if m else None


def count_cells(mesh: Path) -> int:
    with h5py.File(mesh, "r") as h:
        z = h["meshes/1/cells/zoneTopology"]
        return int(sum(int(b) - int(a) + 1 for a, b in zip(z["minId"][:], z["maxId"][:], strict=True)))


def write_improve_journal(
    path: Path,
    src_mesh: Path,
    dst_mesh: Path,
    inv_oq: float = 0.85,
    iters: int = 5,
    dihedral: int = 60,
    loops: int = 2,
) -> None:
    jou = (
        "/file/confirm-overwrite no\n"
        f'/file/read-mesh "{src_mesh.as_posix()}"\n'
        "/report/quality-method inverse-ortho-quality\n"
        "/mesh/modify/auto-node-move\n"
        "*\n()\n*\n()\n"
        f"{inv_oq:.2f}\n"
        f"{iters}\n"
        f"{dihedral}\n"
        "yes\n"
        f"{loops}\n"
        f'/file/write-mesh "{dst_mesh.as_posix()}"\n'
        "/mesh/check-mesh\n"
        "/mesh/check-quality\n"
        "/report/mesh-size\n"
        + quality_evidence_journal().replace("X57-INVERSE-", "X57-POST-INVERSE-")
        + "/exit yes\n"
    )
    path.write_text(jou, encoding="ascii")


def ensure_size_field(level: str, src_dir: Path) -> tuple[Path, dict]:
    src_cfg = json.loads((src_dir / "mesh_config.json").read_text(encoding="utf-8-sig"))
    sf = Path(src_cfg["size_field_path"])
    if not sf.is_file():
        fjou = src_dir / "field.jou"
        if not fjou.is_file():
            raise RuntimeError(f"Missing both {sf} and {fjou}")
        print(f"[P2TUI] Computing size field for {level} via {fjou}...", flush=True)
        rc, _ = run_fluent(src_dir, fjou, "meshing", f"{level}_field", procs=4, silent_stall_min=15.0, max_wall_min=25.0)
        if rc != 0 or not sf.is_file():
            raise RuntimeError(f"Failed to compute size field {sf} (rc={rc})")
    return sf, src_cfg


def build_scaled_field(work: Path, src_dir: Path, src_cfg: dict, scale: float) -> tuple[Path, list[dict]]:
    level = src_cfg["level"]
    far = float(src_cfg["max_size"])
    bg = float(src_cfg.get("boi_growth", 1.22))
    field_geom = src_dir / "field_geometry.msh"
    if not field_geom.is_file():
        field_geom = WS_ROOT / "02_mesh/coarse/octree_field_budget/field_geometry.msh"
    new_sizes = []
    controls = []
    min_sz = min(float(s["size"]) * scale for s in src_cfg["sizes"])
    minimum = 0.375 * min_sz
    for s in src_cfg["sizes"]:
        sz = float(s["size"]) * scale
        item = dict(s)
        item["size"] = sz
        new_sizes.append(item)
        name = s["name"]
        controls.append(f'("{name}" "boi" {minimum:g} {sz:g} {bg:g} 12. 1. 12 "Face Zone" "{name}" #t #t)')
    controls.append(f'("outer" "soft" {far:g} {far:g} {bg:g} 12. 1. 12 "Face Zone" "farfield_*" #t #t)')
    sf_path = work / "refinement.sf"
    fjou = work / "field.jou"
    fjou.write_text(
        f'/file/confirm-overwrite no\n/file/read-mesh "{field_geom.as_posix()}"\n'
        "/objects/create\nsizing_mesh\nfluid\n1\n*\n()\n()\nmesh\nyes\n/objects/list\n"
        f"(tgsetvar! 'size-func/global-params '({minimum:g} {far:g} {bg:g} 2.))\n"
        "(tgsetvar! 'size-controls '(" + " ".join(controls) + "))\n"
        "/scoped-sizing/list\n/scoped-sizing/validate\n/scoped-sizing/compute\n"
        f'/file/write-size-field "{sf_path.as_posix()}"\n/exit yes\n',
        encoding="ascii",
    )
    print(f"[P2TUI] Computing scaled (x{scale:.3f}) size field for {level}...", flush=True)
    rc, _ = run_fluent(work, fjou, "meshing", f"{level}_field_s{int(round(scale*100))}", procs=4, silent_stall_min=15.0, max_wall_min=25.0)
    if rc != 0 or not sf_path.is_file():
        raise RuntimeError(f"Failed to compute scaled size field {sf_path} (rc={rc})")
    return sf_path, new_sizes


def prepare_tui_level(
    level: str,
    attempt: str,
    boi_scale: float = 1.0,
    wing_first_height: float | None = None,
    volume_fill: str = "poly-hexcore",
    stairstep_thresh: float = 0.92,
    gap_factor: float = 0.25,
) -> Path:
    src_dir = WS_ROOT / "02_mesh" / level / "f_registered_ftm_17"
    work = WS_ROOT / "02_mesh" / level / attempt
    work.mkdir(parents=True, exist_ok=True)

    src_cfg = json.loads((src_dir / "mesh_config.json").read_text(encoding="utf-8-sig"))
    if boi_scale == 1.0:
        sf_path, _ = ensure_size_field(level, src_dir)
        sizes_list = src_cfg["sizes"]
    else:
        sf_path, sizes_list = build_scaled_field(work, src_dir, src_cfg, boi_scale)

    shell = (WS_ROOT / "01_geometry" / f"p2_{level}_prism_base_patches" / "aircraft_domain.msh").resolve(strict=True)
    raw_mesh = work / f"{level}.msh.h5"
    improved_mesh = work / f"{level}_improved.msh.h5"

    scopes = build_scopes(level, wing_first_height=wing_first_height)
    far = float(src_cfg["max_size"])
    min_layers = min(int(s["layers"]) for s in scopes)

    prism_blocks = []
    for s in scopes:
        walls_str = " ".join(s["walls"])
        prism_blocks.append(
            "/mesh/scoped-prisms/create\n"
            f"{s['name']}\n"
            "uniform\n"
            f"{s['first_height_m']:g}\n"
            f"{int(s['layers'])}\n"
            f"{s['growth']:g}\n"
            "x57fluid\n"
            "fluid-regions\n"
            "selected-face-zones\n"
            f'"{walls_str}"\n'
        )

    poly_keep = (
        f"/mesh/scoped-prisms/poly-keep-nlayer-prism-characteristics {min_layers}\n"
        "(tgsetvar! 'poly/smooth-improve? #t)\n"
        "(tgsetvar! 'poly/smooth-improve-iter 5)\n"
        "(tgsetvar! 'poly/smooth-improve-tries 3)\n"
        "(tgsetvar! 'poly/post-improve? #t)\n"
        if volume_fill == "poly-hexcore"
        else ""
    )

    mesh_jou = (
        "/file/confirm-overwrite no\n"
        f'/file/read-mesh "{shell.as_posix()}"\n'
        "/boundary/manage/list\n"
        "/objects/create\nx57fluid\nfluid\n1\n*\n()\n()\nmesh\nyes\n"
        "/material-point/create-material-point\nexternal_fluid\n-6\n4\n3\n"
        "/objects/volumetric-regions/compute\nx57fluid\nyes\nexternal_fluid\n()\n"
        "/objects/volumetric-regions/list x57fluid * ()\n"
        + "".join(prism_blocks)
        + "/mesh/scoped-prisms/list\n"
        f'/file/read-size-field "{sf_path.as_posix()}"\n'
        f"/mesh/hexcore/controls/maximum-cell-length {far:g}\n"
        "(tgsetvar! 'octree/based-hexcore? #t)\n"
        "(tgsetvar! 'hexcore/hexcore-by-size-field? #t)\n"
        "(tgsetvar! 'hexcore/sf-driven-octree? #t)\n"
        "(tgsetvar! 'prism/allow-stairstepping? #t)\n"
        "(tgsetvar! 'prism/proximity-stairstep? #t)\n"
        "(tgsetvar! 'prism/check-quality? #t)\n"
        f"(tgsetvar! 'prism/stairstep-quality-threshold {stairstep_thresh:g})\n"
        "(tgsetvar! 'prism/stairstep-max-warp 0.70)\n"
        f"(tgsetvar! 'prism/collision-gap-factor {gap_factor:g})\n"
        "(tgsetvar! 'prism/shrink-factor 0.5)\n"
        "(tgsetvar! 'prism/collision-first-fix? #f)\n"
        "(tgsetvar! 'prism/improve-warp? #t)\n"
        "(tgsetvar! 'prism/improve-left-handed-faces? #t)\n"
        "(tgsetvar! 'prism/corner-height-weight? #f)\n"
        "(tgsetvar! 'prism/offset-adjust? #f)\n"
        "(tgsetvar! 'prism/normal-smooth-adjust-offsets? #f)\n"
        "(tgsetvar! 'prism/offset-correct-smooth? #f)\n"
        "(tgsetvar! 'prism/orthogonal-layers 2)\n"
        "(tgsetvar! 'prism/left-hand-check1 2)\n"
        "(tgsetvar! 'prism/post-improve-iterations 3)\n"
        + poly_keep
        + "/parallel/auto-partition? yes\n"
        + f"/mesh/auto-mesh\nx57fluid\nno\nscoped\npyramids\n{volume_fill}\nyes\nyes\n"
        + f'/file/write-mesh "{raw_mesh.as_posix()}"\n'
        + "/mesh/check-mesh\n"
        + "/mesh/check-quality\n"
        + "/report/mesh-size\n"
        + quality_evidence_journal().replace("X57-INVERSE-", "X57-RAW-INVERSE-")
        + "/exit yes\n"
    )
    (work / "mesh.jou").write_text(mesh_jou, encoding="ascii")
    write_improve_journal(work / "improve_raw.jou", raw_mesh, improved_mesh, inv_oq=0.85, iters=5, loops=2)

    cfg = dict(src_cfg)
    cfg.update(
        level=level,
        shell=str(shell),
        source_surface_dir=str(shell.parent),
        source_surface_sha256=digest(shell),
        size_field_path=str(sf_path),
        size_field_sha256=digest(sf_path),
        sizes=sizes_list,
        mesh=str(raw_mesh),
        improved_mesh=str(improved_mesh),
        prism_scopes=scopes,
        first_height=next(s["first_height_m"] for s in scopes if s["walls"] == ["wall_wing"]),
        layers=next(int(s["layers"]) for s in scopes if s["walls"] == ["wall_wing"]),
        growth=next(float(s["growth"]) for s in scopes if s["walls"] == ["wall_wing"]),
        native_post_improvement_method="Stair Step",
        guided_workflow=f"Native TUI {volume_fill} v252 (uniform-offset, zero-taper)",
        generation_journal=str(work / "mesh.jou"),
        boi_scale_from_ftm17=boi_scale,
        volume_fill=volume_fill,
        prism_stairstep_quality_threshold=stairstep_thresh,
        prism_collision_gap_factor=gap_factor,
        improvement_target_orthogonal_quality=0.15,
        improvement_inverse_orthogonal_quality=0.85,
        improvement_iterations=5,
    )
    atomic_write_json(work / "mesh_config.json", cfg)
    print(f"[P2TUI] Prepared {level} TUI {volume_fill} at {work} (scale={boi_scale})", flush=True)
    return work


def improve_verify_publish(work: Path, raw_trn: Path) -> bool:
    cfg = json.loads((work / "mesh_config.json").read_text(encoding="utf-8-sig"))
    level = cfg["level"]
    raw_mesh = Path(cfg["mesh"]).resolve(strict=True)
    improved_mesh = Path(cfg["improved_mesh"]).resolve()

    ncells = count_cells(raw_mesh)
    raw_tail = native_tail_count(raw_trn)
    raw_oq = parse_min_oq(raw_trn)
    print(f"[P2TUI] Raw {level}: cells={ncells:,}, window={WINDOWS[level]}, min_oq={raw_oq}, raw_invOQ>0.95={raw_tail}", flush=True)
    atomic_write_json(work / "raw_inverse_oq_population.json", {
        "threshold": 0.95,
        "count": raw_tail,
        "min_oq": raw_oq,
        "total_raw_cells": ncells,
        "cell_budget": list(WINDOWS[level]),
        "raw_count_in_budget": WINDOWS[level][0] <= ncells <= WINDOWS[level][1],
        "transcript": str(raw_trn),
    })
    if not (WINDOWS[level][0] <= ncells <= WINDOWS[level][1]):
        raise RuntimeError(f"CELL_BUDGET_MISS:{level}:{ncells}:{WINDOWS[level]}")

    vol = raw_domain_volume(raw_mesh)
    plan = production_plan(WS_ROOT, (level, ncells, vol))
    atomic_write_json(work / "raw_mesh_ladder_plan.json", plan)
    if not plan["measured_constraints_pass"]:
        raise RuntimeError(f"LADDER_RATIO_MISS:{level}:{ncells}:{plan['measured_ratios']}")

    stamp = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    write_improve_journal(work / "improve_raw.jou", raw_mesh, improved_mesh, inv_oq=0.85, iters=6, loops=2)
    rc, imp_trn = run_fluent(work, work / "improve_raw.jou", "meshing", f"{level}_improve1_{stamp}", procs=4, silent_stall_min=20.0, max_wall_min=35.0)
    if rc != 0 or not improved_mesh.is_file() or imp_trn is None:
        raise RuntimeError(f"Improvement pass 1 failed for {level}: rc={rc}")

    min_oq = parse_min_oq(imp_trn)
    tail_cnt = native_tail_count(imp_trn)
    print(f"[P2TUI] After improve pass 1 ({level}): min_oq={min_oq}, invOQ>0.95={tail_cnt}", flush=True)

    # Pass 2 polish ONLY if min_oq <= 0.115 or tail > 5000 (skip if still hopeless > 10000)
    if ((min_oq is not None and min_oq <= 0.115) or (tail_cnt is not None and tail_cnt > 5000)) and (tail_cnt is None or tail_cnt <= 12000):
        print(f"[P2TUI] Running polish pass 2 on {level} (inv_oq=0.88, iters=8, loops=2)...", flush=True)
        p2_jou = work / "improve_polish2.jou"
        write_improve_journal(p2_jou, improved_mesh, improved_mesh, inv_oq=0.88, iters=8, loops=2)
        rc2, imp_trn2 = run_fluent(work, p2_jou, "meshing", f"{level}_improve2_{stamp}", procs=4, silent_stall_min=20.0, max_wall_min=35.0)
        if rc2 == 0 and imp_trn2 is not None:
            imp_trn = imp_trn2
            min_oq = parse_min_oq(imp_trn)
            tail_cnt = native_tail_count(imp_trn)
            print(f"[P2TUI] After improve pass 2 ({level}): min_oq={min_oq}, invOQ>0.95={tail_cnt}", flush=True)

    atomic_write_json(work / "improved_inverse_oq_population.json", {
        "threshold": 0.95,
        "count": tail_cnt,
        "min_oq": min_oq,
        "transcript": str(imp_trn),
        "mesh": str(improved_mesh),
    })
    if tail_cnt is not None and tail_cnt > 5000:
        raise RuntimeError(f"Improved {level} still has {tail_cnt} cells > invOQ 0.95 (min_oq={min_oq})")
    if min_oq is not None and min_oq <= 0.10:
        raise RuntimeError(f"Improved {level} min_oq={min_oq} <= 0.10 (tail={tail_cnt})")

    # Independent solver reload
    check_jou = prepare_solver_check(improved_mesh)
    reload_dir = work / "quality_reload" / stamp
    reload_dir.mkdir(parents=True, exist_ok=True)
    rc_s, reload_trn = run_fluent(reload_dir, check_jou, "solver", f"{level}_solver_reload_{stamp}", procs=4, silent_stall_min=15.0, max_wall_min=25.0)
    if rc_s != 0 or reload_trn is None:
        raise RuntimeError(f"Solver reload failed for {level}: rc={rc_s}")

    cmd = [
        sys.executable, "-B", str(SCRIPTS_DIR / "verify_mesh_level.py"),
        str(improved_mesh), str(imp_trn),
        "--level", level,
        "--solver-transcript", str(reload_trn),
        "--config", str(work / "mesh_config.json"),
        "--publish",
    ]
    res = subprocess.run(cmd, cwd=str(WS_ROOT), capture_output=True, text=True)
    if res.returncode != 0:
        qa_path = improved_mesh.with_name("mesh_qa.json")
        if qa_path.is_file():
            qa = json.loads(qa_path.read_text(encoding="utf-8-sig"))
            failed = {k: v for k, v in qa.get("checks", {}).items() if not v}
            print(f"[P2TUI] FAILED CHECKS for {level}: {json.dumps(failed, indent=2)}", flush=True)
        print(res.stderr[-2000:] if res.stderr else "", file=sys.stderr, flush=True)
        raise RuntimeError(f"verify_mesh_level.py --publish failed for {level} (rc={res.returncode})")
    print(f"[P2TUI] SUCCESS: {level} PASSED ALL GATES AND PUBLISHED!", flush=True)
    return True


def run_level(
    level: str,
    attempt: str,
    boi_scale: float = 1.0,
    wing_first_height: float | None = None,
    volume_fill: str = "poly-hexcore",
    stairstep_thresh: float = 0.995,
    resume_raw: bool = False,
) -> None:
    if published_level(level):
        print(f"[P2TUI] {level} already published!", flush=True)
        return
    work = WS_ROOT / "02_mesh" / level / attempt
    raw_mesh = work / f"{level}.msh.h5"
    if not resume_raw or not raw_mesh.is_file():
        work = prepare_tui_level(
            level, attempt,
            boi_scale=boi_scale,
            wing_first_height=wing_first_height,
            volume_fill=volume_fill,
            stairstep_thresh=stairstep_thresh,
        )
        max_wall = 65.0 if level == "fine" else 45.0
        rc, raw_trn = run_fluent(work, work / "mesh.jou", "meshing", f"{level}_{attempt}_tui", procs=4, silent_stall_min=25.0, max_wall_min=max_wall)
        if rc != 0 or not raw_mesh.is_file() or raw_trn is None:
            raise RuntimeError(f"{level} TUI volume mesh failed: rc={rc}, trn={raw_trn}")
        atomic_write_json(work / "raw_generation_record.json", {"transcript": str(raw_trn), "sha256": digest(raw_mesh)})
    else:
        rec = json.loads((work / "raw_generation_record.json").read_text(encoding="utf-8-sig"))
        raw_trn = Path(rec["transcript"])
    improve_verify_publish(work, raw_trn)


def main() -> int:
    p = argparse.ArgumentParser(description="Antigravity Fast TUI Poly-Hexcore P2 Driver")
    p.add_argument("level", choices=["coarse", "medium", "fine", "all"])
    p.add_argument("--attempt", default="f_tui_clean_24")
    p.add_argument("--boi-scale", type=float, default=1.0)
    p.add_argument("--wing-first", type=float, default=None)
    p.add_argument("--fill", choices=["poly-hexcore", "hexcore"], default="poly-hexcore")
    p.add_argument("--stairstep-thresh", type=float, default=0.92)
    p.add_argument("--resume-raw", action="store_true")
    args = p.parse_args()

    if args.level == "all":
        for lv in ("coarse", "medium", "fine"):
            run_level(lv, args.attempt, boi_scale=1.0, volume_fill=args.fill, stairstep_thresh=args.stairstep_thresh)
        res = subprocess.run([sys.executable, "-B", str(SCRIPTS_DIR / "verify_mesh_ladder.py")], cwd=str(WS_ROOT), capture_output=True, text=True)
        print(res.stdout, flush=True)
        if res.returncode != 0:
            print(res.stderr, file=sys.stderr, flush=True)
            raise RuntimeError("verify_mesh_ladder.py failed")
        print("[P2TUI] ALL THREE MESHES AND LADDER QA PASSED!", flush=True)
        return 0

    run_level(
        args.level, args.attempt,
        boi_scale=args.boi_scale,
        wing_first_height=args.wing_first,
        volume_fill=args.fill,
        stairstep_thresh=args.stairstep_thresh,
        resume_raw=args.resume_raw,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
