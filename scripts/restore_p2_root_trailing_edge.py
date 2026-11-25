"""Restore missing inboard trailing-edge volume using upper/lower CAD external envelopes."""
import argparse,json
import numpy as np
from meshlib import mrmeshpy as mr,mrmeshnumpy as mn
from p2_geometry_io import *
from verify_p2_cad_shell import verify,quality,geom,halo
from restore_p2_hlp5_fairing import loft,mesh

def make_solid(cad):
    rings=[];nx=13
    for z in np.linspace(.38,.685,32):
        sec=section_segments(cad,z);tip=sec[:,:,0].max()-.00065
        fz=np.clip((.685-z)/.050,0,1)
        xx=np.linspace(.225,tip-.002*(1-fz),nx)
        lo=[];hi=[]
        for x in xx:
            h=heights(sec,x);y=.5*(h.min()+h.max())
            scale=.22+.78*min(fz,float(np.clip((x-.225)/.040,0,1)))
            lo.append([x,y+scale*(h.min()-y),z]);hi.append([x,y+scale*(h.max()-y),z])
        rings.append(lo+hi[::-1])
    cap=[]
    for j in range(nx-1):cap.extend([[j,j+1,2*nx-2-j],[j,2*nx-2-j,2*nx-1-j]])
    return loft(rings,cap)[0]

def remesh_wing(tr):
    v,f=indices(tr);m=mesh(v,f)
    for deviation in [.00004,.00010,.00017,.00027,.00045,.00070]:
        for j in range(3):
            v,f=geom(m);cand=v[f];c=cand.mean(1)
            bad=(quality(cand)<.10)&(c[:,0]>.222)&(c[:,0]<.328)&(c[:,2]>.37)&(c[:,2]<.69)
            if not bad.any():break
            cfg=mr.FixMeshDegeneraciesParams();cfg.region=halo(f,bad,2);cfg.maxDeviation=deviation
            cfg.criticalTriAspectRatio=8;cfg.tinyEdgeLength=2*deviation;cfg.mode=cfg.Mode.Decimate
            mr.fixMeshDegeneracies(m,cfg)
    v,f=geom(m);return v[f]

def run(src,target):
    raw={z:stl_triangles(src/(z+'.stl')) for z in TYPES}
    cad=np.load(GEO/'cad_components.npz')['51'].astype(float)
    insert=make_solid(cad)
    v,f=indices(np.concatenate(list(raw.values())));obj=mesh(v,f)
    tag=np.repeat(np.arange(len(raw)),[len(t) for t in raw.values()])
    mapper=mr.BooleanResultMapper();result=mr.boolean(obj,insert,mr.BooleanOperation.DifferenceAB,mr.AffineXf3f(),mapper)
    if not result.valid():raise ValueError(result.errorString)
    m=result.mesh;valid=np.flatnonzero(mn.getNumpyBitSet(m.topology.getValidFaces()))
    tri=mn.getNumpyVerts(m)[mn.getNumpyFaces(m.topology)]
    if len(valid)!=len(tri):raise ValueError('Unexpected CSG face indexing')
    labels=np.full(len(valid),-1)
    for i,name in enumerate(raw):
        old=mn.faceBitSetFromBools(tag==i);newid=np.flatnonzero(mn.getNumpyBitSet(mapper.map(old,mr.BooleanResultMapper.MapObject.A)))
        labels[np.searchsorted(valid,newid)]=i
    wing=list(raw).index('wall_wing')
    new=np.flatnonzero(mn.getNumpyBitSet(mapper.map(insert.topology.getValidFaces(),mr.BooleanResultMapper.MapObject.B)))
    labels[np.searchsorted(valid,new)]=wing
    if (labels<0).any():raise ValueError('Unassigned wall')
    ps={nm:tri[labels==i].copy() for i,nm in enumerate(raw)}
    # Remesh the welded union as the root intersects the fuselage. Preserve both sides of the common edge.
    from scipy.spatial import cKDTree
    from diagnose_prism_stair_locations import closest
    tri=tri.astype('f4')
    tree=cKDTree(tri.mean(1))
    merged=remesh_wing(tri);centers=merged.mean(1)
    dist,near=tree.query(centers,k=16)
    ix=near[:,0].copy()
    for k in np.flatnonzero(dist[:,0]>2.e-6):
        ix[k]=near[k,closest(tri[near[k]].astype(float),centers[k])[0]]
    ps={nm:merged[labels[ix]==i] for i,nm in enumerate(raw)}
    save_patches(target,ps);verify(target,True)
    rows=[];old=raw['wall_wing'].astype(float);new=ps['wall_wing'].astype(float)
    for z in np.linspace(.514,.63,18):
        ac=section_segments(cad,z);ao=section_segments(old,z);an=section_segments(new,z)
        for x in np.linspace(.273,.315,13):
            h=heights(ac,x);h0=heights(ao,x);h1=heights(an,x)
            if len(h)<2:continue
            rows.append(dict(x_m=x,z_m=z,old_hits=list(h0),new_hits=list(h1),cad_envelope=[h.min(),h.max()]))
    miss_old=sum(len(r['old_hits'])<2 for r in rows);miss=sum(len(r['new_hits'])!=2 for r in rows)
    err=max(max(abs(np.array(r['new_hits'])-r['cad_envelope'])) for r in rows if len(r['new_hits'])==2)
    summary=dict(input=str(src),added_wall_faces=sum(len(ps[k])-len(raw[k]) for k in WALLS),rays=len(rows),old_missing=miss_old,candidate_missing_or_extra=miss,max_CAD_upper_lower_height_error_m=err,
        core_min_shape=float(quality(ps['wall_wing']).min()),rays_detail=rows)
    (target/'root_trailing_edge_qa.json').write_text(json.dumps(summary,indent=2))
    print({k:v for k,v in summary.items() if k!='rays_detail'})
    if miss or err>.0015:raise ValueError('Check restored root envelope')
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('source',type=Path);p.add_argument('target',type=Path);a=p.parse_args();run(a.source,a.target)

