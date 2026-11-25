"""Publish verified baseline CFD data for the X-57 mesh, RPM, wing and wake figures."""
from pathlib import Path
import json
import numpy as np
import pandas as pd
from assess_fluent_case import read_force_monitor
from cfd_verification import gci, gci_threshold, rpm_scaling
from compare_x57_cases import ROOT, BASE, ZERO, CASES3, accepted, load3, read_json, reference
from plot_x57_comparisons import sections3
from verify_native_cell_export import verify
from extract_fluent_fields import extract_slice

FINE="fine_rpm100"
OFF=BASE+"_noswirl"
DATA=ROOT/"DELIVERABLES/data"
GEOMETRY=ROOT/"01_geometry/geometry_audit.json"


def save_table(frame,name):
    DATA.mkdir(parents=True,exist_ok=True)
    dest=DATA/name
    pending=dest.with_suffix(".pending")
    frame.to_csv(pending,index=False)
    pending.replace(dest)


def save_json(record,name):
    DATA.mkdir(parents=True,exist_ok=True)
    dest=DATA/name
    pending=dest.with_suffix(".pending")
    pending.write_text(json.dumps(record,indent=2,allow_nan=False),encoding="utf8")
    pending.replace(dest)


def stats(name):
    qa,case,data=accepted(name)
    return qa,case,data,qa["forces_full_aircraft"]


def grid_series():
    rows=[]
    for level in ("coarse","medium","fine"):
        name=level+"_rpm100"
        qa,cas,data,forces=stats(name)
        mesh=read_json(ROOT/"02_mesh"/level/"mesh_qa.json")
        if mesh.get("passed") is not True or mesh["level"]!=level:
            raise ValueError(f"{name} lacks passing mesh QA")
        count=mesh["cells"]; volume=mesh["five_region_evidence"]["fluid_volume_m3"]
        q,geo=reference(); area=geo["full_planform_area_m2"]
        rows.append(dict(case=name,level=level,cells=count,half_domain_volume_m3=volume,
                         h_m=(volume/count)**(1/3),min_orthogonal_quality=mesh["independent_solver_quality"]["standard"],
                         mesh_sha256=mesh["mesh_sha256"],native_case=cas.name,native_data=data.name,
                         L_air_N=forces["L_air"]["mean_N"],L_wing_N=forces["L_wing"]["mean_N"],
                         D_air_N=forces["D_air"]["mean_N"],Mz_Nm=forces["Mz"]["mean_Nm"],
                         C_L=forces["L_air"]["mean_N"]/(q*area),C_D=forces["D_air"]["mean_N"]/(q*area),
                         q_ref_Pa=q,S_ref_m2=area,force_statistic="full symmetric aircraft, accepted plateau mean"))
    frame=pd.DataFrame(rows)
    gcis={k:gci(frame.cells,frame[k],frame.half_domain_volume_m3) for k in ("C_L","C_D","L_air_N","L_wing_N","D_air_N","Mz_Nm")}
    for name in ("L_air_N","D_air_N"):
        row=gcis[name]
        row.update(fine_target_pct=3.,fine_redline_pct=5.,below_target=gci_threshold(row,3.),
                   below_redline=gci_threshold(row,5.))
    return frame,gcis


def histories(name):
    qa,case,_=accepted(name);folder=case.parent
    end=qa["final_iteration"]; stem=qa["accepted_stem"]
    f=read_force_monitor(folder/"force_history.out").loc[:end]
    endfile=folder/(stem+"_residuals.csv")
    files=sorted((p for p in folder.glob("*_residuals.csv") if p.stat().st_mtime_ns<=endfile.stat().st_mtime_ns),key=lambda p:p.stat().st_mtime_ns)
    parts=[pd.read_csv(p) for p in files]
    r=pd.concat(parts).drop_duplicates("iter",keep="last").set_index("iter").sort_index().loc[:end]
    if not len(f) or not len(r) or int(f.index[-1])!=end or int(r.index[-1])!=end:
        raise ValueError(f"Missing endpoint history for {name}")
    return f,r


def convergence_rows(names):
    rows=[]
    for name in names:
        qa,cas,data=accepted(name)
        planar=name.startswith("opt2d_")
        row=dict(case=name,dimension="2D" if planar else "3D",native_case=cas.name,native_data=data.name,
                 final_iteration=qa["final_iteration"],signed_mass_imbalance_pct=100*qa["mass_balance"]["imbalance_fraction"])
        forces=qa["forces_per_span"] if planar else qa["forces_full_aircraft"]
        for part,st in forces.items():
            source_unit="Nm" if part=="Mz" else "N"
            unit=("Nm_per_m" if part=="section-pitch" else "N_per_m") if planar else source_unit
            row.update({part+"_mean_"+unit:st["mean_"+source_unit],part+"_std_"+unit:st["std_"+source_unit],
                        part+"_drift_"+unit:st["drift_"+source_unit],
                        part+"_drift_pct":None if st["near_zero_absolute_tolerance"] else 100*st["relative_drift"]})
        row.update({"max_tail_"+k:v for k,v in qa["max_last_50_scaled_residuals"].items()})
        rows.append(row)
    return pd.DataFrame(rows)


def rpm_series(include_noswirl=True):
    names=[ZERO,"medium_rpm050","medium_rpm075",BASE]
    if include_noswirl:
        names.append(OFF)
    rows=[]
    baseline=load3(ZERO)["L_wall_N"]
    for name,s in zip(names,[0,.5,.75,1,1]):
        t=load3(name)
        if s:
            _,_,_,ff=stats(name)
            lift,wing,drag=[ff[k]["mean_N"] for k in ("L_air","L_wing","D_air")]
        else:
            lift,wing,drag=t["L_wall_N"],t["L_wing_N"],t["D_wall_N"]
        gross=-t["Fx_actuator_reaction_N"]
        rows.append(dict(case=name,s=s,swirl=(name not in (ZERO,OFF)),L_air_N=lift,L_wing_N=wing,D_air_N=drag,
                         delta_L_static_N=lift-baseline,T_gross_N=gross,T_net_N=gross-drag,
                         D_over_s2_N=drag/s**2 if s else None,abs_L_over_s2_N=abs(lift)/s**2 if s else None,
                         native_case=t["native_case"],native_data=t["native_data"]))
    frame=pd.DataFrame(rows);subset=frame[frame.swirl]
    fits={k:rpm_scaling(subset.s,subset[k]) for k in ["delta_L_static_N","D_air_N","L_wing_N"]}
    return frame,fits


def wall_data(name):
    cp,load,out,cas,data=sections3(name)
    metric=read_json(out/"wall_metrics.json")
    return cp,load,np.load(out/"airframe_wall_faces.npz"),metric,cas,data


def swirl_load_partition():
    source={}
    for name in (BASE,OFF):
        _,load,out,case,data=sections3(name)
        source[name]=(load,read_json(out/"wall_metrics.json")["peak_suction"])
    on,off=source[BASE][0],source[OFF][0]
    keys=["z_lo_m","z_hi_m","span_region"]
    if not on[keys].equals(off[keys]):
        raise ValueError("Swirl comparison requires identical physical spanwise intervals")
    delta=on[keys+["z_m"]].copy()
    delta["ON_dL_dz_N_per_m"]=on.dL_dz_N_per_m
    delta["OFF_dL_dz_N_per_m"]=off.dL_dz_N_per_m
    delta["delta_dL_dz_N_per_m"]=on.dL_dz_N_per_m-off.dL_dz_N_per_m
    delta["full_symmetric_bin_delta_L_N"]=2*(on.half_wing_bin_load_N-off.half_wing_bin_load_N)
    contributions=delta.groupby("span_region").full_symmetric_bin_delta_L_N.sum().to_dict()
    direct_half=float(on.half_wing_bin_load_N.sum()-off.half_wing_bin_load_N.sum())
    if not np.isclose(sum(contributions.values()),2*direct_half,atol=1.e-8,rtol=1.e-9):
        raise ValueError("The two signed spanwise contributions do not close")
    return delta,dict(inboard_edge_of_wingtip_disk_m=float(delta.loc[delta.span_region=="outboard_wingtip","z_lo_m"].min()),
                      full_symmetric_wing_delta_L_N=2*direct_half,full_symmetric_delta_by_region_N=contributions,
                      cell_face_pressure_minima={n:source[n][1] for n in source},
                      interpretation="Spatial decomposition of swirl ON minus OFF lift at the inboard tip of the wingtip disk. Both propulsor groups can influence either region.")


def wall_budgets(name):
    cp,load,wall,metric,cas,data=wall_data(name)
    with wall:
        labels=wall["component"];normal_y=wall["inward_fluid_area_vector_m2"][:,1]
        pf=wall["force_pressure_half_N"]; vf=wall["force_viscous_half_N"]
        end=read_json(cas.parent/(cas.name[:-7]+"_force_and_flux.json"))["half_model_force_N"]
        rows=[]
        parts={n:labels==n for n in np.unique(labels)}
        wing=labels=="wall_wing"
        parts.update(wing_upper=wing&(normal_y>0),wing_lower=wing&(normal_y<0),wing_edge=wing&(normal_y==0))
        for part,mask in parts.items():
            p,v=2*pf[mask].sum(axis=0),2*vf[mask].sum(axis=0)
            if part.startswith("wall_"):
                key=part.removeprefix("wall_")
                expected=np.array([end[key]["ForceX"],end[key]["ForceY"]])*2
                if not np.allclose((p+v)[:2],expected,rtol=5e-5,atol=.01):
                    raise ValueError(f"{part} face forces disagree with native terminal report")
            rows.append(dict(case=name,part=part,faces=int(mask.sum()),full_area_m2=2*wall["area_m2"][mask].sum(),
                             D_pressure_N=p[0],D_viscous_N=v[0],L_pressure_N=p[1],L_viscous_N=v[1],
                             source="Fluent terminal face pressures and integrated shear; full-aircraft x/y loads"))
    return pd.DataFrame(rows)


def vorticity_table(case,data):
    stem=case.name[:-7]; mp=case.with_name(stem+"_native_field_manifest.json")
    meta=read_json(mp)
    if meta["case"]!=case.name or meta["data"]!=data.name:
        raise ValueError("Native vorticity manifest does not identify the accepted endpoint")
    qa=verify(mp); cols=[qa["native_id_column"],qa["fields"]["omega_x_per_s"]]
    f=pd.read_csv(mp.parent/meta["file"],skipinitialspace=True,usecols=cols)
    ids=f[cols[0]].to_numpy(dtype=int)+qa["add_to_native_id_for_cff"]
    return pd.Series(f[cols[1]].to_numpy(dtype=float),index=ids)


def crossplanes(name,stations):
    _,case,data=accepted(name)
    omega=vorticity_table(case,data)
    result=[]
    for x in stations:
        d=extract_slice(case,data,0,float(x))
        if list(d["projected_axes"])!=[1,2]:
            raise ValueError("Expected transverse y-z control plane")
        ids=d["cell_ids"]; pos=d["xy"][:,::-1]; ends=d["offsets"]
        keep=(np.minimum.reduceat(pos[:,0],ends[:-1])<5.8)&(np.maximum.reduceat(pos[:,0],ends[:-1])>=0)
        keep&=(np.minimum.reduceat(pos[:,1],ends[:-1])<1.25)&(np.maximum.reduceat(pos[:,1],ends[:-1])>=-1.7)
        use=np.flatnonzero(keep)
        polys=[pos[ends[i]:ends[i+1]] for i in use]
        values={k:d[k][use] for k in ("u_m_s","v_m_s","w_m_s")}
        values["speed"]=np.sqrt(sum(values[k]**2 for k in ("u_m_s","v_m_s","w_m_s")))
        values["axial_vorticity_s_inv"]=omega.loc[ids[use]].to_numpy()
        result.append((polys,values))
    return result
