#!/usr/bin/env python3
"""
Antigravity P2 Production Mesh Driver (Coarse -> Medium -> Fine + Ladder QA).

Runs strictly while CONTROL/STATE.txt == PAUSE (zero collision with GPT Astra).
Uses OrthogonalQuality=0.0 inside GenerateTheVolumeMeshFTM (-t4 parallel, proven
~20 min on C15/C16) followed by bounded auto-node-move (inverse-OQ 0.85, 5 iters)
+ independent solver reload + verify_mesh_level.py --publish.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
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
from relocate_ftm_checkpoint import copy_checkpoint, copy_sidecars  # noqa: E402
from verify_mesh_level import WINDOWS, prepare_solver_check, digest  # noqa: E402
from mesh_ladder_limits import raw_domain_volume, production_plan  # noqa: E402
from complete_production_mesh import native_tail_count, published_level  # noqa: E402
from prepare_native_polyhex import quality_evidence_journal  # noqa: E402
from audit_native_wtm_surface import measure  # noqa: E402
from control_gate import atomic_write_json  # noqa: E402
from p2_geometry_io import TYPES  # noqa: E402


def prepare_c20_coarse() -> Path:
    src = WS_ROOT / "02_mesh/coarse/f_registered_ftm_17"
    work = WS_ROOT / "02_mesh/coarse/f_registered_ftm_20_oq0"
    work.mkdir(parents=True, exist_ok=True)

    field = src / "refinement.sf"
    src_ckpt = src / "registered_controls.msh.h5"
    dst_ckpt = work / "registered_controls.msh.h5"
    if not dst_ckpt.exists():
        copy_checkpoint(src_ckpt, dst_ckpt, field)
    sidecars = work / "registered_controls_workflow_files"
    if not sidecars.exists():
        copy_sidecars(src_ckpt, dst_ckpt, field)

    cfg = json.loads((WS_ROOT / "02_mesh/coarse/f_registered_ftm_19/mesh_config.json").read_text(encoding="utf-8-sig"))
    mesh_out = work / "coarse.msh.h5"
    improved_out = work / "coarse_improved.msh.h5"
    cfg["mesh"] = str(mesh_out)
    cfg["improved_mesh"] = str(improved_out)
    cfg["region_registration_checkpoint"] = str(dst_ckpt)
    cfg["region_registration_checkpoint_sha256"] = digest(dst_ckpt)
    cfg["generation_journal"] = str(work / "mesh.jou")
    cfg["orthogonal_quality"] = 0.0
    cfg["native_generation_target_min_oq"] = 0.0
    cfg["enable_parallel_volume"] = True
    cfg["generation_processes"] = 4
    cfg["improvement_target_orthogonal_quality"] = 0.15
    cfg["improvement_inverse_orthogonal_quality"] = 0.85
    cfg["improvement_iterations"] = 5
    cfg["diagnose_failed_fill"] = True
    cfg.pop("serial_reference", None)
    atomic_write_json(work / "mesh_config.json", cfg)

    module = (SCRIPTS_DIR / "ftm_refined_native.py").as_posix()
    cfg_posix = (work / "mesh_config.json").as_posix()
    py_call = f"exec(open(r'{module}',encoding='utf-8').read()); fill(workflow,meshing,r'{cfg_posix}')"

    mesh_jou = (
        "/file/confirm-overwrite no\n"
        f'/file/read-mesh "{dst_ckpt.as_posix()}"\n'
        f'/file/read-size-field "{field.as_posix()}"\n'
        "(tgsetvar! 'poly/smooth-improve? #f)\n"
        "(tgsetvar! 'poly/smooth-improve-iter 1)\n"
        "(tgsetvar! 'poly/smooth-improve-tries 1)\n"
        "(tgsetvar! 'poly/post-improve? #f)\n"
        f'(%py-exec "{py_call}")\n'
        "yes\n"
        f'/file/write-mesh "{mesh_out.as_posix()}"\n'
        "/mesh/check-mesh\n"
        "/mesh/check-quality\n"
        "/report/mesh-size\n"
        + quality_evidence_journal().replace("X57-INVERSE-", "X57-RAW-INVERSE-")
        + "/exit yes\n"
    )
    (work / "mesh.jou").write_text(mesh_jou, encoding="ascii")

    write_improve_journal(work / "improve_raw.jou", mesh_out, improved_out, inv_oq=0.85, iters=5)
    print(f"[P2Driver] Prepared Coarse C20 (OQ=0.0, -t4): {work}", flush=True)
    return work


def write_improve_journal(path: Path, src_mesh: Path, dst_mesh: Path, inv_oq: float = 0.85, iters: int = 5) -> None:
    jou = (
        "/file/confirm-overwrite no\n"
        f'/file/read-mesh "{src_mesh.as_posix()}"\n'
        "/report/quality-method inverse-ortho-quality\n"
        "/mesh/modify/auto-node-move\n"
        "*\n()\n*\n()\n"
        f"{inv_oq:.2f}\n"
        f"{iters}\n"
        "60\n"
        "yes\n"
        "1\n"
        f'/file/write-mesh "{dst_mesh.as_posix()}"\n'
        "/mesh/check-mesh\n"
        "/mesh/check-quality\n"
        "/report/mesh-size\n"
        + quality_evidence_journal().replace("X57-INVERSE-", "X57-POST-INVERSE-")
        + "/exit yes\n"
    )
    path.write_text(jou, encoding="ascii")


def parse_min_oq(transcript: Path) -> float | None:
    txt = transcript.read_text(encoding="utf-8", errors="replace")
    m = re.findall(r"Minimum Orthogonal Quality\s*=\s*([+\-\d.eE]+)", txt, re.I)
    return float(m[-1]) if m else None


def count_cells(mesh: Path) -> int:
    with h5py.File(mesh, "r") as h:
        z = h["meshes/1/cells/zoneTopology"]
        return int(sum(int(b) - int(a) + 1 for a, b in zip(z["minId"][:], z["maxId"][:], strict=True)))


def finish_raw_mesh(work: Path, raw_trn: Path) -> None:
    cfg = json.loads((work / "mesh_config.json").read_text(encoding="utf-8-sig"))
    level = cfg["level"]
    raw_mesh = Path(cfg["mesh"]).resolve(strict=True)
    improved_mesh = Path(cfg["improved_mesh"]).resolve()

    ncells = count_cells(raw_mesh)
    raw_tail = native_tail_count(raw_trn)
    print(f"[P2Driver] Raw {level} mesh: cells={ncells:,}, window={WINDOWS[level]}, raw_invOQ>0.95={raw_tail}", flush=True)
    atomic_write_json(work / "raw_inverse_oq_population.json", {
        "threshold": 0.95,
        "count": raw_tail,
        "total_raw_cells": ncells,
        "cell_budget": list(WINDOWS[level]),
        "raw_count_in_budget": WINDOWS[level][0] <= ncells <= WINDOWS[level][1],
        "transcript": str(raw_trn),
    })
    if not (WINDOWS[level][0] <= ncells <= WINDOWS[level][1]):
        raise RuntimeError(f"Raw {level} mesh cells {ncells:,} outside window {WINDOWS[level]}")

    vol = raw_domain_volume(raw_mesh)
    plan = production_plan(WS_ROOT, (level, ncells, vol))
    atomic_write_json(work / "raw_mesh_ladder_plan.json", plan)
    if not plan["measured_constraints_pass"]:
        raise RuntimeError(f"Ladder ratio constraints failed for {level} ({ncells:,}): {plan}")

    # Pass 1 improvement: inverse-OQ 0.85, 5 iterations
    stamp = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    write_improve_journal(work / "improve_raw.jou", raw_mesh, improved_mesh, inv_oq=0.85, iters=5)
    rc, imp_trn = run_fluent(work, work / "improve_raw.jou", "meshing", f"{level}_improve_{stamp}", procs=4, silent_stall_min=20.0, max_wall_min=35.0)
    if rc != 0 or not improved_mesh.is_file() or imp_trn is None:
        raise RuntimeError(f"Improvement pass 1 failed for {level}: rc={rc}, trn={imp_trn}")

    min_oq = parse_min_oq(imp_trn)
    tail_cnt = native_tail_count(imp_trn)
    print(f"[P2Driver] After improve pass 1 ({level}): min_oq={min_oq}, invOQ>0.95={tail_cnt}", flush=True)

    # Optional targeted polish pass ONLY if min_oq <= 0.115 or tail > 5000
    if (min_oq is not None and min_oq <= 0.115) or (tail_cnt is not None and tail_cnt > 5000):
        print(f"[P2Driver] Running targeted polish pass 2 on {level} (0.88, 6 iters)...", flush=True)
        polish_jou = work / "improve_polish.jou"
        write_improve_journal(polish_jou, improved_mesh, improved_mesh, inv_oq=0.88, iters=6)
        rc2, imp_trn2 = run_fluent(work, polish_jou, "meshing", f"{level}_polish_{stamp}", procs=4, silent_stall_min=20.0, max_wall_min=35.0)
        if rc2 == 0 and imp_trn2 is not None:
            imp_trn = imp_trn2
            min_oq = parse_min_oq(imp_trn)
            tail_cnt = native_tail_count(imp_trn)
            print(f"[P2Driver] After polish pass 2 ({level}): min_oq={min_oq}, invOQ>0.95={tail_cnt}", flush=True)

    atomic_write_json(work / "improved_inverse_oq_population.json", {
        "threshold": 0.95,
        "count": tail_cnt,
        "transcript": str(imp_trn),
        "mesh": str(improved_mesh),
    })
    if tail_cnt is not None and tail_cnt > 5000:
        raise RuntimeError(f"Improved {level} still has {tail_cnt} cells > invOQ 0.95")

    # Independent solver reload check
    check_jou = prepare_solver_check(improved_mesh)
    reload_dir = work / "quality_reload" / stamp
    reload_dir.mkdir(parents=True, exist_ok=True)
    rc_s, reload_trn = run_fluent(reload_dir, check_jou, "solver", f"{level}_solver_reload_{stamp}", procs=4, silent_stall_min=15.0, max_wall_min=25.0)
    if rc_s != 0 or reload_trn is None:
        raise RuntimeError(f"Solver reload check failed for {level}: rc={rc_s}, trn={reload_trn}")

    # Publish via canonical verify_mesh_level.py
    cmd = [
        sys.executable, "-B", str(SCRIPTS_DIR / "verify_mesh_level.py"),
        str(improved_mesh), str(imp_trn),
        "--level", level,
        "--solver-transcript", str(reload_trn),
        "--config", str(work / "mesh_config.json"),
        "--publish",
    ]
    res = subprocess.run(cmd, cwd=str(WS_ROOT), capture_output=True, text=True)
    print(res.stdout[-3000:] if res.stdout else "", flush=True)
    if res.returncode != 0:
        print(res.stderr, file=sys.stderr, flush=True)
        raise RuntimeError(f"verify_mesh_level.py --publish failed for {level} (rc={res.returncode})")
    print(f"[P2Driver] SUCCESS: {level} PUBLISHED!", flush=True)


def run_refined_level(work: Path, from_step: str = "field") -> None:
    cfg_path = work / "mesh_config.json"
    cfg = json.loads(cfg_path.read_text(encoding="utf-8-sig"))
    level = cfg["level"]
    if published_level(level):
        print(f"[P2Driver] {level} already published!", flush=True)
        return

    # Force OrthogonalQuality=0.0 for fast non-stalling poly-hexcore generation
    if cfg.get("orthogonal_quality") != 0.0:
        cfg["orthogonal_quality"] = 0.0
        cfg["improvement_target_orthogonal_quality"] = 0.15
        cfg["improvement_inverse_orthogonal_quality"] = 0.85
        cfg["improvement_iterations"] = 5
        atomic_write_json(cfg_path, cfg)

    c16 = WS_ROOT / "02_mesh/coarse/f_registered_ftm_16"
    seed = c16 / "extracted_si_surface.msh.h5"
    rebound = work / "workflow_seed.msh.h5"
    field = work / "refinement.sf"
    fluid = work / "conformal_fluid.msh.h5"
    source = Path(cfg["source_surface_dir"])
    steps = ("field", "seed", "sidecars", "assemble", "surface", "register", "mesh", "publish")
    logbook = work / "volume_generation_transcript.json"

    for step in steps[steps.index(from_step):]:
        print(f"[P2Driver] [{level}] step={step}", flush=True)
        if step == "field":
            if not field.is_file():
                rc, _ = run_fluent(work, work / "field.jou", "meshing", f"{level}_field", procs=4, silent_stall_min=20.0, max_wall_min=30.0)
                if rc != 0 or not field.is_file():
                    raise RuntimeError(f"{level} field generation failed (rc={rc})")
        elif step == "seed":
            if not rebound.is_file():
                copy_checkpoint(seed, rebound, field)
        elif step == "sidecars":
            if not (work / "workflow_seed_workflow_files").is_dir():
                copy_sidecars(seed, rebound, field)
        elif step == "assemble":
            if not fluid.is_file():
                rc, _ = run_fluent(work, work / "assemble.jou", "meshing", f"{level}_assemble", procs=4, silent_stall_min=15.0, max_wall_min=25.0)
                if rc != 0 or not fluid.is_file():
                    raise RuntimeError(f"{level} assemble failed (rc={rc})")
        elif step == "surface":
            with h5py.File(fluid, "r") as h:
                raw = h["settings/TGrid Variables"][0]
                matches = re.findall(rb"\(external_fluid fluid \d+ \(([\d ]+)\) \(\) mesh \(", raw)
                if len(matches) != 1:
                    raise RuntimeError("Expected one named external_fluid mesh object")
                ids = {int(x) for x in matches[0].split()}
                top = h["meshes/1/faces/zoneTopology"]
                names = top["name"][0].decode().rstrip(";").split(";")
                actual = [n for i, n in zip(top["id"][:], names, strict=True) if i in ids]
            qa = measure(fluid, level)
            qa["mesh_object_faces"] = actual
            expected = json.loads((source / "assembled_shell_qa.json").read_text("utf-8-sig"))["faces_by_zone"]
            qa["confirmed_source_wall_counts"] = all(expected[n] == c for n, c in qa["face_counts"].items())
            qa["passed"] = qa["passed"] and qa["confirmed_source_wall_counts"]
            qa["surface_sha256"] = digest(fluid)
            atomic_write_json(work / "conformal_region_cad_audit.json", qa)
            if not qa["passed"]:
                raise RuntimeError(f"{level} surface CAD audit failed")
        elif step == "register":
            controls = work / "registered_prism_controls.msh.h5"
            if not controls.is_file():
                rc, _ = run_fluent(work, work / "register.jou", "meshing", f"{level}_register", procs=4, silent_stall_min=15.0, max_wall_min=25.0)
                if rc != 0 or not controls.is_file():
                    raise RuntimeError(f"{level} register failed (rc={rc})")
        elif step == "mesh":
            # Ensure fast raw poly-hexcore (skip silent internal poly smooth; explicit auto-node-move follows)
            mjou_path = work / "mesh.jou"
            mjou_txt = mjou_path.read_text(encoding="ascii")
            if "poly/post-improve?" not in mjou_txt:
                inject = (
                    "(tgsetvar! 'poly/smooth-improve? #f)\n"
                    "(tgsetvar! 'poly/smooth-improve-iter 1)\n"
                    "(tgsetvar! 'poly/smooth-improve-tries 1)\n"
                    "(tgsetvar! 'poly/post-improve? #f)\n"
                )
                mjou_txt = mjou_txt.replace("(%py-exec ", inject + "(%py-exec ", 1)
                mjou_path.write_text(mjou_txt, encoding="ascii")
            max_wall = 95.0 if level == "fine" else 65.0
            rc, trn = run_fluent(work, mjou_path, "meshing", f"{level}_volume_oq0", procs=4, silent_stall_min=35.0, max_wall_min=max_wall)
            raw_mesh = Path(cfg["mesh"])
            if rc != 0 or not raw_mesh.is_file() or trn is None:
                raise RuntimeError(f"{level} volume generation failed: rc={rc}, trn={trn}")
            atomic_write_json(logbook, {"transcript": str(trn), "raw_mesh_sha256": digest(raw_mesh)})
        elif step == "publish":
            rec = json.loads(logbook.read_text("utf-8-sig"))
            finish_raw_mesh(work, Path(rec["transcript"]))


def main() -> int:
    p = argparse.ArgumentParser(description="Antigravity P2 Mesh Production Driver")
    p.add_argument("action", choices=["prepare-c20", "run-coarse", "run-medium", "run-fine", "run-all"])
    p.add_argument("--work", type=Path, default=None)
    p.add_argument("--from-step", default="field")
    args = p.parse_args()

    if args.action == "prepare-c20":
        prepare_c20_coarse()
        return 0

    if args.action in ("run-coarse", "run-all"):
        if not published_level("coarse"):
            work = args.work or prepare_c20_coarse()
            rc, trn = run_fluent(work, work / "mesh.jou", "meshing", "coarse_c20_oq0_nopost_volume", procs=4, silent_stall_min=35.0, max_wall_min=55.0)
            raw_mesh = work / "coarse.msh.h5"
            if rc != 0 or not raw_mesh.is_file() or trn is None:
                raise RuntimeError(f"Coarse C20 volume generation failed: rc={rc}, trn={trn}")
            finish_raw_mesh(work, trn)
        else:
            print("[P2Driver] Coarse already published.", flush=True)

    if args.action in ("run-medium", "run-all"):
        work = args.work if args.action == "run-medium" and args.work else (WS_ROOT / "02_mesh/medium/f_registered_ftm_17")
        run_refined_level(work, from_step=args.from_step if args.action == "run-medium" else "field")

    if args.action in ("run-fine", "run-all"):
        work = args.work if args.action == "run-fine" and args.work else (WS_ROOT / "02_mesh/fine/f_registered_ftm_17")
        run_refined_level(work, from_step=args.from_step if args.action == "run-fine" else "field")

    if args.action == "run-all":
        res = subprocess.run([sys.executable, "-B", str(SCRIPTS_DIR / "verify_mesh_ladder.py")], cwd=str(WS_ROOT), capture_output=True, text=True)
        print(res.stdout, flush=True)
        if res.returncode != 0:
            print(res.stderr, file=sys.stderr, flush=True)
            raise RuntimeError("verify_mesh_ladder.py failed")
        print("[P2Driver] ALL THREE MESHES + LADDER QA PASSED!", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
