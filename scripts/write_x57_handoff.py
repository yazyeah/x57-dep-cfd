"""Write the results index and numerical answers for the coursework report author."""
from pathlib import Path

import pandas as pd
from compare_x57_cases import ROOT,BASE,VECTOR,ZERO,read_json
from control_gate import atomic_write_text

D=ROOT/"DELIVERABLES"
START="<!-- BEGIN VERIFIED COURSEWORK RESULTS -->"
END="<!-- END VERIFIED COURSEWORK RESULTS -->"


def write():
    data=D/"data"
    summary=read_json(data/"summary_metrics.json")
    experiments=read_json(data/"expanded_experiments_summary.json")
    gci=read_json(data/"asme_vv20_gci.json")
    structure=read_json(data/"fsi_structural_stress.json")
    loads=summary["full_aircraft_forces_N"]
    rpm=pd.read_csv(data/"rpm_sweep.csv").set_index("case")
    nominal=rpm.loc[BASE];zero=rpm.loc[ZERO]
    suction=summary["peak_suction"]
    xyz=suction["face_centroid_m"]
    changes=summary["swirl_span_partition"]["full_symmetric_delta_by_region_N"]
    shape=pd.read_csv(data/"design_optimization_results.csv")
    section=shape[shape.dimension=="2D"]
    best=section.loc[section.delta_C_L.idxmax()]
    vec=shape.loc[shape.case==VECTOR].iloc[0]
    grids=pd.read_csv(data/"mesh_convergence.csv").set_index("level")
    walls=pd.read_csv(data/"yplus_stats.csv")
    wing=walls[(walls.case=="fine_rpm100")&(walls.component=="wall_wing")].iloc[0]
    lift_delta=nominal.L_air_N-zero.L_air_N
    ref=read_json(data/"actuator_disk_model.json")
    shell=structure["structural_mesh_study_fixed_fine_CFD_loads"][-1]
    text=[
        "## Verified coursework results",
        "",
        f"The nominal Fine solution gives a full-aircraft vertical airframe force of **{loads['L_air']:.3f} N** and an airframe drag of **{loads['D_air']:.3f} N**. Positive vertical force points upward. The wing contributes {loads['L_wing']:.3f} N. The measured gross static thrust is {loads['T_gross']:.3f} N. The axial force available after airframe drag is {loads['T_net']:.3f} N. [Force summary](data/summary_metrics.json)",
        "",
        f"On a matched Medium mesh, the signed static lift increment between unpowered equilibrium and nominal powered operation is **{lift_delta:+.3f} N**. The endpoints are {zero.L_air_N:.3f} N and {nominal.L_air_N:.3f} N. The through-origin square-speed fits have centered R² of {summary['rpm_fits']['delta_L_static_N']['r_squared_centered']:.6f} for lift increment and {summary['rpm_fits']['D_air_N']['r_squared_centered']:.6f} for drag. [RPM sweep](data/rpm_sweep.csv)",
        "",
        "### Conditions and method",
        "",
        "The baseline represents the start of taxiing at sea level and zero free-stream speed. Fluent uses ideal-gas air at 101325 Pa and 288.15 K, with a dynamic viscosity of 1.789 × 10⁻⁵ Pa s. Each wing carries six 5400 RPM high-lift propellers and one 2700 RPM wingtip propeller. Seven annular volume sources on the starboard half-model impose calibrated axial thrust and swirl. The symmetry plane represents the port half. The stationary runway and external pressure boundaries represent the static ground condition. The nominal turbulence closure is k–ω SST. Mesh and solver settings are preserved in the native submission.",
        "",
        f"The static coefficient reference uses disk-induced dynamic pressure {summary['q_ref_Pa']:.5g} Pa and full wing area {summary['S_ref_m2']:.5g} m². On this convention the Fine solution gives C_L = {summary['C_L']:.6f} and C_D = {summary['C_D']:.6f}. [Actuator inputs and native disk integrals](data/actuator_disk_model.json)",
        "",
        "### Numerical verification",
        "",
        "| Grid | Fluid cells | Minimum orthogonal quality | C_L | C_D |",
        "|---|---:|---:|---:|---:|",
    ]
    for lv,row in grids.iterrows():
        text.append(f"| {lv} | {int(row.cells):,} | {row.min_orthogonal_quality:.4f} | {row.C_L:.6f} | {row.C_D:.6f} |")
    text+=["",
        f"Fine-grid wing y⁺ is {wing['mean']:.3f} by area-weighted mean and {wing.p95:.3f} at P95. Fine-grid GCI is {gci['L_air_N']['fine_percent_GCI']:.3f}% for vertical force and {gci['D_air_N']['fine_percent_GCI']:.3f}% for drag. The documented uncertainty bound is {gci['L_air_N']['reported_fine_percent_uncertainty']:.3f}% and {gci['D_air_N']['reported_fine_percent_uncertainty']:.3f}%, respectively. [Mesh and GCI](data/asme_vv20_gci.json) · [Convergence history](data/convergence_qa.csv)",
        "",
        "### Suction and swirl",
        "",
        f"The lowest Fine-grid wing-face pressure is {suction['p_gauge_Pa']:.3f} Pa gauge, C_p = {suction['Cp']:.6f}. The starboard face centroid is ({xyz[0]:.5f}, {xyz[1]:.5f}, {xyz[2]:.5f}) m, at 2z/b = {suction['span_fraction']:.5f} and x/c = {suction['chord_fraction']:.5f}. The same-mesh swirl ON minus OFF change in full-wing lift is {changes['inboard_HLP']:+.3f} N over the inboard segment and {changes['outboard_wingtip']:+.3f} N over the tip segment. The boundary is the inboard edge of the wingtip disk. [Spanwise loading](data/spanwise_loading.csv) · [Wing pressure sections](data/wing_cp_sections.csv)",
        "",
        "### Design and stress interpretation",
        "",
        f"Among the five computed section designs the maximum change in section lift coefficient is {best.delta_C_L:+.6f} for {best.label}, with ΔC_D = {best.delta_C_D:+.6f}. All section comparisons use the HLP-3 slipstream from the accepted Fine solution and the clean blown section as baseline. The three-dimensional 10° HLP-vector change gives ΔC_L = {vec.delta_C_L:+.6f} and ΔC_D = {vec.delta_C_D:+.6f} against the nominal Medium aircraft. The dimensional section forces are reported per unit span. [Design comparisons](data/design_optimization_results.csv) · [Eighteen-case study](data/expanded_experiments_summary.json)",
        "",
        f"The structural calculation uses static one-way pressure and shear transfer into equivalent SHELL181 component models. Material, shell thicknesses, joint representation and supports are modeled assumptions. Peak element-average von Mises stress is {shell['peak_element_average_top_or_bottom_von_mises_Pa']/1.e6:.4g} MPa. The area-weighted 99th percentile is {shell['area_weighted_p99_von_mises_Pa']/1.e6:.4g} MPa, the nominal yield safety factor is {shell['linear_elastic_nominal_yield_ratio']:.4g}, and the mean wingtip patch displacement magnitude is {1.e3*shell['wingtip_patch_mean_displacement_magnitude_m']:.4g} mm. Structural discretization and CFD-load refinement studies passed their recorded 3% gates. [Structural convergence and assumptions](data/fsi_structural_stress.json) · Each stress CSV row describes one native sample. The named quantity, unit and value give its principal observable. The sample_fields_json column contains the other source-specific measurements, including both shell surfaces, location and sampling identifiers. [Stress fields](data/stress_and_bl_profiles.csv)",
        "",
        "The report author can use Figures 2–3 for mesh and force convergence, 4–11 for native flow and surface results, 12–16 for propulsion and design comparisons, and 17–22 for fluid and structural stress, flow topology and the combined design assessment. Native 3D views 4–5 show the propeller slipstreams and wingtip vortex paths. Views 6–8 show top and bottom pressure and velocity streamlines. [Figure directory](figures/) · [Native 3D views](fluent_renders/) · [Reloadable Fluent attachments](ansys_submission/)",
        "",
        "### Model and verification sources",
        "",
        f"The HLP calibration uses NASA propulsion data. The cruise calibration and section polar underpin the wingtip actuator estimate. The audit contains the extrapolation and similarity assumptions. [NASA HLP data]({ref['sources']['hlp']}) · [NASA cruise propeller data]({ref['sources']['cruise']}) · [OpenFAST section polar]({ref['sources']['cruise_section_polar']})",
        "",
        "The three-grid procedure uses measured fluid volumes and unequal refinement ratios. [Celik et al. (2008)](https://doi.org/10.1115/1.2960953)",
    ]
    if not structure.get("stress_mesh_study_complete",structure.get("stress_mesh_QA_passed")) or len(experiments["cases"])!=18:
        raise ValueError("Incomplete endpoint or structural evidence")
    dest=D/"handoff_notes.md"
    old=dest.read_text(encoding="utf-8-sig")
    if START in old:
        pre,tail=old.split(START,1)
        _,post=tail.split(END,1)
    else:
        pre,post=old,""
    atomic_write_text(dest,pre.rstrip()+"\n\n"+START+"\n"+"\n".join(text)+"\n"+END+"\n"+post.lstrip("\n"))


if __name__=="__main__":
    write()

