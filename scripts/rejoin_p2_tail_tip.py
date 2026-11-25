"""Join a CAD-derived horizontal-tail tip to two spanwise cuts upstream of the lost aft corner."""
import argparse,json
import numpy as np
from meshlib import mrmeshpy as mr,mrmeshnumpy as mn
from p2_geometry_io import *
from verify_p2_cad_shell import verify,geom,quality,halo

def clip(t,z,side):
    kept=(t[:,:,2]-z)*side>=0
    result=[*t[kept.all(1)]]
    for tri,mask in zip(t[kept.sum(1)%3>0],kept[kept.sum(1)%3>0]):
        loop=[]
        for k in range(3):
            a,b=tri[k],tri[(k+1)%3]
            if mask[k]:loop.append(a)
            if mask[k]!=mask[(k+1)%3]:
                a,b=(a,b) if a[2]<b[2] else (b,a)
                h=a+(b-a)*((z-a[2])/(b[2]-a[2]));h[2]=z;loop.append(h)
        for k in range(1,len(loop)-1):result.append([loop[0],loop[k],loop[k+1]])
    return np.array(result,dtype='f4')

def ring(t,z,reverse):
    v,f=indices(t);edges=f[:,[[0,1],[1,2],[2,0]]].reshape(-1,2)
    e=edges if z is None else edges[(abs(v[edges,2]-z)<3.e-7).all(1)]
    u,i,n=np.unique(np.sort(e,axis=1),axis=0,return_inverse=True,return_counts=True)
    e=e[n[i]==1]
    if reverse:e=e[:,::-1]
    follow=dict(e)
    start=e[np.argmin(v[e[:,0],0]),0];path=[start]
    for j in range(len(e)-1):path.append(follow[path[-1]])
    if len(set(path))!=len(e) or follow[path[-1]]!=start:raise ValueError('Expected one span-crossing outer ring')
    v=v[path];return np.vstack([v,v[0]])

def bridge(a,b):
    arc=lambda p:np.r_[0,np.cumsum(np.linalg.norm(np.diff(p,axis=0),axis=1))]
    u,w=arc(a),arc(b);u/=u[-1];w/=w[-1];i=j=0;faces=[]
    while i+1<len(a) or j+1<len(b):
        if i+1==len(a) or (j+1<len(b) and w[j+1]<u[i+1]):
            faces.append([a[i],b[j+1],b[j]]);j+=1
        else:
            faces.append([a[i],a[i+1],b[j]]);i+=1
    return np.array(faces)

def main(src,target):
    ps={k:stl_triangles(src/(k+'.stl')) for k in TYPES}
    old=ps['wall_empennage'];raw=np.load(GEO/'cad_components.npz')['55'].astype(float)
    t=raw[:,::-1];a=1.42131;b=1.44381
    inside=clip(old.astype(float),a,-1);outside=clip(t,b,1)
    # The CAD is densest at the real trailing cap. Retain that sharp edge while reducing the flat skins.
    vo,fo=indices(outside);m=mn.meshFromFacesVerts(fo,vo);q=mr.DecimateSettings()
    q.stabilizer=1.e-7;q.maxError=.00045;q.maxDeletedFaces=max(0,len(fo)-670);q.maxEdgeLen=.070;q.maxTriangleAspectRatio=38
    mr.decimateMesh(m,q);v,f=geom(m);outside=v[f]
    rings=[ring(inside,a,True),ring(outside,None,False)]
    scarf=bridge(*rings);full=np.concatenate((inside,scarf,outside))
    v,f=indices(full);m=mn.meshFromFacesVerts(f,v)
    for dev in [.00005,.00014,.00028,.00052]:
        for j in range(2):
            v,f=geom(m);t=v[f];c=t.mean(1);bad=(quality(t)<.06)&(c[:,2]>1.39)
            if not bad.any():break
            cfg=mr.FixMeshDegeneraciesParams();cfg.region=halo(f,bad,2);cfg.maxDeviation=dev;cfg.criticalTriAspectRatio=9
            cfg.tinyEdgeLength=dev*2;cfg.mode=cfg.Mode.Decimate;mr.fixMeshDegeneracies(m,cfg)
    v,f=geom(m);ps['wall_empennage']=v[f];save_patches(target,ps);verify(target,True)
    result=[]
    for z in np.linspace(1.4451,1.6081,34):
        sr=section_segments(raw,z);sn=section_segments(ps['wall_empennage'].astype(float),z);so=section_segments(old.astype(float),z)
        for x in np.linspace(4.829,4.974,22):
            cad=heights(sr,x)
            if len(cad)<2 or max(cad)-min(cad)<.002:continue
            y=heights(sn,x);y0=heights(so,x);result.append(dict(x=x,z=z,CAD=[min(cad),max(cad)],old=list(y0),candidate=list(y)))
    count=lambda name:sum(len(v[name])!=2 for v in result)
    err=max(max(abs(np.array(v['candidate'])-v['CAD'])) for v in result if len(v['candidate'])==2)
    report=dict(source=str(src),added_faces=len(f)-len(old),tail_min_shape=float(quality(ps['wall_empennage']).min()),old_missing_or_multiply_hit=count('old'),new_missing_or_multiply_hit=count('candidate'),rays=len(result),max_height_error_m=err,probes=result)
    (target/'outer_tail_tip_qa.json').write_text(json.dumps(report,indent=2))
    print({k:v for k,v in report.items() if k!='probes'})
    if count('candidate') or err>.001 or report['tail_min_shape']<.0099:raise ValueError('Inspect CAD tip approximation')
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('source',type=Path);p.add_argument('target',type=Path);a=p.parse_args();main(a.source,a.target)

