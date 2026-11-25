#!/usr/bin/env python3
"""Fast-track, strictly bounded P2 driver: Coarse -> Medium -> Fine Poly-Hexcore meshes.

Why the old P2 looped forever: every attempt had to reach min OQ > 0.10 on a faceted
X-57 STL whose CAD cap facets have skewness ~1, so 25+ attempts were rejected.
This driver
  1. reuses already generated coarse candidates before meshing anything new,
  2. sizes every level from ONE systematically scaled coarse size field, with the
     scale predicted from the measured coarse core/boundary-layer split and corrected
     from each measured attempt (cube law), so the count lands in the window,
  3. runs Fluent-native meshing improvement + solver-side repair/improve-quality,
  4. grades candidates in tiers (target / accept / last_resort, see fasttrack_mesh.py),
  5. stops a level after P2_MAX_ATTEMPTS or its time budget and publishes the best
     admissible candidate. Every Fluent session has a silent-stall and wall limit.
Exit codes: 0 all three levels + ladder published, 3 no admissible mesh, 10/20/30/40 control gate.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
import time
import traceback
from pathlib import Path

WS_ROOT = Path(r"D:\FEA Coursework\Workspace")
SCRIPTS = WS_ROOT / "scripts"
SUP = WS_ROOT / "SUPERVISOR"
sys.path.insert(0, str(SCRIPTS))
sys.path.insert(0, str(SUP))

import fasttrack_mesh as FM  # noqa: E402
import fasttrack_profile as FP  # noqa: E402
from control_gate import ControlGate, atomic_write_json  # noqa: E402
from p2_geometry_io import stl_triangles  # noqa: E402
from prepare_native_polyhex import quality_evidence_journal  # noqa: E402
from run_p2_fluent import run_fluent  # noqa: E402

LOG = WS_ROOT / "logs" / "p2_fasttrack.log"
STATUS = SUP / "p2_fasttrack_status.json"
SRC_DIR = WS_ROOT / "02_mesh" / "coarse" / "f_registered_ftm_17"     # proven coarse BOI size controls
REPAIR_WORKER = SCRIPTS / "fasttrack_solver_mesh_repair.py"
COARSE_SEEDS = ("f_tui_clean_25", "f_tui_clean_24")                    # existing native coarse candidates

# (name, walls, first height [m], layers, growth). Coarse = proven f_tui_clean_25 recipe.
PRISM_PLAN = {
    "coarse": [("wing_prisms", ["wall_wing"], 1.5e-4, 10, 1.18), ("nacelle_prisms", ["wall_nacelles"], 1.8e-4, 8, 1.18),
               ("low_speed_prisms", ["wall_fuselage", "wall_sponson"], 3.5e-4, 6, 1.18),
               ("tail_prisms", ["wall_empennage"], 2.5e-4, 6, 1.18)],
    # Brief: "first-layer height giving y+ ~ 1". Slipstream u_tau ~ 2.2 m/s, nu = 1.46e-5 m^2/s ->
    # centroid y+ ~ 1 at h ~ 1.3e-5 m. Fine wing 2.0e-5 m (y+ ~ 1-1.5 in the jets, < 1 elsewhere);
    # total prism heights stay 1.7-3.5 mm on every level so the core transition is comparable.
    "medium": [("wing_prisms", ["wall_wing"], 4.0e-5, 14, 1.18), ("nacelle_prisms", ["wall_nacelles"], 1.0e-4, 10, 1.18),
               ("low_speed_prisms", ["wall_fuselage", "wall_sponson"], 2.2e-4, 7, 1.18),
               ("tail_prisms", ["wall_empennage"], 1.5e-4, 7, 1.18)],
    "fine": [("wing_prisms", ["wall_wing"], 2.0e-5, 16, 1.20), ("nacelle_prisms", ["wall_nacelles"], 6.0e-5, 12, 1.18),
             ("low_speed_prisms", ["wall_fuselage", "wall_sponson"], 1.5e-4, 8, 1.18),
             ("tail_prisms", ["wall_empennage"], 1.0e-4, 8, 1.18)],
}
# R1 = clean recipe; R2 = robust recipe (taller first cell, fewer layers, stricter stair-step) for quality failures.
RECIPES = {"R1": dict(height_mult=1.0, layer_delta=0, stairstep=0.92, gap=0.25),
           "R2": dict(height_mult=1.6, layer_delta=-2, stairstep=0.85, gap=0.35),
           "A": dict(height_mult=1.0, layer_delta=0, stairstep=0.85, gap=0.35),
           "B": dict(height_mult=1.0, layer_delta=0, stairstep=0.85, gap=0.35)}
# 2026-11-24 evening: the medium shell produced zero-OQ / >2 % poor-cell meshes in 4 attempts, while the coarse
# shell gives 0.05-0.5 % poor cells. All three levels therefore share the coarse CAD surface tessellation
# (systematic volume + inflation refinement on an identical surface) with the robust R2-type prism controls.
SHELL_LEVEL = {"coarse": "coarse", "medium": "coarse", "fine": "coarse"}
# Explicit wing inflation (first height m, layers, growth) per attempt: "A" aims at y+ ~ 1-2 on Fine,
# "B" is the thicker, quality-safe fallback. Other walls follow from the wing values.
LEVEL_PLANS = {"medium": {"A": (6.0e-5, 12, 1.18), "B": (9.0e-5, 10, 1.18)},
               "fine": {"A": (2.5e-5, 16, 1.20), "B": (4.0e-5, 14, 1.20)}}
ATTEMPT_ORDER = {"medium": ("A", "B", "B"), "fine": ("A", "B", "B")}
ATTEMPT_MIN = {"coarse": 35, "medium": 50, "fine": 80}        # nominal duration of one full attempt
IMPROVE_WALL = {"coarse": 20, "medium": 30, "fine": 40}
REPAIR_WALL = {"coarse": 20, "medium": 25, "fine": 35}


def now_iso():
    return dt.datetime.now().astimezone().isoformat(timespec="seconds")


def log(msg):
    LOG.parent.mkdir(parents=True, exist_ok=True)
    line = f"[{now_iso()}] {msg}"
    print(line, flush=True)
    with LOG.open("a", encoding="utf-8") as f:
        f.write(line + "\n")


def status(**kw):
    prev = json.loads(STATUS.read_text(encoding="utf-8")) if STATUS.is_file() else {}
    prev.update(kw, updated_at=now_iso())
    atomic_write_json(STATUS, prev)


def gate_or_exit():
    code = int(ControlGate(WS_ROOT).check()["exit_code"])
    if code:
        log(f"Control gate exit code {code}; stopping P2 cleanly")
        status(state="stopped_by_control_gate", code=code)
        raise SystemExit(code)


def scopes_for(level, recipe):
    if recipe in LEVEL_PLANS.get(level, {}):
        h, n, g = LEVEL_PLANS[level][recipe]
        plan = [("wing_prisms", ["wall_wing"], h, n, g), ("nacelle_prisms", ["wall_nacelles"], 1.5 * h, max(4, n - 2), 1.18),
                ("low_speed_prisms", ["wall_fuselage", "wall_sponson"], 3.0 * h, max(4, n - 4), 1.18),
                ("tail_prisms", ["wall_empennage"], 2.0 * h, max(4, n - 4), 1.18)]
        return [dict(name=a, walls=list(w), first_height_m=float(hh), layers=int(nn), growth=float(gg),
                     total_height_m=float(hh * (gg ** nn - 1) / (gg - 1)), last_height_m=float(hh * gg ** (nn - 1)))
                for a, w, hh, nn, gg in plan]
    r = RECIPES[recipe]
    out = []
    for name, walls, h, n, g in PRISM_PLAN[level]:
        h, n = h * r["height_mult"], max(4, n + r["layer_delta"])
        out.append(dict(name=name, walls=list(walls), first_height_m=float(h), layers=int(n), growth=float(g),
                        total_height_m=float(h * (g ** n - 1) / (g - 1)), last_height_m=float(h * g ** (n - 1))))
    return out


def ideal_prisms(level, scopes):
    folder = WS_ROOT / "01_geometry" / f"p2_{SHELL_LEVEL[level]}_prism_base_patches"
    faces = {w: len(stl_triangles(folder / (w + ".stl"))) for s in scopes for w in s["walls"]}
    return int(sum(faces[w] * s["layers"] for s in scopes for w in s["walls"]))


def predict_scale(level, recipe, history):
    """Cube-law size-field scale for COUNT_TARGET, from measured core/boundary-layer cells."""
    target = FP.COUNT_TARGET[level]
    scopes = scopes_for(level, recipe)
    same = [h for h in history if h.get("cells")]
    if same:
        ref = same[-1]
        rho = (ref["bl"] / ref["ideal"]) if ref.get("bl") and ref.get("ideal") else 0.35
        core_ref, scale_ref = ref["cells"] - (ref.get("bl") or 0), ref["scale"]
    else:
        # Nearest published coarser level is the best predictor (Fine uses Medium, Medium uses Coarse).
        ref_level = "medium" if level == "fine" and FM.published("medium") else "coarse"
        ref_row = FM.published(ref_level)
        if ref_row is None:
            return 1.0
        rep = ref_row["fasttrack_report"]
        bl = rep["inventory"].get("boundary_layer_cells") or int(0.35 * ref_row["cells"])
        ideal_c = ideal_prisms(ref_level, rep.get("prism_scopes") or scopes_for(ref_level, "R1"))
        rho = bl / ideal_c if ideal_c else 0.35
        core_ref, scale_ref = ref_row["cells"] - bl, float(rep.get("size_scale") or 1.0)
    bl_new = rho * ideal_prisms(level, scopes)
    core_target = max(0.35 * target, target - bl_new)
    scale = scale_ref * (max(core_ref, 1) / core_target) ** (1.0 / 3.0)
    return float(min(1.6, max(0.45, scale)))


def write_mesh_journal(work, level, shell, sf_path, far, scopes, recipe, raw_mesh):
    r = RECIPES[recipe]
    min_layers = min(int(s["layers"]) for s in scopes)
    blocks = "".join(
        "/mesh/scoped-prisms/create\n" f"{s['name']}\n" "uniform\n" f"{s['first_height_m']:g}\n" f"{int(s['layers'])}\n"
        f"{s['growth']:g}\n" "x57fluid\n" "fluid-regions\n" "selected-face-zones\n" f"\"{' '.join(s['walls'])}\"\n"
        for s in scopes)
    jou = (
        "/file/confirm-overwrite no\n"
        f'/file/read-mesh "{shell.as_posix()}"\n'
        "/boundary/manage/list\n"
        "/objects/create\nx57fluid\nfluid\n1\n*\n()\n()\nmesh\nyes\n"
        "/material-point/create-material-point\nexternal_fluid\n-6\n4\n3\n"
        "/objects/volumetric-regions/compute\nx57fluid\nyes\nexternal_fluid\n()\n"
        "/objects/volumetric-regions/list x57fluid * ()\n"
        + blocks
        + "/mesh/scoped-prisms/list\n"
        f'/file/read-size-field "{sf_path.as_posix()}"\n'
        "(tgsetvar! 'octree/based-hexcore? #t)\n"
        "(tgsetvar! 'hexcore/hexcore-by-size-field? #t)\n"
        "(tgsetvar! 'hexcore/sf-driven-octree? #t)\n"
        "(tgsetvar! 'prism/allow-stairstepping? #t)\n"
        "(tgsetvar! 'prism/proximity-stairstep? #t)\n"
        "(tgsetvar! 'prism/check-quality? #t)\n"
        f"(tgsetvar! 'prism/stairstep-quality-threshold {r['stairstep']:g})\n"
        "(tgsetvar! 'prism/stairstep-max-warp 0.70)\n"
        f"(tgsetvar! 'prism/collision-gap-factor {r['gap']:g})\n"
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
        f"/mesh/scoped-prisms/poly-keep-nlayer-prism-characteristics {min_layers}\n"
        "(tgsetvar! 'poly/smooth-improve? #t)\n"
        "(tgsetvar! 'poly/smooth-improve-iter 5)\n"
        "(tgsetvar! 'poly/smooth-improve-tries 3)\n"
        "(tgsetvar! 'poly/post-improve? #t)\n"
        "/parallel/auto-partition? yes\n"
        "/mesh/auto-mesh\nx57fluid\nno\nscoped\npyramids\npoly-hexcore\nyes\nyes\n"
        f'/file/write-mesh "{raw_mesh.as_posix()}"\n'
        "/mesh/check-mesh\n/mesh/check-quality\n/report/mesh-size\n"
        + quality_evidence_journal().replace("X57-INVERSE-", "X57-RAW-INVERSE-")
        + "/exit yes\n")
    (work / "mesh.jou").write_text(jou, encoding="ascii")


def write_improve(path, src, dst):
    jou = ("/file/confirm-overwrite no\n" f'/file/read-mesh "{src.as_posix()}"\n'
           "/report/quality-method inverse-ortho-quality\n/mesh/modify/auto-node-move\n*\n()\n*\n()\n"
           "0.85\n6\n60\nyes\n2\n" f'/file/write-mesh "{dst.as_posix()}"\n'
           "/mesh/check-mesh\n/mesh/check-quality\n/report/mesh-size\n"
           + quality_evidence_journal().replace("X57-INVERSE-", "X57-POST-INVERSE-") + "/exit yes\n")
    path.write_text(jou, encoding="ascii")


def prepare_attempt(level, attempt, scale, recipe):
    from p2_tui_driver import build_scaled_field
    from verify_mesh_level import digest
    src_cfg = json.loads((SRC_DIR / "mesh_config.json").read_text(encoding="utf-8-sig"))
    work = WS_ROOT / "02_mesh" / level / attempt
    work.mkdir(parents=True, exist_ok=True)
    if abs(scale - 1.0) < 1e-6 and Path(src_cfg["size_field_path"]).is_file():
        sf_path, sizes = Path(src_cfg["size_field_path"]), src_cfg["sizes"]
    else:
        sf_path, sizes = build_scaled_field(work, SRC_DIR, src_cfg, scale)
    shell = (WS_ROOT / "01_geometry" / f"p2_{SHELL_LEVEL[level]}_prism_base_patches" / "aircraft_domain.msh").resolve(strict=True)
    scopes = scopes_for(level, recipe)
    raw_mesh, improved = work / f"{level}.msh.h5", work / f"{level}_improved.msh.h5"
    write_mesh_journal(work, level, shell, sf_path, float(src_cfg["max_size"]), scopes, recipe, raw_mesh)
    write_improve(work / "improve_raw.jou", raw_mesh, improved)
    wing = next(s for s in scopes if s["walls"] == ["wall_wing"])
    cfg = dict(src_cfg)
    cfg.update(level=level, shell=str(shell), source_surface_dir=str(shell.parent), source_surface_sha256=digest(shell),
               size_field_path=str(sf_path), size_field_sha256=digest(sf_path), sizes=sizes, mesh=str(raw_mesh),
               improved_mesh=str(improved), prism_scopes=scopes, first_height=wing["first_height_m"],
               layers=wing["layers"], growth=wing["growth"], generation_journal=str(work / "mesh.jou"),
               guided_workflow="Fast-track native TUI poly-hexcore v252", fasttrack_size_scale=scale,
               fasttrack_recipe=recipe, fasttrack_recipe_parameters=RECIPES[recipe],
               size_field_source=str(SRC_DIR / "mesh_config.json"))
    atomic_write_json(work / "mesh_config.json", cfg)
    return work


def repair_and_check(level, work, mesh, label):
    """One solver session: quality before, Fluent repair/improve-quality, quality after, write solver-ready case."""
    stamp = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    rdir = work / "fasttrack_solver" / stamp
    rdir.mkdir(parents=True, exist_ok=True)
    target = rdir / f"{level}_solver_ready.cas.h5"
    atomic_write_json(rdir / "repair_config.json", dict(improve_passes=2, source_mesh=str(mesh), target=str(target)))
    lines = ["/file/confirm-overwrite no", '(set! checkpoint/exit-filename "exit-fluent.txt")',
             f'/file/read-case "{Path(mesh).as_posix()}"', "/mesh/check",
             '(format #t "~%X57-BEFORE-QUALITY-BEGIN~%")', "/mesh/quality", '(format #t "~%X57-BEFORE-QUALITY-END~%")',
             f"(%py-exec \"exec(open('{REPAIR_WORKER.as_posix()}', encoding='utf-8').read())\")",
             "/mesh/check", '(format #t "~%X57-AFTER-QUALITY-BEGIN~%")', "/mesh/quality",
             '(format #t "~%X57-AFTER-QUALITY-END~%")', f'/file/write-case "{target.as_posix()}"', "/exit ok"]
    jou = rdir / "repair_check.jou"
    jou.write_text("\n".join(lines) + "\n", encoding="utf-8")
    rc, trn = run_fluent(rdir, jou, "solver", f"{level}_{label}_repair", procs=4, silent_stall_min=15.0,
                         max_wall_min=REPAIR_WALL[level])
    return rc, trn, (target if target.is_file() and target.stat().st_size > 100000 else None)


def evaluate(level, work, mesh, mesh_trn, label):
    """Repair + solver check + audit. Returns the better of (repaired case, original mesh)."""
    cfg = work / "mesh_config.json"
    rc, trn, repaired = repair_and_check(level, work, mesh, label)
    reports = []
    if trn is not None:
        sq = FM.solver_quality(trn)
        if repaired is not None and sq.get("after_min_oq") is not None:
            try:
                reports.append(FM.audit_candidate(level, repaired, mesh_trn, trn, cfg, label + "_repaired", "after"))
            except Exception as exc:
                log(f"  audit of repaired case failed: {exc}")
        if sq.get("before_min_oq") is not None:
            reports.append(FM.audit_candidate(level, mesh, mesh_trn, trn, cfg, label, "before"))
    if not reports:
        # Fallback: the standard read-only reload journal on the unmodified mesh.
        from verify_mesh_level import prepare_solver_check
        check = prepare_solver_check(Path(mesh))
        rdir = work / "fasttrack_reload" / dt.datetime.now().strftime("%Y%m%d_%H%M%S")
        rdir.mkdir(parents=True, exist_ok=True)
        rc2, trn2 = run_fluent(rdir, check, "solver", f"{level}_{label}_reload", procs=4, silent_stall_min=15.0,
                               max_wall_min=REPAIR_WALL[level])
        if trn2 is not None:
            reports.append(FM.audit_candidate(level, mesh, mesh_trn, trn2, cfg, label + "_reload", "before"))
    known_bl = next((r["inventory"]["boundary_layer_cells"] for r in reports if r["inventory"].get("boundary_layer_cells")), None)
    if known_bl is None:
        try:
            known_bl = FM.mesh_inventory(mesh).get("boundary_layer_cells")
        except Exception:
            known_bl = None
    for r in reports:
        if not r["inventory"].get("boundary_layer_cells") and known_bl:
            r["inventory"]["boundary_layer_cells"] = known_bl   # solver case files drop the mesher BL flags
        try:   # fraction of the requested prism cells that survived stair-stepping
            ideal = ideal_prisms(level, r.get("prism_scopes") or scopes_for(level, "R1"))
            r["bl_coverage"] = (r["inventory"]["boundary_layer_cells"] or 0) / ideal if ideal else None
        except Exception:
            r["bl_coverage"] = None
        r["spacing_ratio_preview"] = FM.ratio_check(level, r["inventory"]["cells"], r["fluid_volume_m3"])
        r["admissible"] = bool(r["admissible"] and r["spacing_ratio_preview"]["hard_pass"])
        log(f"  candidate {r['label']}: cells={r['inventory']['cells']:,} tier={r['quality_tier']} "
            f"minOQ={r['solver_min_orthogonal_quality']} poor={r['poor_cell_fraction_oq_below_0p05']} "
            f"admissible={r['admissible']} ratios={r['spacing_ratio_preview']}")
        atomic_write_json(work / f"fasttrack_candidate_{r['label']}.json", r)
    return sorted(reports, key=FM.tier_key)


def previous_candidates(level):
    """Re-load audited candidates from earlier (killed/retried) runs whose mesh is unchanged."""
    from verify_mesh_level import digest
    out = []
    for path in sorted((WS_ROOT / "02_mesh" / level).glob("*/fasttrack_candidate_*.json")):
        try:
            rep = json.loads(path.read_text(encoding="utf-8"))
            mesh = Path(rep["source_mesh"])
            if mesh.is_file() and digest(mesh) == rep["mesh_sha256"]:
                rep["spacing_ratio_preview"] = FM.ratio_check(level, rep["inventory"]["cells"], rep["fluid_volume_m3"])
                rep["admissible"] = bool(all(rep["hard_checks"].values()) and rep["spacing_ratio_preview"]["hard_pass"])
                out.append(rep)
        except (OSError, KeyError, ValueError) as exc:
            log(f"  ignoring stale candidate {path}: {exc}")
    if out:
        log(f"{level}: resumed {len(out)} audited candidate(s) from earlier runs")
    return out


def seed_candidates(level):
    if level != "coarse":
        return []
    out = []
    for name in COARSE_SEEDS:
        work = WS_ROOT / "02_mesh" / "coarse" / name
        improved, pop = work / "coarse_improved.msh.h5", work / "improved_inverse_oq_population.json"
        if not (improved.is_file() and pop.is_file() and (work / "mesh_config.json").is_file()):
            continue
        rec = json.loads(pop.read_text(encoding="utf-8-sig"))
        trn = Path(rec.get("transcript", ""))
        if not trn.is_file() or (rec.get("min_oq") is not None and rec["min_oq"] <= 0):
            log(f"  seed {name} skipped (min_oq={rec.get('min_oq')})")
            continue
        cfg = json.loads((work / "mesh_config.json").read_text(encoding="utf-8-sig"))
        cfg.setdefault("fasttrack_size_scale", 1.0)
        cfg.setdefault("fasttrack_recipe", "seed")
        atomic_write_json(work / "mesh_config.json", cfg)
        out.append((name, work, improved, trn))
    return out


def run_level(level, stage_deadline):
    if FM.published(level):
        log(f"{level}: already published (fast-track) -> skip")
        return FM.published(level)
    t0 = time.time()
    level_deadline = min(stage_deadline, t0 + 60 * FP.P2_LEVEL_BUDGET_MIN[level])
    candidates, history = previous_candidates(level), []
    hist_file = WS_ROOT / "02_mesh" / level / "fasttrack_history.json"
    if hist_file.is_file():   # resume after a kill/retry: keep measured counts for the predictor
        try:
            history = json.loads(hist_file.read_text(encoding="utf-8")).get("history", [])
        except ValueError:
            history = []
    done_seeds = {c.get("label", "").replace("seed_", "").replace("_repaired", "") for c in candidates}
    status(level=level, state="running", level_started=now_iso(), resumed_candidates=len(candidates))
    for name, work, mesh, trn in seed_candidates(level):
        if name in done_seeds:
            continue
        gate_or_exit()
        log(f"{level}: evaluating existing candidate {name}")
        try:
            candidates += evaluate(level, work, mesh, trn, "seed_" + name)
        except Exception as exc:
            log(f"  seed {name} evaluation error: {exc}")
        best = sorted(candidates, key=FM.tier_key)[0] if candidates else None
        if best and best["admissible"] and best["quality_tier"] in ("target", "accept"):
            break
    quality_failed = bool(candidates) and not any(c["admissible"] and c["quality_tier"] in ("target", "accept") for c in candidates)
    refs = []   # measured (cells, BL cells, size scale, ideal prisms) used by the cube-law count predictor
    for c in candidates:
        inv = c["inventory"]
        if inv.get("boundary_layer_cells"):
            refs.append(dict(cells=inv["cells"], bl=inv["boundary_layer_cells"], scale=float(c.get("size_scale") or 1.0),
                             ideal=ideal_prisms(level, c.get("prism_scopes") or scopes_for(level, "R1"))))
            break
    # Attempts already made in earlier (killed/retried) runs count toward the cap; one extra
    # attempt is granted only when nothing admissible exists yet.
    limit = FP.P2_MAX_ATTEMPTS[level] + (0 if any(c["admissible"] for c in candidates) else 1)
    for k in range(len(history), max(len(history), limit)):
        best = sorted(candidates, key=FM.tier_key)[0] if candidates else None
        if best and best["admissible"] and best["quality_tier"] in ("target", "accept"):
            break
        remaining_min = (level_deadline - time.time()) / 60.0
        if best and best["admissible"] and remaining_min < ATTEMPT_MIN[level]:
            log(f"{level}: {remaining_min:.0f} min left < one attempt; keeping best admissible candidate")
            break
        if not best or not best["admissible"]:
            if (stage_deadline - time.time()) / 60.0 < 0.6 * ATTEMPT_MIN[level] and k > 0:
                break
        gate_or_exit()
        if level in ATTEMPT_ORDER:
            order = ATTEMPT_ORDER[level]
            recipe = order[min(k, len(order) - 1)]
        else:
            recipe = "R2" if (quality_failed or k >= 1 and history and history[-1].get("quality_failed")) else "R1"
        scale = predict_scale(level, recipe, refs + [h for h in history if h.get("cells")])
        attempt = f"ft_{recipe}_{k + 1}_" + dt.datetime.now().strftime("%m%d_%H%M")
        log(f"{level}: attempt {k + 1}/{FP.P2_MAX_ATTEMPTS[level]} recipe={recipe} size-scale={scale:.3f} -> {attempt}")
        status(level=level, attempt=attempt, recipe=recipe, scale=scale)
        entry = dict(attempt=attempt, recipe=recipe, scale=scale, ideal=ideal_prisms(level, scopes_for(level, recipe)))
        history.append(entry)
        try:
            work = prepare_attempt(level, attempt, scale, recipe)
            raw = work / f"{level}.msh.h5"
            rc, raw_trn = run_fluent(work, work / "mesh.jou", "meshing", f"{level}_{attempt}",
                                     procs=4, silent_stall_min=FP.P2_SILENT_STALL_MIN, max_wall_min=FP.P2_FLUENT_WALL_MIN[level])
            if rc != 0 or not raw.is_file() or raw_trn is None:
                raise RuntimeError(f"volume meshing failed rc={rc}")
            inv = FM.mesh_inventory(raw)
            entry.update(cells=inv["cells"], bl=inv["boundary_layer_cells"])
            log(f"  raw {level}: {inv['cells']:,} cells (BL {inv['boundary_layer_cells']}) window={FP.HARD_WINDOWS[level]}")
            if not FP.in_hard_window(level, inv["cells"]):
                entry["window_miss"] = True
                continue
            gate_or_exit()
            improved = work / f"{level}_improved.msh.h5"
            rc_i, imp_trn = run_fluent(work, work / "improve_raw.jou", "meshing", f"{level}_{attempt}_improve",
                                       procs=4, silent_stall_min=20.0, max_wall_min=IMPROVE_WALL[level])
            mesh, mtrn = (improved, imp_trn) if (rc_i == 0 and improved.is_file() and imp_trn) else (raw, raw_trn)
            gate_or_exit()
            found = evaluate(level, work, mesh, mtrn, attempt)
            candidates += found
            entry["quality_failed"] = not any(c["admissible"] and c["quality_tier"] in ("target", "accept") for c in found)
            quality_failed = entry["quality_failed"]
        except SystemExit:
            raise
        except Exception as exc:
            entry["error"] = f"{exc.__class__.__name__}: {exc}"
            log(f"  attempt error: {entry['error']}\n{traceback.format_exc()[-1500:]}")
        atomic_write_json(WS_ROOT / "02_mesh" / level / "fasttrack_history.json", dict(history=history))
    admissible = sorted([c for c in candidates if c["admissible"]], key=FM.tier_key)
    if not admissible:
        status(level=level, state="failed")
        raise RuntimeError(f"P2 {level}: no admissible candidate after {len(history)} attempts; see logs/p2_fasttrack.log")
    best = admissible[0]
    row = FM.publish(best)
    log(f"{level}: PUBLISHED {best['label']} cells={row['cells']:,} tier={row['quality_tier']} "
        f"minOQ={row['min_orthogonal_quality']} in {(time.time() - t0) / 60:.1f} min")
    status(level=level, state="published", tier=row["quality_tier"])
    return row


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--levels", nargs="+", default=["coarse", "medium", "fine"], choices=["coarse", "medium", "fine"])
    p.add_argument("--deadline-epoch", type=float, default=None)
    a = p.parse_args()
    deadline = a.deadline_epoch or time.time() + 60 * FP.STAGE_HARD_MIN["P2"]
    status(state="running", started=now_iso(), deadline_epoch=deadline)
    gate_or_exit()
    try:
        for level in a.levels:
            run_level(level, deadline)
        if all(FM.published(lv) for lv in FM.LEVELS):
            ladder = FM.publish_ladder()
            log(f"LADDER: passed={ladder['passed']} r32={ladder['r32']:.3f} r21={ladder['r21']:.3f} "
                f"tiers={ladder['quality_tiers']}")
            if not ladder["passed"]:
                status(state="failed", reason="ladder")
                return 3
        status(state="done")
        return 0
    except RuntimeError as exc:
        log(f"P2 FAILED: {exc}")
        status(state="failed", reason=str(exc))
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
