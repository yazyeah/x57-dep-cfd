"""Package the actual Fine endpoint in Fluent and audit the full coursework deliverable set."""
import argparse
import csv
import math
import datetime as dt
import hashlib
import json
import os
import shutil
import sys
from pathlib import Path

import h5py
import numpy as np
from PIL import Image

from assess_fluent_case import flux_value
from compare_x57_cases import CASES3, ROOT, accepted
from control_gate import atomic_write_json
from fluent_checkpoints import latest_pair, check_mesh_file
from prepare_airfoil_sections import CASES as SECTION_CASES
from run_x57_converged import control, managed_step, grid_for
import verify_deliverables as spec

D=ROOT/"DELIVERABLES"
A=D/"ansys_submission"
SOURCE=ROOT/"04_postproc"/"package_verification"
BASENAME="X57_DEP_fine_rpm100"


def digest(p):
    h=hashlib.sha256()
    with p.open("rb") as f:
        for piece in iter(lambda:f.read(8<<20),b""):h.update(piece)
    return h.hexdigest()


def journal(name,commands):
    control()
    p=SOURCE/(name+".jou")
    p.write_text('/file/confirm-overwrite no\n(set! checkpoint/exit-filename "exit-fluent.txt")\n(set! checkpoint/check-filename "check-fluent.txt")\n'+commands+'\n/exit ok\n',encoding="utf-8")
    managed_step([sys.executable,"-B",str(ROOT/"scripts/run_fluent_managed.py"),"--mode","solver","--gui",
                  "--dim","3ddp","--procs","4","--workdir",str(SOURCE),"--journal",str(p),"--stage","P12","--case",name])


def spatial_cell_order(case):
    """Canonical cell ordering by identical physical faces, independent of MPI numbering."""
    from collections import defaultdict
    from cut_fluent_cells import bounds,read_id_blocks
    def canonical_rows(matrix):
        matrix=np.ascontiguousarray(matrix,dtype="<i4")
        keys=matrix.view(np.dtype((np.void,matrix.shape[1]*matrix.dtype.itemsize))).ravel()
        order=np.argsort(keys,kind="stable")
        if np.any(keys[order[1:]]==keys[order[:-1]]):
            raise ValueError("Ambiguous duplicate physical face or cell")
        return order,matrix[order]
    with h5py.File(case) as h:
        m=h["meshes/1"]
        nnode=int(max(m["nodes/zoneTopology/maxId"]));nf=int(max(m["faces/zoneTopology/maxId"]))
        nc=int(max(m["cells/zoneTopology/maxId"]))
        xyz=read_id_blocks(m["nodes/coords"],nnode,float,3)[1:]
        if not np.isfinite(xyz).all():raise ValueError("Nonfinite grid coordinates")
        coordinates,node=np.unique(np.rint(xyz*1.e9).astype("<i8"),axis=0,return_inverse=True)
        token=hashlib.sha256(coordinates.tobytes())
        entries=defaultdict(list)
        for block in m["faces/nodes"].values():
            lo,hi=bounds(block)
            n=block["nnodes"][:].astype("i4")
            start=np.r_[0,np.cumsum(n[:-1],dtype="i8")]
            vertex_ids=block["nodes"][:].astype("i4")-1
            for width in np.unique(n):
                group=np.flatnonzero(n==width)
                vertices=node[vertex_ids[start[group,None]+np.arange(width)]].astype("<i4")
                vertices.sort(axis=1)
                entries[int(width)].append((lo+group,vertices))
        face_rank=np.zeros(nf+1,"i4");offset=1
        for width in sorted(entries):
            blocks=entries.pop(width)
            ids=np.concatenate([v[0] for v in blocks])
            order,rows=canonical_rows(np.concatenate([v[1] for v in blocks]))
            token.update(np.array([width,len(ids)],"<i8").tobytes());token.update(memoryview(rows).cast("B"))
            face_rank[ids[order]]=np.arange(offset,offset+len(ids))
            offset+=len(ids)
        if not np.all(face_rank[1:]>0):raise ValueError("Missing faces in the grid")
        own=read_id_blocks(m["faces/c0"],nf,np.int32)[1:]
        adj=read_id_blocks(m["faces/c1"],nf,np.int32)[1:]
        cell=np.r_[own,adj];faces=np.tile(face_rank[1:],2)
        valid=cell>0;cell,faces=cell[valid],faces[valid]
        order=np.lexsort((faces,cell));faces=faces[order]
        lengths=np.bincount(cell,minlength=nc+1)[1:]
        if len(lengths)!=nc or min(lengths)<4:raise ValueError("Incomplete 3D cell-face incidence")
        starts=np.r_[0,np.cumsum(lengths[:-1])]
        canonical=[]
        for width in np.unique(lengths):
            ids=np.flatnonzero(lengths==width)
            order,rows=canonical_rows(faces[starts[ids,None]+np.arange(width)])
            token.update(np.array([width,len(ids)],"<i8").tobytes());token.update(memoryview(rows).cast("B"))
            canonical.extend([ids[order]+1])
        return np.concatenate(canonical),token.hexdigest()


def compare_solution(src_case,src_data,dest_case,dest_data):
    from cut_fluent_cells import read_id_blocks
    a_order,a_key=spatial_cell_order(src_case);b_order,b_key=spatial_cell_order(dest_case)
    if a_key!=b_key:raise ValueError("Submission lacks one-to-one matching cell geometry")
    result={"geometry_sha256":a_key,"cell_count":len(a_order),"primary_max_abs_delta":{}}
    with h5py.File(src_data) as orig,h5py.File(dest_data) as copied:
        for key in ("SV_P","SV_U","SV_V","SV_W","SV_DENSITY","SV_T","SV_K","SV_O","SV_MU_T"):
            path="results/1/phase-1/cells/"+key
            a=read_id_blocks(orig[path],len(a_order),float)[a_order]
            b=read_id_blocks(copied[path],len(b_order),float)[b_order]
            if not np.isfinite(a).all() or not np.isfinite(b).all():raise ValueError(f"Missing or nonfinite {key}")
            delta=float(np.max(np.abs(a-b)))
            if key=="SV_MU_T":
                result["derived_eddy_viscosity_max_abs_delta_Pa_s"]=delta
            else:
                if not np.allclose(a,b,rtol=5.e-8,atol=1.e-9):raise ValueError(f"Packaged {key} changed at corresponding cells")
                result["primary_max_abs_delta"][key]=delta
    return result


def package():
    control()
    qa,cas,dat=accepted("fine_rpm100")
    A.mkdir(exist_ok=True,parents=True)
    SOURCE.mkdir(exist_ok=True,parents=True)
    target_c=A/(BASENAME+".cas.h5");target_d=A/(BASENAME+".dat.h5");msh=A/(BASENAME+".msh.h5")
    native=grid_for("fine")
    if not msh.is_file() or digest(msh)!=digest(native):
        tmp=A/(BASENAME+".pending.msh.h5")
        shutil.copyfile(native,tmp)
        if digest(native)!=digest(tmp) or not check_mesh_file(tmp,deep=True)[1]:raise ValueError("Submission mesh copy failed")
        os.replace(tmp,msh)
    control()
    auto='/file/auto-save/data-frequency 50\n/file/auto-save/case-frequency each-time\n/file/auto-save/retain-most-recent-files yes\n/file/auto-save/max-files 2'
    previous=SOURCE/"native_pair_sources.json"
    sources={k:digest(v) for k,v in (("source_case",cas),("source_data",dat),("source_mesh",native))}
    ready=(previous.is_file() and json.loads(previous.read_text())==sources and target_c.is_file() and target_d.is_file())
    if not ready:
        journal("package_fine_named_pair",f'/file/read-case "{cas.as_posix()}"\n/file/read-data "{dat.as_posix()}"\n{auto}\n/file/write-case-data "{target_c.as_posix()}"')
    c,d,errors=latest_pair(A,deep=True)
    if c!=target_c or d!=target_d:raise ValueError(f"Incomplete renamed native pair {errors}")
    field_errors=compare_solution(cas,dat,c,d)
    atomic_write_json(previous,sources)
    capture=SOURCE/"read_back.py"
    capture.write_text('''import os,sys,json
from pathlib import Path
sys.path.insert(0,str(Path(os.environ["FLUENT_PROD_DIR"])/"cortex/pylib"))
import flsetup
flsetup.insert_pyfluent_module_path()
from flapi.flproxy import Proxy
from flapi.generated.solver.settings_252 import root
s=root()
s.set_flproxy(Proxy)
report=s.solution.report_definitions
keys=("airframe-lift-half","airframe-drag-half","wing-lift-half","airframe-pitch-mz-half")
Path("reload_forces.json").write_text(json.dumps({k:report.compute(report_defs=[k]) for k in keys}))
''',encoding="utf-8")
    journal("reload_packaged_fine",f'''/file/read-case "{target_c.as_posix()}"
/file/read-data "{target_d.as_posix()}"
{auto}
/mesh/check
(%py-exec "exec(open('{capture.as_posix()}',encoding='utf-8').read())")''')
    recorded=json.loads((SOURCE/"reload_forces.json").read_text())
    f=qa["half_model_endpoint_force_N"]
    m=qa["half_model_endpoint_pitch_Nm"]
    expected={"airframe-lift-half":f["airframe"]["ForceY"],"airframe-drag-half":f["airframe"]["ForceX"],
              "wing-lift-half":f["wing"]["ForceY"],"airframe-pitch-mz-half":m}
    if not isinstance(m,(int,float)):
        expected["airframe-pitch-mz-half"]=flux_value(m,"airframe-pitch-mz-half")
    actual={key:flux_value(value,key) for key,value in recorded.items()}
    if any(not np.isclose(actual[k],float(expected[k]),atol=1.e-5,rtol=1.e-6) for k in expected):
        raise ValueError("Native reload did not reproduce the accepted Fine aerodynamic loads")
    atomic_write_json(SOURCE/"submission_qa.json",dict(passed=True,source_sha256=sources,
        submission_sha256={p.name:digest(p) for p in (msh,c,d)},native_half_aircraft_reports=actual,cell_field_max_delta=field_errors))
    control()


# Source tables combine planes, wall normals, individual faces, and shell elements.
# Keep each sample's physical schema, without blank columns for unrelated domains.
STRESS_SCHEMA = {
    "wake_area_mean": "x_m quantity value unit fluid_area_m2 region_z_y_m",
    "circulation": "x_m quantity value unit fluid_area_m2 region_z_y_m",
    "induced_angle": "x_m y_m z_m quantity value unit component z_lo_m z_hi_m native_cell_id axial_m_s vertical_m_s",
    "boundary_layer": ("x_m y_m z_m quantity value unit station x_over_c face_id native_cell_id "
                       "normal_distance_m normal_interval_start_m normal_interval_end_m y_plus wall_shear_Pa "
                       "u_tau_m_s rho_kg_m3 rho_source mu_Pa_s normal_x normal_y normal_z"),
    "wall_face": ("x_m y_m z_m component native_face_id half_domain_area_m2 "
                  "wall_shear_Pa pressure_gauge_Pa y_plus"),
}
STRESS_LABELS = {"method", "case", "native_case", "native_data", "record_type", "unit", "quantity",
                 "component", "rho_source", "station", "structural_grid", "source_domain"}


def stress_sample(row, source, is_shell):
    from assemble_fsi_structural_table import HEAD
    kind = "shell_element" if is_shell else row["record_type"]
    required = set(HEAD) if is_shell else set(STRESS_SCHEMA[kind].split()) | {
        "method", "case", "native_case", "native_data", "record_type",
    }
    if not all(row.get(key) and row[key].strip() for key in required):
        raise ValueError(f"Missing physical measurement for {source} {kind}: {sorted(k for k in required if not row.get(k) or not row[k].strip())}")
    values = {}
    for key, raw in row.items():
        if not raw:
            continue
        raw = raw.strip()
        if raw.lower() in {"nan", "inf", "-inf", "+inf", "infinity", "-infinity", "+infinity", "none", "null"}:
            raise ValueError(f"Invalid {key} in {source} {kind}")
        if key in STRESS_LABELS:
            values[key] = raw
        elif key == "region_z_y_m":
            window = json.loads(raw)
            if len(window) != 4 or not all(math.isfinite(v) for v in window):
                raise ValueError(f"Invalid plane sampling window in {source}")
            values[key] = window
        else:
            numeric = float(raw)
            if not math.isfinite(numeric):
                raise ValueError(f"Invalid {key} in {source} {kind}")
            values[key] = int(raw) if raw.isdecimal() else numeric
    case_name, x = values.pop("case"), values.pop("x_m")
    values.pop("record_type", None)
    if is_shell:
        quantity, unit = "max_top_bottom_von_mises", "Pa"
        value = max(values["sigma_vm_top_Pa"], values["sigma_vm_bottom_Pa"])
    elif kind == "wall_face":
        quantity, unit, value = "wall_shear", "Pa", values["wall_shear_Pa"]
    else:
        quantity, unit, value = (values.pop(key) for key in ("quantity", "unit", "value"))
    return (source, case_name, kind, x, quantity, unit, value,
            json.dumps(values, ensure_ascii=False, allow_nan=False, separators=(",", ":")))


def export_stress_samples(fluid, shell, output):
    temp = output.with_suffix(".pending.csv")
    with temp.open("w", encoding="utf-8", newline="") as dst:
        writer = csv.writer(dst)
        writer.writerow(("source_table", "case", "record_type", "x_m", "quantity", "unit", "value", "sample_fields_json"))
        for path in (fluid, shell):
            control()
            with path.open(encoding="utf-8-sig", newline="") as src:
                count = 0
                for count, row in enumerate(csv.DictReader(src), 1):
                    writer.writerow(stress_sample(row, path.name, path == shell))
                    if count % 16384 == 0:
                        control()
                if not count:
                    raise ValueError(f"Empty native stress source: {path}")
    control()
    os.replace(temp, output)


def finish():
    import pymupdf
    control()
    for cs in list(CASES3)+list(SECTION_CASES):
        q,c,d=accepted(cs)
        if q.get("passed") is not True or not c.is_file() or not d.is_file():raise ValueError(cs)
    req=json.loads((SOURCE/"submission_qa.json").read_text())
    if not req.get("passed"):raise ValueError("Native reload QA missing")
    for name,h in req["submission_sha256"].items():
        if digest(A/name)!=h:raise ValueError("An Ansys submission file changed after reload")
    fluid=ROOT/"04_postproc/fine_rpm100/stress_and_bl_fluid.csv"
    shell=ROOT/"04_postproc/fsi_structural/stress_and_bl_structural.csv"
    export_stress_samples(fluid, shell, D/"data/stress_and_bl_profiles.csv")
    artifacts=[]
    for name in spec.REQUIRED_DATA_JSON+spec.REQUIRED_DATA_CSV:artifacts.append(D/"data"/name)
    detail={}
    for stem in spec.REQUIRED_FIGURES_STEMS:
        control()
        png,pdf=[D/"figures"/(stem+ext) for ext in (".png",".pdf")]
        with Image.open(png) as im:
            im.load()
            dpi=im.info.get("dpi")
            if not dpi or max(abs(d-400) for d in dpi)>.1:raise ValueError(f"Wrong PNG DPI: {png}")
            dims=im.size
        with pymupdf.open(pdf) as doc:
            fonts={tuple(font[:5]) for page in doc for font in page.get_fonts()}
            if not fonts or not all("timesnewroman" in font[3].replace(" ","").lower() and doc.extract_font(font[0])[-1] for font in fonts):
                raise ValueError(f"PDF font embedding mismatch: {pdf.name}")
            if not any(page.get_text().strip() for page in doc):raise ValueError(f"PDF has no vector text: {pdf.name}")
        detail[stem]=dict(pixels=dims,dpi=dpi,embedded_fonts=sorted({f[3] for f in fonts}))
        artifacts.extend((png,pdf))
    for name in spec.REQUIRED_FLUENT_RENDERS:
        path=D/"fluent_renders"/name
        with Image.open(path) as im:
            im.load()
            if im.width<1920 or im.height<1080:raise ValueError(f"Undersized render {name}")
            detail[name]=dict(pixels=im.size)
        artifacts.append(path)
    artifacts.extend((A/n for n in spec.REQUIRED_ANSYS_FILES))
    control()
    from write_x57_handoff import write as write_handoff
    write_handoff()
    control()
    artifacts.append(D/"handoff_notes.md")
    if any(not path.is_file() for path in artifacts):raise ValueError("Expected a missing deliverable")
    manifest=dict(created_at=dt.datetime.now().astimezone().isoformat(timespec="seconds"),asset_specification="VISUALIZATION_MASTER_BLUEPRINT.md",
                  counts=dict(figures=22,renders=22,data_files=19,fluent_attachments=3),
                  assets=[dict(path=p.relative_to(D).as_posix(),size_bytes=p.stat().st_size,sha256=digest(p)) for p in artifacts],
                  visual_inspection=detail,submission_reload=req)
    atomic_write_json(D/"DELIVERABLES_MANIFEST.json",manifest)
    control()
    with (ROOT/"logs"/"final_deliverables_verification.log").open("w",encoding="utf-8") as out:
        managed_step([sys.executable,"-B",str(ROOT/"scripts/verify_deliverables.py")],stdout=out)
    print((ROOT/"logs"/"final_deliverables_verification.log").read_text(encoding="utf-8").splitlines()[-2])
    control()


if __name__=="__main__":
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("action",choices=("package","verify"))
    (package if p.parse_args().action=="package" else finish)()

