"""Verify mesh count windows, native per-level checks and effective grid spacing ratios."""
import argparse
import json
import math
from pathlib import Path
from verify_mesh_level import WINDOWS,FINE_HARD_MAX,digest,source_geometry,fine_resolution_checks,physical_mesh_checks
from control_gate import atomic_write_json
from mesh_ladder_limits import LEVELS, MIN_R21, MIN_R32, ratio_pass, production_plan

def evaluate(rows):
    counts={n:rows[n]["cells"] for n in LEVELS}
    volumes={n:rows[n].get("five_region_evidence",{}).get("fluid_volume_m3") for n in LEVELS}
    valid=all(isinstance(v,(float,int)) and math.isfinite(v) and v>0 for v in volumes.values()) and all(
        isinstance(n,int) and n>0 for n in counts.values())
    h={n:(volumes[n]/counts[n])**(1/3) for n in LEVELS} if valid else {}
    r32=h["coarse"]/h["medium"] if valid else None
    r21=h["medium"]/h["fine"] if valid else None
    checks={"each_grid_passed":all(rows[n]["passed"] and rows[n].get("level")==n for n in LEVELS),
            "native_boundaries_and_wall_depths":all(all(physical_mesh_checks(rows[n].get("five_region_evidence",{})).values()) for n in LEVELS),
            "fine_native_resolution":all(fine_resolution_checks(rows["fine"].get("five_region_evidence",{})).values()),
            "count_windows":all(WINDOWS[n][0]<=counts[n]<=WINDOWS[n][1] for n in LEVELS),
            "ratio_gate":valid and ratio_pass(r32,r21),
            "fine_cap_gate":counts["fine"]<=FINE_HARD_MAX and counts["fine"]<1048576}
    return dict(levels=counts,fluid_volume_m3=volumes,h_m=h,
                spacing_ratio_definition="h=(V/N)^(1/3) using each native fluid mesh volume; r32=h_coarse/h_medium, r21=h_medium/h_fine",
                minimum_r32=MIN_R32,minimum_r21=MIN_R21,coarse_to_medium=r32,medium_to_fine=r21,r32=r32,r21=r21,
                **checks,passed=all(checks.values()),solver_admissible=all(checks.values()),fine_count_disposition="strict_target_window")


def publish_ladder(folder):
    rows={n:json.loads((folder/n/"mesh_qa.json").read_text(encoding="utf-8-sig")) for n in WINDOWS}
    result=evaluate(rows)
    hashes={}
    for level,row in rows.items():
        mesh=Path(row["source_mesh"]).resolve(strict=True)
        if not mesh.is_relative_to((folder/level).resolve()) or digest(mesh)!=row["mesh_sha256"]:
            raise ValueError(f"{level} canonical QA refers to a different mesh.")
        if source_geometry(row["source_geometry"]["meshing_config_path"])!=row["source_geometry"]:
            raise ValueError(f"{level} source shell or configuration has changed.")
        hashes[level]=row["mesh_sha256"]
    result["mesh_sha256"]=hashes
    payload=json.dumps(result,indent=2)
    atomic_write_json(folder/"grid_ladder_qa.json",result)
    return result

if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root",type=Path,default=Path(__file__).resolve().parents[1]/"02_mesh")
    parser.add_argument("--plan",action="store_true",help="Print feasible closed count ranges using accepted meshes and pending oriented surfaces")
    args=parser.parse_args()
    if args.plan:
        info=production_plan(args.root.resolve().parent)
        print(json.dumps(info,indent=2))
        raise SystemExit(0 if info["feasible"] else 1)
    result=publish_ladder(args.root)
    payload=json.dumps(result,indent=2)
    print(payload)
    raise SystemExit(0 if result["passed"] else 1)
