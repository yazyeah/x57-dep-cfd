"""Measure five disjoint refinement regions and flagged prism columns from a native Fluent CFF mesh."""
import json
import re
from pathlib import Path
import h5py
import numpy as np
from scipy.sparse import coo_matrix
from scipy.sparse.csgraph import connected_components
from cut_fluent_cells import bounds, read_id_blocks, zones
from mesh_physical_zone_audit import physical_zones, wall_depths
from mesh_resolution_audit import fine_sizing_controls, native_wake_hex_edges, rotor_ray_floors

ROOT=Path(__file__).resolve().parents[1]
TARGETS={"wing_wall_layers":(.28,.42),"disk_annuli":(.15,.25),"near_wake":(.17,.28),
         "other_components_and_mid_wake":(.12,.24),"outer_farfield":(0.,.06)}

def boi_bounds(path):
    """Read bounds of named BOI zones from the mesh-input generator's ASCII triangles."""
    contents=Path(path).read_text(encoding="ascii")
    node=re.search(r"\(10 \(1 1 [\da-fA-F]+ 1 3\)\(\s*(.*?)\s*\)\)",contents,re.S)
    if node is None:
        raise ValueError("Cannot parse BOI coordinate block.")
    xyz=np.fromstring(node[1],sep=" ").reshape(-1,3)
    out={}
    pat=r"\(13 \(([\da-fA-F]+) [\da-fA-F]+ [\da-fA-F]+ [\da-fA-F]+ 3\)\(\s*(.*?)\s*\)\)\s*\(45 \((\d+) \S+ (\S+)\)\(\)\)"
    for match in re.finditer(pat,contents,re.S):
        if int(match[1],16)!=int(match[3]):
            raise ValueError("BOI zone IDs disagree.")
        faces=np.asarray([[int(c,16)-1 for c in row.split()[:3]] for row in match[2].splitlines()])
        points=xyz[faces.ravel()]
        out[match[4]]=[points.min(axis=0).tolist(),points.max(axis=0).tolist()]
    for name in ["near_wake_boi","mid_wake_boi"]:
        if name not in out:raise ValueError(f"Missing {name} in BOI input.")
    return out

def quant(v):
    v=np.asarray(v); v=v[np.isfinite(v)]
    return dict(count=len(v),min=float(v.min()),p10=float(np.percentile(v,10)),median=float(np.median(v)),
                p90=float(np.percentile(v,90)),max=float(v.max())) if len(v) else {"count":0}

def actuator_rays(rotors):
    rays=[]
    for rotor in rotors:
        c=np.asarray(rotor["center_m"]);rh,rt=rotor["r_hub_m"],rotor["r_tip_m"];t=rotor["thickness_m"]
        for deg in (22.5,112.5,202.5,292.5):
            angle=np.radians(deg); pos=c.copy();pos[1:]+=(rh+rt)*.5*np.array([np.cos(angle),np.sin(angle)])
            rays.append(dict(name=rotor["name"],direction="axial",sample_deg=deg,axis=0,pos=pos,
                             low=c[0]-t/2,high=c[0]+t/2,hits=[],boundary=[]))
        for axis in (1,2):
            other=3-axis
            for sign in (-1,1):
                pos=c.copy();pos[0]+=.00137*t;offset=.002*rh;pos[other]+=offset
                ends=sorted([c[axis]+sign*np.sqrt(r*r-offset*offset) for r in (rh,rt)])
                rays.append(dict(name=rotor["name"],direction="radial",sample_deg=(0 if axis==1 else 90)+(180 if sign<0 else 0),
                                 axis=axis,pos=pos,low=ends[0],high=ends[1],hits=[],boundary=[]))
    return rays

def intersect_rays(rays,nodes,center,fid,neighbor):
    lo,hi=nodes.min(axis=1),nodes.max(axis=1)
    for ray in rays:
        d=ray["axis"];a,b=(d+1)%3,(d+2)%3;q=ray["pos"]
        mask=(lo[:,a]<=q[a])&(hi[:,a]>=q[a])&(lo[:,b]<=q[b])&(hi[:,b]>=q[b])&(lo[:,d]<ray["high"])&(hi[:,d]>ray["low"])
        if not mask.any():continue
        pts=nodes[mask];mid=center[mask]
        v=pts-mid[:,None,:];w=np.roll(v,-1,axis=1)
        da,db=q[a]-mid[:,a],q[b]-mid[:,b]
        det=v[:,:,a]*w[:,:,b]-v[:,:,b]*w[:,:,a]
        with np.errstate(invalid="ignore",divide="ignore"):
            u=(da[:,None]*w[:,:,b]-db[:,None]*w[:,:,a])/det
            h=(v[:,:,a]*db[:,None]-v[:,:,b]*da[:,None])/det
        usable=(abs(det)>1.e-24)&(u>=-1e-10)&(h>=-1e-10)&(u+h<=1+1e-10)
        i,j=np.where(usable)
        loc=mid[i,d]+u[i,j]*v[i,j,d]+h[i,j]*w[i,j,d]
        keep=(loc>ray["low"]+1e-10)&(loc<ray["high"]-1e-10)
        hit=loc[keep]; outside=neighbor[fid[mask][i[keep]]]==0
        ray["hits"].extend(hit[~outside].tolist());ray["boundary"].extend(hit[outside].tolist())

def ray_records(rays,name):
    result=[]
    for ray in rays:
        if ray["name"]!=name:continue
        x=np.sort(ray["hits"]);distinct=x[np.r_[True,np.diff(x)>1e-8]] if len(x) else x
        bounds=np.r_[ray["low"],distinct,ray["high"]]
        valid=not ray["boundary"] and len(distinct)>0
        result.append(dict(direction=ray["direction"],azimuth_deg=ray["sample_deg"],axis="xyz"[ray["axis"]],
                           fixed_point_m=ray["pos"].tolist(),interval_m=[ray["low"],ray["high"]],
                           cells_crossed=len(bounds)-1 if valid else None,wall_or_open_boundary_hits=len(ray["boundary"]),
                           within_interval_chord_lengths_m=quant(np.diff(bounds)) if valid else None))
    return result

def face_metrics(mesh,xyz,owner,neighbor,nc,rays):
    """Oriented tetrahedral face-fan sums give each CFF polyhedral volume and centroid."""
    # Work about each cell's local reference to avoid global-coordinate cancellation
    # in thin prisms. The face ring is inward for the Fluent c0 side.
    reference=np.zeros((nc+1,3))
    count=np.zeros(nc+1,dtype=np.int32)
    for group in mesh["faces/nodes"].values():
        lo,_=bounds(group)
        nn=group["nnodes"][:].astype(np.int64)
        offset=np.r_[0,np.cumsum(nn)]
        for start in range(0,len(nn),20000):
            end=min(start+20000,len(nn))
            ids=group["nodes"][offset[start]:offset[end]]
            center=np.add.reduceat(xyz[ids],offset[start:end]-offset[start],axis=0)/nn[start:end,None]
            for zone in (owner[lo+start:lo+end],neighbor[lo+start:lo+end]):
                live=zone>0
                np.add.at(reference,zone[live],center[live])
                np.add.at(count,zone[live],1)
    if np.any(count[1:]<4):
        raise ValueError("Incomplete native cell topology in volume audit")
    reference[1:]/=count[1:,None]
    volume=np.zeros(nc+1)
    moment=np.zeros((nc+1,3))
    areas=np.zeros(len(owner))
    for group in mesh["faces/nodes"].values():
        lo,hi=bounds(group)
        nn=group["nnodes"][:].astype(np.int64)
        offsets=np.r_[0,np.cumsum(nn)]
        for begin in range(0,len(nn),20000):
            end=min(begin+20000,len(nn))
            local=nn[begin:end]
            indices=group["nodes"][offsets[begin]:offsets[end]]
            starts=offsets[begin:end]-offsets[begin]
            for n in np.unique(local):
                sel=np.flatnonzero(local==n); fid=lo+begin+sel
                nodes=xyz[indices[starts[sel,None]+np.arange(n)]]
                center=nodes.mean(axis=1)
                intersect_rays(rays,nodes,center,fid,neighbor)
                nxt=np.roll(nodes,-1,axis=1)
                areas[fid]=np.linalg.norm(np.cross(nodes-center[:,None],nxt-center[:,None]).sum(axis=1),axis=1)/2
                p=nodes-center[:,None,:];q=np.roll(p,-1,axis=1)
                normal=np.cross(p,q)
                for cell,sign in ((owner[fid],1.0),(neighbor[fid],-1.0)):
                    live=cell>0;cell=cell[live]
                    arm=center[live]-reference[cell]
                    vol=sign*np.einsum("ij,ikj->ik",arm,normal[live])/6.
                    first=(3*arm[:,None,:]+p[live]+q[live])/4.
                    np.add.at(volume,cell,vol.sum(axis=1))
                    np.add.at(moment,cell,np.einsum("ik,ikj->ij",vol,first))
    if np.any(volume[1:]>=0):
        raise ValueError("Nonpositive fluid volume under the native Fluent c0-inward face orientation.")
    centers=reference.copy();centers[1:]+=moment[1:]/volume[1:,None]
    return centers,-volume,areas

def native_flags(group,n):
    flag=np.zeros(n+1,bool)
    for k,d in group.items():
        if k!="topology":
            lo,hi=bounds(d)
            flag[lo:hi+1]=np.asarray(d["data"][:],bool)
    return flag

def region_budget(mesh_path,config_path):
    config=json.loads(Path(config_path).read_text(encoding="utf-8-sig"))
    boi=boi_bounds(config["boi_file"])
    for region in ("near_wake","mid_wake"):
        requested=config.get(region+"_bounds")
        if requested is not None and not np.allclose(requested,boi[region+"_boi"],rtol=0,atol=1.e-6):
            raise ValueError(f"{region} configuration and native BOI bounds differ")
    model=json.loads((ROOT/"DELIVERABLES/data/actuator_disk_model.json").read_text())
    with h5py.File(mesh_path) as h:
        m=h["meshes/1"]; topology=m["faces/zoneTopology"]
        nc=int(max(m["cells/zoneTopology/maxId"]));nf=int(max(topology["maxId"]))
        owner=read_id_blocks(m["faces/c0"],nf,np.int64); neighbor=read_id_blocks(m["faces/c1"],nf,np.int64)
        xyz=read_id_blocks(m["nodes/coords"],int(max(m["nodes/zoneTopology/maxId"])),float,3)
        rays=actuator_rays(model["rotors"])
        centers,volume,areas=face_metrics(m,xyz,owner,neighbor,nc,rays)
        cap=native_flags(h["special/boundary_layer_flags/faces"],nf)
        prisms=native_flags(h["special/boundary_layer_flags/cells"],nc)
        active=np.flatnonzero(prisms)
        index=np.full(nc+1,-1,np.int64);index[active]=np.arange(len(active))
        join=cap & prisms[owner] & prisms[neighbor]
        graph=coo_matrix((np.ones(join.sum(),np.uint8),(index[owner[join]],index[neighbor[join]])),shape=(len(active),len(active))).tocsr()
        ncol,comps=connected_components(graph,directed=False)
        sizes=np.bincount(comps,minlength=ncol)
        nbase=np.zeros(ncol,int); wingbase=np.zeros(ncol,int); allbase={}; wall_metrics={}; base_areas={}
        desired={w:g["layers"] for g in config.get("prism_scopes",[]) for w in g["walls"]}
        for zone,(lo,hi) in zones(topology).items():
            if not zone.startswith("wall_"):continue
            face_ids=np.arange(lo,hi+1); fid=face_ids[cap[face_ids]]
            wallcell=np.maximum(owner[fid],neighbor[fid]); keep=prisms[wallcell];wallcell=wallcell[keep];fid=fid[keep]
            ids=comps[index[wallcell]];np.add.at(nbase,ids,1)
            if zone=="wall_wing":np.add.at(wingbase,ids,1)
            allbase[zone]=ids
            base_areas[zone]=areas[fid]
            total_area=float(areas[face_ids].sum())
            covered_area=float(areas[fid].sum())
            wall_metrics[zone]=dict(wall_faces=len(face_ids),flagged_base_faces=len(ids),
                                    wall_area_m2=total_area,prism_base_area_m2=covered_area,
                                    prism_wall_area_coverage=covered_area/total_area,
                                    face_area_equilateral_edge_m=quant(np.sqrt(4*areas[face_ids]/np.sqrt(3))),
                                    effective_first_layer_V_over_A_m=quant(volume[wallcell]/areas[fid]))
        incoming=np.zeros(nc+1);layer=np.zeros(nc+1,int);growth=np.full(nc+1,np.nan)
        for zone,(lo,hi) in zones(topology).items():
            if zone not in allbase:continue
            faces=np.arange(lo,hi+1);faces=faces[cap[faces]]
            cell=np.maximum(owner[faces],neighbor[faces])
            usable=prisms[cell].copy()
            usable[usable]=nbase[comps[index[cell[usable]]]]==1
            incoming[cell[usable]]=volume[cell[usable]]/areas[faces[usable]]
            layer[cell[usable]]=1
        iface=np.flatnonzero(join);a=owner[iface];b=neighbor[iface];depth=1
        while np.any(layer[a]==depth) or np.any(layer[b]==depth):
            advancements=0
            for before,after in ((a,b),(b,a)):
                edge=(layer[before]==depth)&(layer[after]==0)
                n1,n2=before[edge],after[edge]
                incoming[n2]=volume[n2]/areas[iface[edge]]
                growth[n2]=incoming[n2]/incoming[n1]
                layer[n2]=depth+1;advancements+=int(edge.sum())
            if advancements==0:break
            depth+=1
        for zone,ids in allbase.items():
            if zone in desired:
                single=nbase[ids]==1
                full=single & (sizes[ids]==desired[zone])
                area=wall_metrics[zone]["wall_area_m2"]
                wall_metrics[zone].update(requested_columns_depth=desired[zone],
                    confirmed_full_depth_single_base_wall_area_fraction=float(base_areas[zone][full].sum()/area),
                    unresolved_multi_base_wall_area_fraction=float(base_areas[zone][~single].sum()/area))
            uniq=ids[nbase[ids]==1]
            selected=np.zeros(ncol,bool);selected[uniq]=True
            wall_metrics[zone]["effective_successive_V_over_A_growth"]=quant(growth[active[selected[comps]]])
            column_cells=active[selected[comps]]
            observed=layer[column_cells]
            transitions={}
            for number in np.unique(observed[observed>=2]):
                sample=growth[column_cells[observed==number]]
                transitions[str(int(number))]=quant(sample)
            wall_metrics[zone]["effective_growth_by_layer"]=transitions
            ns,number=np.unique(sizes[uniq],return_counts=True)
            wall_metrics[zone]["single_base_column_layer_histogram"]={str(k):int(v) for k,v in zip(ns,number)}
            wall_metrics[zone]["multi_base_columns_touching_this_wall"]=int(len(np.unique(ids[nbase[ids]>1])))
        zone_proof=physical_zones(h,owner,neighbor,nc)
        depth_proof=wall_depths(m,xyz,owner,neighbor,areas,cap,prisms,index,comps,sizes,nbase,graph,config)
        wing=np.zeros(nc+1,bool); wing[active]=(wingbase[comps]>0)
        other_prism=np.zeros(nc+1,bool);other_prism[active]=(nbase[comps]>0)&(wingbase[comps]==0)
    fine=config.get("level")=="fine"
    region=np.zeros(nc+1,np.int8)
    region[wing]=1
    if fine:
        # The named airframe components retain their own anchored inflation even inside overlapping BOIs.
        region[other_prism]=4
    def inbox(name):
        low,high=np.array(boi[name]);return ((centers>=low)&(centers<=high)).all(axis=1)
    annular_union=np.zeros(nc+1,bool)
    disks=[]
    for r in model["rotors"]:
        q=centers-np.array(r["center_m"]);rad=np.hypot(q[:,1],q[:,2])
        disk=(abs(q[:,0])<=r["thickness_m"]/2)&(rad>=r["r_hub_m"])&(rad<=r["r_tip_m"])
        disk[0]=False
        annular_union |= disk
        mask=disk&(region==0);region[mask]=2
        cellscale=np.cbrt(volume[disk])
        rays_here=ray_records(rays,r["name"])
        axial=[item["cells_crossed"] for item in rays_here if item["direction"]=="axial" and item["cells_crossed"] is not None]
        radial=[item["cells_crossed"] for item in rays_here if item["direction"]=="radial" and item["cells_crossed"] is not None]
        disks.append(dict(name=r["name"],measured_valid_axial_cells=quant(axial),measured_valid_radial_cells=quant(radial),unshared_annular_cells=int(mask.sum()),all_annular_cells=int(disk.sum()),
                          cell_volume_cuberoot_m=quant(cellscale),face_crossing_rays=rays_here,
                          volume_weighted_cuberoot_m=float(np.average(cellscale,weights=volume[disk])) if len(cellscale) else None))
    for n,mask in [(3,inbox("near_wake_boi")),(4,other_prism|inbox("mid_wake_boi"))]:
        region[(region==0)&mask]=n
    region[region==0]=5
    groups={}
    for idx,(name,(lo,hi)) in enumerate(TARGETS.items(),1):
        mask=region[1:]==idx;count=int(mask.sum());frac=count/nc
        groups[name]=dict(cells=count,fraction=frac,target_fraction=[lo,hi],within_target=bool(round(100*lo)*nc <= 100*count <= round(100*hi)*nc),
                          cell_volume_cuberoot_m=quant(np.cbrt(volume[1:][mask])))
    extra={}
    method="CFF face-fan volume centroids. Disjoint precedence: wing-anchored flagged prism columns, loaded annuli, near-wake box, remaining anchored prism columns or mid-wake box, remainder."
    if fine:
        method=("Native CFF face-fan centroids and cap-connected prism columns. Cells are counted once: "
                "wing-anchored prisms, other wall-anchored prisms, seven loaded annuli in calibrated order, "
                "remaining near-wake box, remaining mid-wake box, then farfield. Shared wing/other columns "
                "are assigned to the wing and reported as explicit bounds on either component allocation.")
        near=inbox("near_wake_boi")
        shared=int(sizes[(wingbase>0)&(nbase>wingbase)].sum())
        extra["geometric_overlaps_before_exclusive_assignment"]={
            "wing_prisms_in_near_box":int(np.count_nonzero(wing&near)),
            "other_wall_prisms_in_near_box":int(np.count_nonzero(other_prism&near)),
            "all_wall_prisms_in_disk_annuli":int(np.count_nonzero((wing|other_prism)&annular_union)),
            "annular_cells_in_near_box":int(np.count_nonzero(annular_union&near)),
            "annular_cells_in_more_than_one_disk_counted_extra_times":sum(d["all_annular_cells"] for d in disks)-int(annular_union.sum()),
            "shared_wing_and_other_wall_column_cells":shared}
        for key,delta in (("wing_wall_layers",-shared),("other_components_and_mid_wake",shared)):
            row=groups[key];lo,hi=row["target_fraction"]
            low_count,high_count=sorted((row["cells"],row["cells"]+delta))
            least,most=low_count/nc,high_count/nc
            row["fraction_bounds_from_shared_columns"]=[least,most]
            row["within_target_for_any_shared_assignment"]=bool(round(100*lo)*nc<=100*low_count and 100*high_count<=round(100*hi)*nc)
        extra["sizing_controls"]=fine_sizing_controls(config,model["rotors"],boi)
        extra["rotor_ray_floors"]=rotor_ray_floors(disks,dict(axial_cells_min=6,radial_cells_min=22))
        extra["near_wake_measured_hex_edges"]=native_wake_hex_edges(
            mesh_path,xyz,centers,volume,owner,neighbor,model["rotors"],(region==3)&~prisms,
            dict(core=(.035,.045),outer_transition=(.050,.065)))
    return dict(**extra,method=method,
                region_cells=groups,all_regions_sum_to_mesh=sum(g["cells"] for g in groups.values())==nc,
                native_bounds_m=boi,tagged_prism_cells=len(active),columns_with_multiple_bases=int(np.sum(nbase>1)),
                tagged_cells_unconnected_to_aircraft_bases=int(sizes[nbase==0].sum()),wall_measurements=wall_metrics,
                native_physical_zone_evidence=zone_proof,native_wall_depth_evidence=depth_proof,
                actuator_regions=disks,fluid_volume_m3=float(volume[1:].sum()),reference_cell_volume_range_m3=quant(volume[1:]),
                fine_design_targets=dict(wing_walls=dict(equivalent_edge_m=[.012,.018],curvature_deg=[10,12],layer_count=18,first_layer_m=1.2e-5,successive_growth=[1.16,1.18]),
                    disk_boi=dict(hlp_size_m=[.007,.009],wingtip_size_m=[.010,.014],axial_cells_min=6,radial_cells_min=22,wingtip_radial_note="Floor only; 40-55 radial cells across WT-1 is higher resolution and passes."),
                    near_wake_core_hex_size_m=[.035,.045],near_wake_box_outer_transition_m=[.050,.065],other_walls=dict(layers=[14,16],mid_wake_size_m=[.080,.110]),
                    external_farfield=dict(growth=1.22,max_size_m=[2.,2.5])),
                recorded_mesh_request=config,estimated_linear_size="Cube root of cell volume (isotropic-equivalent); independent centroid-to-fan polygon ray intersections report actual local axial/radial intervals.")
