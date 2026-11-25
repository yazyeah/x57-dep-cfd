"""Integrate native wall tractions and intersect wing-face polygons with specified stations."""
import argparse
import json
from pathlib import Path
import h5py
import numpy as np
import pandas as pd
from cut_fluent_cells import bounds, read_id_blocks, zones
from extract_fluent_fields import extract_walls
from cfd_verification import weighted_distribution
from p2_geometry_io import section_segments

ROOT=Path(__file__).resolve().parents[1]


def clip_z(poly,z,greater):
    a=poly
    b=np.roll(a,-1,axis=0)
    keep=(a[:,2]>=z) if greater else (a[:,2]<=z)
    cross=keep!=np.roll(keep,-1)
    vertices=[]
    for k in range(len(poly)):
        if keep[k]:
            vertices.append(a[k])
        if cross[k]:
            t=(z-a[k,2])/(b[k,2]-a[k,2])
            vertices.append(a[k]+t*(b[k]-a[k]))
    return np.array(vertices)


def poly_area(poly,normal):
    if len(poly)<3:
        return 0.
    p=poly-poly[0]
    return abs(np.sum(np.cross(p[1:-1],p[2:])@normal))*.5


def wing_faces(case):
    with h5py.File(case) as f:
        mesh=f["meshes/1"]
        xyz=read_id_blocks(mesh["nodes/coords"],int(max(mesh["nodes/zoneTopology/maxId"])),float,3)
        for name,(lo,hi) in zones(mesh["faces/zoneTopology"]).items():
            if not name.startswith("wall_wing"):
                continue
            for block in mesh["faces/nodes"].values():
                first,last=bounds(block)
                a,b=max(lo,first),min(hi,last)
                if a>b:
                    continue
                sizes=block["nnodes"][:].astype(np.int64)
                offsets=np.r_[0,np.cumsum(sizes)]
                start=offsets[a-first]
                refs=block["nodes"][start:offsets[b-first+1]]
                for face in range(a,b+1):
                    k=face-first
                    yield face, xyz[refs[offsets[k]-start:offsets[k+1]-start]]


def examine(case, data, output):
    output.mkdir(parents=True,exist_ok=True)
    audit=json.loads((ROOT/"01_geometry/geometry_audit.json").read_text())
    config=json.loads((case.parent/"solver_physics.json").read_text())
    qref=float(config["q_ref_Pa"])
    ref=audit["wing_reference"]
    props=audit["starboard_propellers_detected"]
    components=json.loads((ROOT/"01_geometry/cad_component_regions.json").read_text())
    with np.load(ROOT/"01_geometry/cad_components.npz") as parts:
        cad=np.concatenate([parts[k] for k,tag in components.items() if tag=="wall_wing"]).astype(float)
    def chord(z):
        hits=section_segments(cad,z).reshape(-1,2)
        return float(hits[:,0].min()),float(np.ptp(hits[:,0]))
    w=extract_walls(case,data)
    a=w["inward_fluid_area_vector_m2"]
    pressure=-w["p_gauge_Pa"][:,None]*a
    # SV_WALL_SHEAR is the face-integrated tangential force on the fluid.
    viscous=-w["wall_shear_storage"]
    force=pressure+viscous
    wing=np.char.startswith(w["component"],"wall_wing")
    ids=np.flatnonzero(wing)
    w["force_pressure_half_N"]=pressure
    w["force_viscous_half_N"]=viscous
    w["Cp"]=w["p_gauge_Pa"]/qref
    np.savez_compressed(output/"airframe_wall_faces.npz",**w)
    minface=ids[np.argmin(w["p_gauge_Pa"][wing])]
    x,y,z=w["xyz"][minface]
    xle,c=chord(z)
    suction={"face_id":int(w["face_id"][minface]),"face_centroid_m":[x,y,z],
             "span_fraction":2*z/ref["full_span_m"],"chord_fraction":(x-xle)/c,
             "p_gauge_Pa":w["p_gauge_Pa"][minface],"Cp":w["Cp"][minface],"q_ref_Pa":qref}
    summary={"peak_suction":suction,"wall_force_components_half_N":{},"yplus":{}}
    for key in list(np.unique(w["component"]))+["all_aircraft"]:
        select=w["component"]==key if key!="all_aircraft" else np.ones(len(wing),dtype=bool)
        summary["wall_force_components_half_N"][key]={"pressure":pressure[select].sum(axis=0).tolist(),
                                                       "viscous":viscous[select].sum(axis=0).tolist()}
        summary["yplus"][key]=weighted_distribution(w["yplus"][select],w["area_m2"][select])
    stations={p["name"]:p["z_axis_m"] for p in [props[0],props[2],props[3],props[5]]}
    stations["HLP-2/3 gap"]=(props[1]["z_axis_m"]+props[2]["z_axis_m"])/2
    stations["inboard wingtip rotor"]=props[-1]["z_axis_m"]-.35*props[-1]["r_tip_m"]
    sections={key:chord(z) for key,z in stations.items()}
    # Split exactly at the inboard edge of the wingtip disk. The same CAD-based
    # clipped face intervals apply in the swirl-on, swirl-off and Fine cases.
    z_split=props[-1]["z_axis_m"]-props[-1]["r_tip_m"]
    edges=np.unique(np.r_[np.linspace(0,ref["full_span_m"]*.5+.03,81),z_split])
    bins=np.zeros(len(edges)-1)
    rows=[]
    index={face:i for i,face in enumerate(w["face_id"])}
    for face,poly in wing_faces(case):
        k=index[face]
        low,high=poly[:,2].min(),poly[:,2].max()
        if low < edges[0]-1.e-8 or high>edges[-1]:
            raise ValueError("Wing exceeds common spanwise integration limits.")
        lo,hi=np.clip(np.searchsorted(edges,[low,high],side="right")-1,0,len(bins)-1)
        if lo==hi:
            bins[lo]+=force[k,1]
        else:
            normal=a[k]/w["area_m2"][k]
            fractions=[]
            for j in range(lo,hi+1):
                part=clip_z(poly,edges[j],True)
                if len(part):
                    part=clip_z(part,edges[j+1],False)
                fractions.append(poly_area(part,normal))
            weights=np.array(fractions)/sum(fractions)
            bins[lo:hi+1]+=force[k,1]*weights
        for label,station in stations.items():
            if not low<=station<high:
                continue
            nxt=np.roll(poly,-1,axis=0)
            cross=(poly[:,2]>station)!=(nxt[:,2]>station)
            before,after=poly[cross],nxt[cross]
            t=(station-before[:,2])/(after[:,2]-before[:,2])
            mid=(before+t[:,None]*(after-before)).mean(axis=0)
            leading,length=sections[label]
            rows.append(dict(station=label,z_m=station,face_id=int(face),side="upper" if a[k,1]>0 else "lower",
                             x_m=mid[0],y_m=mid[1],x_over_c=(mid[0]-leading)/length,Cp=w["Cp"][k],
                             p_gauge_Pa=w["p_gauge_Pa"][k]))
    if not np.isclose(bins.sum(),force[wing,1].sum(),rtol=1e-10,atol=1e-8):
        raise ValueError("Spanwise wall force does not integrate to the half-wing load.")
    pd.DataFrame(rows).sort_values(["station","side","x_over_c"]).to_csv(output/"wing_sections.csv",index=False)
    pd.DataFrame(dict(z_lo_m=edges[:-1],z_hi_m=edges[1:],z_m=(edges[1:]+edges[:-1])/2,
                      dL_dz_N_per_m=bins/np.diff(edges),half_wing_bin_load_N=bins,
                      span_region=np.where(edges[1:]<=z_split,"inboard_HLP","outboard_wingtip"))).to_csv(output/"loading.csv",index=False)
    (output/"wall_metrics.json").write_text(json.dumps(summary,indent=2),encoding="utf-8")


if __name__=="__main__":
    p=argparse.ArgumentParser(description=__doc__)
    for arg in ("case","data","output"):
        p.add_argument(arg,type=Path)
    args=p.parse_args()
    examine(args.case,args.data,args.output)
