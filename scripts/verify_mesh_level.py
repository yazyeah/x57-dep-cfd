"""Read genuine Fluent mesh outputs and audit the gating criteria before solving."""
from pathlib import Path
import argparse
import hashlib
import json
import re
import numpy as np
import h5py
from check_mesh_clearance import measure_stations, names
from mesh_region_budget import region_budget
from control_gate import atomic_write_json
from mesh_ladder_limits import WINDOWS, production_plan

ROOT=Path(__file__).resolve().parents[1]
CTYPE={1:"triangle",2:"tetrahedron",3:"quadrilateral",4:"hexahedron",5:"pyramid",6:"wedge",7:"polyhedron"}

FINE_HARD_MAX=WINDOWS["fine"][1]

def digest(path):
    with path.open("rb") as f:
        return hashlib.file_digest(f,"sha256").hexdigest()

def infer_level(mesh, explicit):
    if explicit:
        return explicit
    found=[n for n in WINDOWS if mesh.name.startswith(n+".") or n in mesh.parts]
    if len(found)!=1:raise ValueError("Supply --level coarse, medium or fine for a nonstandard mesh name.")
    return found[0]

def prepare_solver_check(mesh):
    sha=digest(mesh)
    lines=["/file/confirm-overwrite no",'(set! checkpoint/exit-filename "exit-fluent.txt")',
           f'/file/read-case "{mesh.as_posix()}"',"/mesh/check-verbosity 3","/mesh/check",
           f'(format #t "~%X57-MESH-SHA256 {sha}~%")',
           '(format #t "~%X57-STANDARD-QUALITY-BEGIN~%")',"/mesh/enhanced-orthogonal-quality? no","/mesh/quality",
           '(format #t "~%X57-STANDARD-QUALITY-END~%")','(format #t "~%X57-ENHANCED-QUALITY-BEGIN~%")',
           "/mesh/enhanced-orthogonal-quality? yes","/mesh/quality",'(format #t "~%X57-ENHANCED-QUALITY-END~%")',"/exit ok"]
    target=mesh.with_name("solver_mesh_reload_check.jou")
    target.write_text("\n".join(lines)+"\n",encoding="utf-8")
    return target

def solver_report(source,sha):
    txt=source.read_text(encoding="utf-8",errors="replace")
    if not re.search(r"(?m)^\s*X57-MESH-SHA256 "+sha+r"\s*$",txt):
        raise ValueError("Independent solver transcript is not bound to the supplied mesh SHA-256.")
    groups={}
    for key in ("standard","enhanced"):
        mark="X57-"+key.upper()+"-QUALITY-"
        section=re.search(r"(?ms)^\s*"+mark+r"BEGIN\s*$.*?^\s*"+mark+r"END\s*$",txt)
        if section is None:raise ValueError(f"Incomplete {key} solver quality section.")
        found=re.findall(r"Minimum Orthogonal Quality\s*=\s*([+\-\d.eE]+)",section[0],re.I)
        if not found:raise ValueError(f"No solver minimum in the {key} section.")
        groups[key]=float(found[-1])
    groups["managed_transcript"]=str(source)
    return groups

def source_geometry(config_path):
    config_path=Path(config_path).resolve(strict=True)
    cfg=json.loads(config_path.read_text(encoding="utf-8-sig"))
    shell=Path(cfg["shell"]).resolve(strict=True)
    folder=Path(cfg.get("source_surface_dir") or shell.parent).resolve(strict=True)
    if not all(p.is_relative_to(ROOT) for p in (config_path,shell,folder)) or not folder.is_dir():
        raise ValueError("Meshing inputs must be in this workspace.")
    shell_hash=digest(shell)
    if cfg.get("source_surface_sha256") and cfg["source_surface_sha256"]!=shell_hash:
        raise ValueError("The shell differs from the mesh generator's recorded source hash.")
    evidence=dict(meshing_config_path=str(config_path),meshing_config_sha256=digest(config_path),
                  source_surface_dir=str(folder),source_surface_path=str(shell),source_surface_sha256=shell_hash)
    if cfg.get("level")=="fine":
        bodies=Path(cfg["boi_file"]).resolve(strict=True)
        if not bodies.is_relative_to(ROOT):
            raise ValueError("Fine refinement geometry must reside in the workspace")
        rotor_file=ROOT/"DELIVERABLES/data/actuator_disk_model.json"
        rotors=json.loads(rotor_file.read_text(encoding="utf-8-sig"))["rotors"]
        geometry=[{k:r[k] for k in ("name","center_m","r_hub_m","r_tip_m","thickness_m")} for r in rotors]
        binary=json.dumps(geometry,sort_keys=True,separators=(",",":"),allow_nan=False).encode("utf8")
        evidence.update(BOI_geometry_path=str(bodies),BOI_geometry_sha256=digest(bodies),
                        actuator_geometry_source=str(rotor_file),actuator_geometry_sha256=hashlib.sha256(binary).hexdigest())
    return evidence


def fine_resolution_checks(budget):
    """Re-evaluate measured Fine evidence on admission and on ladder reload."""
    expected={"WT-1"}|{f"HLP-{i}" for i in range(1,7)}
    rays=budget.get("rotor_ray_floors",{})
    scales=budget.get("near_wake_measured_hex_edges",{})
    tubes=scales.get("per_rotor_core",{})
    regions=budget.get("region_cells",{})
    names={"wing_wall_layers","disk_annuli","near_wake","other_components_and_mid_wake","outer_farfield"}
    return {
        "seven_native_actuator_rays_meet_floors":set(rays)==expected and all(
            row[direction]["passed"] for row in rays.values() for direction in ("axial","radial")),
        "measured_near_wake_hex_regions":all(scales.get(k,{}).get("hex_count",0)>0 for k in ("core","outer_transition")),
        "fine_nominal_BOI_targets":budget.get("sizing_controls",{}).get("passed") is True,
        "seven_native_wake_core_representative_sizes":set(tubes)==expected and all(
            t.get("representative_resolution_at_or_finer_than_upper") for t in tubes.values()),
        "native_wake_outer_representative_size":scales.get("outer_transition",{}).get(
            "representative_resolution_at_or_finer_than_upper") is True,
        "five_fine_allocation_targets":set(regions)==names and all(row.get("within_target") for row in regions.values())
            and all(regions[name].get("within_target_for_any_shared_assignment")
                    for name in ("wing_wall_layers","other_components_and_mid_wake")),
    }


def physical_mesh_checks(budget):
    from p2_geometry_io import WALLS
    native=budget.get("native_physical_zone_evidence",{})
    depths=budget.get("native_wall_depth_evidence",{})
    checks={"single_fluid_region":native.get("single_connected_fluid_region") is True,
            "boundary_zones":native.get("exact_physical_boundaries") is True}
    for name in WALLS:
        row=depths.get(name,{})
        counts=row.get("wall_face_status",{})
        count=sum(group.get("faces",0) for group in counts.values())
        checks["native_full_depth_split_"+name]=bool(row.get("passed") is True and count>0
            and count==row.get("wall_faces") and row.get("failed_faces")==0)
    return checks


def publish(report,mesh_root):
    level=report["level"]
    if level not in WINDOWS or report.get("passed") is not True or not all(report["checks"].values()):
        raise ValueError("Only a passing single-level native QA can be published.")
    if not all(physical_mesh_checks(report.get("five_region_evidence",{})).values()):
        raise ValueError("Missing native boundary types, physical connectivity, or five-wall column evidence")
    if level=="fine" and not all(fine_resolution_checks(report.get("five_region_evidence",{})).values()):
        raise ValueError("Fine resolution evidence is missing, stale or failed")
    folder=(Path(mesh_root)/level).resolve(strict=True)
    mesh=Path(report["source_mesh"]).resolve(strict=True)
    if not mesh.is_relative_to(folder) or digest(mesh)!=report["mesh_sha256"]:
        raise ValueError("Source mesh is outside its level or has changed since verification.")
    if source_geometry(report["source_geometry"]["meshing_config_path"]) != report["source_geometry"]:
        raise ValueError("Source geometry or meshing configuration changed since verification.")
    atomic_write_json(folder/"mesh_qa.json",report)


def audit(mesh_path, transcript, level=None, solver_transcript=None, config_path=None):
    level=infer_level(mesh_path,level)
    sha=digest(mesh_path)
    config_path=config_path or mesh_path.with_name("mesh_config.json")
    text=transcript.read_text("utf-8",errors="replace")
    def last(pattern):
        matches=re.findall(pattern,text,re.I)
        if not matches:
            raise ValueError(f"No completed Fluent diagnostic matched {pattern!r}")
        return float(matches[-1])
    min_ortho=last(r"Minimum Orthogonal Quality\s*=\s*(\S+)")
    max_aspect=last(r"Maximum Aspect Ratio\s*=\s*(\S+)")
    min_volume=last(r"minimum volume:\s*(\S+?)\.(?:\s|$)")
    with h5py.File(mesh_path,"r") as f:
        m=f["meshes/1"]
        cells=m["cells/zoneTopology"]
        cell_count=int(np.sum(cells["maxId"][:]-cells["minId"][:]+1))
        node_count=sum(ds.shape[0] for ds in m["nodes/coords"].values())
        cell_types={}
        for block in m["cells/ctype"].values():
            uniform=int(np.asarray(block.attrs["elementType"]).item())
            if uniform==0:
                values, counts=np.unique(block["cell-types"][:],return_counts=True)
            else:
                values=[uniform]
                counts=[int((block.attrs["maxId"]-block.attrs["minId"]+1).item())]
            for value,count in zip(values,counts):
                key=CTYPE.get(int(value),str(value))
                cell_types[key]=cell_types.get(key,0)+int(count)
        fluid_regions=names(cells)
        ft=m["faces/zoneTopology"]
        faces=names(ft)
        fb=f["special/boundary_layer_flags/faces"]
        cb=f["special/boundary_layer_flags/cells"]
        inflation_cells=sum(int(np.count_nonzero(g["data"][:])) for k,g in cb.items() if k!="topology")
        inflation_faces={}
        for name,zid,n0,n1 in zip(faces,ft["id"][:],ft["minId"][:],ft["maxId"][:]):
            zid=str(int(zid))
            if name.startswith("wall_"):
                affected=int(np.count_nonzero(fb[zid]["data"][:])) if zid in fb else 0
                inflation_faces[name]={"flagged":affected,"total":int(n1)-int(n0)+1}
    license_cap=json.loads((ROOT/"DELIVERABLES/data/environment_and_license.json").read_text("utf-8-sig"))["license"]["solver_cell_threshold"]
    cad=json.loads((ROOT/"01_geometry/geometry_audit.json").read_text("utf-8-sig"))["cad_clearance_vertical_rays"]
    gaps=[]
    rays=measure_stations(mesh_path,[(item["x_m"],item["z_m"]) for item in cad])
    for station,ray in zip(cad,rays,strict=True):
        ray["cad_gap_m"]=station["clearance_m"]
        ray["gap_change_m"]=(ray["gap_m"]-ray["cad_gap_m"]
                             if ray["gap_m"] is not None and ray["cad_gap_m"] is not None else None)
        gaps.append(ray)
    primary=next(g for g in gaps if g["z_m"]==.86)
    outboard=next(g for g in gaps if g["z_m"]==.88832)
    checks={"positive_cell_volume":min_volume>0,"min_orthogonal_quality_gt_0p1":min_ortho>.1,
            "below_cell_cap":cell_count<license_cap,"sponson_gap_open":primary["gap_m"] is not None and primary["gap_m"]>0,
            "no_spurious_outboard_sponson":outboard["sponson_top_y_m"] is None and outboard["underside_y_m"] is not None,
            "hexahedral_core_present":cell_types.get("hexahedron",0)>0,
            "native_report_consistency":int(last(r"number of interior cells\s*=\s*([0-9]+)"))==cell_count,
            "ctype_section_complete":sum(cell_types.values())==cell_count}
    checks["cad_gap_within_8mm"]=primary["gap_change_m"] is not None and abs(primary["gap_change_m"])<.008
    checks["all_station_sponson_presence"]=all((g["cad_gap_m"] is None)==(g["gap_m"] is None) for g in gaps)
    checks["all_station_upper_surface_present"]=all(g["underside_y_m"] is not None for g in gaps)
    valid_gaps=[abs(g["gap_change_m"]) for g in gaps if g["gap_change_m"] is not None]
    checks["all_measured_cad_gaps_within_production_tolerance"]=bool(valid_gaps) and (
        max(valid_gaps)<=.005 if level=="fine" else max(valid_gaps)<=.003)
    lower,upper=WINDOWS[level]
    checks["level_cell_window"]=lower<=cell_count<=upper
    checks["production_cell_limit"]=cell_count<=FINE_HARD_MAX
    if level=="fine":
        checks["cad_gap_within_5mm"]=primary["gap_change_m"] is not None and abs(primary["gap_change_m"])<=.005
    independent=solver_report(solver_transcript,sha) if solver_transcript else None
    budget=region_budget(mesh_path,config_path)
    opts=budget["recorded_mesh_request"]
    checks.update(physical_mesh_checks(budget))
    checks["scoped_inflation_present"] = all(v for k,v in checks.items() if k.startswith("native_full_depth_split_"))
    native_vol=budget["reference_cell_volume_range_m3"]["min"]
    checks["minimum_volume_consistency"]=bool(np.isclose(min_volume,native_vol,rtol=.02,atol=0.))
    checks["exhaustive_disjoint_budget"]=budget["all_regions_sum_to_mesh"]
    checks["solver_reload_orthogonal_quality"]=bool(independent and independent["standard"]>.1)
    if level=="fine":
        configured={Path(opts[key]).resolve() for key in ("mesh","improved_mesh") if opts.get(key)}
        checks["matched_fine_native_mesh_configuration"]=(opts.get("level")=="fine" and mesh_path.resolve() in configured)
        checks.update(fine_resolution_checks(budget))
    plan=production_plan(ROOT,(level,cell_count,float(budget["fluid_volume_m3"])))
    checks["feasible_three_level_refinement"]=plan["measured_constraints_pass"]
    return {"level":level,"mesh_sha256":sha,"source_geometry":source_geometry(config_path),"cell_target_window":[lower,upper],
            "three_level_count_plan":plan,"recommended_solver_minimum_OQ":.12,
            "solver_reaches_recommended_OQ":bool(independent and independent["standard"]>=.12),
            "fine_hard_max_cells":FINE_HARD_MAX,"independent_solver_quality":independent,
            "mesher_and_solver_standard_min_difference":(independent["standard"]-min_ortho) if independent else None,
            "five_region_evidence":budget,"boundary_layer_cell_count":inflation_cells,"boundary_layer_wall_face_counts":inflation_faces,"source_mesh":str(mesh_path),"managed_transcript":str(transcript),"cells":cell_count,
            "nodes":node_count,"cell_type_counts":cell_types,"cell_zones":fluid_regions,"face_zones":faces,
            "min_orthogonal_quality":min_ortho,"max_aspect_ratio":max_aspect,"min_volume_m3":min_volume,
            "sponson_gap":gaps,"checks":checks,"solver_admissible":all(checks.values()),"passed":all(checks.values())}


if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mesh",type=Path)
    parser.add_argument("transcript",type=Path,nargs="?",help="Fluent Meshing native diagnostics transcript")
    parser.add_argument("--level",choices=list(WINDOWS))
    parser.add_argument("--solver-transcript",type=Path,help="Managed solver reload of the same saved mesh with the generated read-only journal")
    parser.add_argument("--config",type=Path,help="Meshing input JSON adjacent to the mesh by default")
    parser.add_argument("--prepare-solver-check",action="store_true",help="Write a read-only verification journal without launching Fluent")
    parser.add_argument("--publish",action="store_true",help="Publish a passing candidate QA to its canonical 02_mesh/<level> directory")
    args=parser.parse_args()
    if args.prepare_solver_check:
        print(prepare_solver_check(args.mesh.resolve(strict=True)))
        raise SystemExit(0)
    if args.transcript is None:
        parser.error("The meshing transcript is required to audit a mesh.")
    report=audit(args.mesh.resolve(strict=True),args.transcript.resolve(strict=True),args.level,
                 args.solver_transcript.resolve(strict=True) if args.solver_transcript else None,args.config)
    payload=json.dumps(report,indent=2)
    print(payload)
    atomic_write_json(args.mesh.with_name("mesh_qa.json"),report)
    if args.publish and report["passed"]:
        publish(report,ROOT/"02_mesh")
    raise SystemExit(0 if report["passed"] else 1)
