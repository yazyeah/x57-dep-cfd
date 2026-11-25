"""Audit a completed physical stage and record its native quantitative evidence."""
import argparse
import json
from pathlib import Path
import numpy as np

from cfd_verification import gci_threshold
from cfd_case_identity import digest
from compare_x57_cases import BASE, ROOT, ZERO, accepted, read_json
from control_gate import atomic_write_json
from run_x57_converged import control
from x57_baseline_data import FINE, OFF, grid_series, rpm_series, save_json, save_table, swirl_load_partition, wall_data


def wing_first_height(mesh):
    origin=mesh["source_geometry"]
    path=Path(origin["meshing_config_path"])
    if digest(path)!=origin["meshing_config_sha256"]:
        raise ValueError("Mesh-generation controls changed after native mesh sign-off")
    settings=read_json(path)
    heights=[row["first_height_m"] for row in settings["prism_scopes"] if "wall_wing" in row["walls"]]
    if len(heights)!=1 or not np.isfinite(heights[0]) or heights[0]<=0:
        raise ValueError("Expected one positive initial prism height on the wing")
    return heights[0]


def record_disk_integrals(names):
    path=ROOT/"DELIVERABLES/data/actuator_disk_model.json"
    model=read_json(path)
    records=model.get("fluent_discrete_integrals") or {}
    for name in names:
        control()
        qa,case,data=accepted(name)
        disks=qa["disk_integrals"]
        if len(disks)!=7 or not all(d["thrust_passes"] and d["torque_passes"] for d in disks):
            raise ValueError(f"Invalid native disk integrals in {name}")
        records[name]={"native_case":str(case.relative_to(ROOT)),"native_data":str(data.relative_to(ROOT)),
                       "source":str((case.parent/"fluent_discrete_disk_integrals.json").relative_to(ROOT)),
                       "disks":disks}
        control()
    model["fluent_discrete_integrals"]=records
    atomic_write_json(path,model)


def timed_case(case_name):
    qa,case,data=accepted(case_name)
    blocks=[json.loads(s) for s in (case.parent/"convergence_blocks.jsonl").read_text().splitlines() if s]
    if not blocks or blocks[-1]["final_iteration"]!=qa["final_iteration"]:
        raise ValueError(f"Unmatched accepted iteration times for {case_name}")
    n=sum(s["actual_iteration_samples"] for s in blocks)
    native=sum(s["solver_wall_seconds"] for s in blocks)
    return dict(case=case_name,endpoint=qa["final_iteration"],measured_iterations=n,solver_seconds=native,
                seconds_per_iteration=native/n,native_case=str(case),native_data=str(data),qa=qa["checks"],
                forces=qa["forces_full_aircraft"],mass_imbalance_percent=100*qa["mass_balance"]["imbalance_fraction"],
                last50_residual_max=qa["max_last_50_scaled_residuals"])


def audit(stage):
    control()
    names={"P3":["coarse_rpm100"],"P4":[BASE],"P5":[FINE],"P6":["medium_rpm050","medium_rpm075"],"P7":[OFF],
           "P8":[BASE+"_hlp_only",BASE+"_wt_only",BASE+"_alt_swirl"],
           "P9":[BASE+"_oge",BASE+"_takeoff_v10",BASE+"_rke"]}[stage]
    cases={}
    for name in names:
        control()
        cases[name]=timed_case(name)
        control()
    result=dict(stage=stage,cases=cases,checks={"accepted_native_cases":all(all(v["qa"].values()) for v in cases.values())})
    record_disk_integrals(names)
    if stage in ("P3","P4","P5"):
        name=names[0]
        _,_,w,metric,_,_=wall_data(name)
        w.close()
        value=metric["yplus"]["wall_wing"]
        result["wing_yplus"]=value
        mesh=read_json(ROOT/"02_mesh"/name.split("_")[0]/"mesh_qa.json")
        first=wing_first_height(mesh)
        if value["mean"]>0 and value["p95"]>0:
            result["first_layer_m"]=first
            result["estimated_first_layer_for_mean_0p85_m"]=first*.85/value["mean"]
            if stage=="P4":
                fine=read_json(ROOT/"02_mesh/fine/mesh_qa.json")
                fine_first=wing_first_height(fine)
                ratio=fine_first/first
                predicted_mean=ratio*value["mean"]
                predicted_p95=ratio*value["p95"]
                # A uniform height scales the mean and upper tail together. Choose a
                # height within both intervals before a physical Fine-grid confirmation.
                allowed_min=first*.5/value["mean"]
                allowed_max=min(first*1.2/value["mean"],first*2.5/value["p95"])
                result["fine_wall_calibration"]=dict(medium_mesh_sha256=mesh["mesh_sha256"],medium_first_m=first,
                    measured_medium_wing_yplus=value,verified_fine_mesh_sha256=fine["mesh_sha256"],
                    current_fine_first_m=fine_first,predicted_mean=predicted_mean,predicted_p95=predicted_p95,
                    all_bounds_predicted=.5<=predicted_mean<=1.2 and predicted_p95<2.5,
                    uniform_height_interval_m=[allowed_min,allowed_max],
                    recommended_m=min(first*.85/value["mean"],.98*allowed_max) if allowed_min<allowed_max else None,
                    basis="Linear wall-unit scaling from the resolved Medium solution. Final acceptance uses the actual Fine solution.")

        # Fast-track: y+ and GCI are measured, recorded and graded in final_quality_audit.py;
        # they are physical outcomes and never block the pipeline.
        if stage=="P4":
            result.setdefault("targets",{})["measured_medium_yplus_for_fine"] = "fine_wall_calibration" in result
        if stage=="P5":
            frame,gci=grid_series()
            save_table(frame,"mesh_convergence.csv")
            save_json(gci,"asme_vv20_gci.json")
            result["gci"]={k:gci[k] for k in ("L_air_N","D_air_N")}
            result["targets"]=dict(wing_yplus_mean_0p5_to_1p2=.5<=value["mean"]<=1.2,wing_yplus_p95=value["p95"]<2.5,
                                   lift_and_drag_gci_redline=all(gci_threshold(v,5.) for v in result["gci"].values()),
                                   wing_mean_0p5_to_1p2=.5<=value["mean"]<=1.2,
                                   fine_gci_below_3pct=all(gci_threshold(v,3.) for v in result["gci"].values()))
    elif stage=="P6":
        rpm,fits=rpm_series(include_noswirl=False)
        save_table(rpm,"rpm_sweep.csv")
        result["squared_speed_fits"]=fits
        result["targets"]={k+"_R2_at_least_0p999":v["r_squared_centered"] is not None and v["r_squared_centered"]>=.999 for k,v in fits.items()}
        result["collapse"]=rpm.loc[rpm.s>0,["s","D_over_s2_N","abs_L_over_s2_N"]].to_dict("records")
    elif stage=="P7":
        _,result["swirl_load_and_suction"]=swirl_load_partition()
    result["acceptance_tiers"]={name:read_json(ROOT/"03_cases"/name/"iteration_qa.json").get("acceptance_tier") for name in names}
    result["passed"]=all(result["checks"].values())
    target=ROOT/"logs"/(stage+"_quantitative_audit.json")
    atomic_write_json(target,result)
    control()
    print(json.dumps({"evidence":str(target),"checks":result["checks"],"targets":result.get("targets",{})}))
    return result["passed"]


if __name__=="__main__":
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("stage",choices=["P3","P4","P5","P6","P7","P8","P9"])
    raise SystemExit(0 if audit(p.parse_args().stage) else 1)

