"""Restore the independent hinge facet improvement and validate every P2 surface tier."""
import argparse,json,shutil,hashlib
from pathlib import Path
import numpy as np
from meshlib import mrmeshpy as mr,mrmeshnumpy as mn
from scipy.sparse import coo_matrix
from scipy.sparse.csgraph import connected_components
from p2_geometry_io import *
POINTS=[(4.948840,1.226184),(4.958696,.850782),(4.935035,.399190),(4.860000,.691500),(4.862147,.802703)]
def geom(m):
    m.pack();return mn.getNumpyVerts(m).copy(),mn.getNumpyFaces(m.topology).copy()
def quality(t):
    t=t.astype(float);e=t-np.roll(t,-1,axis=1);return 2*np.sqrt(3)*np.linalg.norm(np.cross(e[:,0],e[:,1]),axis=1)/np.maximum((e**2).sum((1,2)),1e-40)
def region(mask):
    out=mr.FaceBitSet();out.resize(len(mask))
    for i in np.flatnonzero(mask):out.set(mr.FaceId(int(i)))
    return out
def halo(f,mask,n):
    for _ in range(n):mask=np.isin(f,np.unique(f[mask])).any(1)
    return region(mask)
def improve(src,dest):
    ps={k:stl_triangles(src/(k+'.stl')) for k in TYPES};v,f=indices(ps['wall_empennage']);m=mn.meshFromFacesVerts(f,v)
    def fix(limit,depth,maxdev,tiny,aspect):
        v,f=geom(m);q=quality(v[f]);idx=halo(f,q<limit,depth)
        s=mr.FixMeshDegeneraciesParams();s.region=idx;s.maxDeviation=maxdev;s.criticalTriAspectRatio=aspect;s.tinyEdgeLength=tiny;s.mimicPatch=True;s.mode=s.Mode.Decimate
        mr.fixMeshDegeneracies(m,s)
    for _ in range(2):fix(.024,2,.00045,.00065,12)
    v,f=geom(m);r=halo(f,quality(v[f])<.015,1);s=mr.RemeshSettings();s.region=r;s.targetEdgeLen=.006;s.maxEdgeSplits=1000
    s.projectOnOriginalMesh=True;s.frozenBoundary=False;s.maxBdShift=.00004;s.finalRelaxIters=0;s.maxAngleChangeAfterFlip=.06
    mr.remesh(m,s);fix(.02,1,.00030,.00050,15);v,f=geom(m);ps['wall_empennage']=v[f]
    print('Tail triangles and min shape',len(f),quality(v[f]).min(),flush=True)
    save_patches(dest,ps)
def fans(f):
    a=f.ravel();b=np.roll(f,-1,axis=1).ravel();corn=np.arange(f.size).reshape(-1,3)
    x=corn.ravel();y=np.roll(corn,-1,axis=1).ravel();flip=a>b;lo=np.minimum(a,b);hi=np.maximum(a,b);idx=np.lexsort((hi,lo));lo,hi=lo[idx],hi[idx]
    pairs=np.flatnonzero((lo[1:]==lo[:-1])&(hi[1:]==hi[:-1]));u,w=np.where(flip,y,x)[idx],np.where(flip,x,y)[idx]
    i=np.r_[u[pairs],w[pairs]];j=np.r_[u[pairs+1],w[pairs+1]]
    _,g=connected_components(coo_matrix((np.ones(len(i),dtype='i1'),(i,j)),shape=(len(a),len(a))),directed=False)
    s=np.unique(np.c_[a,g],axis=0);_,c=np.unique(s[:,0],return_counts=True);return int(sum(c>1))
def sections(ps):
    cad=np.load(GEO/'cad_components.npz');wing=ps['wall_wing'].astype(float);hscan=np.concatenate((wing,ps['wall_nacelles'].astype(float)))
    reference=cad['51'].astype(float);wr=[];tr=[];gr=[]
    for z in [1.90,2.125,2.35,2.716,3.10,3.65,3.800848,4.25,4.45]:
        sc=section_segments(reference,z);sw=section_segments(hscan,z)
        for dx in [.030,.020,.015,.010,.006,.003]:
            x=sc[:,:,0].max()-dx;h=heights(sc,x);s=heights(sw,x)
            if len(h)<2 or len(s)<2:raise ValueError(('Wing sheet missing',x,z))
            wr.append(dict(x_m=x,z_m=z,cad_thickness_m=float(np.ptp(h)),surface_thickness_m=float(np.ptp(s)),error_m=float(abs(np.ptp(s)-np.ptp(h)))))
    fixed=np.concatenate([cad['54'],cad['55']]).astype(float)
    for x,z in POINTS:
        h=heights(section_segments(fixed,z),x);s=heights(section_segments(ps['wall_empennage'].astype(float),z),x)
        if len(h)<2 or len(s)<2:raise ValueError(('Tail skin missing',x,z))
        tr.append(dict(x_m=x,z_m=z,source_thickness_m=float(np.ptp(h)),surface_thickness_m=float(np.ptp(s)),max_vertical_error_m=float(np.max(np.abs(h[[0,-1]]-s[[0,-1]])))))
    hinge=[.08,.25,.39919,.6915,.802703,.850782,.96]
    if any(len(heights(section_segments(ps['wall_empennage'].astype(float),z),4.8423)) for z in hinge):raise ValueError('Sealed CAD hinge')
    for z in [.85,.855,.86,.865,.87,.875,.88,.885,.88832]:
        refs=[section_segments(cad[k].astype(float),z) for k in ['56','42']]
        actual=[section_segments(ps[k].astype(float),z) for k in ['wall_sponson','wall_nacelles']]
        for x in [-.10,-.075,-.05,-.025,0,.025,.05,.075,.10]:
            def gap(form):
                a,b=(heights(s,x) for s in form);return float(b.min()-a.max()) if len(a) and len(b) else None
            gr.append(dict(x_m=x,z_m=z,cad_gap_m=gap(refs),surface_gap_m=gap(actual)))
    return wr,tr,hinge,gr
def verify(path,require_gap):
    ps={k:stl_triangles(path/(k+'.stl')) for k in TYPES};v,f=indices(np.concatenate(list(ps.values())));m=mn.meshFromFacesVerts(f,v)
    count=len(f);inc=mr.findSelfCollidingTrianglesBS(m).count();holes=len(mr.findRightBoundary(m.topology));contacts=fans(f)
    qq={k:{'min_shape':float(quality(t).min()),'below_0.01':int((quality(t)<.01).sum()),'zero_area':int((quality(t)<=0).sum())} for k,t in ps.items()}
    if inc or holes or contacts or sum(s['zero_area'] for s in qq.values()):raise ValueError(('Surface topology',inc,holes,contacts,qq))
    wr,tr,hinge,gr=sections(ps);w=max(r['error_m'] for r in wr);t=max(r['max_vertical_error_m'] for r in tr)
    gap=max(abs(r['cad_gap_m']-r['surface_gap_m']) for r in gr if r['cad_gap_m'] is not None and r['surface_gap_m'] is not None)
    mismatch=sum((r['cad_gap_m'] is None)!=(r['surface_gap_m'] is None) for r in gr)
    if w>.001 or t>.0008 or (require_gap and (gap>.003 or mismatch)):raise ValueError(('Surface does not meet CAD gate',w,t,gap,mismatch))
    out=path/'aircraft_domain.msh';write_surface(out,ps)
    report={'faces':count,'wall_faces':sum(len(ps[k]) for k in WALLS),'faces_by_zone':{k:len(v) for k,v in ps.items()},'min_shapes':qq,
            'self_intersections':inc,'open_loops':holes,'multifan_vertices':contacts,'signed_edge_check':'passed','wing_checks':wr,'tail_checks':tr,
            'open_hinge_stations_z_m':hinge,'gap_checks':gr,'max_wing_thickness_error_m':w,'max_tail_surface_error_m':t,
            'max_gap_error_m':gap,'gap_occupancy_mismatches':mismatch,'gap_required':bool(require_gap),
            'msh_sha256':hashlib.sha256(out.read_bytes()).hexdigest()}
    (path/'assembled_shell_qa.json').write_text(json.dumps(report,indent=2))
    print(path,report['wall_faces'],count,'wing/tail/gap m',w,t,gap,'gap mismatches',mismatch,flush=True)
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('source',type=Path);p.add_argument('--improved',type=Path);p.add_argument('--require-gap',action='store_true');a=p.parse_args()
    if a.improved:improve(a.source,a.improved)
    verify(a.improved or a.source,a.require_gap)

