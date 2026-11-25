"""Run actual Fluent graphics scenes on the accepted Fine aircraft endpoint."""
import argparse
import json
import shutil
from control_gate import checked_command
from uuid import uuid4
from cfd_case_identity import digest
from control_gate import atomic_write_json
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont
from scipy import ndimage

from compare_x57_cases import ROOT, accepted
from p2_geometry_io import section_segments
from publication_fonts import font_file
from verify_deliverables import REQUIRED_FLUENT_RENDERS

DEFAULT_NUMBERS = (1,2,3,4,5,6,7,8,9,10,13,14,15,16)
TITLES={"pressure":"Static pressure","pressure-top":"Static pressure","pressure-bottom":"Static pressure",
        "wall-shear-top":"Wall shear","wall-shear-bottom":"Wall shear","surface-yplus":"Wall y+",
        "x57-r15-shell":"Modeled shear", "x57-r15-slices":"Modeled shear",
        "x57-r16-shell":"Speed", "x57-r16-slices":"Total pressure coeff.",
        "q-speed":"Velocity","velocity-magnitude":"Velocity"}


def gated():
    checked_command([sys.executable, str(ROOT/"scripts/control_gate.py"),"check"])


def colorbar_pixels(raw, clean):
    delta=np.max(np.abs(raw.astype(np.int16)-clean),axis=-1)>24
    chroma=np.ptp(raw.astype(np.int16),axis=-1)>18
    # The image and camera are identical except for Fluent's scalar bar and text.
    mask=ndimage.binary_closing(delta & chroma,structure=np.ones((9,1)))
    labels,_=ndimage.label(mask)
    candidates=[]
    for i,region in enumerate(ndimage.find_objects(labels),1):
        if region is None:continue
        ys,xs=region
        height,width=ys.stop-ys.start,xs.stop-xs.start
        if height<raw.shape[0]*.10 or width<4 or height/width<2.8:continue
        if xs.start>raw.shape[1]*.40 and xs.stop<raw.shape[1]*.60:continue
        candidates.append((height*min(width,50),ys,xs))
    if not candidates:
        raise ValueError("Cannot verify the native colorbar against the legend-free frame")
    _,ys,xs=max(candidates,key=lambda e:e[0])
    x=(xs.start+xs.stop)//2
    return Image.fromarray(raw[ys,x:x+1]).resize((25,420),Image.Resampling.NEAREST)


def frame(row, image_path, output):
    with Image.open(image_path) as im:
        if im.size!=(2560,1440):
            raise ValueError(f"Unexpected Fluent viewport {im.size}")
        pix=np.asarray(im.convert("RGB").resize((320,180)),dtype=np.int16)
        if np.quantile(np.max(np.abs(pix-pix[0,0]),axis=2),.998)<10:
            raise ValueError(f"Nearly blank Fluent scene {image_path}")
    if not row.get("font_overlay_required"):
        shutil.copyfile(image_path,output)
        return
    legend,=row["legend_records"]
    lo,hi=legend["range"]
    with Image.open(row["original_native"]) as im, Image.open(row["clean_native"]) as clean:
        raw=np.array(im.convert("RGB")); canvas=clean.convert("RGB")
        swatch=colorbar_pixels(raw,np.asarray(canvas))
    # Reserve a gutter so that the legend cannot hide any field data.
    final=Image.new("RGB",(canvas.width+260,canvas.height),"white")
    final.paste(canvas,(260,0))
    y0=(canvas.height-swatch.height)//2
    final.paste(swatch,(35,y0))
    draw=ImageDraw.Draw(final)
    regular=ImageFont.truetype(str(font_file()),28)
    bold=ImageFont.truetype(str(font_file(True)),27)
    label=TITLES.get(legend["object"],TITLES.get(legend["field"],legend["field"].replace("-"," ")))
    draw.text((25,y0-75),label,font=bold,fill="black")
    draw.text((25,y0-41),f'[{legend["units"]}]',font=regular,fill="black")
    for i,val in enumerate(np.linspace(hi,lo,6)):
        y=y0+(swatch.height-1)*i/5
        draw.line((61,y,70,y),fill="black",width=2)
        draw.text((77,y),f"{val:.4g}",font=regular,fill="black",anchor="lm")
    final.save(output)


def wake_config(case, data):
    from x57_stress_profiles import STATIONS, WAKE, native_volume
    import h5py

    path, source_case, source_data = native_volume()
    if (source_case, source_data) != (case, data):
        raise ValueError("Wake volume differs from the accepted Fine endpoint")
    with h5py.File(path) as volume:
        xyz = volume["xyz_m"][:]
        zmin, zmax, ymin, ymax = WAKE
        mask = ((xyz[:, 0] >= min(STATIONS)) & (xyz[:, 0] <= max(STATIONS)) &
                (xyz[:, 1] >= ymin) & (xyz[:, 1] <= ymax) &
                (xyz[:, 2] >= zmin) & (xyz[:, 2] <= zmax))
        if not np.any(mask):
            raise ValueError("No Fine wake cells inside the declared inspection region")
        row = dict(sections_x_m=list(STATIONS), wake_zy_bounds_m=list(WAKE),
                   q_ref_Pa=float(volume.attrs["q_ref_Pa"]), wake_cell_count=int(mask.sum()))
        for field, key in (("k_m2_s2", "k_isovalue_m2_s2"), ("Cp0", "Cp0_isovalue")):
            values = volume[field][:][mask]
            if not np.isfinite(values).all() or not np.any(values > 0.):
                raise ValueError("Invalid native wake distribution for "+field)
            row[key] = float(np.quantile(values[values > 0.], .85))
        native_q = float(json.loads((case.parent/"solver_physics.json").read_text())["q_ref_Pa"])
        if not np.isfinite(native_q) or native_q <= 0 or native_q != row["q_ref_Pa"]:
            raise ValueError("Fine wake coefficient reference differs from the solved case")
    return row


def plate(number, stem, evidence, folder, dest):
    row=evidence[stem]
    temp=dest/(stem+".pending.png")
    if "error" in row:
        raise ValueError(row["error"])
    if number not in (15,16):
        frame(row,folder/(stem+".png"),temp)
        return temp,[stem]
    iso,slices=row["panels"]
    section_label=", ".join(f"{v:g}" for v in evidence[slices]["metadata"]["sections_x_m"])
    level=row["k_or_Cp0_isovalue"]
    if number==15:
        labels=[f"(a)  k = {level:.3g} m²/s² shell, colored by modeled Reynolds shear",
                f"(b)  Modeled −ρ⟨u′v′⟩ (Pa) at x = {section_label} m"]
    else:
        labels=[f"(a)  Energy core at Cp0 = {level:.3g}, colored by speed",
                f"(b)  Gauge total pressure / qref at x = {section_label} m"]
    paths=[]
    for key in (iso,slices):
        gated()
        png=folder/(key+".framed.png")
        frame(evidence[key],folder/(key+".png"),png)
        paths.append(png)
    with Image.open(paths[0]) as first, Image.open(paths[1]) as second:
        size=(first.width+second.width,max(first.height,second.height)+75)
        combined=Image.new("RGB",size,"white")
        draw=ImageDraw.Draw(combined)
        font=ImageFont.truetype(str(font_file(True)),36)
        for x,title,panel in zip((0,first.width),labels,(first,second)):
            combined.paste(panel,(x,75))
            draw.text((x+30,14),title,font=font,fill="black")
        combined.save(temp)
    return temp,[iso,slices]

def run(numbers):
    gated()
    qa,case,data=accepted("fine_rpm100")
    if not qa["passed"]:
        raise RuntimeError("Fine-rpm100 must pass convergence before graphics export")
    run_id=uuid4().hex
    folder=ROOT/"04_postproc"/"native_fine_rpm100"/run_id
    folder.mkdir(parents=True,exist_ok=True)
    model=json.loads((ROOT/"DELIVERABLES/data/actuator_disk_model.json").read_text())
    disks=[]
    for rotor in model["rotors"]:
        x,y,z=rotor["center_m"]
        disks.append(dict(name=rotor["name"],x_disk_m=x,y_axis_m=y,z_axis_m=z,
                          thickness_m=rotor.get("thickness_m",.05),inner_radius_m=rotor["r_hub_m"],outer_radius_m=rotor["r_tip_m"]))
    tags=json.loads((ROOT/"01_geometry/cad_component_regions.json").read_text())
    with np.load(ROOT/"01_geometry/cad_components.npz") as f:
        wing=np.concatenate([f[k] for k,v in tags.items() if v=="wall_wing"])
    section=disks[2]["z_axis_m"]+.20*disks[2]["outer_radius_m"]
    xy=section_segments(wing,section).reshape(-1,2)
    leading=xy[np.argmin(xy[:,0])]
    from cut_fluent_cells import zones
    import h5py
    with h5py.File(case) as native:
        labels=zones(native["meshes/1/faces/zoneTopology"])
    config=dict(mode="production",run_id=run_id,case_file=str(case),data_file=str(data),numbers=numbers,
                names=[Path(p).stem for p in REQUIRED_FLUENT_RENDERS],section_z=section,leading_edge_xy=leading.tolist(),
                closeup_width_m=.012,disks=disks,sponson_section_z=.86,symmetry="symmetry",
                wall_zones=[name for name in labels if name.startswith("wall_")])
    if {15,16}.intersection(numbers):
        config["wake_display"]=wake_config(case,data)
    (folder/"render_config.json").write_text(json.dumps(config,indent=2),encoding="utf-8")
    journal=folder/"native_render.jou"
    worker=(ROOT/"scripts/render_x57_native.py").as_posix()
    journal.write_text(f'''/file/confirm-overwrite no
(set! checkpoint/exit-filename "exit-fluent.txt")
(set! checkpoint/check-filename "check-fluent.txt")
/file/read-case "{case.as_posix()}"
/file/read-data "{data.as_posix()}"
/file/auto-save/data-frequency 50
/file/auto-save/case-frequency each-time
/file/auto-save/retain-most-recent-files yes
/file/auto-save/max-files 2
(%py-exec "exec(open('{worker}', encoding='utf-8').read())")
/exit ok
''',encoding="utf-8")
    gated()
    checked_command([sys.executable,str(ROOT/"scripts/run_fluent_managed.py"),"--mode","solver","--gui",
                    "--dim","3ddp","--procs","4","--workdir",str(folder),"--journal",str(journal),
                    "--stage","P11","--case","fine_rpm100_native_renders"])
    gated()
    evidence=json.loads((folder/"native_render_evidence.json").read_text())
    evidence_hash=digest(folder/"native_render_evidence.json")
    config_hash=digest(folder/"render_config.json")
    dest=ROOT/"DELIVERABLES/fluent_renders"
    dest.mkdir(parents=True,exist_ok=True)
    for i in numbers:
        gated()
        file=Path(REQUIRED_FLUENT_RENDERS[i-1])
        temp,panels=plate(i,file.stem,evidence,folder,dest)
        raw={}
        for stem in panels:
            row=evidence[stem]
            if (row.get("engine")!="ANSYS Fluent 2025 R2" or row.get("run_id")!=config["run_id"]
                    or row.get("source_case")!=str(case) or row.get("source_data")!=str(data)):
                raise ValueError("Stale or unbound Fluent viewport: "+stem)
            for path in [folder/(stem+".png")]+[Path(row[k]) for k in ("clean_native","original_native") if k in row]:
                raw[path.relative_to(folder).as_posix()]=digest(path)
        receipt=dict(engine="ANSYS Fluent 2025 R2",run_id=config["run_id"],source_case=str(case),
                     source_data=str(data),case_sha256=qa["case_sha256"],data_sha256=qa["data_sha256"],
                     panels=panels,raw_sha256=raw,render_evidence_sha256=evidence_hash,
                     render_config_sha256=config_hash,published_sha256=digest(temp))
        gated()
        temp.replace(dest/file)
        atomic_write_json(ROOT/"04_postproc/native_render_evidence"/(file.stem+".json"),receipt)
        gated()


if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--numbers",type=int,nargs="+",choices=DEFAULT_NUMBERS,default=DEFAULT_NUMBERS)
    run(parser.parse_args().numbers)

