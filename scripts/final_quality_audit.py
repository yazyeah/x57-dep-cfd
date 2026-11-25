"""Independent end-of-run quality audit of the X-57 fast-track results.

Reads only accepted native evidence and grades every user-facing quality criterion:
  PASS  meets the project target, WARN  meets the engineering redline only,
  FAIL  physically unacceptable / missing evidence.
Writes DELIVERABLES/data/final_quality_report.json and DELIVERABLES/final_quality_report.md.
Exit 0 when nothing is FAIL, 5 otherwise. Never modifies any result.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np

from fasttrack_profile import (FORCE_TIERS, GCI_REDLINE_PCT, GCI_TARGET_PCT, MASS_TIERS, ROOT, STRESS_BLUE_AREA_MIN,
                               STRESS_BLUE_BINS, STRESS_MIN_YIELD_FOS, STRESS_SCALE_MAX_MPA, snapshot)

DATA = ROOT / "DELIVERABLES" / "data"
CASES3 = ["coarse_rpm100", "medium_rpm100", "fine_rpm100", "medium_rpm050", "medium_rpm075", "medium_rpm100_noswirl",
          "medium_rpm100_hlp_only", "medium_rpm100_wt_only", "medium_rpm100_alt_swirl", "medium_rpm100_takeoff_v10",
          "medium_rpm100_oge", "medium_rpm100_rke", "medium_opt_hlp_vector10"]
SECTIONS = ["opt2d_01_clean", "opt2d_02_flap15", "opt2d_03_flap30", "opt2d_04_slat_flap30", "opt2d_05_camber_opt"]
ROWS = []


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def add(group, item, grade, value, criterion):
    ROWS.append(dict(group=group, item=item, grade=grade, value=value, criterion=criterion))


def guarded(group, item, fn):
    try:
        fn()
    except Exception as exc:  # missing evidence is itself a finding
        add(group, item, "FAIL", f"{exc.__class__.__name__}: {exc}"[:300], "evidence must exist")


def mesh_audit():
    for lv in ("coarse", "medium", "fine"):
        def one(lv=lv):
            row = read(ROOT / "02_mesh" / lv / "mesh_qa.json")
            tier = row.get("quality_tier")
            grade = {"target": "PASS", "accept": "PASS", "last_resort": "WARN"}.get(tier, "FAIL")
            add("P2 mesh", f"{lv} quality tier", grade,
                dict(tier=tier, cells=row.get("cells"), min_OQ=row.get("min_orthogonal_quality"),
                     poor_cell_fraction=row.get("poor_cell_fraction_oq_below_0p05")),
                "solver min OQ >= 0.01 (Ansys) and <=1% cells OQ<0.05; last_resort = >0 with poor-mesh numerics")
            cov = (row.get("fasttrack_report") or {}).get("bl_coverage")
            add("P2 mesh", f"{lv} prism-layer coverage", "PASS" if cov and cov >= 0.6 else ("WARN" if cov and cov >= 0.3 else "FAIL"),
                cov, "surviving / requested prism cells after stair-stepping: >=0.6 PASS, >=0.3 WARN")
            gap = row.get("cad_gap_audit", {})
            add("P2 mesh", f"{lv} CAD sponson clearance", "PASS" if gap.get("within_tolerance") else "WARN",
                gap.get("max_gap_error_m"), "|gap - CAD| <= 8 mm")
        guarded("P2 mesh", lv, one)

    def ladder():
        lad = read(ROOT / "02_mesh" / "grid_ladder_qa.json")
        grade = "PASS" if lad.get("ratio_target_pass") else ("WARN" if lad.get("passed") else "FAIL")
        add("P2 mesh", "refinement ratios r32/r21", grade, dict(r32=lad.get("r32"), r21=lad.get("r21")),
            "target r32>=1.18, r21>=1.15; hard >=1.10")
    guarded("P2 mesh", "ladder", ladder)


def case_audit():
    rel_std_eng, rel_drift_eng = FORCE_TIERS["engineering"]
    for name in CASES3 + SECTIONS:
        def one(name=name):
            qa = read(ROOT / "03_cases" / name / "iteration_qa.json")
            tier = qa.get("acceptance_tier") or ("strict" if qa.get("passed") else None)
            grade = {"strict": "PASS", "engineering": "PASS", "budget": "WARN"}.get(tier, "FAIL")
            from fasttrack_profile import REQUIRED_CASES
            if name in REQUIRED_CASES and tier not in ("strict", "engineering"):
                grade = "FAIL"   # coursework-brief cases must converge at engineering tier or better
            add("Convergence", f"{name} acceptance tier" + (" [brief-required]" if name in REQUIRED_CASES else " [extension]"), grade,
                dict(tier=tier, final_iteration=qa.get("final_iteration"),
                     total_iterations=(qa.get("fasttrack") or {}).get("total_iterations")),
                "strict/engineering = converged; budget = plateau within 2 %; flagged = FAIL")
            forces = qa.get("forces_full_aircraft") or qa.get("forces_per_span") or {}
            lift = forces.get("L_air") or forces.get("section-lift")
            if lift:
                rs, rd = lift.get("relative_std"), lift.get("relative_drift")
                ok = rs is not None and rd is not None and rs < rel_std_eng and rd < rel_drift_eng
                warn = rs is not None and rd is not None and rs < FORCE_TIERS["budget"][0] and rd < FORCE_TIERS["budget"][1]
                add("Lift stability", f"{name} lift plateau (last 200 it.)", "PASS" if ok else ("WARN" if warn else "FAIL"),
                    dict(mean_N=lift.get("mean_N"), rel_std=rs, rel_drift=rd), "rel. std < 1 %, drift < 0.5 %")
            mb = (qa.get("mass_balance") or {}).get("imbalance_fraction")
            if mb is not None:
                add("Conservation", f"{name} mass imbalance", "PASS" if mb < MASS_TIERS["engineering"]
                    else ("WARN" if mb < MASS_TIERS["budget"] else "FAIL"), mb, "< 1 % (strict 0.5 %)")
            disks = qa.get("disk_integrals")
            if disks:
                err = max(max(d.get("thrust_error_fraction") or 0, d.get("torque_error_fraction") or 0) for d in disks)
                add("Actuator disks", f"{name} max disk integral error", "PASS" if err < 0.01 else "FAIL", err, "< 1 %")
        guarded("Convergence", name, one)


def gci_audit():
    def one():
        gci = read(DATA / "asme_vv20_gci.json")
        for key in ("L_air_N", "D_air_N", "C_L", "C_D"):
            if key not in gci:
                continue
            u = gci[key].get("reported_fine_percent_uncertainty")
            grade = "PASS" if u is not None and u < GCI_TARGET_PCT else ("WARN" if u is not None and u < GCI_REDLINE_PCT else "FAIL")
            add("Mesh convergence", f"GCI fine {key}", grade,
                dict(U_fine_pct=u, convergence=gci[key].get("convergence_type"), p=gci[key].get("observed_order")),
                "fine-grid uncertainty < 3 % target, < 5 % redline (Celik 2008)")
    guarded("Mesh convergence", "GCI", one)

    def yplus():
        p5 = read(ROOT / "logs" / "P5_quantitative_audit.json")
        wy = p5.get("wing_yplus") or {}
        ok = 0.5 <= (wy.get("mean") or -1) <= 1.2 and (wy.get("p95") or 99) < 2.5
        add("Wall resolution", "fine wing y+ (area-weighted)", "PASS" if ok else "WARN",
            dict(mean=wy.get("mean"), p95=wy.get("p95")), "mean 0.5-1.2, p95 < 2.5 (SST all-y+ treatment otherwise)")
    guarded("Wall resolution", "y+", yplus)


def stress_audit():
    def one():
        from native_mapdl_deck import fields_for_comparison
        struct = ROOT / "03_cases" / "fsi_structural"
        with np.load(struct / "models" / "fine" / "shell_mesh.npz") as m:
            sect, area = m["element_section"], m["area_m2"]
        with np.load(struct / "fine_struct__fine_rpm100" / "shell_fields.npz") as d:
            fields = {k: d[k] for k in d.files}
        vm = fields_for_comparison(fields)["VMMPA"]
        skin = np.isin(sect, np.arange(5))
        band = STRESS_SCALE_MAX_MPA / 9.0 * STRESS_BLUE_BINS
        frac = float(area[skin & (vm < band)].sum() / area[skin].sum())
        fos = float(np.min(fields["safety_factor"][skin]))
        add("Structural stress", f"skin area in the LOWEST colour band (render17/18, allowable scale 0-{STRESS_SCALE_MAX_MPA:.0f} MPa)",
            "PASS" if frac >= STRESS_BLUE_AREA_MIN else "FAIL", dict(area_fraction=frac, blue_below_MPa=band,
            peak_vm_MPa=float(vm[skin].max()), p99_vm_MPa=float(np.quantile(vm[skin], .99))),
            f">= {100*STRESS_BLUE_AREA_MIN:.0f} % of exterior skin area below {band:.1f} MPa")
        add("Structural stress", "minimum yield factor of safety", "PASS" if fos >= STRESS_MIN_YIELD_FOS else "FAIL",
            fos, f">= {STRESS_MIN_YIELD_FOS} (503 MPa yield)")
        study = read(DATA / "fsi_structural_stress.json")
        add("Structural stress", "structural mesh convergence",
            "PASS" if study.get("stress_mesh_QA_target_3pct_passed") else ("WARN" if study.get("stress_mesh_QA_passed") else "FAIL"),
            {k: v.get("reported_fine_percent_uncertainty") for k, v in study.get("shell_GCI", {}).items()},
            "smooth metrics < 10 % (engineering), all metrics < 3 % (target)")
    guarded("Structural stress", "FSI", one)


def other_audit():
    def rpm():
        p6 = read(ROOT / "logs" / "P6_quantitative_audit.json")
        fits = p6.get("squared_speed_fits", {})
        r2 = {k: v.get("r_squared_centered") for k, v in fits.items()}
        ok = all(v is not None and v >= 0.99 for v in r2.values()) and r2
        add("Physics checks", "RPM^2 scaling R^2", "PASS" if ok else "WARN", r2, ">= 0.99 (target 0.999)")
    guarded("Physics checks", "rpm", rpm)

    def zero():
        z = read(ROOT / "03_cases" / "medium_rpm000" / "static_equilibrium_audit.json")
        add("Physics checks", "zero-RPM static equilibrium", "PASS" if z.get("passed") else "FAIL", z.get("checks"), "all exact")
    guarded("Physics checks", "zero", zero)


def integrity_audit():
    def one():
        import hashlib
        from fasttrack_profile import PROTECTED_FILES
        base = read(ROOT / "SUPERVISOR" / "fasttrack_integrity.json")["sha256"]
        changed = [rel for rel in PROTECTED_FILES
                   if base.get(rel) != hashlib.sha256((ROOT / rel).read_bytes()).hexdigest()]
        add("Integrity", "acceptance thresholds unchanged since first launch", "FAIL" if changed else "PASS",
            changed or "all protected files match", "SHA-256 of fasttrack_profile/assess/verify/audit scripts")
    guarded("Integrity", "protected files", one)


def main():
    integrity_audit()
    mesh_audit()
    case_audit()
    gci_audit()
    stress_audit()
    other_audit()
    counts = {g: sum(1 for r in ROWS if r["grade"] == g) for g in ("PASS", "WARN", "FAIL")}
    report = dict(summary=counts, overall="FAIL" if counts["FAIL"] else ("PASS_WITH_WARNINGS" if counts["WARN"] else "PASS"),
                  rows=ROWS, profile=snapshot())
    DATA.mkdir(parents=True, exist_ok=True)
    (DATA / "final_quality_report.json").write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    lines = ["# X-57 final quality report", "", f"Overall: **{report['overall']}**  (PASS {counts['PASS']}, "
             f"WARN {counts['WARN']}, FAIL {counts['FAIL']})", "", "| Group | Item | Grade | Value | Criterion |",
             "|---|---|---|---|---|"]
    for r in ROWS:
        lines.append(f"| {r['group']} | {r['item']} | {r['grade']} | {json.dumps(r['value'], default=str)[:160]} | {r['criterion']} |")
    (ROOT / "DELIVERABLES" / "final_quality_report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps(dict(overall=report["overall"], summary=counts,
                          fails=[f"{r['group']}: {r['item']} -> {r['value']}" for r in ROWS if r["grade"] == "FAIL"]),
                     indent=2, default=str))
    return 5 if counts["FAIL"] else 0


if __name__ == "__main__":
    sys.exit(main())
