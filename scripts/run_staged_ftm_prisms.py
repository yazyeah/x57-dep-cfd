"""Prepare or run a guarded native FTM volume fill and capture its actual error state."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import uuid

ROOT=Path(__file__).resolve().parents[1] if "__file__" in globals() else None
WALLS={"wall_wing","wall_nacelles","wall_fuselage","wall_sponson","wall_empennage"}
STEM="f_scoped_prism_stage_20"

def write(path,record):
    path.write_text(json.dumps(record,indent=2,allow_nan=False),encoding="utf-8")

def digest(path):
    with path.open("rb") as fp:
        return hashlib.file_digest(fp,"sha256").hexdigest()

def native_stage(workflow,meshing,settings):
    """Invoke the same public GenerateTheVolumeMeshFTM command and controls as C17."""
    cfg=json.loads(Path(settings).read_text(encoding="utf8"))
    evidence=Path(cfg["evidence"])
    found=set()
    for name,walls in cfg["controls"].items():
        child=workflow.TaskObject[name]
        state=child.Arguments.get_state()
        if (child.State.get_state()!="Up-to-date" or set(state["BLZoneList"])!=set(walls)
                or state["BLRegionList"]!=["external_fluid"]):
            raise ValueError(f"Registered scope changed: {name}")
        found.update(walls)
    if found!=WALLS:raise ValueError("Incomplete aircraft wall scopes")

    captured=cfg["native_volume_readback"]
    registry=meshing.GlobalSettings.FTMRegionData
    table=registry.get_state()
    names=table["AllRegionNameList"]
    fills=captured["AllRegionVolumeFillList"]
    if (names!=captured["AllRegionNameList"] or table["AllRegionTypeList"].count("fluid")!=1
            or table["AllRegionTypeList"][names.index("external_fluid")]!="fluid"
            or len(fills)!=len(names) or fills!=["poly-hexcore" if n=="external_fluid" else "none" for n in names]):
        raise ValueError("Physical fluid region table changed")
    registry.AllRegionVolumeFillList.set_state(fills)
    registry.AllRegionSizeList.set_state(captured["AllRegionSizeList"])
    keys=("EnableParallel","AdvancedOptions","SaveVolumeMesh","EditVolumeSettings","OrthogonalQuality",
          "AllRegionNameList","AllRegionVolumeFillList","AllRegionSizeList","FillWithSizeField","QualityMethod")
    args={key:captured[key] for key in keys}
    command=meshing.GenerateTheVolumeMeshFTM.create_instance()
    command.set_state(args)
    actual=command.get_state()
    for key in keys:
        if actual.get(key)!=args[key]:raise ValueError(f"FTM changed {key}: {actual.get(key)!r}")
    parent=workflow.TaskObject["Generate the Volume Mesh"]
    command_name=parent.CommandName.get_state() if hasattr(parent,"CommandName") else None
    if command_name and command_name!="GenerateTheVolumeMeshFTM":
        raise ValueError(f"Unexpected volume task: {command_name}")
    parent.Arguments.set_state(args)
    write(evidence/"native_fill_before.json",dict(command=command_name,arguments=args,readback=actual))
    print("X57_GUARDED_FTM_FILL_BEGIN",flush=True)
    success=parent.Execute()
    state=parent.State.get_state()
    write(evidence/"native_fill_after.json",dict(returned_success=success is not False,state=state))
    if success is False or state!="Up-to-date":raise RuntimeError(f"FTM volume generation failed: {state}")
    (evidence/"volume_returned.flag").write_text("FTM volume generation returned Up-to-date\n",encoding="ascii")
    print("X57_GUARDED_FTM_FILL_RETURNED",flush=True)


def journal(cfg,config_path):
    e=Path(cfg["evidence"])
    pyfile=(ROOT/"scripts/run_staged_ftm_prisms.py").as_posix()
    setup=f"import runpy; runpy.run_path(r'{pyfile}')['native_stage'](workflow,meshing,r'{config_path.as_posix()}')"
    quot=lambda s:json.dumps(str(s),ensure_ascii=True)
    pause='(or (file-exists? "exit-fluent.txt") (file-exists? "exit-fluent"))'
    def native_write(filename):
        return '(ti-menu-load-string '+quot('/file/write-mesh "'+(e/filename).as_posix()+'"')+')'
    # Keep yes after the complete compound form. It is used only if Fluent needs
    # region-recompute confirmation. The success branch exits before any trailing
    # token is interpreted and the error branch rethrows after attempting a write.
    expr=('(let ((returned (err-protect (begin (%py-exec '+quot(setup)+') #t)))) '
          '(cond ('+pause+' (ti-menu-load-string "/exit yes")) '
          '((and returned (file-exists? '+quot((e/"volume_returned.flag").as_posix())+')) '
          +native_write("full_volume.msh.h5")+' (ti-menu-load-string "/exit yes")) '
          '(else (format #t "~%X57_GUARDED_FTM_FILL_NATIVE_ERROR~%") '
          '(err-protect '+native_write("state_at_fill_error.msh.h5")+') '
          '(error "X57 native FTM volume fill failed; retained available diagnostic state."))))')
    return ('/file/confirm-overwrite no\n/file/read-mesh '+quot(Path(cfg["registered"]).as_posix())+
            '\n(if '+pause+' (ti-menu-load-string "/exit yes"))\n/file/read-size-field '+
            quot(Path(cfg["size_field"]).as_posix())+'\n'+expr+'\nyes\n')

def prepare(work):
    src=ROOT/"02_mesh/coarse/f_registered_ftm_17"
    prior=json.loads((src/"mesh_config.json").read_text(encoding="utf8"))
    registered=Path(prior["region_registration_checkpoint"])
    field=Path(prior["size_field_path"])
    if digest(registered)!=prior["region_registration_checkpoint_sha256"] or digest(field)!=prior["size_field_sha256"]:
        raise ValueError("Registered controls or field differs from source hashes")
    captures=json.loads((src/"volume_readback.json").read_text(encoding="utf8"))
    if captures["AllRegionVolumeFillList"].count("poly-hexcore")!=1:
        raise ValueError("Incorrect source volume-region table")
    controls={k["BLControlName"]:k["BLZoneList"] for k in prior["native_input_stacks"]}
    report=ROOT/"logs/ftm_staged_prisms"/uuid.uuid4().hex
    work.mkdir(parents=True,exist_ok=False);report.mkdir(parents=True,exist_ok=False)
    conf=dict(level="coarse",source=str(src),registered=str(registered),registered_sha256=digest(registered),
              size_field=str(field),size_field_sha256=digest(field),native_volume_readback=captures,
              generation_journal=str(work/"mesh.jou"),evidence=str(report),controls=controls,
              execution_strategy="guarded_public_ftm_full_fill",eligible_for_production=False)
    config_path=work/"mesh_config.json";write(config_path,conf)
    (work/"mesh.jou").write_text(journal(conf,config_path),encoding="ascii")
    return conf

def physical_boundary_geometry(path):
    """Sum the actual facets of the five named walls and all of the native symmetry patches."""
    import h5py
    import numpy as np
    from cut_fluent_cells import bounds,read_id_blocks
    out={}
    with h5py.File(path) as h:
        m=h["meshes/1"]
        xyz=read_id_blocks(m["nodes/coords"],int(max(m["nodes/zoneTopology/maxId"])),float,3)
        f=m["faces"];t=f["zoneTopology"]
        all_names=t["name"][0].decode().rstrip(";").split(";")
        lookup=[]
        for name,typ,lo,hi in zip(all_names,t["zoneType"][:],t["minId"][:],t["maxId"][:],strict=True):
            key=name if name in WALLS and typ==3 else "symmetry" if typ==7 and name.lower().startswith("symmetry") else None
            if key:lookup.append((key,int(lo),int(hi)))
        for blk in f["nodes"].values():
            blo,bhi=bounds(blk)
            selected=[(k,max(lo,blo),min(hi,bhi)) for k,lo,hi in lookup if max(lo,blo)<=min(hi,bhi)]
            if not selected:continue
            nn=blk["nnodes"][:].astype(np.int64)
            ptr=np.r_[0,np.cumsum(nn)]
            for key,lo,hi in selected:
                counts=nn[lo-blo:hi-blo+1]
                logical=ptr[lo-blo:hi-blo+1]-ptr[lo-blo]
                ids=blk["nodes"][ptr[lo-blo]:ptr[hi-blo+1]]
                corners=xyz[ids]
                r=out.setdefault(key,dict(area_m2=0.,min_xyz=[float("inf")]*3,max_xyz=[-float("inf")]*3))
                for count in np.unique(counts):
                    if count<3:raise ValueError("Unexpected non-face in physical zone "+key)
                    head=logical[counts==count]
                    poly=corners[head[:,None]+np.arange(count)]
                    # Triangle fans cover triangles, quadrilaterals, and coplanar polygons.
                    area=np.linalg.norm(np.cross(poly[:,1:-1]-poly[:,:1],poly[:,2:]-poly[:,:1]),axis=2).sum()*.5
                    r["area_m2"]+=float(area)
                r["min_xyz"]=np.minimum(r["min_xyz"],corners.min(0)).tolist()
                r["max_xyz"]=np.maximum(r["max_xyz"],corners.max(0)).tolist()
    if set(out)!=WALLS|{"symmetry"}:
        raise ValueError("Missing native physical boundary geometry")
    return out

def inspect(evidence,registered):
    import h5py
    import numpy as np
    from ftm_failure_faces import face_counts
    from cut_fluent_cells import bounds,read_id_blocks
    normal=evidence/"full_volume.msh.h5"
    path=normal if normal.is_file() else evidence/"state_at_fill_error.msh.h5"
    if not path.is_file():raise ValueError(f"Native stage produced no snapshot: {evidence}")
    info=face_counts(path)
    count={}
    with h5py.File(path) as file:
        m=file["meshes/1"]
        if "cells/zoneTopology/minId" in m and len(m["cells/zoneTopology/minId"]):
            cellmax=int(max(m["cells/zoneTopology/maxId"]))
            types=np.zeros(cellmax+1,dtype=np.int16)
            for lo,hi,kind in zip(m["cells/zoneTopology/minId"][:],m["cells/zoneTopology/maxId"][:],m["cells/zoneTopology/cellType"][:],strict=True):
                types[int(lo):int(hi)+1]=kind
            for block in m.get("cells/ctype",{}).values():
                lo,hi=bounds(block)
                if "cell-types" in block:types[lo:hi+1]=block["cell-types"][:]
            codes,counts=np.unique(types[1:],return_counts=True)
            count=dict(zip(map(str,codes),map(int,counts)))
            face=m["faces"];n=int(max(face["zoneTopology/maxId"]))
            owner=read_id_blocks(face["c0"],n,np.int64)
            neighbor=read_id_blocks(face["c1"],n,np.int64)
            top=face["zoneTopology"]
            for row,a,b in zip(info["zones"],top["minId"][:],top["maxId"][:],strict=True):
                sl=slice(int(a),int(b)+1)
                c0,c1=owner[sl],neighbor[sl]
                row["wedge_connected_boundary_faces"]=int(np.count_nonzero(((c0>0)^(c1>0))&(types[np.maximum(c0,c1)]==6)))
    zones={r["name"]:r for r in info["zones"]}
    physical_ok=all(n in zones and zones[n]["zone_type"]==3 and zones[n].get("wedge_connected_boundary_faces",0)>0 for n in WALLS)
    sym_ok=any(n.lower().startswith("symmetry") and row["zone_type"]==7 for n,row in zones.items())
    walls_present=all(n in zones and zones[n]["zone_type"]==3 for n in WALLS)
    reference=physical_boundary_geometry(registered)
    current=physical_boundary_geometry(path) if walls_present and sym_ok else {}
    geometry={}
    for key in sorted(reference):
        if key not in current:continue
        before,after=reference[key],current[key]
        span_error=float(np.max(np.abs(np.r_[before["min_xyz"],before["max_xyz"]]-np.r_[after["min_xyz"],after["max_xyz"]])))
        rel=abs(after["area_m2"]-before["area_m2"])/before["area_m2"]
        geometry[key]=dict(input_area_m2=before["area_m2"],snapshot_area_m2=after["area_m2"],
                           relative_area_change=rel,maximum_bbox_shift_m=span_error)
    # These measurements accompany the snapshot. Preserve P2's separate CAD probes as the geometry authority.
    safe_candidates=[r["name"] for r in info["zones"] if r["name"].lower().startswith(("prism-side","prism-cap"))
                     and r["one_sided_quads"] and r["total_faces"]==r["one_sided_quads"]
                     and r["zone_type"]!=7 and not any(k in r["name"].lower() for k in ("symmetry","wall_","farfield","runway","origin"))]
    returned=(evidence/"volume_returned.flag").is_file()
    valid=(path==normal and returned and count.get("4",0)>0 and count.get("7",0)>0 and walls_present and sym_ok)
    if valid:kind="full_native_fill_raw"
    elif path==normal:kind="unconfirmed_normal_return"
    elif not sum(count.values()):kind="failed_native_fill_rolled_back_surface"
    elif count.get("6",0) or physical_ok:kind="failed_native_fill_prism_state"
    else:kind="failed_native_fill_other_state"
    info.update(source=str(path),source_sha256=digest(path),cell_type_counts=count,result_kind=kind,
                all_walls_wedge_connected=physical_ok,symmetry_present=sym_ok,physical_boundary_geometry=geometry,
                full_native_fill_checkpoint=valid,eligible_for_production=False,isolated_all_quad_prism_side_or_cap_zones=safe_candidates,
                disposition="Preserve symmetry, physical walls and ambiguous zones. A complete raw fill requires native improvement, independent reload and all P2 checks.")
    write(evidence/"prism_interface_audit.json",info)
    return info

def main():
    from control_gate import ControlGate
    def check():
        code=ControlGate().check()["exit_code"]
        if code:raise SystemExit(code)
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument("action",choices=["prepare","run","inspect"])
    ns=ap.parse_args();check()
    work=ROOT/"02_mesh/coarse"/STEM
    cfg=prepare(work) if ns.action=="prepare" else json.loads((work/"mesh_config.json").read_text(encoding="utf8"))
    evidence=Path(cfg["evidence"])
    if ns.action=="prepare":
        print(f"Staged native input {work}. Evidence {evidence}");check();return
    if ns.action=="inspect":
        info=inspect(evidence,Path(cfg["registered"]));print(info["result_kind"]);check();return
    if any(evidence.iterdir()) or any(work.glob("fluent-*.trn")):
        raise ValueError("Retain previous stage evidence; prepare a fresh attempt rather than overwriting it.")
    if digest(Path(cfg["registered"]))!=cfg["registered_sha256"] or digest(Path(cfg["size_field"]))!=cfg["size_field_sha256"]:
        raise ValueError("Input changed after preparation")
    check()
    rc=subprocess.run([sys.executable,"-B",str(ROOT/"scripts/run_fluent_managed.py"),"--mode","meshing","--gui",
        "--dim","3ddp","--procs","4","--workdir",str(work),"--journal",str(work/"mesh.jou"),
        "--stage","S2_MESH_STUDY","--case","coarse_scoped_prism_stage_20"],cwd=ROOT).returncode
    check()
    if any(evidence.glob("*.msh.h5")):
        try:
            info=inspect(evidence,Path(cfg["registered"]))
            print(info["result_kind"])
            if not rc and not info["full_native_fill_checkpoint"]:rc=2
        except (OSError,ValueError,KeyError):
            if not rc:raise
    elif not rc:raise ValueError("Native process exited without a raw fill or diagnostic CFF")
    check()
    if rc:raise SystemExit(rc)

if __name__=="__main__":main()
