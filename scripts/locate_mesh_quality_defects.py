"""Locate low-orthogonality cells in a diagnostic native mesh, including meshes with mixed signed volumes."""
import argparse
import json
from pathlib import Path

import h5py
import numpy as np
from scipy.spatial import cKDTree

from cut_fluent_cells import bounds, read_id_blocks, zones
from mesh_region_budget import boi_bounds, native_flags
from mesh_quality_groups import cell_groups

ROOT=Path(__file__).resolve().parents[1]


def face_blocks(mesh,xyz):
    for group in mesh["faces/nodes"].values():
        lo,_=bounds(group)
        counts=group["nnodes"][:].astype(np.int64)
        ofs=np.r_[0,np.cumsum(counts)]
        for start in range(0,len(counts),16000):
            end=min(start+16000,len(counts))
            n=counts[start:end]
            ids=group["nodes"][ofs[start]:ofs[end]]
            for k in np.unique(n):
                sub=np.flatnonzero(n==k)
                at=ofs[start+sub]-ofs[start]
                points=xyz[ids[at[:,None]+np.arange(k)]]
                yield lo+start+sub,points


def directions(v):
    mag=np.linalg.norm(v,axis=1)
    return np.divide(v,mag[:,None],out=np.zeros_like(v),where=mag[:,None]>0)


def zone_counts(indices,labels,names):
    n=np.bincount(labels[indices],minlength=len(names))
    return {name:int(v) for name,v in zip(names,n,strict=True)}


def inspect(path,boi_file):
    with h5py.File(path) as f:
        m=f["meshes/1"]
        nf=int(max(m["faces/zoneTopology/maxId"]));nc=int(max(m["cells/zoneTopology/maxId"]))
        xyz=read_id_blocks(m["nodes/coords"],int(max(m["nodes/zoneTopology/maxId"])),float,3)
        a=read_id_blocks(m["faces/c0"],nf,np.int32); b=read_id_blocks(m["faces/c1"],nf,np.int32)
        wall_ranges={k:v for k,v in zones(m["faces/zoneTopology"]).items() if k.startswith("wall_")}
        reference=np.zeros((nc+1,3));count=np.zeros(nc+1,dtype="i2")
        wall_points=[]; wall_names=[];names=list(wall_ranges)
        for ids,nodes in face_blocks(m,xyz):
            mid=nodes.mean(1)
            for c in [a[ids],b[ids]]:
                use=c>0
                np.add.at(reference,c[use],mid[use]);np.add.at(count,c[use],1)
            for i,name in enumerate(names):
                low,high=wall_ranges[name];take=(ids>=low)&(ids<=high)
                if np.any(take):
                    wall_points.append(mid[take]);wall_names.extend([i]*np.count_nonzero(take))
        if np.any(count[1:]<4):raise ValueError("Missing cell faces or a surface-only mesh")
        reference[1:]/=count[1:,None]
        volume=np.zeros(nc+1);moment=np.zeros_like(reference)
        for ids,pts in face_blocks(m,xyz):
            mid=pts.mean(1)
            p=pts-mid[:,None];nxt=np.roll(p,-1,axis=1)
            normal=np.cross(p,nxt)
            for c,side in [(a[ids],1.),(b[ids],-1.)]:
                use=c>0
                cells=c[use];arm=mid[use]-reference[cells]
                vol=side*np.einsum("ij,ikj->ik",arm,normal[use])/6
                # First moment relative to the cell's own reference point.
                moment_vec=(3*arm[:,None]+p[use]+nxt[use])/4
                np.add.at(volume,cells,vol.sum(axis=1))
                np.add.at(moment,cells,np.einsum("ij,ijk->ik",vol,moment_vec))
        # Native Fluent CFF face rings point into c0. Fix this sign so a globally
        # reversed mesh remains visible in the diagnostic.
        orient=-1
        raw_majority=1 if np.count_nonzero(volume[1:]>0)>nc/2 else -1
        center=reference+np.divide(moment,volume[:,None],out=np.zeros_like(reference),where=volume[:,None]!=0)
        signed=orient*volume
        quality=np.ones(nc+1)
        face_quality=np.ones(nc+1)
        neighbor_quality=np.ones(nc+1)
        for ids,nodes in face_blocks(m,xyz):
            mid=nodes.mean(1); pts=nodes-mid[:,None];nxt=np.roll(pts,-1,axis=1)
            cross=np.cross(pts,nxt);vec=cross.sum(1)
            unit=directions(vec)
            weights=np.einsum("ijk,ik->ij",cross,unit)
            shift=np.einsum("ij,ijk->ik",weights,(pts+nxt)/3)
            tot=weights.sum(1)
            face_center=mid+np.divide(shift,tot[:,None],out=np.zeros_like(shift),where=tot[:,None]!=0)
            unit*=orient
            for c,other,sgn in [(a[ids],b[ids],1.),(b[ids],a[ids],-1.)]:
                use=c>0;cells=c[use];n=unit[use]*sgn
                q=np.einsum("ij,ij->i",n,directions(face_center[use]-center[cells]))
                np.minimum.at(face_quality,cells,q)
                interior=other[use]>0
                if np.any(interior):
                    sep=center[other[use][interior]]-center[cells[interior]]
                    nq=np.einsum("ij,ij->i",n[interior],directions(sep))
                    np.minimum.at(neighbor_quality,cells[interior],nq)
                    q[interior]=np.minimum(q[interior],nq)
                np.minimum.at(quality,cells,q)
        flags=(native_flags(f["special/boundary_layer_flags/cells"],nc)
               if "special/boundary_layer_flags/cells" in f else None)
    reference[1:]=np.where((signed[1:]<=0)[:,None],reference[1:],center[1:])
    near_labels=np.r_[0,cKDTree(np.concatenate(wall_points)).query(reference[1:],workers=2)[1]]
    nearest=np.asarray(wall_names,dtype="i1")[near_labels]
    rotors=json.loads((ROOT/"DELIVERABLES/data/actuator_disk_model.json").read_text())["rotors"]
    bounds_map=boi_bounds(boi_file)
    region=np.zeros(nc+1,dtype="i1")
    if flags is not None and "wall_wing" in names: region[flags&(nearest==names.index("wall_wing"))]=1
    for d in rotors:
        xd,yd,zd=d["center_m"]
        rad=np.hypot(reference[:,1]-yd,reference[:,2]-zd)
        disk=(abs(reference[:,0]-xd)<=d["thickness_m"]/2)&(rad>=d["r_hub_m"])&(rad<=d["r_tip_m"])
        region[(region==0)&disk]=2
    for group,number in [("near_wake_boi",3),("mid_wake_boi",4)]:
        lo,hi=np.asarray(bounds_map[group])
        region[(region==0)&np.all((reference>=lo)&(reference<=hi),axis=1)]=number
    if flags is not None:region[(region==0)&flags]=4
    region[region==0]=5
    region_names=["unused","wing_prism_nearest_wall","actuator_annuli","near_wake","other_body_mid_wake","outer"]
    def summary(ids):
        return {"count":len(ids),"boi_counts":zone_counts(ids,region,region_names),"nearest_wall":zone_counts(ids,nearest,names),
                "prism_flagged":int(flags[ids].sum()) if flags is not None else None,
                "location_bounds_m":[reference[ids].min(0).tolist(),reference[ids].max(0).tolist()] if len(ids) else []}
    groups=cell_groups(path,quality,signed,face_quality,neighbor_quality)
    order=np.argsort(quality[1:])[:25]+1
    return {"source":str(path),"cells":nc,"native_cell_group_quality":groups,"cell_locations":"Volume centroids for positive cells, incident-face means for inverted cells.",
            "metric":"Offline face-normal versus centroid-to-face and centroid-to-neighbor direction cosines. Standard polyhedral geometric orthogonality; compare native values independently.",
            "region_note":"Boundary-layer classification uses native flag plus nearest wall, when native flags are available. BOI counts use centroids.",
            "raw_volume_orientation_for_majority":raw_majority,"CFF_c0_face_normal_volume_sign":orient,"raw_negative_cell_count":int(np.sum(volume[1:]<0)),
            "scope":"Face-normal/cell-centre orthogonality proxy only. Fluent's tet, prism and pyramid metric also includes skewness; nearest-wall labels are diagnostic attribution.",
            "minimum_volume_m3":float(signed[1:].min()),"total_fluid_volume_m3":float(signed[1:].sum()),
            "all":summary(np.arange(1,nc+1)),"nonpositive":summary(np.flatnonzero(signed[1:]<=0)+1),
            "proxy_lt_005":summary(np.flatnonzero(quality[1:]<.05)+1),"proxy_lt_010":summary(np.flatnonzero(quality[1:]<.10)+1),
            "native_style_percentiles":np.quantile(quality[1:],[0,.01,.05,.5,1]).tolist(),
            "worst_cells":[dict(id=int(i),proxy=float(quality[i]),signed_volume_m3=float(signed[i]),xyz_m=reference[i].tolist(),
                                closest_wall=names[nearest[i]]) for i in order]}


if __name__=="__main__":
    p=argparse.ArgumentParser(description=__doc__);p.add_argument("mesh",type=Path);p.add_argument("boi",type=Path);p.add_argument("output",type=Path)
    a=p.parse_args();r=inspect(a.mesh,a.boi);a.output.write_text(json.dumps(r,indent=2,allow_nan=False),encoding="utf-8")
    for k in ["cells","all","nonpositive","proxy_lt_005","proxy_lt_010","native_style_percentiles"]:print(k,r[k],flush=True)
