"""Capture the live failed FTM state and enumerate its native CFF face topology."""
import json
import os
from pathlib import Path
import subprocess
import uuid

def scope():
    root=Path(os.environ["X57_WORKSPACE"]).resolve(strict=True)
    return root, root/".venv"/"Scripts"/"python.exe"

def control_code(work,root,python):
    command=[str(python),"-B",str(root/"scripts/control_gate.py"),"check"]
    result=subprocess.run(command,cwd=root,capture_output=True).returncode
    if result:
        return result
    return 20 if any((work/f).exists() for f in ("exit-fluent","exit-fluent.txt")) else 0

def save_report(path,value):
    temp=path.with_suffix(".pending.json")
    temp.write_text(json.dumps(value,indent=2,ensure_ascii=True),encoding="utf-8")
    temp.replace(path)

def capture(meshing,work,task,error,traceback_text,utilities=None):
    root,python=scope()
    work=work.resolve(strict=True)
    if work.parent.parent!=root/"02_mesh" or control_code(work,root,python):
        return
    folder=root/"logs"/"ftm_failed_fills"/work.parent.name/work.name/uuid.uuid4().hex
    folder.mkdir(parents=True,exist_ok=False)
    report=folder/"failure.json"
    snapshot=folder/"partial.msh.h5"
    data=dict(eligible_for_production=False,attempt=str(work),original_error=str(error),
              exception_type=type(error).__name__,traceback=traceback_text,
              native_write_method="meshing.File.WriteMesh(FileName=...)",snapshot_requested=str(snapshot),
              snapshot_state="native_write_requested")
    # Geometry can roll back inside Execute; retain native error evidence first.
    for attribute in ("State","Errors"):
        try:
            data["task_"+attribute.lower()]=getattr(task,attribute).get_state()
        except Exception as exc:
            data["task_"+attribute.lower()+"_unavailable"]=repr(exc)
    candidates=list(work.glob(f"fluent-*-{os.getpid()}.trn"))
    if len(candidates)==1:
        trn=candidates[0]
        try:
            with trn.open("rb") as stream:
                stream.seek(max(0,trn.stat().st_size-16384))
                data["native_transcript_tail"]=stream.read().decode("utf-8",errors="replace")
            data["native_transcript"]=str(trn)
        except OSError as exc:
            data["transcript_read_error"]=repr(exc)
    save_report(report,data)
    print("X57 failed FTM evidence:",str(report),flush=True)
    if control_code(work,root,python):
        return
    if utilities is not None:
        try:
            data["native_face_zone_ids_by_filter"]={key:utilities.get_face_zones(filter=key)
                for key in ("*prism*side*","*prism*cap*","*symmetry*")}
            save_report(report,data)
        except Exception as exc:
            data["native_face_zone_query_error"]=repr(exc)
    if control_code(work,root,python):
        return
    try:
        meshing.File.WriteMesh(FileName=snapshot.as_posix())
        if not snapshot.is_file() or not snapshot.stat().st_size:
            raise ValueError("No nonempty CFF was written by the live native mesher")
    except Exception as exc:
        if control_code(work,root,python):
            return
        data.update(snapshot_state="write_failed",native_write_error=repr(exc))
        save_report(report,data)
        return
    if control_code(work,root,python):
        return
    # Use the isolated project environment for h5py. No second Fluent process is started.
    args=[str(python),"-B",str(root/"scripts/ftm_failure_faces.py"),str(report)]
    done=subprocess.run(args,cwd=root,capture_output=True)
    if done.returncode and done.returncode not in (10,20,30,40) and not control_code(work,root,python):
        data.update(snapshot_state="face_report_failed",analysis_error=done.stderr.decode(errors="replace")[-3000:])
        save_report(report,data)

def face_counts(path):
    import h5py
    import numpy as np
    from cut_fluent_cells import bounds,read_id_blocks
    with h5py.File(path,"r") as h5:
        mesh=h5["meshes/1"];faces=mesh["faces"];top=faces["zoneTopology"]
        names=top["name"][0].decode().rstrip(";").split(";")
        mins=top["minId"][:];maxs=top["maxId"][:]
        nf=int(max(maxs))
        nodes_per_face=np.zeros(nf+1,dtype=np.int32)
        for block in faces["nodes"].values():
            first,last=bounds(block)
            nodes_per_face[first:last+1]=block["nnodes"][:]
        volume="cells/zoneTopology/maxId" in mesh and len(mesh["cells/zoneTopology/maxId"])>0
        c0=read_id_blocks(faces["c0"],nf,np.int64) if "c0" in faces else None
        c1=read_id_blocks(faces["c1"],nf,np.int64) if "c1" in faces else None
        adj=volume and c0 is not None and c1 is not None
        records=[]
        for nm,zid,kind,a,b in zip(names,top["id"][:],top["zoneType"][:],mins,maxs,strict=True):
            idx=slice(int(a),int(b)+1)
            counts=nodes_per_face[idx]
            if np.any(counts<=0):
                raise ValueError(f"Missing native node counts in face zone {nm}")
            quad=counts==4
            match=nm.lower().replace("_","-")
            family=next((s for s in ("prism-side","prism-cap","symmetry-quad","symmetry") if s in match),"other")
            record=dict(name=nm,zone_id=int(zid),zone_type=int(kind),family=family,total_faces=len(counts),
                        triangles=int(np.count_nonzero(counts==3)),quads=int(np.count_nonzero(quad)),
                        one_sided_quads=None,two_sided_quads=None,unattached_quads=None)
            if adj:
                sides=(c0[idx]>0).astype(np.int8)+(c1[idx]>0)
                record.update(one_sided_quads=int(np.sum(quad&(sides==1))),
                              two_sided_quads=int(np.sum(quad&(sides==2))),
                              unattached_quads=int(np.sum(quad&(sides==0))))
            records.append(record)
    named=[r for r in records if r["family"]!="other" or r["quads"]]
    return dict(snapshot_state="volume_topology_saved" if volume else "surface_only_after_failure",
                total_faces=sum(r["total_faces"] for r in records),
                total_quads=sum(r["quads"] for r in records),
                total_one_sided_quads=sum(r["one_sided_quads"] for r in records) if adj else None,
                named_prism_side_cap_one_sided_quads=sum(r["one_sided_quads"] for r in records
                    if r["family"] in ("prism-side","prism-cap")) if adj else None,
                note="One-sided means that exactly one native C0/C1 cell exists. Physical symmetry, wall and other intended boundaries are included in the per-zone counts. The prism-side/cap subtotal covers only those names retained by Fluent. A post-error rollback to a surface cannot measure failed-volume exposure.",
                interface_or_quad_zone_names=[r["name"] for r in named],zones=records)

def summarize(report):
    root,python=scope()
    report=report.resolve(strict=True)
    if not report.is_relative_to(root/"logs/ftm_failed_fills") or report.name!="failure.json":
        raise ValueError("Expected a failed-fill diagnostic report")
    data=json.loads(report.read_text(encoding="utf-8"))
    work=Path(data["attempt"])
    code=control_code(work,root,python)
    if code:
        raise SystemExit(code)
    snapshot=report.parent/"partial.msh.h5"
    data.update(face_counts(snapshot))
    code=control_code(work,root,python)
    if code:
        raise SystemExit(code)
    save_report(report,data)
    print("Native diagnostic CFF measured",data["total_faces"],"faces in",len(data["zones"]),"zones")

if __name__=="__main__":
    import sys
    summarize(Path(sys.argv[1]))
