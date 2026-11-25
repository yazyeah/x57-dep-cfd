"""Read native 2-D Fluent CFF face and cell fields for high-lift comparisons."""
from pathlib import Path
import h5py
import numpy as np
import pandas as pd
from cut_fluent_cells import bounds, read_id_blocks, zones, polygon_loops
from extract_fluent_fields import sample
from cfd_verification import weighted_distribution
from compare_x57_cases import ROOT,accepted,read_json,reference

DESIGNS=["Clean","15° flap","30° slotted flap","Slat and 30° flap","3% camber"]

def case_names():
    names=[]
    for idx in range(1,6):
        match=list((ROOT/"03_cases").glob(f"opt2d_{idx:02d}_*"))
        if len(match)!=1:raise ValueError(f"Expected exactly one opt2d_{idx:02d} case.")
        names.append(match[0].name)
    return names

def mesh2(m):
    nnode=int(max(m["nodes/zoneTopology/maxId"]));nf=int(max(m["faces/zoneTopology/maxId"]));nc=int(max(m["cells/zoneTopology/maxId"]))
    dim=next(iter(m["nodes/coords"].values())).shape[-1]
    xyz=read_id_blocks(m["nodes/coords"],nnode,float,dim)[:,:2]
    owner=read_id_blocks(m["faces/c0"],nf,int);neighbor=read_id_blocks(m["faces/c1"],nf,int)
    nodes=np.zeros((nf+1,2),int)
    for g in m["faces/nodes"].values():
        lo,hi=bounds(g)
        if not np.all(g["nnodes"][:]==2):raise ValueError("Expected a planar two-node Fluent edge mesh.")
        nodes[lo:hi+1]=g["nodes"][:].reshape(-1,2)
    center=xyz[nodes].mean(axis=1)
    sums=np.zeros((nc+1,2));counts=np.zeros(nc+1)
    for side in (owner,neighbor):
        np.add.at(sums,side[1:],center[1:]);np.add.at(counts,side[1:],1)
    if np.any(counts[1:]<3):raise ValueError("An accepted 2D cell has fewer than three edge incidences.")
    cent=sums/np.maximum(counts,1)[:,None]
    return xyz,nodes,center,owner,neighbor,cent

def load_section(name,flow=False):
    qa,cas,dat=accepted(name); cfg=read_json(cas.parent/"section_config.json");q,_=reference()
    chord=float(cfg["chord_m"]); xle=float(cfg["x_le_m"])
    with h5py.File(cas) as fc,h5py.File(dat) as fd:
        m=fc["meshes/1"];xyz,nodes,center,owner,neighbor,cent=mesh2(m);zs=zones(m["faces/zoneTopology"])
        faces=fd["results/1/phase-1/faces"];cells=fd["results/1/phase-1/cells"]
        pieces=[]
        for tag in ["wall_main","wall_flap","wall_slat"]:
            if tag not in zs:continue
            a,b=zs[tag];fid=np.arange(a,b+1);ends=xyz[nodes[fid]];ds=ends[:,1]-ends[:,0]
            area=np.column_stack((-ds[:,1],ds[:,0])); fluid=np.maximum(owner[fid],neighbor[fid])
            area*=np.where(np.einsum("ij,ij->i",area,cent[fluid]-center[fid])>=0,1.,-1.)[:,None]
            p=sample(faces,"SV_P",fid).ravel();shear=sample(faces,"SV_WALL_SHEAR",fid)[:,:2]
            pressure=-p[:,None]*area;visc=-shear;force=pressure+visc;length=np.linalg.norm(area,axis=1)
            pieces.append(pd.DataFrame(dict(zone=tag,face_id=fid,x_m=center[fid,0],y_m=center[fid,1],x_over_c=(center[fid,0]-xle)/chord,
                         side=np.where(area[:,1]>=0,"upper","lower"),Cp=p/q,p_gauge_Pa=p,area=length,
                         Lp=pressure[:,1],Lv=visc[:,1],D=force[:,0],Mz=center[fid,0]*force[:,1]-center[fid,1]*force[:,0],
                         tau_Pa=np.linalg.norm(shear,axis=1)/length,yplus=sample(faces,"SV_WALL_YPLUS",fid).ravel())))
        if not pieces or "wall_main" not in zs:raise ValueError("Missing 2D main-element wall.")
        wall=pd.concat(pieces,ignore_index=True);L=wall.Lp.sum()+wall.Lv.sum();D=wall.D.sum()
        inlet=[z for z in zs if "inlet" in z.lower()]
        if not inlet:raise ValueError("The 2D case has no identifiable native inlet boundary.")
        fi=np.concatenate([np.arange(zs[z][0],zs[z][1]+1) for z in inlet]);ci=np.maximum(owner[fi],neighbor[fi])
        u=sample(cells,"SV_U",ci).ravel();v=sample(cells,"SV_V",ci).ravel()
        inlet_speed=np.average(np.hypot(u,v),weights=np.linalg.norm(xyz[nodes[fi,1]]-xyz[nodes[fi,0]],axis=1))
        field=None
        if flow:
            edges=[[] for _ in range(len(cent))]
            for i in range(1,len(nodes)):
                edges[owner[i]].append(tuple(nodes[i]))
                if neighbor[i]:edges[neighbor[i]].append(tuple(nodes[i]))
            polys=[]
            for item in edges[1:]:
                loops=list(polygon_loops(item))
                if len(loops)!=1:raise ValueError("Invalid 2D native cell polygon.")
                polys.append(xyz[loops[0]])
            ids=np.arange(1,len(cent))
            field=polys,{k:sample(cells,var,ids).ravel() for k,var in [("u_m_s","SV_U"),("v_m_s","SV_V")]}
    idx=int(name.split("_")[1])-1
    row=dict(case=name,label=DESIGNS[idx],dimension="2D",native_case=str(cas.relative_to(ROOT)),native_data=str(dat.relative_to(ROOT)),
             qa_file=str((cas.parent/"iteration_qa.json").relative_to(ROOT)),provenance="Native Fluent CFF edge pressure, shear and y-plus. Derived forces use unit depth; coefficients use the baseline CAD chord and fixed nominal dynamic pressure.",
             q_ref_Pa=q,c_ref_m=chord,S_ref_m2=chord,L_wall_N=L,D_wall_N=D,Mz_wall_Nm=wall.Mz.sum(),C_L=L/(q*chord),C_D=D/(q*chord),
             C_M=wall.Mz.sum()/(q*chord**2),CL_pressure=wall.Lp.sum()/(q*chord),CL_viscous=wall.Lv.sum()/(q*chord),
             L_over_D=L/D if abs(D)>1e-10*q*chord else np.nan,Cp_min=wall.Cp.min(),tau95_Pa=weighted_distribution(wall.tau_Pa,wall.area)["p95"],
             yplus95=weighted_distribution(wall.yplus,wall.area)["p95"],inlet_mean_speed_adjacent_m_s=inlet_speed,
             x_le_m=xle,section_z_m=cfg["section_z_m"],inlet_x_m=cfg["inlet_x_m"],final_iteration=qa.get("final_iteration"),qa_passed=True)
    return row,wall,field
