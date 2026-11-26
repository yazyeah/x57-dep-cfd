"""Generate nested, conforming SHELL181 discretizations of the same sheet geometry."""
import argparse, json
from pathlib import Path
import numpy as np
from scipy.spatial import cKDTree
from scipy.sparse import coo_matrix
from scipy.sparse.csgraph import connected_components
from p2_geometry_io import section_segments, heights, read_patches, stl_triangles
from fsi_provenance import geometry,lock_geometry,hashes,signature,commit,accepted_model
from mapdl_shell_fields import source_hash

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / '03_cases/fsi_structural'
GEO = ROOT / '01_geometry'
WALLS = ['wall_wing','wall_fuselage','wall_nacelles','wall_sponson','wall_empennage']
SECTIONS = WALLS + ['main_web','aft_web','wing_ribs','carry_covers']
GAUGES = [.0025,.0018,.0035,.0020,.0018,.003,.0025,.002,.0025]
# Model B (2026-11-26): the 30 %/65 % chord spar webs continue from the first exposed rib (z = 0.67 m) through the
# fuselage to the symmetry plane, closed by upper/lower carry-through covers (wing-skin gauge 2.5 mm) where the
# fuselage replaces the wing skin, with a side-of-body rib at the wing/fuselage junction. Model A ended the box at
# z = 0.67 m, so the wing bending and the thrust in-plane moment reached the symmetry plane only through the thin
# fuselage skin (singular junction peak, minimum yield FoS 0.62).
CARRY_THROUGH = True
DT = np.dtype([('normal','<f4',3),('v','<f4',(3,3)),('attr','<u2')])

def canonical_faces(t):
    # The starting corner and the record order do not change a triangle's oriented geometry.
    first=np.lexsort((t[:,:,2],t[:,:,1],t[:,:,0]),axis=1)[:,0]
    rows=t[np.arange(len(t))[:,None],(first[:,None]+np.arange(3))%3].reshape(-1,9)
    return rows[np.lexsort(rows.T[::-1])]

def read_skin(source):
    directory=Path(source['source_surface_dir'])
    native=read_patches(Path(source['source_surface_file']))
    meshes=[]
    for name in WALLS:
        stored=stl_triangles(directory/(name+'.stl'))
        if not np.array_equal(canonical_faces(stored),canonical_faces(native[name])):
            raise ValueError('Named STL wall differs from the accepted mesher input '+name)
        meshes.append(native[name])
    # CFD patch normals point from the fluid into the solid. Shell TOP is exterior.
    tris=np.concatenate(meshes)[:,[0,2,1],:].astype(float)
    xyz,idx=np.unique(tris.reshape(-1,3),axis=0,return_inverse=True)
    return xyz,idx.reshape(-1,3),np.repeat(np.arange(5),[len(m) for m in meshes])

def refine(v,f,tag,level):
    if level=='coarse':return v,f,tag
    ed=np.sort(f[:,[[0,1],[1,2],[2,0]]],axis=2)
    ue,m=np.unique(ed.reshape(-1,2),axis=0,return_inverse=True)
    lengths=np.linalg.norm(v[ue[:,0]]-v[ue[:,1]],axis=1)
    selected=np.ones(len(ue),bool) if level=='fine' else lengths>=np.quantile(lengths,.55)
    node=np.full(len(ue),-1,int);node[selected]=len(v)+np.arange(sum(selected))
    v=np.vstack((v,v[ue[selected]].mean(1)))
    F=[];T=[]
    for face,split,group in zip(f,node[m].reshape(-1,3),tag):
        use=np.flatnonzero(split>=0);n=len(use)
        if n==0:ff=[face]
        elif n==3:
            a,b,c=face;l,k,j=split;ff=[[a,l,j],[l,b,k],[j,k,c],[l,k,j]]
        elif n==1:
            i=use[0];a,b,c=np.roll(face,-i);d=split[i];ff=[[a,d,c],[d,b,c]]
        else:
            i=(np.flatnonzero(split<0)[0]+1)%3
            a,b,c=np.roll(face,-i);d,e,_=np.roll(split,-i)
            ff=[[b,e,d],[a,d,e],[a,e,c]] if np.linalg.norm(v[a]-v[e])<np.linalg.norm(v[c]-v[d]) else [[b,e,d],[a,d,c],[d,e,c]]
        F.extend(ff);T.extend([group]*len(ff))
    return v,np.asarray(F),np.asarray(T)

def pair_skin(v,f,tag):
    ed=f[:,[[0,1],[1,2],[2,0]]].reshape(-1,2)
    _,inv,count=np.unique(np.sort(ed,axis=1),axis=0,return_inverse=True,return_counts=True)
    order=np.argsort(inv);start=np.r_[0,count.cumsum()][:-1][count==2]
    A=order[start];B=order[start+1]
    i,j=A//3,B//3
    same=tag[i]==tag[j];A,B,i,j=A[same],B[same],i[same],j[same]
    a,b=ed[A].T
    c=f[i,(A%3+2)%3];d=f[j,(B%3+2)%3]
    quad=np.column_stack((c,a,d,b))
    xyz=v[quad];tang=np.roll(xyz,-1,axis=1)-xyz
    norms=np.cross(tang,np.roll(tang,-1,axis=1))
    norm=np.linalg.norm(norms,axis=2)
    orient=norms.sum(1); orient/=np.maximum(np.linalg.norm(orient,axis=1,keepdims=True),1e-30)
    cos=np.einsum('ijk,ik->ij',norms,orient)/np.maximum(norm,1e-30)
    side=np.linalg.norm(tang,axis=2)
    sint=norm/(side*np.roll(side,-1,axis=1))
    score=np.min(cos,axis=1)*np.min(sint,axis=1)*side.min(1)/side.max(1)
    # MAPDL's SHELL181 warping factor is the distance between the two quad diagonals divided by the shell
    # thickness (reproduced to 5e-4 from the 2026-11-25 .err files); it warns above 1 and rejects above 5.
    # Keep only planar-enough triangle pairs (factor < 1); others stay two triangles, as MAPDL advises.
    d1=xyz[:,2]-xyz[:,0];d2=xyz[:,3]-xyz[:,1];nd=np.cross(d1,d2)
    gap=np.abs(np.einsum('ij,ij->i',xyz[:,1]-xyz[:,0],nd))/np.maximum(np.linalg.norm(nd,axis=1),1e-30)
    warp=gap/np.asarray(GAUGES)[tag[i]]
    ranked=np.flatnonzero((cos.min(1)>.97)&(sint.min(1)>.45)&(warp<1.));ranked=ranked[np.argsort(-score[ranked])]
    used=np.zeros(len(f),bool);picked=[]
    for k in ranked:
        if not (used[i[k]] or used[j[k]]):
            picked.append(k);used[[i[k],j[k]]]=True
    tri=f[~used]
    return np.vstack((quad[picked],tri[:,[0,1,2,2]])),np.r_[tag[i[picked]],tag[~used]]

def split_warped(v,el,group):
    """Split quadrilaterals whose SHELL181 warping factor (diagonal gap / shell thickness) is >= 1 into two
    triangles with the same orientation; MAPDL warns above 1 and rejects above 5 (e.g. twisted coarse web panels)."""
    el=np.asarray(el);group=np.asarray(group)
    P=v[el];d1=P[:,2]-P[:,0];d2=P[:,3]-P[:,1];nd=np.cross(d1,d2)
    gap=np.abs(np.einsum('ij,ij->i',P[:,1]-P[:,0],nd))/np.maximum(np.linalg.norm(nd,axis=1),1e-30)
    bad=(el[:,2]!=el[:,3])&(gap/np.asarray(GAUGES)[group]>=1.)
    a,b,c,d=el[bad].T
    tri=np.vstack((np.column_stack((a,b,c,c)),np.column_stack((a,c,d,d))))
    return np.vstack((el[~bad],tri)),np.r_[group[~bad],group[bad],group[bad]]

def add_wingbox(v,f,tag,step):
    skin=f[tag==0]
    n=np.cross(v[skin[:,1]]-v[skin[:,0]],v[skin[:,2]]-v[skin[:,0]])
    surf=[np.unique(skin[n[:,1]*sign>.35*np.linalg.norm(n,axis=1)]) for sign in (1,-1)]
    trees=[cKDTree(v[ids]) for ids in surf]
    cad=np.fromfile(GEO/'cad_patches/wall_wing.stl',dtype=DT,offset=84)['v'].astype(float)
    output=v.tolist();elements=[];groups=[]
    # The first/last ribs remain on the exposed wing skin. The exterior shell
    # transmits loads from the box ends into the fuselage and wingtip nacelle.
    ribs=np.linspace(.67,4.57,8);segments=[];rib_indices=[0]
    for a,b in zip(ribs,ribs[1:]):
        segments.extend(np.linspace(a,b,1+round((b-a)/step))[:-1]);rib_indices.append(len(segments))
    stations=np.r_[segments,ribs[-1]]
    junction=None
    if CARRY_THROUGH:
        # Inboard stations from the symmetry plane (z = 0 exactly, so they join the symmetry constraint set) to the
        # first exposed rib. Where the structural wing skin exists the webs are tied to skin nodes as outboard;
        # inside the fuselage (below the lowest wing-skin node) they get their own cap nodes at the CAD section.
        inboard=np.linspace(0.,ribs[0],1+max(2,round(ribs[0]/step)))[:-1]
        stations=np.r_[inboard,stations];rib_indices=[i+len(inboard) for i in rib_indices]
        # Side-of-body station: the first inboard station from which every station out to the first exposed rib
        # has all four web caps (both webs, top and bottom) within 0.75 step of a wing-skin node.
        def cap_distance(z):
            cut=section_segments(cad,max(z,.005));worst=0.
            for frac in (.30,.65):
                x=cut[:,:,0].min()+frac*np.ptp(cut[:,:,0]);e=heights(cut,x)
                for tree,y in zip(trees,[e.max(),e.min()]):worst=max(worst,float(tree.query([x,y,z])[0]))
            return worst
        tied=[cap_distance(z)<=.75*step for z in inboard]
        junction=len(inboard)
        while junction>0 and tied[junction-1]:junction-=1
    maxerr=0.;webs=[]
    for g,frac in [(5,.30),(6,.65)]:
        grid=[]
        for i,z in enumerate(stations):
            cut=section_segments(cad,max(z,.005));x=cut[:,:,0].min()+frac*np.ptp(cut[:,:,0])
            elevations=heights(cut,x)
            if len(elevations)<2:raise ValueError(('Wing box CAD section missing',x,z))
            if junction is not None and i<junction:
                top=len(output);output.append([x,float(elevations.max()),z])
                bottom=len(output);output.append([x,float(elevations.min()),z])
                pts=np.array(output)
            else:
                anchors=[]
                for tree,ids,y in zip(trees,surf,[elevations.max(),elevations.min()]):
                    dist,ix=tree.query([x,y,z]);maxerr=max(maxerr,float(dist));anchors.append(ids[ix])
                top,bottom=anchors
                pts=v
            assert pts[top,1]>pts[bottom,1]
            mid=len(output);output.append(((np.asarray(output[top])+np.asarray(output[bottom]))*.5).tolist())
            grid.append([top,mid,bottom])
        grid=np.array(grid);webs.append(grid)
        for a,b in zip(grid,grid[1:]):
            for k in [0,1]:
                loop=list(dict.fromkeys([a[k],b[k],b[k+1],a[k+1]]))
                if len(loop)==3:loop.append(loop[-1])
                if len(loop)==4:elements.append(loop);groups.append(g)
    for i in rib_indices+([junction] if junction else []):
        a,b=webs[0][i],webs[1][i]
        for k in (0,1):
            elements.append([a[k],b[k],b[k+1],a[k+1]]);groups.append(7)
    if junction:
        # Carry-through covers between the two webs, from the symmetry plane to the side-of-body rib.
        for i in range(junction):
            for k in (0,2):
                a,b,c,d=webs[0][i][k],webs[1][i][k],webs[1][i+1][k],webs[0][i+1][k]
                elements.append([a,b,c,d]);groups.append(8)
    return np.array(output),np.array(elements),np.array(groups),maxerr

def build(level):
    source=geometry();lock=lock_geometry(source)
    if (OUT/'models'/level/'model.json').is_file():
        try:
            existing=accepted_model(level,source)
            print('Verified existing structural model',level,existing['model_signature'],flush=True)
            return
        except (ValueError,FileNotFoundError,KeyError):
            pass
    base_mesh=read_skin(source);base_node_count=len(base_mesh[0])
    v,faces,tags=refine(*base_mesh,level)
    skin_nodes=len(v);quad,qtag=pair_skin(v,faces,tags)
    step={'coarse':.075,'medium':.052,'fine':.0375}[level]
    v,web,webtag,tie_error=add_wingbox(v,faces,tags,step)
    elements,sect=split_warped(v,np.vstack([quad,web]),np.r_[qtag,webtag])
    assert len(v)<128000 and len(elements)<128000
    v0=v[elements[:,0]];v1=v[elements[:,1]];v2=v[elements[:,2]];v3=v[elements[:,3]]
    area=.5*(np.linalg.norm(np.cross(v1-v0,v2-v0),axis=1)+np.linalg.norm(np.cross(v2-v0,v3-v0),axis=1))
    assert np.all(area>1e-12)
    ed=elements[:,[[0,1],[1,2],[2,3],[3,0]]].reshape(-1,2)
    graph=coo_matrix((np.ones(len(ed)),ed.T),shape=(len(v),len(v))).tocsr()
    n_parts,labels=connected_components(graph,directed=False)
    if n_parts not in (2,3):raise ValueError(('Inspect detached/bonded structural parts',n_parts))
    primary=labels[np.argmin(v[:,0])]
    tail_component=next(k for k in range(n_parts) if k!=primary and v[labels==k,2].max()>1.25)
    tail_ids=np.flatnonzero((labels==tail_component)&(v[:,2]>.015)&(v[:,2]<.14))
    body_ids=np.flatnonzero((labels==primary)&(v[:,0]>4.0)&(v[:,1]<-.30)&(v[:,2]<.17))
    body_ids=body_ids[body_ids<base_node_count];tail_ids=tail_ids[tail_ids<base_node_count]
    body_tree=cKDTree(v[body_ids]);tail_tree=cKDTree(v[tail_ids])
    lug_pairs=[]
    for xc in (4.47,4.78):
        for zc in (.045,.105):
            candidates=tail_ids[tail_tree.query([xc,-.442,zc],k=8)[1]]
            slave=next(int(a) for a in candidates if a not in [pp[1] for pp in lug_pairs])
            d,idx=body_tree.query(v[slave]);master=int(body_ids[idx])
            if d>.12:raise ValueError(('unphysical tail lug distance',d))
            if slave not in [pp[1] for pp in lug_pairs]:lug_pairs.append([master,slave])
    assert len(lug_pairs)==4
    if n_parts==3:
        elevator=next(k for k in range(n_parts) if k not in (primary,tail_component))
        movable=np.flatnonzero((labels==elevator)&(np.arange(len(v))<base_node_count))
        fixed=np.flatnonzero((labels==tail_component)&(np.arange(len(v))<base_node_count))
        tree=cKDTree(v[fixed]);slave_tree=cKDTree(v[movable])
        for z in (.16,.48,.82):
            slave=int(movable[slave_tree.query([4.846,-.431,z])[1]])
            gap,nearest=tree.query(v[slave])
            if gap>.035:raise ValueError(('Elevator hinge not found',z,gap))
            lug_pairs.append([int(fixed[nearest]),slave])
    # Gear is absent from CAD. Use finite patches on its assumed attachment skin.
    def support(index,center,radius):
        ids=np.unique(faces[tags==index]);nearest=ids[np.argmin(np.linalg.norm(v[ids]-center,axis=1))]
        return ids[np.linalg.norm(v[ids]-v[nearest],axis=1)<=radius]
    nose=support(1,[-2.2,-.92,.03],.13);main=support(3,[.15,-.9,.49],.15)
    sym=np.flatnonzero(abs(v[:,2])<1e-7)
    assert min(len(nose),len(main),len(sym))>=4
    tip=np.flatnonzero(np.linalg.norm(v-[.0,.14,4.70],axis=1)<.10)
    out=OUT/'models'/level;out.mkdir(parents=True,exist_ok=True)
    center=np.array([v[np.unique(ids)].mean(0) for ids in elements])
    is_pylon=(sect==2)&(center[:,0]>-.38)&(center[:,0]<.23)&(center[:,1]>.035)
    is_box=sect>=5
    np.savez(out/'shell_mesh.npz',xyz=v,faces=faces,face_zone=tags,skin_nodes=skin_nodes,
             elements=elements,element_section=sect,pylon=is_pylon,wingbox=is_box,area_m2=area,sym=sym,nose=nose,main=main,tip=tip)
    with (out/'model.inp').open('w',encoding='ascii') as h:
        h.write('/PREP7\n/UNITS,SI\nET,1,SHELL181\nKEYOPT,1,3,2\nKEYOPT,1,8,2\nMP,EX,1,7.17E10\nMP,PRXY,1,0.33\nMP,DENS,1,2810\n')
        for j,thick in enumerate(GAUGES,1):
            h.write(f'SECTYPE,{j},SHELL\nSECDATA,{thick:.5f},1,0,5\nSECOFFSET,MID\n')
        for i,(x,y,z) in enumerate(v,1):h.write(f'N,{i},{x:.12g},{y:.12g},{z:.12g}\n')
        h.write('LOCAL,11,CART,0,0,0,0,0,-90\nLOCAL,12,CART,0,0,0\nCSYS,0\nTYPE,1\nMAT,1\n')
        current=-1
        for ele,group in zip(elements,sect):
            if group!=current:
                # Spar webs use +span; ribs and nacelles use +chord as their in-plane reference.
                h.write(f'SECNUM,{group+1}\nESYS,{11 if group in (0,5,6,8) else 12}\n')
                current=group
            h.write('E,'+','.join(str(int(index+1)) for index in ele)+'\n')
        for key,mask in [('PYLON',is_pylon),('WINGBOX',is_box)]+[(name.replace('wall_','').upper(),sect==j) for j,name in enumerate(WALLS)]:
            h.write('ESEL,NONE' + chr(10))
            ordered=np.flatnonzero(mask)+1
            for streak in np.split(ordered,np.flatnonzero(np.diff(ordered)>1)+1):
                if len(streak):h.write(f'ESEL,A,ELEM,,{streak[0]},{streak[-1]}'+chr(10))
            h.write(f'CM,{key},ELEM'+chr(10))
        h.write('ALLSEL,ALL'+chr(10))
        for master,slave in lug_pairs:
            h.write(f'CERIG,{master+1},{slave+1},ALL\n')
        for ids,dofs in [(sym,['UZ','ROTX','ROTY']),(np.union1d(nose,main),['UX','UY'])]:
            for j in ids:
                for dof in dofs:h.write(f'D,{j+1},{dof},0\n')
        h.write('ALLSEL,ALL\nFINISH\n')
    stats={'level':level,'nodes':len(v),'elements':len(elements),'quadrilaterals':int(sum(elements[:,2]!=elements[:,3])),
        'tail_attachment_rigid_pairs_1based':(np.asarray(lug_pairs)+1).tolist(),'max_surrogate_lug_length_m':float(max(np.linalg.norm(v[a]-v[b]) for a,b in lug_pairs)),'components':list(SECTIONS),'shell_gauges_m':GAUGES,'area_by_section_m2':np.bincount(sect,weights=area).tolist(),
        'maximum_web_anchor_distance_from_section_target_m':tie_error,'gear_patch_nodes':[len(nose),len(main)],
        'symmetry_nodes':len(sym),'wingtip_readout_nodes':len(tip),'geometric_source':source['source_surface_dir'],'geometry_signature':source['signature'],'geometry_lock':str(lock),
        'carry_through':CARRY_THROUGH,'shear_axes':'SHELL181 local x is the projected positive span for wing skin, spar webs and carry-through covers, positive chord for ribs and other exterior shells. MAPDL uses local y where x is nearly normal. Local y completes the right-handed x, y, shell normal frame. Spar normals point approximately aft; rib normals approximately inboard.',
        'material':{'name':'assumed homogeneous 7075-T6','E_Pa':71.7e9,'nu':.33,'density_kg_m3':2810,'nominal_yield_Pa':503e6},
        'assumptions':'Half airframe. Actual exterior CAD represented by the qualified P2 coarse surface, fixed across the structural refinement study. No measured internal structure or material layup. Shell midsurfaces coincide with the exterior, component joints are bonded via shared nodes. The separated horizontal stabilizer root uses four assumed rigid offsets at two chord and span stations, with all six DOFs coupled. Where topologically separate, the trim-fixed inboard control surface uses three assumed hinge links to the stabilizer. PYLON is an engineering subregion of the nacelle skins at the wing attachment; WINGBOX comprises the two internal webs, ribs and (model B) the carry-through covers. Skin triangle pairs form SHELL181 quadrilaterals only below the MAPDL warping limit (diagonal gap < shell thickness); the rest stay triangles. Two surrogate webs at 30%/65% chord joined to skin nodes; eight ribs on exposed semi-wing. Model B: webs continued through the fuselage to the symmetry plane with upper/lower carry-through covers (2.5 mm) and a side-of-body rib; the inboard box section follows the CAD wing section, cap nodes inside the fuselage are not tied to the fuselage skin. Nose and main gear attach to assumed finite patches. Static symmetric taxi load only; no gravity, gear dynamics, cabin pressure or design flight loads.'}
    if geometry()!=source:raise ValueError('Accepted source changed while generating the structural model')
    files=hashes([out/'model.inp',out/'shell_mesh.npz'])
    stats['model_generator_sha256']=source_hash(Path(__file__))
    stats['model_files_sha256']=files
    stats['model_signature']=signature({'geometry':source['signature'],'grid':level,'model_files_sha256':files})
    commit(out/'model.json',stats);print(json.dumps(stats),flush=True)

if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('level',choices=['coarse','medium','fine']);build(ap.parse_args().level)
