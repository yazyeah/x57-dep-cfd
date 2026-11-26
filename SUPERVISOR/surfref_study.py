#!/usr/bin/env python3
"""Surface-refinement study for the mesh-convergence section (brief: "refine the surface and volume mesh").

The volume ladder (coarse/medium/fine) shares one surface tessellation. This study re-meshes the published
Medium grid on a refined surface mesh while keeping the Medium volume size field and the recipe-C inflation
identical, so the change in lift/drag isolates surface refinement. The refined CAD re-tessellations failed to
inflate (see SHELLS); the surface used is the coarse facet geometry with subdivided wall facets (2.0x faces). Steps (each resumable; Fluent only through the P2 managed
runner and run_fluent_managed via run_x57_converged):
  1. mesh    -> 02_mesh/surfref/mesh_qa.json   (P2 quality tiers via the protected auditor; Student cell cap)
  2. solve   -> 03_cases/surfref_rpm100         (run_x57_converged, Fine plan: strict/engineering only)
  3. compare -> DELIVERABLES/data/surface_refinement_study.json/.csv
Exit 0 all done | 3 no admissible mesh | 4 solve not accepted | 10/20/30/40 control gate.
"""
from __future__ import annotations

import csv
import datetime as dt
import json
import subprocess
import sys
import traceback
from pathlib import Path

WS = Path(r"D:\FEA Coursework\Workspace")
SCRIPTS, SUP = WS / "scripts", WS / "SUPERVISOR"
sys.path.insert(0, str(SCRIPTS))
sys.path.insert(0, str(SUP))

import fasttrack_mesh as FM  # noqa: E402  (protected; used read-only)
import fasttrack_profile as FP  # noqa: E402  (protected; used read-only)
import p2_fasttrack as P2  # noqa: E402
from control_gate import ControlGate, atomic_write_json  # noqa: E402
from run_p2_fluent import run_fluent  # noqa: E402

LOG = WS / "logs" / "surfref_study.log"
FOLDER = WS / "02_mesh" / "surfref"
CASE = "surfref_rpm100"
# 2026-11-25 14:08-14:21: the refined CAD re-tessellations ("fine" 2.1x, "medium" 1.5x wall faces) both failed
# with the Medium recipe-C inflation ("No cell zones (check for holes in boundary mesh)" after prism
# stair-stepping; hexcore found 0 live regions), as the medium shell already had inverted cells at the outboard
# HLP junction on 2026-11-24. The study therefore refines the SURFACE MESH on the identical coarse facet geometry
# (scripts/build_subdivided_shell.py: planar edge-midpoint subdivision of wall facets, 2.0x wall faces, vertices
# fixed, symmetry/ground/far field untouched), so size field, inflation AND geometry match the Medium grid.
SHELLS = ("subdivD",)   # 11-26: subdivA 2.0x, subdivB 1.5x and subdivC 1.74x (nacelles frozen) each kept a zero-OQ junction cell; subdivD = 1.81x with nacelles frozen and a 0.12 m unsplit band around every wall-zone junction
REFINED_CAD_SHELL_ATTEMPTS = [
    dict(surface="p2_fine_prism_base_patches (78,482 wall faces)", attempt="sr_fine_1125_1408",
         result="volume meshing failed: No cell zones after prism stair-stepping (0 live hexcore regions)"),
    dict(surface="p2_medium_prism_base_patches (55,476 wall faces)", attempt="sr_medium_1125_1416",
         result="volume meshing failed: No cell zones after prism stair-stepping (0 live hexcore regions)"),
    dict(surface="p2_medium_prism_base_patches", attempt="02_mesh/medium/ft_R1_*, ft_R2_* (2026-11-24, thinner "
         "inflation)", result="meshed but rejected: min orthogonal quality 0 (inverted cells, outboard HLP junction)")]


def surface_description(level):
    meta = WS / "01_geometry" / f"p2_{level}_prism_base_patches" / "surface_subdivision.json"
    if meta.is_file():
        m = read(meta)
        return (f"coarse facet geometry, wall facets subdivided ({m['wall_face_ratio']:.2f}x wall faces, "
                f"edges > {1000 * m['split_threshold_edge_length_m']:.0f} mm split)"), m
    return f"refined CAD tessellation {level}", None
MESH_WALL_MIN, IMPROVE_WALL_MIN = 120, 40
P2.REPAIR_WALL["surfref"] = 45
OUT_JSON = WS / "DELIVERABLES" / "data" / "surface_refinement_study.json"


def log(msg):
    LOG.parent.mkdir(parents=True, exist_ok=True)
    line = f"[{dt.datetime.now().astimezone().isoformat(timespec='seconds')}] {msg}"
    print(line, flush=True)
    with LOG.open("a", encoding="utf-8") as f:
        f.write(line + "\n")


def gate():
    code = int(ControlGate(WS).check()["exit_code"])
    if code:
        log(f"control gate {code}: stopping")
        raise SystemExit(code)


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


# ------------------------------------------------------------------ mesh
def published():
    path = FOLDER / "mesh_qa.json"
    if not path.is_file():
        return None
    row = read(path)
    mesh = Path(row["source_mesh"])
    return row if row.get("passed") is True and mesh.is_file() and FM.digest(mesh) == row["mesh_sha256"] else None


def medium_recipe():
    q = read(WS / "02_mesh" / "medium" / "mesh_qa.json")
    cfg_path = Path(q["fasttrack_report"]["meshing_config_path"])
    return q, cfg_path, read(cfg_path)


def shell_faces(level):
    return read(WS / "01_geometry" / f"p2_{level}_prism_base_patches" / "assembled_shell_qa.json")


def judge(rep):
    """P2 hard checks, except the volume-ladder count window / level folder (this grid is not in the ladder)."""
    hard = {k: v for k, v in rep["hard_checks"].items() if k not in ("admissible_cell_window", "mesh_inside_level_folder")}
    hard["inside_surfref_folder"] = Path(rep["source_mesh"]).resolve().is_relative_to(FOLDER.resolve())
    rep.update(level="surfref", surfref_hard_checks=hard, admissible=all(hard.values()))
    return rep


def rescuable(rep):
    try:
        h = rep["hard_checks"]
        return (not rep["admissible"] and not rep["label"].endswith("_bndrepair") and h["single_fluid_zone"]
                and h["eleven_physical_boundaries"] and h["below_licence_cap"]
                and float(rep["poor_cell_fraction_oq_below_0p05"]) <= FP.MESH_POOR_FRACTION_LASTRESORT)
    except (KeyError, TypeError, ValueError):
        return False


def evaluate(work, mesh, mesh_trn, label, bl_cells):
    cfg = work / "mesh_config.json"
    reps = []
    rc, trn, repaired = P2.repair_and_check("surfref", work, mesh, label)
    if trn is not None:
        sq = FM.solver_quality(trn)
        if repaired is not None and sq.get("after_min_oq") is not None:
            reps.append(judge(FM.audit_candidate("medium", repaired, mesh_trn, trn, cfg, label + "_repaired", "after")))
        if sq.get("before_min_oq") is not None:
            reps.append(judge(FM.audit_candidate("medium", mesh, mesh_trn, trn, cfg, label, "before")))
    pool = [r for r in reps if rescuable(r)]
    if pool and not any(r["admissible"] for r in reps):
        base = sorted(pool, key=FM.tier_key)[0]["source_mesh"]
        log(f"  {label}: boundary repair (Fluent allow-repair-at-boundaries) of {Path(base).name}")
        rc, trn, repaired = P2.repair_and_check("surfref", work, base, label + "_bnd", allow_boundary=True, passes=4)
        if trn is not None and repaired is not None and FM.solver_quality(trn).get("after_min_oq") is not None:
            rep = judge(FM.audit_candidate("medium", repaired, mesh_trn, trn, cfg, label + "_bndrepair", "after"))
            rep["boundary_repair"] = dict(allowed_boundary_node_motion=True, base_mesh=str(base))
            reps.append(rep)
    for r in reps:
        if not r["inventory"].get("boundary_layer_cells"):
            r["inventory"]["boundary_layer_cells"] = bl_cells   # solver case files drop the mesher BL flags
        log(f"  candidate {r['label']}: cells={r['inventory']['cells']:,} tier={r['quality_tier']} "
            f"minOQ={r['solver_min_orthogonal_quality']} poor={r['poor_cell_fraction_oq_below_0p05']} "
            f"admissible={r['admissible']}")
        atomic_write_json(work / f"surfref_candidate_{r['label']}.json", r)
    return sorted(reps, key=FM.tier_key)


def mesh_attempt(shell_level):
    q, cfg_path, src = medium_recipe()
    shell = (WS / "01_geometry" / f"p2_{shell_level}_prism_base_patches" / "aircraft_domain.msh").resolve(strict=True)
    sf = Path(src["size_field_path"]).resolve(strict=True)
    scopes = src["prism_scopes"]
    name = f"sr_{shell_level}_" + dt.datetime.now().strftime("%m%d_%H%M")
    work = FOLDER / name
    work.mkdir(parents=True, exist_ok=True)
    raw, improved = work / "surfref.msh.h5", work / "surfref_improved.msh.h5"
    P2.write_mesh_journal(work, "medium", shell, sf, float(src["max_size"]), scopes, "C", raw)
    P2.write_improve(work / "improve_raw.jou", raw, improved)
    cfg = dict(src)
    cfg.update(level="surfref", shell=str(shell), source_surface_dir=str(shell.parent),
               source_surface_sha256=FM.digest(shell), size_field_path=str(sf), size_field_sha256=FM.digest(sf),
               mesh=str(raw), improved_mesh=str(improved), generation_journal=str(work / "mesh.jou"),
               surface_refinement_study=dict(surface_level=shell_level, volume_recipe_source=str(cfg_path),
                                             volume_size_field_identical_to_medium=True,
                                             inflation_identical_to_medium=src["prism_scopes"] == scopes))
    atomic_write_json(work / "mesh_config.json", cfg)
    log(f"mesh attempt {name}: {shell_level} surface ({shell_faces(shell_level)['wall_faces']:,} wall faces), "
        f"Medium size field {sf.name}, recipe C inflation")
    rc, raw_trn = run_fluent(work, work / "mesh.jou", "meshing", f"surfref_{name}", procs=4,
                             silent_stall_min=FP.P2_SILENT_STALL_MIN, max_wall_min=MESH_WALL_MIN)
    if rc != 0 or not raw.is_file() or raw_trn is None:
        log(f"  {name}: volume meshing failed rc={rc}")
        return []
    inv = FM.mesh_inventory(raw)
    log(f"  raw: {inv['cells']:,} cells (BL {inv['boundary_layer_cells']})")
    if inv["cells"] > FP.LICENSE_CELL_CAP:
        log(f"  {name}: above the Student cell cap; trying the next surface")
        return []
    gate()
    rc_i, imp_trn = run_fluent(work, work / "improve_raw.jou", "meshing", f"surfref_{name}_improve", procs=4,
                               silent_stall_min=20.0, max_wall_min=IMPROVE_WALL_MIN)
    mesh, mtrn = (improved, imp_trn) if (rc_i == 0 and improved.is_file() and imp_trn) else (raw, raw_trn)
    gate()
    return evaluate(work, mesh, mtrn, name, inv["boundary_layer_cells"])


def build_mesh():
    row = published()
    if row:
        log(f"mesh: already published {row['source_mesh']} ({row['cells']:,} cells, {row['quality_tier']})")
        return row
    candidates = []
    for path in sorted(FOLDER.glob("sr_*/surfref_candidate_*.json")):   # resume audited candidates
        try:
            rep = read(path)
            if Path(rep["source_mesh"]).is_file() and FM.digest(Path(rep["source_mesh"])) == rep["mesh_sha256"]:
                candidates.append(rep)
        except (OSError, KeyError, ValueError):
            continue
    tried = {Path(c["meshing_config_path"]).parent.name.split("_")[1] for c in candidates}
    for shell_level in SHELLS:
        if any(c["admissible"] for c in candidates):   # same admissible tiers as the published ladder grids
            break
        if shell_level in tried:
            continue
        gate()
        try:
            candidates += mesh_attempt(shell_level)
        except SystemExit:
            raise
        except Exception as exc:
            log(f"  attempt on {shell_level} surface errored: {exc.__class__.__name__}: {exc}\n{traceback.format_exc()[-1200:]}")
    good = sorted([c for c in candidates if c["admissible"]], key=FM.tier_key)
    if not good:
        return None
    best = good[0]
    inv = best["inventory"]
    q, cfg_path, src = medium_recipe()
    surf = Path(best["meshing_config_path"]).parent.name.split("_")[1]
    row = dict(level="surfref", passed=True, quality_tier=best["quality_tier"], cells=inv["cells"], nodes=inv["nodes"],
               boundary_layer_cell_count=inv["boundary_layer_cells"], source_mesh=best["source_mesh"],
               mesh_sha256=best["mesh_sha256"], min_orthogonal_quality=best["solver_min_orthogonal_quality"],
               poor_cell_fraction_oq_below_0p05=best["poor_cell_fraction_oq_below_0p05"],
               face_zones=inv["boundary_zones"], cell_zones=inv["cell_zones"], checks=best["surfref_hard_checks"],
               surface_level=surf, surface_wall_faces=shell_faces(surf)["wall_faces"],
               surface_faces_by_zone=shell_faces(surf)["faces_by_zone"],
               surface_description=surface_description(surf)[0], surface_construction=surface_description(surf)[1],
               geometry_identical_to_medium=surface_description(surf)[1] is not None,
               refined_cad_shell_attempts=REFINED_CAD_SHELL_ATTEMPTS,
               reference_medium=dict(mesh=q["source_mesh"], cells=q["cells"],
                                     boundary_layer_cells=q["boundary_layer_cell_count"],
                                     surface_wall_faces=shell_faces("coarse")["wall_faces"],
                                     meshing_config=str(cfg_path), size_field_sha256=FM.digest(Path(src["size_field_path"]))),
               volume_size_field_identical_to_medium=True, inflation_identical_to_medium=True,
               candidate_report=best, published_at=dt.datetime.now().astimezone().isoformat(timespec="seconds"))
    atomic_write_json(FOLDER / "mesh_qa.json", row)
    log(f"mesh: PUBLISHED {best['label']} cells={inv['cells']:,} tier={best['quality_tier']} "
        f"minOQ={best['solver_min_orthogonal_quality']} ({surf} surface)")
    return row


# ------------------------------------------------------------------ solve
def accepted_ok():
    try:
        from compare_x57_cases import accepted
        accepted(CASE)
        return True
    except Exception:
        return False


def solve():
    from run_fluent_managed import build_f_only_env
    env = build_f_only_env()
    for k in ("X57_CASE_DEADLINE_EPOCH", "X57_STAGE_DEADLINE_EPOCH"):
        env.pop(k, None)
    for attempt in range(1, 4):
        if accepted_ok():
            return True
        gate()
        log(f"solve attempt {attempt}: run_x57_converged {CASE}")
        with (WS / "logs" / "surfref_solve_console.log").open("a", encoding="utf-8") as out:
            rc = subprocess.run([sys.executable, "-B", str(SCRIPTS / "run_x57_converged.py"), CASE, "--stage", "P6"],
                                cwd=str(WS), env=env, stdout=out, stderr=subprocess.STDOUT).returncode
        log(f"  solve attempt {attempt} rc={rc}")
    return accepted_ok()


# ------------------------------------------------------------------ compare
def case_row(name, grid):
    from compare_x57_cases import accepted, reference, pitch_report_to_Nm
    from assess_fluent_case import flux_value
    qa, cas, dat = accepted(name)
    end = read(cas.parent / (cas.name[:-7] + "_force_and_flux.json"))
    a = end["half_model_force_N"]["airframe"]
    q, g = reference()
    area = g["full_planform_area_m2"]
    f = qa["forces_full_aircraft"]
    mq = read(WS / "02_mesh" / grid / "mesh_qa.json")
    L, D = 2 * a["ForceY"], 2 * a["ForceX"]
    return dict(case=name, grid=grid, cells=mq["cells"], boundary_layer_cells=mq.get("boundary_layer_cell_count"),
                surface=(mq.get("surface_description") or "refined " + mq["surface_level"]) if grid == "surfref"
                else "coarse CAD tessellation (shared ladder surface)",
                surface_wall_faces=mq.get("surface_wall_faces") or shell_faces("coarse")["wall_faces"],
                min_orthogonal_quality=mq.get("min_orthogonal_quality"), quality_tier=mq.get("quality_tier"),
                acceptance_tier=qa.get("acceptance_tier"), final_iteration=qa.get("final_iteration"),
                L_wall_N=L, D_wall_N=D, L_wing_N=2 * end["half_model_force_N"]["wing"]["ForceY"],
                Mz_wall_Nm=2 * flux_value(end["half_model_pitch_moment_Nm"], "airframe-pitch-mz-half") * pitch_report_to_Nm(cas.parent),
                L_tail_mean_N=f["L_air"]["mean_N"], L_tail_std_N=f["L_air"]["std_N"],
                D_tail_mean_N=f["D_air"]["mean_N"], D_tail_std_N=f["D_air"]["std_N"],
                C_L=L / (q * area), C_D=D / (q * area), q_ref_Pa=q, S_ref_m2=area,
                native_case=str(cas.relative_to(WS)), native_data=str(dat.relative_to(WS)))


def compare():
    base, ref = case_row("medium_rpm100", "medium"), case_row(CASE, "surfref")
    pct = lambda k: 100.0 * (ref[k] - base[k]) / ref[k] if ref[k] else None
    mq = read(FOLDER / "mesh_qa.json")
    result = dict(study="surface-mesh refinement at fixed Medium volume size field, fixed inflation"
                        + (" and identical facet geometry" if mq.get("geometry_identical_to_medium") else ""),
                  surface_construction=mq.get("surface_construction"),
                  refined_cad_shell_attempts=mq.get("refined_cad_shell_attempts", REFINED_CAD_SHELL_ATTEMPTS),
                  rows=[base, ref],
                  linear_surface_refinement_ratio=(ref["surface_wall_faces"] / base["surface_wall_faces"]) ** 0.5,
                  change_percent_relative_to_refined={k: pct(k) for k in ("L_wall_N", "D_wall_N", "L_wing_N", "C_L", "C_D")},
                  provenance="Native Fluent endpoints (half model x2) of the accepted iteration QA; "
                             "coefficients with the compare_x57_cases q_ref and full planform area.",
                  generated=dt.datetime.now().astimezone().isoformat(timespec="seconds"))
    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_json(OUT_JSON, result)
    with OUT_JSON.with_suffix(".csv").open("w", newline="", encoding="utf-8") as fp:
        w = csv.DictWriter(fp, fieldnames=list(base))
        w.writeheader()
        w.writerows([base, ref])
    log(f"compare: dCL={result['change_percent_relative_to_refined']['C_L']:+.2f}% "
        f"dCD={result['change_percent_relative_to_refined']['C_D']:+.2f}% -> {OUT_JSON.name}")
    return result


def main():
    log("surface-refinement study start")
    gate()
    if build_mesh() is None:
        log("no admissible surface-refined mesh; stopping (exit 3)")
        return 3
    if not solve():
        log(f"{CASE} not accepted after 3 attempts (exit 4)")
        return 4
    compare()
    log("surface-refinement study complete")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
