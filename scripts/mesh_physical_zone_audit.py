"""Physical boundary and wall-column evidence from the native Fluent CFF topology."""
import re
import numpy as np
from scipy.sparse import coo_matrix
from scipy.sparse.csgraph import connected_components
from scipy.spatial import cKDTree
from cut_fluent_cells import bounds, zones
from p2_geometry_io import TYPES, WALLS


def physical_zones(h,owner,neighbor,ncell):
    mesh=h["meshes/1"]
    records=h["settings/Thread Variables"][0].decode()
    threads={int(i):(kind.strip('"'),name.strip('"')) for i,kind,name in re.findall(
        r'\(\s*(?:39|45)\s+\(\s*(\d+)\s+([^\s()]+)\s+("[^"]*"|[^\s()]+)\s*\)',records)}
    def entries(part):
        group=mesh[part+"/zoneTopology"]
        names=group["name"][0].decode().rstrip(";").split(";")
        return zip(names,group["id"][:],group["minId"][:],group["maxId"][:],group["dimension"][:],strict=True)
    cells=[]
    for name,zid,lo,hi,dim in entries("cells"):
        kind,thread_name=threads.get(int(zid),(None,None))
        cells.append(dict(name=name,thread_type=kind,thread_name=thread_name,zone_id=int(zid),
                          cells=int(hi)-int(lo)+1,dimension=int(dim)))
    inside=(owner>0)&(neighbor>0)
    graph=coo_matrix((np.ones(np.count_nonzero(inside),dtype=np.uint8),(owner[inside]-1,neighbor[inside]-1)),
                     shape=(ncell,ncell)).tocsr()
    connected=int(connected_components(graph,directed=False,return_labels=False))
    single=(len(cells)==1 and cells[0]["thread_type"]=="fluid" and cells[0]["name"]==cells[0]["thread_name"]
            and cells[0]["cells"]==ncell and ncell>0 and cells[0]["dimension"]==3 and connected==1)
    faces={}
    checked=True
    code={"interior":2,"wall":3,"pressure-inlet":4,"pressure-outlet":5,"symmetry":7,"pressure-far-field":9}
    bc=mesh["faces/zoneTopology/zoneType"][:]
    for row,ftype in zip(entries("faces"),bc,strict=True):
        name,zid,lo,hi,dim=row
        i,j=int(lo),int(hi)+1
        kind,thread_name=threads.get(int(zid),(None,None))
        one=int(np.sum((owner[i:j]>0)^(neighbor[i:j]>0)))
        two=int(np.count_nonzero(inside[i:j]))
        n=j-i
        native_ok=(n>0 and dim==3 and name==thread_name and code.get(kind)==int(ftype))
        if kind=="interior":
            checked &= native_ok and two==n
            continue
        allowed={TYPES[name][0]} if name in TYPES else set()
        if name in TYPES and name.startswith("farfield_"):
            # Meshing may preserve a pressure-far-field patch until the static solver configures it.
            allowed.add("pressure-far-field")
        valid=bool(native_ok and one==n and kind in allowed)
        checked &= valid and name not in faces
        faces[name]=dict(zone_id=int(zid),native_type=kind,zone_type_code=int(ftype),faces=n,
                         one_fluid_neighbor_faces=one,dimension=int(dim),passed=valid)
    return dict(cell_zones=cells,native_connected_fluid_components=connected,physical_boundaries=faces,
                single_connected_fluid_region=bool(single),exact_physical_boundaries=bool(checked and set(faces)==set(TYPES)))


def wall_polygons(mesh,topology):
    groups={}
    for name in WALLS:
        low,high=topology[name]
        faces={}
        for blk in mesh["faces/nodes"].values():
            lo,hi=bounds(blk)
            a,b=max(low,lo),min(high,hi)
            if a>b:continue
            counts=blk["nnodes"][:].astype(np.int64);offsets=np.r_[0,np.cumsum(counts)]
            offset=offsets[a-lo]; part=blk["nodes"][offset:offsets[b-lo+1]]
            for fid in range(a,b+1):
                idx=fid-lo
                faces[fid]=part[offsets[idx]-offset:offsets[idx+1]-offset]
        if len(faces)!=high-low+1:raise ValueError("Missing native wall polygon on "+name)
        groups[name]=faces
    return groups


def verify_prismatic_geometry(mesh,xyz,owner,neighbor,ids,rings,normals,targets,initial,growth,indices,prisms,caps):
    """Recover unflagged polygonal columns by native cell-face incidence and physical layer thickness."""
    cells=np.r_[owner[1:],neighbor[1:]]
    face_ids=np.tile(np.arange(1,len(owner),dtype=np.int32),2)
    present=cells>0
    incidence=coo_matrix((np.ones(np.count_nonzero(present),np.uint8),(cells[present],face_ids[present])),
                         shape=(len(prisms),len(owner))).tocsr()
    blocks=[]
    for group in mesh["faces/nodes"].values():
        lo,hi=bounds(group)
        blocks.append((lo,hi,np.r_[0,np.cumsum(group["nnodes"][:],dtype=np.int64)],group["nodes"][:]))
    def vertices(fid):
        for lo,hi,offset,nodes in blocks:
            if lo<=fid<=hi:
                k=fid-lo
                return nodes[offset[k]:offset[k+1]].ravel()
        raise ValueError("Missing CFF face-node block")
    result=np.zeros(len(ids),int)
    tolerance=128*np.finfo(float).eps*max(1.,np.abs(xyz).max())
    for i in indices:
        base=int(ids[i]);cell=int(max(owner[base],neighbor[base]));ring=rings[i]
        actual=0.;nominal=0.;h=initial[i]
        for k in range(targets[i]):
            if cell<=0:break
            faces=incidence.indices[incidence.indptr[cell]:incidence.indptr[cell+1]]
            n=len(ring)
            if len(faces)!=n+2:break
            lower=set(ring.tolist())
            upper=None;sides=[]
            for fid in faces:
                if fid==base:continue
                points=vertices(fid)
                common=lower.intersection(points)
                if not common and len(points)==n and upper is None:
                    upper=(int(fid),points)
                elif len(common)==2 and len(points)==4:sides.append(points)
                else:break
            if upper is None or len(sides)!=n:break
            other_face,upper_ring=upper
            top=set(upper_ring.tolist())
            side_edges=set()
            for side in sides:
                if len(top.intersection(side))!=2:break
                side_edges.add(frozenset(lower.intersection(side)))
            edges={frozenset((ring[j-1],ring[j])) for j in range(n)}
            if side_edges!=edges:break
            rise=float((xyz[upper_ring].mean(axis=0)-xyz[ring].mean(axis=0))@normals[i])
            actual+=rise;nominal+=h
            # Native tagged cap and cell, or a geometrical n-gonal prism within the
            # cumulative requested physical near-wall envelope. This excludes bulk core cells.
            if rise<=0 or (not (prisms[cell] and (caps[base] or caps[other_face])) and actual>nominal+tolerance):
                break
            result[i]+=1;h*=growth[i]
            cell=int(neighbor[other_face] if owner[other_face]==cell else owner[other_face])
            ring=upper_ring;base=other_face
    return result


def wall_depths(mesh,xyz,owner,neighbor,area,caps,prisms,cell_index,components,sizes,nbase,cap_graph,config):
    """Shorter columns require a native adjacent depth step or an opposing wall inside the two prism envelopes."""
    scopes={wall:s for s in config.get("prism_scopes",[]) for wall in s["walls"]}
    if set(scopes)!=set(WALLS):raise ValueError("Five explicit wall prism scopes are required")
    stair=config.get("native_post_improvement_method")=="Stair Step"
    topology=zones(mesh["faces/zoneTopology"])
    groups=wall_polygons(mesh,topology)
    ids=np.array([fid for records in groups.values() for fid in records],dtype=np.int64)
    label=np.array([z for z,p in groups.items() for _ in p])
    rings=[ring for p in groups.values() for ring in p.values()]
    cen=np.array([xyz[r].mean(axis=0) for r in rings])
    normals=np.array([np.cross(xyz[r]-c,np.roll(xyz[r],-1,axis=0)-c).sum(axis=0) for c,r in zip(cen,rings)])
    normals*=np.where(owner[ids]>0,1.,-1.)[:,None]
    norm=np.linalg.norm(normals,axis=1)
    if (norm<=0).any():raise ValueError("A real wall face has zero area")
    normals/=norm[:,None]
    radii=np.array([np.linalg.norm(xyz[r]-c,axis=1).max() for c,r in zip(cen,rings)])
    distance=np.array([scopes[z]["total_height_m"] for z in label])
    target=np.array([scopes[z]["layers"] for z in label])
    base=np.maximum(owner[ids],neighbor[ids])
    flagged=caps[ids]&prisms[base]
    comp=np.full(len(ids),-1,dtype=int);comp[flagged]=components[cell_index[base[flagged]]]
    degree=cap_graph.getnnz(axis=0)+cap_graph.getnnz(axis=1)
    bad_degree=np.bincount(components,weights=degree>2,minlength=len(sizes))>0
    ends=np.bincount(components,weights=degree==1,minlength=len(sizes))
    is_path=(~bad_degree)&((sizes==1)|(ends==2))
    terminal=np.zeros(len(ids),bool);terminal[flagged]=degree[cell_index[base[flagged]]]<=1
    single=flagged&terminal&(nbase[comp]==1)&is_path[comp] if len(sizes) else np.zeros(len(ids),bool)
    depth=np.zeros(len(ids),dtype=int)
    depth[single]=sizes[comp[single]]
    unresolved=np.flatnonzero(~single | (depth<target))
    verified_by_geometry=np.zeros(len(ids),bool)
    if len(unresolved):
        first=np.array([scopes[z]["first_height_m"] for z in label])
        growth=np.array([scopes[z]["growth"] for z in label])
        recovered=verify_prismatic_geometry(mesh,xyz,owner,neighbor,ids,rings,normals,target,first,growth,
                                            unresolved,prisms,caps)
        verified_by_geometry=recovered>depth
        depth=np.maximum(depth,recovered)
    known=single|verified_by_geometry
    full=known&(depth>=target)
    depth_known=known&(depth<target)
    category=np.full(len(ids),"unresolved_shared_or_branched",dtype=object)
    category[~flagged]="unproven_prism_base"
    category[depth_known]="unexplained_short_column"
    category[full]="full_depth"
    edge_owner={}
    a=[];b=[]
    for i,ring in enumerate(rings):
        for start,end in zip(ring,np.roll(ring,-1)):
            key=(int(min(start,end)),int(max(start,end)))
            if key in edge_owner:
                a.append(edge_owner[key]);b.append(i)
            else:edge_owner[key]=i
    a=np.asarray(a,dtype=int);b=np.asarray(b,dtype=int)
    match=label[a]==label[b]
    surface=coo_matrix((np.ones(match.sum(),dtype=np.uint8),(a[match],b[match])),shape=(len(ids),len(ids))).tocsr()
    _,island=connected_components(surface,directed=False)
    transition_sample={}
    clash_sample={}
    if stair:
        for x,y in ((a,b),(b,a)):
            step=depth_known[x]&known[y]&(label[x]==label[y])&(depth[y]>depth[x])
            category[x[step]]="local_native_depth_step"
            for i,j in zip(x[step],y[step]):
                if label[i] not in transition_sample:
                    transition_sample[label[i]]=dict(wall_face_id=int(ids[i]),actual_depth=int(depth[i]),
                        neighboring_face_id=int(ids[j]),neighbor_depth=int(depth[j]))
        tree=cKDTree(cen)
        longest=distance.max()
        face_radius=radii.max()
        atol=128*np.finfo(float).eps*max(1.,np.abs(xyz).max())
        for i in np.flatnonzero((category=="unexplained_short_column")|(category=="unresolved_shared_or_branched")):
            forward=normals[i]
            for j in tree.query_ball_point(cen[i],distance[i]+longest+face_radius):
                if i==j or np.dot(forward,normals[j])>=0:continue
                # Intersect the wall normal with each triangle of the actual opposing face.
                verts=xyz[rings[j]];va=verts-cen[j];vb=np.roll(va,-1,axis=0)
                hv=np.cross(forward,vb);det=np.einsum('ij,ij->i',va,hv)
                use=abs(det)>atol*atol
                if not np.any(use):continue
                delta=cen[i]-cen[j]; qv=np.cross(delta,va[use])
                u=(hv[use]@delta)/det[use]
                v=(qv@forward)/det[use];t=np.einsum('ij,ij->i',vb[use],qv)/det[use]
                hit=(u>=0)&(v>=0)&(u+v<=1)&(t>atol)&(t<=distance[i]+distance[j])
                if np.any(hit):
                    category[i]="opposing_wall_within_prism_envelopes"
                    if label[i] not in clash_sample:
                        gap=float(t[hit].min())
                        clash_sample[label[i]]=dict(wall_face_id=int(ids[i]),opposing_wall=str(label[j]),
                            opposing_face_id=int(ids[j]),normal_clearance_m=gap,
                            available_stack_sum_m=float(distance[i]+distance[j]),hit_xyz_m=(cen[i]+gap*forward).tolist())
                    break
    output={}
    for z in WALLS:
        selected=label==z
        areas=area[ids]
        counts={};patches=[]
        for value in np.unique(category[selected]):
            ii=selected&(category==value)
            counts[value]=dict(faces=int(ii.sum()),area_m2=float(areas[ii].sum()),
                               first_face_id=int(ids[ii][0]),first_centroid_m=cen[ii][0].tolist())
        for patch in np.unique(island[selected]):
            ii=selected&(island==patch)
            patches.append(dict(faces=int(ii.sum()),full_depth_faces=int((ii&full).sum()),
                                wall_area_m2=float(areas[ii].sum())))
        bad=selected&~np.isin(category,["full_depth","local_native_depth_step","opposing_wall_within_prism_envelopes"])
        hist={int(d):int(np.count_nonzero(selected&known&(depth==d))) for d in np.unique(depth[selected&known])}
        output[z]=dict(requested_depth=int(scopes[z]["layers"]),wall_faces=int(selected.sum()),
                       verified_column_depth_histogram=hist,wall_face_status=counts,connected_wall_patches=patches,
                       native_flagged_base_faces=int(flagged[selected].sum()),
                       recovered_geometric_prism_faces=int(verified_by_geometry[selected].sum()),
                       native_stair_step_sample=transition_sample.get(z),opposing_wall_sample=clash_sample.get(z),
                       failed_faces=int(bad.sum()),passed=bool(not bad.any() and patches and all(p["full_depth_faces"] for p in patches)))
    return output
