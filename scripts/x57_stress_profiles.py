"""Trace wing-wall normals through native Fluent cells and integrate clipped wake polygons."""
from pathlib import Path
import json
import h5py
import numpy as np
import pandas as pd
from cut_fluent_cells import bounds,read_id_blocks
from extract_fluent_fields import sample
from native_flow_data import intersect,write_volume
from x57_baseline_data import ROOT,DATA,FINE,accepted,wall_data,read_json

STATIONS=(-.30,.35,1.20,3.)
WAKE=(0.,5.8,-1.7,1.25)  # z_min,z_max,y_min,y_max
OUT=ROOT/"04_postproc"/FINE


def native_volume():
    _,case,data=accepted(FINE);path=OUT/"native_volume_fields.h5"
    if path.is_file():
        with h5py.File(path) as f:
            if Path(f.attrs["mesh"])==case and Path(f.attrs["data"])==data and path.stat().st_mtime_ns>=max(case.stat().st_mtime_ns,data.stat().st_mtime_ns):
                return path,case,data
    return write_volume(FINE),case,data


def clip_polygon(poly,box):
    for ax,lo,hi in ((0,box[0],box[1]),(1,box[2],box[3])):
        for bound,sign in ((lo,1),(hi,-1)):
            if not len(poly):return poly
            nextp=np.roll(poly,-1,axis=0);inside=(poly[:,ax]-bound)*sign>=0
            crossing=inside!=np.roll(inside,-1);out=[]
            for i,p in enumerate(poly):
                if inside[i]:out.append(p)
                if crossing[i]:
                    q=nextp[i];out.append(p+(q-p)*((bound-p[ax])/(q[ax]-p[ax])))
            poly=np.asarray(out)
    return poly


def area(poly):
    if len(poly)<3:return 0.
    q=poly-poly[0];r=np.roll(q,-1,axis=0)
    return .5*abs(np.sum(q[:,0]*r[:,1]-q[:,1]*r[:,0]))


def plane_records(x,path,rotors):
    with np.load(path) as f:
        if list(f["projected_axes"])!=[1,2]:raise ValueError("Expected transverse y,z plane")
        vertices=f["xy"][:,::-1]; ends=f["offsets"];fields={}
        for n in ("Cp0","k_m2_s2","reynolds_shear_xy_Pa","axial_vorticity_s_inv","u_m_s","v_m_s","w_m_s"):
            fields[n]=f[n]
        fields["cell_id"]=f["cell_ids"]
    zmin=np.minimum.reduceat(vertices[:,0],ends[:-1]);zmax=np.maximum.reduceat(vertices[:,0],ends[:-1])
    ymin=np.minimum.reduceat(vertices[:,1],ends[:-1]);ymax=np.maximum.reduceat(vertices[:,1],ends[:-1])
    def crop(box):
        ids=np.flatnonzero((zmax>box[0])&(zmin<box[1])&(ymax>box[2])&(ymin<box[3]))
        polys=[];used=[];areas=[]
        for i in ids:
            poly=vertices[ends[i]:ends[i+1]]
            if not(zmin[i]>=box[0] and zmax[i]<=box[1] and ymin[i]>=box[2] and ymax[i]<=box[3]):
                poly=clip_polygon(poly,box)
            a=area(poly)
            if a>1.e-18:polys.append(poly);used.append(i);areas.append(a)
        return polys,np.asarray(used,int),np.asarray(areas)
    pol,ix,weights=crop(WAKE)
    if not len(ix):raise ValueError("Wake interrogation window contains no fluid")
    out=[]
    for key,unit in (("Cp0","1"),("k_m2_s2","m2/s2"),("reynolds_shear_xy_Pa","Pa")):
        out.append(dict(record_type="wake_area_mean",quantity=key,value=float(np.average(fields[key][ix],weights=weights)),unit=unit,
                        x_m=x,fluid_area_m2=weights.sum(),region_z_y_m=json.dumps(WAKE),
                        method="polygon intersection with fixed starboard window; fluid-area-weighted cell values"))
    wt=rotors[-1];_,y0,z0=wt["center_m"];r=wt["r_tip_m"]
    box=(z0-r,z0+r,y0-r,y0+r);_,cell_index,wt_area=crop(box)
    if not len(cell_index):raise ValueError("Wingtip wake region empty")
    gamma=np.dot(wt_area,fields["axial_vorticity_s_inv"][cell_index])
    out.append(dict(record_type="circulation",quantity="Gamma_x",value=gamma,unit="m2/s",
                    x_m=x,fluid_area_m2=wt_area.sum(),region_z_y_m=json.dumps(box),
                    method="signed +x vorticity integrated over fluid part of fixed wingtip shaft-centered square, width 2R"))
    if x==STATIONS[0]:
        for rotor in rotors:
            _,ry,rz=rotor["center_m"];tip=rotor["r_tip_m"]
            for poly,i in zip(pol,ix):
                a,b=poly,np.roll(poly,-1,axis=0)
                hit=(a[:,1]>ry)!=(b[:,1]>ry)
                if not hit.any():continue
                aa,bb=a[hit],b[hit]
                zs=np.sort(aa[:,0]+(bb[:,0]-aa[:,0])*(ry-aa[:,1])/(bb[:,1]-aa[:,1]))
                if len(zs)%2:raise ValueError("Unpaired crossings in disk-axis line")
                for l,h in zip(zs[::2],zs[1::2]):
                    l,h=max(l,rz-tip),min(h,rz+tip)
                    u,v=fields["u_m_s"][i],fields["v_m_s"][i]
                    if h<=l or np.hypot(u,v)<1.e-10:continue
                    out.append(dict(record_type="induced_angle",quantity="alpha_ind",unit="deg",value=np.degrees(np.arctan2(v,u)),
                                    component=rotor["name"],x_m=x,y_m=ry,z_m=(l+h)/2,z_lo_m=l,z_hi_m=h,
                                    native_cell_id=int(fields["cell_id"][i]),axial_m_s=u,vertical_m_s=v,
                                    method="atan2(v,u) over fluid-cell intervals on disk-axis height; positive up"))
    return (pol,{k:v[ix] for k,v in fields.items()}),out


def ray_events(native_case,rays,distance):
    with h5py.File(native_case) as f:
        mesh=f["meshes/1"];nf=int(max(mesh["faces/zoneTopology/maxId"]))
        owner=read_id_blocks(mesh["faces/c0"],nf,np.int64);neighbor=read_id_blocks(mesh["faces/c1"],nf,np.int64)
        xyz=read_id_blocks(mesh["nodes/coords"],int(max(mesh["nodes/zoneTopology/maxId"])),float,3)
        for block in mesh["faces/nodes"].values():
            lo,_=bounds(block);nn=block["nnodes"][:].astype(np.int64);span=np.r_[0,np.cumsum(nn)]
            for k in range(0,len(nn),15000):
                end=min(k+15000,len(nn));ids=block["nodes"][span[k]:span[end]]
                for n in np.unique(nn[k:end]):
                    sel=k+np.flatnonzero(nn[k:end]==n);fid=lo+sel
                    polygons=xyz[ids[(span[sel]-span[k])[:,None]+np.arange(n)]]
                    mi,ma=polygons.min(axis=1),polygons.max(axis=1)
                    for ray in rays:
                        start,axis=ray["origin"],ray["normal"];stop=start+axis*distance
                        hit=np.flatnonzero(((ma>=np.minimum(start,stop)-1e-10)&(mi<=np.maximum(start,stop)+1e-10)).all(axis=1))
                        if not len(hit):continue
                        pp=polygons[hit];center=pp.mean(axis=1);a=pp-center[:,None];b=np.roll(a,-1,axis=1)
                        pv=np.cross(axis,b);det=np.einsum("ijk,ijk->ij",a,pv)
                        ok=np.abs(det)>1e-18;iv=np.divide(1.,det,out=np.zeros_like(det),where=ok)
                        v0=start-center;u=np.einsum("ik,ijk->ij",v0,pv)*iv
                        q=np.cross(v0[:,None,:],a);v=np.einsum("k,ijk->ij",axis,q)*iv
                        d=np.einsum("ijk,ijk->ij",b,q)*iv
                        use=ok&(u>=-1e-9)&(v>=-1e-9)&(u+v<=1+1e-9)&(d>1e-10)&(d<distance)
                        for ii,jj in zip(*np.where(use)):
                            face=int(fid[hit[ii]])
                            if face!=ray["face_id"]:
                                ray["events"].append((float(d[ii,jj]),face,int(owner[face]),int(neighbor[face])))


def trace_path(start_cell,events,limit):
    events=sorted(events);prev=0.;cell=start_cell;intervals=[];i=0
    while i<len(events):
        dist=events[i][0];j=i+1
        while j<len(events) and abs(events[j][0]-dist)<2e-10:j+=1
        adj={int(b if a==cell else a) for _,_,a,b in events[i:j] if cell in (a,b)}
        i=j
        if not adj:continue
        if len(adj)!=1:raise ValueError("Ambiguous edge crossing on requested physical wall normal")
        if dist>prev:intervals.append((prev,dist,cell))
        cell=adj.pop();prev=dist
        if not cell:return intervals
    if prev<limit:intervals.append((prev,limit,cell))
    return intervals


def wall_profiles(case,data,volume,cp,wall):
    rays=[];wall_ids=wall["face_id"];lookup={int(fid):k for k,fid in enumerate(wall_ids)}
    with h5py.File(case) as fc,h5py.File(volume) as h,h5py.File(data) as fd:
        mesh=fc["meshes/1"];nf=int(max(mesh["faces/zoneTopology/maxId"]))
        own=read_id_blocks(mesh["faces/c0"],nf,int);other=read_id_blocks(mesh["faces/c1"],nf,int)
        for station,xc in [("HLP-1",.30),("HLP-3",.30),("HLP-3",.70),("HLP-6",.30)]:
            part=cp[(cp.station==station)&(cp.side=="upper")]
            if part.empty:raise ValueError(f"Missing upper wing at {station}")
            sel=part.loc[(part.x_over_c-xc).abs().idxmin()];fid=int(sel.face_id);k=lookup[fid];cell=max(own[fid],other[fid])
            origin=wall["xyz"][k];normal=wall["inward_fluid_area_vector_m2"][k]/wall["area_m2"][k]
            if np.dot(normal,h["xyz_m"][cell-1]-origin)<0:normal=-normal
            shear=-wall["wall_shear_storage"][k]/wall["area_m2"][k];shear=shear-np.dot(shear,normal)*normal
            tau=float(np.linalg.norm(shear))
            if tau==0:raise ValueError("Zero skin friction at specified normal probe")
            group=fd["results/1/phase-1/faces"]
            rho=float(h["rho_kg_m3"][cell-1]);rho_source="adjacent native fluid cell"
            if "SV_DENSITY" in group:
                try:
                    face_rho=float(sample(group,"SV_DENSITY",np.array([fid])).item())
                    if face_rho>0 and np.isfinite(face_rho):rho=face_rho;rho_source="native face density"
                except (ValueError,KeyError):pass
            rays.append(dict(station=station,x_over_c=float(sel.x_over_c),face_id=fid,start_cell=int(cell),origin=origin,
                             normal=normal,tan=shear/tau,tau=tau,rho=rho,rho_source=rho_source,events=[]))
    max_dist=.080;ray_events(case,rays,max_dist)
    result=[]
    physics=read_json(case.parent/"solver_physics.json")
    raw=physics["air"]["viscosity"]["value"];mu=float(raw["value"] if isinstance(raw,dict) else raw)
    with h5py.File(volume) as h:
        for ray in rays:
            rt=np.sqrt(ray["tau"]/ray["rho"])
            path=trace_path(ray["start_cell"],ray["events"],max_dist)
            if len(path)<3:raise ValueError("Too few physical cell intervals on sampled wall normal")
            for d0,d1,cell in path:
                d=(d0+d1)/2;p=ray["origin"]+d*ray["normal"]
                ut=float(np.dot(h["velocity_m_s"][cell-1],ray["tan"]))
                result.append(dict(record_type="boundary_layer",quantity="u_plus",unit="1",value=ut/rt,
                                   station=ray["station"],x_over_c=ray["x_over_c"],face_id=ray["face_id"],native_cell_id=cell,
                                   x_m=p[0],y_m=p[1],z_m=p[2],normal_distance_m=d,normal_interval_start_m=d0,
                                   normal_interval_end_m=d1,y_plus=d*ray["rho"]*rt/mu,wall_shear_Pa=ray["tau"],
                                   u_tau_m_s=rt,rho_kg_m3=ray["rho"],rho_source=ray["rho_source"],mu_Pa_s=mu,
                                   normal_x=ray["normal"][0],normal_y=ray["normal"][1],normal_z=ray["normal"][2],
                                   method="piecewise native-cell velocity at exact centroid-normal ray interval midpoint; signed projection on wall traction"))
    return result
