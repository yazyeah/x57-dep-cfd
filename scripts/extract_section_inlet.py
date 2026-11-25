"""Extract the 2D HLP-3 inlet from native cells of the accepted powered 3D solution."""
import argparse
import json
from pathlib import Path

import h5py
import numpy as np

from cut_fluent_cells import cut_mesh
from extract_fluent_fields import sample
from prepare_airfoil_sections import section_envelope

ROOT = Path(__file__).resolve().parents[1]
FIELDS = {"u_m_s":"SV_U","v_m_s":"SV_V","w_m_s":"SV_W","k_m2_s2":"SV_K","omega_s_inv":"SV_O"}


def line_segments(cut, station_z, bottom, top):
    """Intersect each actual fluid polygon in (y,z) with one line at fixed z."""
    xy, offsets = cut["xy"], cut["offsets"]
    hits = []
    for cell, start, end in zip(cut["cell_ids"],offsets[:-1],offsets[1:],strict=True):
        p=xy[start:end]
        if station_z<p[:,1].min() or station_z>=p[:,1].max():
            continue
        q=np.roll(p,-1,axis=0)
        crossing=(p[:,1]<=station_z)!=(q[:,1]<=station_z)
        a,b=p[crossing],q[crossing]
        y=np.sort(a[:,0]+(station_z-a[:,1])*(b[:,0]-a[:,0])/(b[:,1]-a[:,1]))
        if len(y)%2:raise ValueError("Open line intersection in a native fluid cell.")
        for lo,hi in y.reshape(-1,2):
            lo,hi=max(float(lo),bottom),min(float(hi),top)
            if hi-lo>1.e-10:hits.append((lo,hi,int(cell)))
    hits.sort()
    if not hits:raise ValueError("No 3D fluid cells intersect the HLP-3 inlet line.")
    return hits


def split_bands(segments,tol=1.e-8):
    groups=[]
    for lo,hi,cell in segments:
        if groups:
            previous=groups[-1][-1][1]
            if lo<previous-tol:
                raise ValueError("Overlapping cell intersections on the inlet sampling line.")
        if not groups or lo>previous+tol:
            groups.append([])
        groups[-1].append((lo,hi,cell))
    return groups


def write_profile(output, groups, fields, plane_x):
    lines=[]
    metadata=[]
    index=0
    for number,group in enumerate(groups,1):
        # Write each open part to its own Fluent profile. No interpolation crosses a solid.
        name=f"hlp3-{number}"
        ypoints=[]; rows=[]
        for i,(lo,hi,_) in enumerate(group):
            eps=min(1.e-8,(hi-lo)*.01)
            ypoints.extend([lo if not i else lo+eps,hi if i==len(group)-1 else hi-eps])
            rows.extend([index,index]);index+=1
        values={"x":np.full(len(ypoints),plane_x),"y":ypoints,
                "u":fields["u_m_s"][rows],"v":fields["v_m_s"][rows],
                "k":fields["k_m2_s2"][rows],"omega":fields["omega_s_inv"][rows]}
        lines.append(f"(({name} line {len(ypoints)})")
        for key,array in values.items():
            lines.append("("+key+" "+" ".join(f"{val:.12g}" for val in array)+")")
        lines.append(")")
        metadata.append(dict(profile=name,zone=f"inlet_{number}",bottom_m=group[0][0],top_m=group[-1][1],
                             source_cells=len(group)))
    output.write_text("\n".join(lines)+"\n",encoding="ascii")
    return metadata


def extract(folder,output):
    qc=json.loads((folder/"iteration_qa.json").read_text(encoding="utf-8-sig"))
    if not qc["passed"] or qc["case"]!="fine_rpm100":
        raise ValueError("HLP-3 inlet requires an accepted fine_rpm100 endpoint.")
    stem=qc["accepted_stem"]
    case=folder/(stem+".cas.h5"); data=folder/(qc.get("accepted_data") or stem+".dat.h5")
    from fluent_checkpoints import case_for_data
    if case_for_data(data)!=case.resolve():raise ValueError("Fine section inlet source data and mesh differ")
    xmin,chord,_,_,rotor=section_envelope()
    plane_x=rotor["x_disk_m"]+.04; station_z=rotor["z_axis_m"]
    bottom=-1.70; top=rotor["y_axis_m"]+7*chord
    segments=line_segments(cut_mesh(case,0,plane_x),station_z,bottom,top)
    groups=split_bands(segments)
    if max(abs(groups[0][0][0]-bottom),abs(groups[-1][-1][1]-top))>1.e-6:
        raise ValueError("Native volume cut does not cover the intended inlet bounds.")
    ids=np.asarray([c for _,_,c in segments])
    length=np.asarray([b-a for a,b,_ in segments])
    with h5py.File(data) as cf:
        cells=cf["results/1/phase-1/cells"]
        fields={k:sample(cells,v,ids).reshape(-1) for k,v in FIELDS.items()}
    if np.any(fields["k_m2_s2"]<0) or np.any(fields["omega_s_inv"]<=0):
        raise ValueError("Invalid native SST inlet data.")
    output.mkdir(parents=True,exist_ok=True)
    profiles=write_profile(output/"hlp3.prof",groups,fields,plane_x)
    np.savez_compressed(output/"native_samples.npz",cell_ids=ids,y_intervals_m=np.asarray(segments)[:,:2],
                        **fields)
    summary={"source_case":str(case),"source_data":str(data),"accepted_iteration":qc["final_iteration"],
             "source_case_id":qc["case"],"plane_x_m":plane_x,"station_z_m":station_z,"bottom_m":bottom,
             "top_m":top,"x_le_m":xmin,"chord_m":chord,"open_bands":profiles,
             "open_length_m":float(sum(length)),"blocked_length_m":float(top-bottom-sum(length)),
             "inlet_mean_speed_m_s":float(np.average(np.hypot(fields["u_m_s"],fields["v_m_s"]),weights=length)),
             "axial_volume_flux_per_m_span_m2_s":float(length@fields["u_m_s"]),
             "mean_out_of_plane_velocity_m_s":float(np.average(fields["w_m_s"],weights=length)),
             "profile_file":str((output/"hlp3.prof").resolve()),
             "method":"Native 3D cell values on fluid-only intervals. The 2D comparison uses in-plane velocity and SST k/omega. A stationary closure represents every blocked part of the upstream boundary."}
    (output/"inlet.json").write_text(json.dumps(summary,indent=2,allow_nan=False),encoding="utf-8")
    print("Open bands",profiles,flush=True)


if __name__=="__main__":
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument("accepted_case_folder",type=Path);ap.add_argument("output_directory",type=Path)
    args=ap.parse_args();extract(args.accepted_case_folder.resolve(),args.output_directory.resolve())
