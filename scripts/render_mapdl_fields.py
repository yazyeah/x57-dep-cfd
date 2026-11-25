"""Display the six MAPDL SHELL181 stress/deformation scenes from converged physical loads."""
import argparse
import json
import os,re
from pathlib import Path

import numpy as np
from control_gate import ControlGate

from compare_x57_cases import ROOT
from assemble_fsi_structural_table import CASES
from mapdl_shell_fields import element_centers, source_hash
from fsi_provenance import accepted_result
GATE=ControlGate()

def check():
    code=GATE.check()["exit_code"]
    if code:
        raise SystemExit(code)

STRUCT=ROOT/"03_cases"/"fsi_structural"
OUT=ROOT/"DELIVERABLES"/"fluent_renders"


def physical_shell(case="fine_rpm100"):
    if case not in CASES:
        raise ValueError(f"Unsupported structural operating point {case}")
    model=STRUCT/"models"/"fine"/"shell_mesh.npz"
    work=STRUCT/("fine_struct__"+case)
    metrics,source=accepted_result("fine",case)
    with np.load(model) as data: mesh=dict(data)
    with np.load(work/"shell_fields.npz") as data: fields=dict(data)
    n=len(mesh["elements"])
    centers=element_centers(mesh["xyz"],mesh["elements"])
    if not np.array_equal(fields["element_id"],np.arange(1,n+1)) or not np.allclose(fields["centroid_m"],centers,rtol=0,atol=1.e-11):
        raise ValueError("MAPDL fields do not match the Fine structural mesh")
    if not np.array_equal(fields["node_id"],np.arange(1,len(mesh["xyz"])+1)):
        raise ValueError("MAPDL displacement rows do not correspond to shell node IDs")
    for key,expected in [("section",mesh["element_section"]),("wingbox",mesh["wingbox"]),("pylon",mesh["pylon"])]:
        if not np.array_equal(fields[key],expected):
            raise ValueError(f"MAPDL region identity mismatch {key}")
    metrics["source_provenance"]=source
    return mesh,fields,metrics


def build_panels(numbers,mesh,fields):
    from native_mapdl_deck import ENGINEERING,SIGNED,fields_for_comparison
    values=fields_for_comparison(fields)
    centers=fields["centroid_m"]
    rotor=json.loads((ROOT/"01_geometry"/"geometry_audit.json").read_text())["starboard_propellers_detected"][2]
    z,x=rotor["z_axis_m"],rotor["x_disk_m"]
    def in_box(lower,upper):
        return np.all((centers>=lower)&(centers<=upper),axis=1)
    masks={
        "skin": np.isin(fields["section"],np.arange(5)),
        "root": in_box([-.6,-.3,.48],[.65,.36,1.35]),
        "pylon3": fields["pylon"] & in_box([x-.05,-.33,z-.21],[.4,.38,z+.21]),
        "internal": fields["wingbox"] | fields["pylon"],
    }
    if abs(mesh["xyz"][:,2].min())>1e-6:
        raise ValueError("Exterior mirror needs a solved starboard half-model ending at z=0")
    vmax=float(values["VMMPA"].max())
    min_fos=float(fields["safety_factor"].min())
    umax=float(fields["displacement_magnitude_m"].max())
    if not np.isfinite([vmax,min_fos,umax]).all() or min(vmax,min_fos,umax)<=0:
        raise ValueError("Invalid structural extrema")
    magnification=.055*float(np.ptp(mesh["xyz"][:,2]))/umax
    skin=masks["skin"]
    principal=max(np.abs(values["S1MPA"][skin]).max(),np.abs(values["S3MPA"][skin]).max())
    shear=np.abs(values["XYMPA"][masks["internal"]]).max()
    # Scalar invariants can be reflected in these projections. Signed local-coordinate
    # shear is drawn on the actual solved elements only.
    upper=(-3,9,0); lower=(-3,-9,0); iso=(-6.5,9.5,8)
    panels=[]
    def add(number,region,key,title,label,view,limits=None,palette=ENGINEERING,note=None):
        if number not in numbers:
            return
        unit_scale=1.
        if key=="U":
            unit_scale=1000.
            nodes=np.unique(mesh["elements"][masks[region]])
            arr=fields["displacement_magnitude_m"][nodes]*unit_scale
        else:
            arr=values[key][masks[region]]
        if not len(arr):
            raise ValueError(f"Empty MAPDL picture selection {region}")
        actual=[float(arr.min()),float(arr.max())]
        bounds=[float(v) for v in (limits if limits is not None else actual)]
        if bounds[1]<=bounds[0]:
            raise ValueError(f"Degenerate field range {key} in {region}")
        mirrored=region=="skin"
        command="PLNSOL,U,SUM,1" if key=="U" else "PLETAB,"+key+",NOAV"
        panel=dict(number=number,region=region,field=key,label=title,unit_label=label,
                   color_limits=bounds,actual_range=actual,palette=list(palette),
                   label_multiplier=unit_scale,view_vector=list(view),up="X" if mirrored else "Y",
                   mirror_z0=mirrored,plot_command=command,
                   note=note or ("Full exterior from solved starboard symmetry." if mirrored else
                                f"Solved starboard elements. Local range {actual[0]:.4g} to {actual[1]:.4g} MPa."))
        if key=="FOSCAP":
            genuine=fields["safety_factor"][masks[region]]
            finite=genuine[np.isfinite(genuine)]
            panel["unclipped_finite_range"]=[float(finite.min()),float(finite.max())] if len(finite) else None
            panel["zero_stress_elements"]=int(np.sum(~np.isfinite(genuine)))
        if key=="U":
            panel["deformation_factor"]=magnification
        panels.append(panel)
    from fasttrack_profile import STRESS_SCALE_MAX_MPA,STRESS_YIELD_MPA,STRESS_DESIGN_FACTOR
    for number,view,side in ((17,upper,"Upper"),(18,lower,"Lower")):
        add(number,"skin","VMMPA",side+" exterior","von Mises stress (MPa)",view,[0.,STRESS_SCALE_MAX_MPA],
            note=(f"Symmetric exterior. Allowable-stress scale 0–{STRESS_SCALE_MAX_MPA:.1f} MPa "
                  f"(yield {STRESS_YIELD_MPA:.0f} MPa / {STRESS_DESIGN_FACTOR}); both shell faces enveloped. "
                  f"Actual skin maximum {float(values['VMMPA'][masks['skin']].max()):.1f} MPa."))
    add(19,"root","VMMPA","Wing-root junction","von Mises stress (MPa)",(-2,2.5,2.1))
    add(19,"pylon3","VMMPA","HLP-3 pylon attachment","von Mises stress (MPa)",(-2.1,-2,2.2))
    add(20,"skin","S1MPA","Maximum principal stress","σ₁ (MPa)",upper,[-principal,principal],SIGNED)
    add(20,"skin","S3MPA","Minimum principal stress","σ₃ (MPa)",lower,[-principal,principal],SIGNED)
    add(21,"internal","TRESCA","Wing box and motor mounts","Tresca maximum shear stress (MPa)",iso)
    add(21,"internal","XYMPA","Element-local in-plane shear","Signed local τxy (MPa)",iso,[-shear,shear],SIGNED,
        note="Solved side. Shell face with the greater shear magnitude; signed in element axes.")
    add(22,"skin","U","Deformed and undeformed exterior","Total displacement (mm)",upper,[0,umax*1000],
        note=f"Deformation magnified {magnification:.4g}×; native undeformed outline overlaid.")
    add(22,"skin","FOSCAP","Yield safety factor","Yield stress / von Mises stress",upper,[0,20],ENGINEERING[::-1],
        note=f"503 MPa nominal yield. Values ≥20 share the last bin. Actual global minimum {min_fos:.4g}.")
    return panels,masks,(vmax,min_fos,umax)


def run_native(folder,job):
    import msvcrt
    import subprocess
    import psutil
    from run_fluent_managed import build_f_only_env,attach_kill_on_close_job,close_job_handle
    from run_mapdl_structural import EXE
    from native_mapdl_deck import MARKER
    check()
    log=folder/(job+".out")
    cmd=[str(EXE),"-b","-smp","-np","2","-dir",str(folder),"-j",job,
         "-i",str(folder/"render.inp"),"-o",str(log)]
    with (ROOT/"CONTROL/fluent_seat.lock").open("a+b") as seat:
        seat.seek(0)
        try:
            msvcrt.locking(seat.fileno(),msvcrt.LK_NBLCK,1)
        except OSError as err:
            raise RuntimeError("Student seat is occupied; MAPDL rendering requires the production seat") from err
        check()
        process=subprocess.Popen(cmd,cwd=folder,env=build_f_only_env(),creationflags=0x00000004|subprocess.CREATE_NO_WINDOW)
        handle=None
        try:
            handle=attach_kill_on_close_job(process)
            if not handle:
                raise RuntimeError("Could not contain native MAPDL process tree")
            GATE.register_pid(process.pid,"mapdl_post1_renders",str(folder),job)
            psutil.Process(process.pid).resume()
            import time as _time
            limit_s=60.*float(os.environ.get("X57_MAPDL_MAX_WALL_MIN","40"))
            started_s=_time.monotonic()
            while process.poll() is None:
                if _time.monotonic()-started_s>limit_s:
                    raise RuntimeError(f"Fast-track MAPDL render wall limit exceeded ({limit_s/60:.0f} min): {log}")
                interrupted=GATE.check()["exit_code"]
                if interrupted:
                    # POST1 produces pictures only; the signed solved RST already exists.
                    (folder/(job+".abt")).write_text("nonlinear\n",encoding="ascii")
                    raise SystemExit(interrupted)
                try:
                    process.wait(timeout=1)
                except subprocess.TimeoutExpired:
                    continue
        finally:
            close_job_handle(handle)
            if process.poll() is None:
                process.kill()
            process.wait()
            GATE.unregister_pid(process.pid)
    check()
    transcript=log.read_text(errors="replace")
    if process.returncode or MARKER not in transcript or re.search(r"\*{3}\s*(ERROR|FATAL)\s*\*{3}",transcript,re.I):
        raise RuntimeError(f"Native MAPDL render did not complete cleanly: {log}")
    return log


def plot_scenes(numbers,case="fine_rpm100"):
    import shutil,tempfile
    from fsi_provenance import commit
    from native_mapdl_deck import plot_deck,verify_readback
    from native_mapdl_layout import compose
    from verify_deliverables import REQUIRED_FLUENT_RENDERS
    check()
    study=json.loads((ROOT/"DELIVERABLES/data/fsi_structural_stress.json").read_text())
    if not study.get("stress_mesh_study_complete",study.get("stress_mesh_QA_passed")):
        raise ValueError("Three-mesh structural convergence must pass before rendering")
    mesh,fields,metrics=physical_shell(case)
    native=metrics["source_provenance"]
    work=STRUCT/("fine_struct__"+case)
    dest=OUT if case=="fine_rpm100" else ROOT/"04_postproc"/"fsi_structural"/case/"renders"
    name={"fine_rpm100":"Static baseline","medium_rpm100_takeoff_v10":"Take-off roll, 10 m/s",
          "medium_opt_hlp_vector10":"Vectored HLP, 10 degrees"}[case]
    panels,masks,extrema=build_panels(numbers,mesh,fields)
    rst=(work/(native["job"]+".rst")).resolve()
    sf=work/"native_result_provenance.json"
    folder=Path(tempfile.mkdtemp(prefix="post1_",dir=work))
    job="post1"
    shutil.copyfile(work/"model.inp",folder/"model.inp")
    os.link(rst,folder/"source.rst")
    deck=folder/"render.inp"
    deck.write_text(plot_deck(panels,masks),encoding="ascii")
    log=run_native(folder,job)
    check()
    raw=sorted(folder.glob(job+"[0-9][0-9][0-9].png"))
    if [r.name for r in raw]!=[f"{job}{i:03}.png" for i in range(len(panels))]:
        raise ValueError(f"Unexpected MAPDL picture sequence in {folder}")
    eread,nread=verify_readback(folder,fields)
    check()
    _,confirmed=accepted_result("fine",case)
    if confirmed!=native:
        raise ValueError("Source solve changed while MAPDL was rendering")
    dest.mkdir(parents=True,exist_ok=True)
    manifest=work/"render_sources.json"
    old=json.loads(manifest.read_text()) if manifest.is_file() else {}
    meta={k:v for k,v in old.items() if v.get("result_sha256")==native["sha256"][str(rst)]}
    common_paths=[deck,log,eread,nread,folder/"model.inp",sf]
    tools_used=[Path(__file__).with_name(f) for f in ("render_mapdl_fields.py","native_mapdl_deck.py","native_mapdl_layout.py")]
    common={str(p):source_hash(p) for p in common_paths+tools_used}
    for number in sorted(set(numbers)):
        check()
        pairs=[(p,r) for p,r in zip(panels,raw) if p["number"]==number]
        selected,images=map(list,zip(*pairs))
        final=dest/REQUIRED_FLUENT_RENDERS[number-1]
        tmp=folder/f"render{number}.png"
        compose(selected,images,name,*extrema).save(tmp,format="PNG",dpi=(400,400))
        temp_dest=final.with_suffix(".pending.png")
        shutil.copyfile(tmp,temp_dest)
        os.replace(temp_dest,final)
        meta[final.name]=dict(solver="Mechanical APDL 2025 R2 SHELL181",renderer="ANSYS Mechanical APDL POST1",
            title=name,source_case=case,load_signature=native["load_signature"],result_file=str(rst),
            result_sha256=native["sha256"][str(rst)],native_source_manifest=str(sf),job=job,
            batch_directory=str(folder),raw_pngs=[str(p) for p in images],
            native_evidence_sha256={**common,**{str(p):source_hash(p) for p in images}},
            half_model_display="Global scalar pictures are reflected at z=0 in a symmetry-plane orthographic projection. Internal signed shear is plotted only on its solved side.",
            assumption=metrics["interpretation"],image_sha256=source_hash(final),path=str(final),
            peak_vm_MPa=extrema[0],min_yield_safety_factor=extrema[1],max_displacement_m=extrema[2],panels=selected)
        commit(manifest,meta)
        check()


if __name__=="__main__":
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--numbers",type=int,nargs="+",choices=range(17,23),default=list(range(17,23)))
    p.add_argument("--cases",nargs="+",choices=CASES,default=CASES)
    args=p.parse_args()
    for operation in args.cases:
        plot_scenes(args.numbers,operation)

