"""Audit the single Fine BOI refinement allowed by troubleshooting manual section 1."""
import argparse
import json
import math
from pathlib import Path

import h5py
from control_gate import atomic_write_json
from verify_mesh_level import FINE_HARD_MAX, ROOT, digest, source_geometry

LOW = (960000, 1019000)
FINE = ROOT/"02_mesh"/"fine"
TRIAL = FINE/"manual_1_refinement.json"


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def count_cells(path):
    from fluent_checkpoints import check_mesh_file
    if check_mesh_file(path,deep=True)!=(True,True):
        raise ValueError("The Fine CFF must contain a readable volume mesh")
    with h5py.File(path) as native:
        mesh=native["meshes/1"]
        for field in ("faces/c0","faces/c1","faces/nodes","nodes/coords","cells/ctype"):
            if field not in mesh or not len(mesh[field]):
                raise ValueError(f"Missing native mesh field {field}")
        topology=native["meshes/1/cells/zoneTopology"]
        intervals=sorted((int(lo),int(hi)) for lo,hi in zip(topology["minId"],topology["maxId"],strict=True))
        if not intervals or intervals[0][0]!=1 or any(hi<lo for lo,hi in intervals):
            raise ValueError("Invalid native volume-cell ranges")
        if any(a[1]+1!=b[0] for a,b in zip(intervals,intervals[1:])):
            raise ValueError("Discontinuous native volume-cell IDs")
        return intervals[-1][1]


def base_evidence(qa):
    row=read(qa)
    mesh=Path(row["source_mesh"]).resolve(strict=True)
    other={k:v for k,v in row["checks"].items() if k!="level_cell_window"}
    if not (mesh.is_relative_to(FINE) and row["level"]=="fine" and LOW[0]<=row["cells"]<=LOW[1]
            and row["independent_solver_quality"]["standard"]>.15
            and other.get("cad_gap_within_5mm") and other.get("all_station_sponson_presence")
            and other.get("five_fine_allocation_targets") and all(other.values())):
        raise ValueError("Fine candidate fails a case-independent manual section 1 requirement")
    if digest(mesh)!=row["mesh_sha256"] or count_cells(mesh)!=row["cells"]:
        raise ValueError("Fine candidate CFF differs from its native QA")
    g=row["source_geometry"]
    if source_geometry(g["meshing_config_path"])!=g:
        raise ValueError("Fine candidate geometry or inputs changed")
    return row,mesh


def fingerprint(path):
    path=Path(path).resolve(strict=True)
    if not path.is_relative_to(ROOT):
        raise ValueError("Expected a file in this workspace")
    return dict(path=str(path),sha256=digest(path))


def sizes(cfg):
    return {r["name"]:float(r["size"]) for r in cfg["sizes"] if r["type"].lower()=="body of influence"}


def compare_refinement(initial,trial):
    a,b=sizes(initial),sizes(trial)
    if not a or a.keys()!=b.keys() or len(a)<9:
        raise ValueError("Fine trial needs the same rotor and near/mid-wake BOIs")
    ratios={k:b[k]/a[k] for k in a}
    changed=[v for v in ratios.values() if not math.isclose(v,1.,abs_tol=1e-8)]
    if not changed or any(not .96<=v<=.98 for v in changed) or max(ratios.values())>1.00000001:
        raise ValueError("The single trial must record a roughly 3 percent BOI refinement")
    for key in ("layers","other_wall_layers","first_height","growth","near_wake_bounds","mid_wake_bounds"):
        if initial[key]!=trial[key]:
            raise ValueError(f"Fine trial also changed {key}")
    if initial["layers"]<18 or trial["level"]!="fine":
        raise ValueError("The Fine wing prism controls must be retained")
    return ratios


def register(qa,trial_config):
    if Path(qa).resolve()==FINE/"mesh_qa.json":
        raise ValueError("Register the original QA beside the candidate, before canonical admission.")
    row,base=base_evidence(qa)
    config=Path(trial_config).resolve(strict=True)
    current=read(row["source_geometry"]["meshing_config_path"])
    trial=read(config)
    target=Path(trial["mesh"]).resolve()
    if not (target.is_relative_to(FINE) and config.parent==target.parent and target!=base
            and Path(trial["size_field_path"]).resolve()!=Path(current["size_field_path"]).resolve()):
        raise ValueError("Specify a distinct Fine trial configuration and size field")
    if source_geometry(config)["source_surface_sha256"]!=row["source_geometry"]["source_surface_sha256"]:
        raise ValueError("The Fine trial uses a different surface")
    ratios=compare_refinement(current,trial)
    evidence=dict(initial_qa=fingerprint(qa),initial_mesh=fingerprint(base),initial_field=fingerprint(current["size_field_path"]),
                  trial_config=fingerprint(config),
                  trial_mesh_path=str(target),BOI_trial_to_initial_size_ratios=ratios)
    if TRIAL.exists():
        if read(TRIAL)==evidence:
            return evidence
        raise ValueError("A different Fine refinement has already been registered under section 1")
    if target.exists():
        raise ValueError("Register the single candidate before volume mesh generation")
    with TRIAL.open("x",encoding="utf-8") as f:
        json.dump(evidence,f,indent=2)
    return evidence


def proof():
    rec=read(TRIAL)
    for name in ("initial_qa","initial_mesh","initial_field","trial_config"):
        if fingerprint(rec[name]["path"])!=rec[name]:
            raise ValueError(f"Changed registered input: {name}")
    row,mesh=base_evidence(rec["initial_qa"]["path"])
    trial_cfg=read(rec["trial_config"]["path"])
    config=read(row["source_geometry"]["meshing_config_path"])
    if compare_refinement(config,trial_cfg)!=rec["BOI_trial_to_initial_size_ratios"]:
        raise ValueError("BOI trial settings changed")
    target=Path(rec["trial_mesh_path"]).resolve(strict=True)
    if target != Path(trial_cfg["mesh"]).resolve() or not target.is_relative_to(FINE):
        raise ValueError("Native oversized CFF is outside the registered trial")
    cells=count_cells(target)
    if cells<=FINE_HARD_MAX:
        raise ValueError("The single refinement did not exceed the project hard cell cap")
    initial_field=fingerprint(config["size_field_path"])
    trial_field=fingerprint(trial_cfg["size_field_path"])
    for cfg,field in [(config,initial_field),(trial_cfg,trial_field)]:
        if cfg.get("size_field_sha256") and cfg["size_field_sha256"]!=field["sha256"]:
            raise ValueError("The native field differs from its generator-side digest.")
    if initial_field["sha256"]==trial_field["sha256"]:
        raise ValueError("The regenerated Fine field is identical to the initial field")
    return row,dict(registration=fingerprint(TRIAL),initial_mesh_sha256=digest(mesh),trial_mesh=fingerprint(target),
                    trial_cells=cells,student_license_limit_reached=cells>=1048576,
                    initial_field=initial_field,trial_field=trial_field,BOI_size_ratios=rec["BOI_trial_to_initial_size_ratios"])


def conditional():
    row,ev=proof()
    row["solver_admissible"]=True
    row["passed"]=False
    row["fine_count_disposition"]="manual_section_1_pending_native_yplus"
    row["manual_section_1"]=ev
    return row


def finalize():
    from extract_fluent_fields import extract_walls
    from cfd_verification import weighted_distribution
    from compare_x57_cases import accepted
    row=conditional()
    qa,cas,dat=accepted("fine_rpm100")
    # This case must already carry the exact P2 mesh identity used by the solver.
    actual=qa.get("volume_mesh_sha256")
    if actual!=row["mesh_sha256"]:
        raise ValueError("Accepted Fine endpoint does not identify the registered Fine grid")
    faces=extract_walls(cas,dat)
    wing_mask=faces["component"]=="wall_wing"
    wing=weighted_distribution(faces["yplus"][wing_mask],faces["area_m2"][wing_mask])
    if not (.5<=wing["mean"]<=1.2 and wing["p95"]<2.5):
        raise ValueError(f"The native Fine wing y+ criterion failed: {wing}")
    row["manual_section_1"]["native_yplus"]=dict(wing=wing,case=fingerprint(cas),data=fingerprint(dat),
                           iteration_qa=fingerprint(cas.parent/"iteration_qa.json"),source_mesh_sha256=actual)
    row["fine_count_disposition"]="manual_section_1_accepted_native_yplus"
    row["passed"]=True
    return row


if __name__=="__main__":
    raise SystemExit("Production Fine is restricted to 940,000–1,044,000 cells. Use verify_mesh_level.py --publish.")
