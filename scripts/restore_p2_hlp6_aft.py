"""Rebuild the free aft end of one nacelle from exterior CAD cross-sections."""
import argparse,json
import numpy as np
from scipy.sparse import coo_matrix
from scipy.sparse.csgraph import connected_components
from p2_geometry_io import *
from rejoin_p2_tail_tip import clip,ring,bridge
from meshlib import mrmeshpy as mr,mrmeshnumpy as mn
from verify_p2_cad_shell import verify,geom,halo,quality

def main(src,target):
    a=.14173;b=.14633;zend=3.769;ps={k:stl_triangles(src/(k+'.stl')) for k in TYPES};raw=np.load(GEO/'cad_components.npz')
    source=[raw[k].astype(float) for k in ['7','13']]
    geom_cad=[t[:,:,[1,2,0]] for t in source];tem=[];key=[]
    for nm in ['wall_wing','wall_nacelles']:
        t=ps[nm];ids=np.where((t[:,:,0].max(1)>=a)&(t[:,:,0].min(1)<.23)&(t[:,:,2].max(1)>zend-.14)&(t[:,:,2].min(1)<zend+.14)&(t[:,:,1].min(1)<.112))[0]
        for j in ids:
            pos=clip(t[j:j+1][:,:,[1,2,0]].astype(float),a,1)
            for tri in pos:tem.append(tri);key.append((nm,j))
    v,f=indices(np.asarray(tem));ed=f[:,[[0,1],[1,2],[2,0]]].reshape(-1,2)
    n,labels=connected_components(coo_matrix((np.ones(len(ed)),ed.T),shape=(len(v),len(v))),directed=False)
    idx=np.argmin(np.linalg.norm(v-[.025,zend,.18],axis=1));use=labels[f[:,0]]==labels[idx]
    selected={key[i] for i in np.flatnonzero(use)}
    rim=[]
    for nm in ['wall_wing','wall_nacelles']:
        idx=[j for k,j in selected if k==nm]
        if not idx:continue
        mask=np.ones(len(ps[nm]),bool);mask[idx]=False
        rem=clip(ps[nm][idx][:,:,[1,2,0]].astype(float),a,-1)
        if len(rem):rim.append(rem);ps[nm]=np.vstack((ps[nm][mask],rem[:,:,[2,0,1]]))
        else:ps[nm]=ps[nm][mask]
    from p2_hlp6_exact_cad import actual
    r0=ring(np.vstack(rim),a,True);outside=actual(geom_cad,b)
    va,fa=indices(outside);ma=mn.meshFromFacesVerts(fa,va)
    for cap_only,eps in [(True,.00046),(False,.000078)]:
        va,fa=geom(ma);dec=mr.DecimateSettings()
        dec.stabilizer=1.e-8;dec.maxError=eps;dec.maxEdgeLen=.024;dec.maxTriangleAspectRatio=85
        if cap_only:dec.region=mn.faceBitSetFromBools(va[fa].mean(1)[:,2]>.20127)
        dec.maxDeletedFaces=max(0,len(fa)-740);mr.decimateMesh(ma,dec)
    va,fa=geom(ma);outside=va[fa]
    scarf=bridge(r0,ring(outside,None,False))
    addition=np.concatenate([scarf,outside]).astype('f4')[:,:,[2,0,1]]
    old=ps['wall_nacelles'];ps['wall_nacelles']=np.vstack((old,addition))
    v,f=indices(ps['wall_nacelles']);m=mn.meshFromFacesVerts(f,v)
    for dev in [.000025,.00006,.00012,.00020]:
        for j in range(2):
            v,f=geom(m);t=v[f];c=t.mean(1);bad=(quality(t)<.1)&(c[:,0]>.138)&(abs(c[:,2]-zend)<.035)&(c[:,1]<.11)
            if not bad.any():break
            par=mr.FixMeshDegeneraciesParams();par.region=halo(f,bad,2);par.maxDeviation=dev;par.criticalTriAspectRatio=10;par.tinyEdgeLength=dev*1.8
            par.mode=par.Mode.Decimate;mr.fixMeshDegeneracies(m,par)
    v,f=geom(m);ps['wall_nacelles']=v[f]
    save_patches(target,ps);verify(target,True)
    region=ps['wall_nacelles'].astype(float);region=region[(region[:,:,1].min(1)<.110)&(abs(region.mean(1)[:,2]-zend)<.15)]
    rr=[]
    for x in np.r_[np.linspace(.148,.201,20),.173776]:
        ss=np.vstack([section_segments(v,x) for v in geom_cad]);span=ss[:,:,1]
        zz=np.r_[np.linspace(span.min()+.08*np.ptp(span),span.max()-.08*np.ptp(span),13),3.758776 if x==.173776 else .5*(span.max()+span.min())]
        for z in zz:
            from diagnose_prism_stair_locations import merged
            intervals=[]
            for sub in geom_cad:
                roots=heights(section_segments(sub,x)[:,:,::-1],z)
                if len(roots)%2:raise ValueError(('Ambiguous native CAD material at probe',x,z,roots))
                intervals+=list(zip(roots[::2],roots[1::2]))
            ref=merged(intervals);y=heights(section_segments(region,z),x)
            if ref:rr.append({'x':x,'z':z,'candidate':list(y),'CAD':[ref[0][0],ref[-1][-1]],'CAD_intervals':ref})
    bad=sum(len(r['candidate'])<2 or len(r['candidate'])%2 for r in rr)
    E=[max(abs(np.array(r['candidate'])[[0,-1]]-r['CAD'])) for r in rr if len(r['candidate'])>=2]
    focus=rr[-1];a0=ps['wall_nacelles']
    info=dict(source=str(src),old_clipped=len(selected),added_wall_faces=sum(len(ps[n])-len(stl_triangles(src/(n+'.stl'))) for n in WALLS),rays=len(rr),missing_or_odd_rays=bad,CAD_interval_count_disagreements=sum(len(q['candidate'])!=2*len(q['CAD_intervals']) for q in rr),max_height_error_m=max(E),p95_height_error_m=float(np.percentile(E,95)),stair_point=focus,min_nacelle_shape=float(quality(a0).min()),samples=rr)
    (target/'hlp6_aft_qa.json').write_text(json.dumps(info,indent=2))
    print({k:v for k,v in info.items() if k!='samples'})
    if bad or max(E)>.0015 or info['min_nacelle_shape']<.01:raise ValueError('Inspect aft fairing')
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('source',type=Path);p.add_argument('target',type=Path);a=p.parse_args();main(a.source,a.target)

