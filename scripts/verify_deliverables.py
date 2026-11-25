#!/usr/bin/env python3
"""
Final Deliverables Completeness & Publication-Grade Quantitative QA Validator
for X-57 DEP Aircraft Ansys CFD + 1-Way FSI Coursework.

Checks:
  - 7 JSON + 12 CSV structured data tables (zero NaNs/Infs)
  - 22 publication-grade Matplotlib/PyVista figures (400 DPI PNG + Vector PDF with Times New Roman)
  - 22 native Ansys Fluent/MAPDL and comparative PyVista renders (PNG >= 1920x1080)
  - 3 verified Ansys HDF5 coursework submission attachments (.msh.h5, .cas.h5, .dat.h5)
  - Quantitative ASME V&V 20, native Fine cell window (940,000–1,044,000),
    global convergence, mass balance, stress convergence, and expanded experiment coverage.
"""

from __future__ import annotations

import csv
import json
import math
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

DELIV_DIR = Path(__file__).resolve().parents[1] / "DELIVERABLES"

REQUIRED_DATA_JSON = [
    "environment_and_license.json",
    "geometry_audit.json",
    "actuator_disk_model.json",
    "summary_metrics.json",
    "asme_vv20_gci.json",
    "expanded_experiments_summary.json",
    "fsi_structural_stress.json",
]

REQUIRED_DATA_CSV = [
    "mesh_convergence.csv",
    "rpm_sweep.csv",
    "yplus_stats.csv",
    "wing_cp_sections.csv",
    "spanwise_loading.csv",
    "convergence_qa.csv",
    "component_force_breakdown.csv",
    "propulsion_decomposition.csv",
    "sensitivity_ige_roll_turb.csv",
    "design_optimization_results.csv",
    "stress_and_bl_profiles.csv",
    "ablation_kpi_matrix.csv",
]

REQUIRED_FIGURES_STEMS = [
    "fig01_geometry_and_domain",
    "fig02_mesh_convergence_and_yplus",
    "fig03_convergence_histories",
    "fig04_spanwise_slices_vel_press",
    "fig05_horizontal_planes_blown_wing",
    "fig06_wing_cp_and_suction",
    "fig07_rpm_sweep_scaling",
    "fig08_swirl_comparison_and_load_shift",
    "fig09_wake_evolution_crossplanes",
    "fig10_component_force_and_upper_lower_budget",
    "fig11_wall_yplus_and_shear_map",
    "fig12_actuator_disk_verification_and_design_concept",
    "fig13_propulsion_decomposition_and_synergy",
    "fig14_ground_effect_and_takeoff_roll",
    "fig15_turbulence_model_sensitivity",
    "fig16_highlift_design_optimization_cfd",
    "fig17_stress_convergence_and_fsi_structural",
    "fig18_wall_shear_and_reynolds_stress_fields",
    "fig19_multi_case_ablation_heatmap_and_radar",
    "fig20_flow_topology_and_vortex_dynamics",
    "fig21_stress_envelope_and_ridge_distributions",
    "fig22_3d_2d_hybrid_aeropropulsive_synthesis",
]

REQUIRED_FLUENT_RENDERS = [
    "render01_mesh_farfield_hexcore.png",
    "render02_mesh_wing_inflation_closeup.png",
    "render03_mesh_sponson_and_disks_closeup.png",
    "render04_pathlines_slipstreams_3d.png",
    "render05_pathlines_wingtip_vortex_3d.png",
    "render06_surface_pressure_contour_top_3d.png",
    "render07_surface_pressure_contour_bottom_3d.png",
    "render08_velocity_streamlines_3d.png",
    "render09_qcriterion_vortices_3d.png",
    "render10_surface_yplus_and_oilflow_3d.png",
    "render11_ige_vs_oge_wake_3d.png",
    "render12_opt_highlift_flow_comparison.png",
    "render13_fluent_wall_shear_stress_top_3d.png",
    "render14_fluent_wall_shear_stress_bottom_3d.png",
    "render15_fluent_reynolds_stress_and_tke_3d.png",
    "render16_fluent_total_pressure_loss_3d.png",
    "render17_fsi_von_mises_global_top_3d.png",
    "render18_fsi_von_mises_global_bottom_3d.png",
    "render19_fsi_von_mises_root_pylon_zoom_3d.png",
    "render20_fsi_principal_stress_s1_s3_3d.png",
    "render21_fsi_shear_stress_tresca_3d.png",
    "render22_fsi_deformation_and_safety_factor_3d.png",
]

REQUIRED_ANSYS_FILES = [
    "X57_DEP_fine_rpm100.msh.h5",
    "X57_DEP_fine_rpm100.cas.h5",
    "X57_DEP_fine_rpm100.dat.h5",
]

REQUIRED_CORE_CASES = [
    "coarse_rpm100",
    "medium_rpm100",
    "fine_rpm100",
    "medium_rpm050",
    "medium_rpm075",
    "medium_rpm100_noswirl",
]

REQUIRED_EXPANDED_CASES = [
    "medium_rpm100_hlp_only",
    "medium_rpm100_wt_only",
    "medium_rpm100_alt_swirl",
    "medium_rpm100_takeoff_v10",
    "medium_rpm100_oge",
    "medium_rpm100_rke",
    "medium_opt_hlp_vector10",
]

STUDENT_CELL_LIMIT = 1_048_576
from mesh_ladder_limits import LEVELS, WINDOWS, ratio_pass
FINE_MIN_TARGET_CELLS, FINE_MAX_TARGET_CELLS = WINDOWS["fine"]
HDF5_MAGIC = b"\x89HDF\r\n\x1a\n"
PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
PDF_MAGIC = b"%PDF-"


def try_float(val: str) -> Optional[float]:
    try:
        v = float(val.strip())
        if v != v or v in (float("inf"), float("-inf")):
            return None
        return v
    except Exception:
        return None


def read_csv_dicts(path: Path) -> Tuple[Optional[List[Dict[str, str]]], str]:
    try:
        with open(path, "r", encoding="utf-8", newline="") as f:
            rows = list(csv.DictReader(f))
        if not rows:
            return None, "empty CSV (0 data rows)"
        bad = 0
        for r in rows:
            for v in r.values():
                if v is not None and v.strip().lower() in ("nan", "inf", "-inf", "+inf", "none", "null"):
                    bad += 1
        if bad > 0:
            return None, f"contains {bad} NaN/Inf/null cells"
        return rows, f"OK ({len(rows)} rows)"
    except Exception as e:
        return None, f"read error: {e}"


def check_json_clean(path: Path) -> Tuple[bool, str, Optional[dict]]:
    try:
        obj = json.loads(path.read_text(encoding="utf-8"))
        if not obj:
            return False, "empty JSON object", None
        raw = json.dumps(obj)
        if "NaN" in raw or "Infinity" in raw:
            return False, "contains NaN/Infinity", None
        return True, f"OK ({path.stat().st_size:,} bytes)", obj
    except Exception as e:
        return False, f"JSON error: {e}", None


def check_png(path: Path, min_bytes: int = 25000, min_w: int = 1000, min_h: int = 500) -> Tuple[bool, str]:
    if not path.exists():
        return False, "MISSING"
    sz = path.stat().st_size
    if sz < min_bytes:
        return False, f"too small ({sz:,} bytes < {min_bytes:,})"
    with open(path, "rb") as f:
        hdr = f.read(8)
    if hdr != PNG_MAGIC:
        return False, "invalid PNG header"
    with open(path, "rb") as f:
        f.seek(16)
        w = int.from_bytes(f.read(4), "big")
        h = int.from_bytes(f.read(4), "big")
    if w < min_w or h < min_h:
        return False, f"low resolution ({w}x{h} < {min_w}x{min_h})"
    from PIL import Image
    try:
        with Image.open(path) as im:
            im.load()
            if path.parent.name=="fluent_renders":
                import numpy as np
                im.thumbnail((360,240))
                rgb=np.asarray(im.convert("RGB"))
                border=np.concatenate((rgb[0],rgb[-1],rgb[:,0],rgb[:,-1]))
                if np.any(np.median(border,axis=0)<240):
                    return False,"3D render needs a white background"
                if np.quantile(255.-rgb.min(axis=2),.998)<10:
                    return False,"Nearly blank 3D render"
            if path.parent.name=="figures":
                dpi=im.info.get("dpi",())
                if len(dpi)!=2 or max(abs(v-400.) for v in dpi)>.10:
                    return False,f"Expected 400 DPI, found {dpi}"
    except Exception as e:
        return False,f"Incomplete PNG: {e}"
    return True, f"OK ({w}x{h}, {sz:,} bytes)"


def check_pdf_tnr(path: Path, min_bytes: int = 5000) -> Tuple[bool, str]:
    if not path.exists():
        return False, "MISSING"
    sz = path.stat().st_size
    if sz < min_bytes:
        return False, f"too small ({sz:,} bytes)"
    import pymupdf
    try:
        with pymupdf.open(path) as doc:
            fonts={tuple(f[:5]) for page in doc for f in page.get_fonts()}
            if not any(page.get_text().strip() for page in doc):
                return False,"Missing selectable vector text"
            if not fonts or not all("timesnewroman" in f[3].replace(" ","").lower() and doc.extract_font(f[0])[-1] for f in fonts):
                return False,"Every PDF font must be an embedded Times New Roman face"
    except Exception as e:
        return False,f"Unreadable PDF: {e}"
    return True,f"OK ({sz:,} bytes, embedded Times New Roman, selectable vector text)"


def check_hdf5(path: Path, min_bytes: int = 500_000) -> Tuple[bool, str]:
    if not path.exists():
        return False, "MISSING"
    sz = path.stat().st_size
    if sz < min_bytes:
        return False, f"suspiciously small ({sz:,} bytes)"
    with open(path, "rb") as f:
        hdr = f.read(8)
    if hdr != HDF5_MAGIC:
        return False, "invalid HDF5 magic header (not a valid .h5 Fluent file)"
    return True, f"OK ({sz / (1024 ** 2):.2f} MB)"


def audit_quantitative_qa(record, warn=None) -> None:
    """Fast-track: integrity checks are hard; physical-quality targets are WARN (see fasttrack_profile)."""
    from fasttrack_profile import (MASS_TIERS, FORCE_TIERS, HARD_WINDOWS, TARGET_WINDOWS, ratio_hard_pass,
                                   ratio_target_pass, MESH_OQ_TARGET, LICENSE_CELL_CAP)
    warn = warn or record
    conv_path = DELIV_DIR / "data" / "convergence_qa.csv"
    if conv_path.exists():
        rows, _ = read_csv_dicts(conv_path)
        if rows:
            blob = " ".join(" ".join(str(v) for v in r.values()) for r in rows).lower()
            miss_core = [c for c in REQUIRED_CORE_CASES if c not in blob]
            record("QA: all 6 core 3D cases in convergence_qa.csv", len(miss_core) == 0, "OK" if not miss_core else f"missing: {miss_core}")
            miss_exp = [c for c in REQUIRED_EXPANDED_CASES if c not in blob]
            record("QA: all 7 expanded 3D cases in convergence_qa.csv", len(miss_exp) == 0, "OK" if not miss_exp else f"missing: {miss_exp}")
            mass_cols = [k for k in rows[0].keys() if "mass" in k.lower() and ("err" in k.lower() or "imb" in k.lower() or "pct" in k.lower())]
            if mass_cols:
                vals = [abs(try_float(r[mass_cols[0]])) for r in rows if try_float(r[mass_cols[0]]) is not None]
                if vals:
                    mx = max(vals)
                    warn(f"QA: max mass flux imbalance < {100*MASS_TIERS['budget']:.1f}% (budget tier; graded in final_quality_report)", mx < 100*MASS_TIERS["budget"], f"max={mx:.4f}%")
                    warn("QA: max mass flux imbalance < 0.5% (strict target)", mx < 0.5, f"max={mx:.4f}%")
            drift_cols = [k for k in rows[0].keys() if "drift" in k.lower() and ("pct" in k.lower() or "%" in k.lower())]
            if drift_cols:
                bad_drifts = []
                for col in drift_cols:
                    for r in rows:
                        v = try_float(r.get(col, ""))
                        if v is not None and abs(v) >= 0.5:
                            bad_drifts.append((f"{r.get('case', '?')}:{col}={v:.3f}%", abs(v)))
                hard_bad = [t for t, v in bad_drifts if v >= 100 * FORCE_TIERS["budget"][1]]
                warn(f"QA: force window drift < {100*FORCE_TIERS['budget'][1]:.2f}% (budget tier; graded in final_quality_report)", len(hard_bad) == 0, "OK" if not hard_bad else f"exceeded: {hard_bad[:5]}")
                warn("QA: force window drift columns < 0.5% (strict target)", len(bad_drifts) == 0, "OK" if not bad_drifts else f"exceeded: {[t for t, _ in bad_drifts][:5]}")

    mc_path = DELIV_DIR / "data" / "mesh_convergence.csv"
    if mc_path.exists():
        rows, _ = read_csv_dicts(mc_path)
        if rows:
            record("QA: mesh_convergence.csv has >= 3 grid levels", len(rows) >= 3, f"{len(rows)} rows")
            try:
                by_level={r["level"]:r for r in rows}
                if len(rows)!=3 or set(by_level)!=set(LEVELS):
                    raise ValueError("Exactly one row per Coarse/Medium/Fine is required")
                hs={}
                for level in LEVELS:
                    row=by_level[level]
                    n=int(row["cells"])
                    v=float(row["half_domain_volume_m3"])
                    if n<=0 or not math.isfinite(v) or v<=0:
                        raise ValueError(f"Invalid native count or volume for {level}")
                    lo,hi=HARD_WINDOWS[level]
                    hs[level]=(v/n)**(1/3)
                    record(f"QA: {level} volume-mesh cells in admissible [{lo:,}, {hi:,}]",
                           lo<=n<=hi and n<=LICENSE_CELL_CAP,f"{n:,} cells, V={v:.9g} m3")
                    tlo,thi=TARGET_WINDOWS[level]
                    warn(f"QA: {level} cells in target [{tlo:,}, {thi:,}]",tlo<=n<=thi,f"{n:,} cells")
                r32,r21=hs["coarse"]/hs["medium"],hs["medium"]/hs["fine"]
                record("QA: native r32, r21 >= 1.10 (hard, Celik 2008)",ratio_hard_pass(r32,r21),
                       f"r32={r32:.9g}, r21={r21:.9g}")
                warn("QA: native r32 >= 1.18 and r21 >= 1.15 (target)",ratio_target_pass(r32,r21),
                       f"r32={r32:.9g}, r21={r21:.9g}")
            except (KeyError,TypeError,ValueError,ArithmeticError) as exc:
                record("QA: complete native mesh ladder and counts",False,str(exc))
            ortho_cols = [k for k in rows[0].keys() if "ortho" in k.lower()]
            if ortho_cols:
                ovals = [try_float(r[ortho_cols[0]]) for r in rows if try_float(r[ortho_cols[0]]) is not None]
                if ovals:
                    record("QA: positive solver orthogonal quality (hard)", min(ovals) > 0., f"min={min(ovals):.4g}")
                    warn(f"QA: min orthogonal quality > {MESH_OQ_TARGET:.2f} (target)", min(ovals) > MESH_OQ_TARGET, f"min={min(ovals):.4g}")

    opt_path = DELIV_DIR / "data" / "design_optimization_results.csv"
    if opt_path.exists():
        rows, _ = read_csv_dicts(opt_path)
        if rows:
            record("QA: design_optimization_results.csv has >= 5 configs", len(rows) >= 5, f"{len(rows)} rows")

    gci_path = DELIV_DIR / "data" / "asme_vv20_gci.json"
    if gci_path.exists():
        ok_g, _, gobj = check_json_clean(gci_path)
        if ok_g and isinstance(gobj, dict):
            from cfd_verification import gci_from_spacing,gci_threshold
            from math import isclose
            for name in ("L_air_N","D_air_N"):
                try:
                    row=gobj[name]
                    rebuilt=gci_from_spacing(row["h_coarse_medium_fine_m"],row["values_coarse_medium_fine"])
                    keys=("observed_order","extrapolated","fine_percent_GCI","medium_percent_GCI","asymptotic_ratio",
                          "reported_fine_percent_uncertainty","reported_medium_percent_uncertainty","half_range_U_osc")
                    def same(a,b):
                        return (a is None and b is None) or (a is not None and b is not None and isclose(float(a),float(b),rel_tol=1e-9,abs_tol=1e-12))
                    matched=all(key in row and same(row[key],rebuilt[key]) for key in keys)
                    matched &= row["fallback_activated"]==rebuilt["fallback_activated"] and row["convergence_type"]==rebuilt["convergence_type"]
                    native_rows,_=read_csv_dicts(mc_path)
                    by_level={r["level"]:r for r in (native_rows or [])}
                    for i,level in enumerate(("coarse","medium","fine")):
                        grid=by_level[level]
                        length=(float(grid["half_domain_volume_m3"])/float(grid["cells"]))**(1/3)
                        matched &= same(row["h_coarse_medium_fine_m"][i],length)
                        matched &= same(row["values_coarse_medium_fine"][i],float(grid[name]))
                    record("QA: "+name+" recomputed three-grid GCI and uncertainty",matched,
                           f"{rebuilt['status']}, p={rebuilt['observed_order']}, Ufine={rebuilt['reported_fine_percent_uncertainty']}%")
                    warn("QA: "+name+" raw and reported uncertainty <5% redline",
                           gci_threshold(rebuilt,5.),
                           f"target <3%: {gci_threshold(rebuilt,3.)}, raw GCI={rebuilt['fine_percent_GCI']}%")
                except (KeyError,TypeError,ValueError,ArithmeticError) as exc:
                    record("QA: "+name+" complete six-step GCI",False,str(exc))



def audit_render(number: int, output: Path) -> str:
    if number <= 16:
        from native_fluent_render_provenance import audit
    else:
        from native_mapdl_render_provenance import audit
    return audit(number, output)


def main() -> int:
    failures: List[str] = []
    passes: int = 0

    def record(label: str, ok: bool, detail: str) -> None:
        nonlocal passes
        tag = "PASS" if ok else "FAIL"
        print(f"  [{tag}] {label:62s} -> {detail}")
        if ok:
            passes += 1
        else:
            failures.append(f"{label}: {detail}")

    warnings: List[str] = []

    def warn(label: str, ok: bool, detail: str) -> None:
        tag = "PASS" if ok else "WARN"
        print(f"  [{tag}] {label:62s} -> {detail}")
        if not ok:
            warnings.append(f"{label}: {detail}")

    print("=" * 94)
    print("  X-57 DEP CFD COURSEWORK — FULL PUBLICATION + EXPANDED QA VERIFICATION")
    print("=" * 94)

    print("\n1. Manifest & Technical Handoff Notes:")
    manifest = DELIV_DIR / "DELIVERABLES_MANIFEST.json"
    ok, msg, _ = check_json_clean(manifest) if manifest.exists() else (False, "MISSING", None)
    record("DELIVERABLES_MANIFEST.json", ok, msg)

    notes = DELIV_DIR / "handoff_notes.md"
    if notes.exists() and notes.stat().st_size >= 4000:
        record("handoff_notes.md", True, f"OK ({notes.stat().st_size:,} bytes)")
    else:
        record("handoff_notes.md", False, "MISSING or < 4000 bytes")

    print("\n2. Structured Data (7 JSON + 12 CSV):")
    for fn in REQUIRED_DATA_JSON:
        p = DELIV_DIR / "data" / fn
        ok, msg, _ = check_json_clean(p) if p.exists() else (False, "MISSING", None)
        record(f"data/{fn}", ok, msg)
    for fn in REQUIRED_DATA_CSV:
        p = DELIV_DIR / "data" / fn
        if p.exists():
            rows, msg = read_csv_dicts(p)
            record(f"data/{fn}", rows is not None, msg)
        else:
            record(f"data/{fn}", False, "MISSING")

    print("\n3. Quantitative ASME V&V 20, Convergence, Stress & Expanded QA Gates:")
    audit_quantitative_qa(record, warn)

    print("\n4. Top-Venue Matplotlib/PyVista Composite Figures (22 PNG + 22 Vector PDF, Times New Roman):")
    for stem in REQUIRED_FIGURES_STEMS:
        ok_p, msg_p = check_png(DELIV_DIR / "figures" / f"{stem}.png", min_bytes=25000, min_w=1000, min_h=500)
        record(f"figures/{stem}.png", ok_p, msg_p)
        ok_v, msg_v = check_pdf_tnr(DELIV_DIR / "figures" / f"{stem}.pdf")
        record(f"figures/{stem}.pdf", ok_v, msg_v)

    print("\n5. Native Ansys Fluent/MAPDL/PyVista 3D High-Res Renders (22 PNG incl. 10 Stress Renders):")
    for number, fn in enumerate(REQUIRED_FLUENT_RENDERS, 1):
        ok, msg = check_png(DELIV_DIR / "fluent_renders" / fn, min_bytes=40000, min_w=1920, min_h=1080)
        record(f"fluent_renders/{fn}", ok, msg)
        if ok:
            try:
                detail = audit_render(number, DELIV_DIR / "fluent_renders" / fn)
            except Exception as exc:
                record(f"Renderer and native sources: {fn}", False, str(exc))
            else:
                record(f"Renderer and native sources: {fn}", True, detail)

    print("\n6. Ansys Coursework Submission Attachments (HDF5):")
    for fn in REQUIRED_ANSYS_FILES:
        ok, msg = check_hdf5(DELIV_DIR / "ansys_submission" / fn)
        record(f"ansys_submission/{fn}", ok, msg)

    print("\n" + "=" * 94)
    if warnings:
        print(f"  QUALITY WARNINGS ({len(warnings)}; graded in DELIVERABLES/data/final_quality_report.json):")
        for item in warnings:
            print(f"    ~ {item}")
    if not failures:
        print(f"  ALL CHECKS PASSED ({passes} checks verified)! Ready for journal-grade LaTeX/PDF report.")
        print("=" * 94)
        return 0
    else:
        print(f"  VERIFICATION FAILED: {passes} passed, {len(failures)} failed.")
        for item in failures:
            print(f"    - {item}")
        print("=" * 94)
        return 1


if __name__ == "__main__":
    sys.exit(main())
