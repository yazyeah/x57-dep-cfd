"""Restore the HLP-5 aft fairing and the intersecting wing as separate CAD solids."""
import json
import numpy as np
from meshlib import mrmeshpy as mr,mrmeshnumpy as mn
from scipy.spatial import cKDTree
from p2_geometry_io import *
from verify_p2_cad_shell import verify,quality
def mesh(v,f):
    return mn.meshFromFacesVerts(np.array(f,dtype='i4'),np.array(v,dtype='f4'))
def positive(v,f):
    f=np.asarray(f);v=np.asarray(v);tr=v[f];vol=np.einsum('ij,ij->i',tr[:,0],np.cross(tr[:,1],tr[:,2])).sum()/6
    if vol<0:f=f[:,::-1]
    out=mesh(v,f)
    if len(mr.findRightBoundary(out.topology)) or mr.findSelfCollidingTrianglesBS(out).count():raise ValueError('Reconstructed source solid is invalid')
    return out,tr
def loft(rings,caps):
    xyz=np.array(rings);nn,n,_=xyz.shape;faces=[]
    for k in range(nn-1):
        for j in range(n):
            a=k*n+j;b=k*n+(j+1)%n;faces.extend([[a,b,b+n],[a,b+n,a+n]])
    for a,b,c in caps:
        faces.extend(([c,b,a],[a+(nn-1)*n,b+(nn-1)*n,c+(nn-1)*n]))
    return positive(xyz.reshape(-1,3),faces)
def wing(cad):
    xx=np.linspace(.1771,.2757,21);zz=np.linspace(3.0849,3.2971,40);rings=[]
    for z in zz:
        s=section_segments(cad,z);ym=[heights(s,x) for x in xx]
        if any(len(y)<2 for y in ym):raise ValueError('Wing ends before loft')
        rings.append([[x,min(y),z] for x,y in zip(xx,ym)]+[[x,max(y),z] for x,y in zip(xx[::-1],ym[::-1])])
    k=len(xx);cap=[]
    for j in range(k-1):cap.extend(([j,j+1,2*k-2-j],[j,2*k-2-j,2*k-1-j]))
    return loft(rings,cap)
def pylon(cad):
    rings=[];theta=2*np.pi*np.arange(36)/36;dire=np.c_[np.cos(theta),np.sin(theta)]
    cross=lambda a,b:a[...,0]*b[...,1]-a[...,1]*b[...,0]
    for x in np.linspace(.17705,.23950,49):
        s=section_segments(cad[:,:,[1,2,0]],x);pt=s.reshape(-1,2);o=(pt.max(0)+pt.min(0))*.5
        med=heights(s[:,:,::-1],o[1]);o[0]=(med.min()+med.max())/2
        a,b=s[:,0]-o,s[:,1]-o;e=b-a;rr=[]
        for d in dire:
            det=cross(d,e);take=abs(det)>1e-15;u=cross(a[take],d)/det[take];distance=cross(a[take],e[take])/det[take]
            hit=distance[(u>=-1e-7)&(u<=1+1e-7)&(distance>0)]
            if not len(hit):raise ValueError(('Non-star-shaped HLP5 section',x,d))
            rr.append([x,*(o+d*max(hit))])
        rings.append(rr)
    return loft(rings,[[0,k,k+1] for k in range(1,len(theta)-1)])
def boolean(a,b,op):
    r=mr.boolean(a,b,op)
    if not r.valid():raise ValueError(r.errorString)
    r.mesh.pack();return r.mesh
def main():
    src=GEO/'p2_coarse_fold_blend';out=GEO/'p2_coarse_hlp5_cad'
    ps={n:stl_triangles(src/(n+'.stl')) for n in TYPES};names=list(ps);old=np.concatenate(list(ps.values()));oldtags=np.repeat(np.arange(len(names)),[len(t) for t in ps.values()]);tree=cKDTree(old.mean(1));v,f=indices(old);skin=mesh(v,f)
    cad=np.load(GEO/'cad_components.npz');solidwing,tw=wing(cad['51'].astype(float));solidpylon,tp=pylon(cad['49'].astype(float))
    relief=mr.makeCube(mr.Vector3f(.2688-.184,.25,3.288-3.093),mr.Vector3f(.184,-.08,3.093))
    old=boolean(skin,relief,mr.BooleanOperation.Union)
    shape=boolean(solidwing,solidpylon,mr.BooleanOperation.Union)
    combined=boolean(old,shape,mr.BooleanOperation.DifferenceAB);combined.pack()
    v=mn.getNumpyVerts(combined).copy();f=mn.getNumpyFaces(combined.topology).copy()
    v,iv=np.unique(v,axis=0,return_inverse=True);f=iv[f];f=f[(np.diff(np.sort(f,axis=1),axis=1)!=0).all(1)]
    tri=v[f];c=tri.mean(1);dist,idx=tree.query(c);tags=oldtags[idx]
    pset=(dist>2e-6)&(c[:,0]>.17)&(c[:,0]<.282)&(c[:,2]>3.075)&(c[:,2]<3.305)
    wdist=cKDTree(tw.mean(1)).query(c[pset])[0];ndist=cKDTree(tp.mean(1)).query(c[pset])[0]
    tags[pset]=np.where(ndist<wdist,names.index('wall_nacelles'),names.index('wall_wing'))
    ps={k:tri[tags==j] for j,k in enumerate(names)}
    save_patches(out,ps);verify(out,True)
    joined=np.concatenate([ps['wall_wing'],ps['wall_nacelles']]).astype(float)
    report=[]
    for x,z in [(.21777572,3.2052927),(.23723802,3.22049),(.24588485,3.17411745),(.25643058,3.14908576)]:
        intervals=np.r_[heights(section_segments(cad['49'].astype(float),z),x),heights(section_segments(cad['51'].astype(float),z),x)]
        sample=heights(section_segments(joined,z),x);err=abs(sample[[0,-1]]-intervals[[np.argmin(intervals),np.argmax(intervals)]])
        report.append({'x_m':x,'z_m':z,'source_outer_bounds_m':[min(intervals),max(intervals)],'result_outer_bounds_m':[min(sample),max(sample)],'max_height_error_m':float(max(err))})
    if max(r['max_height_error_m'] for r in report)>.0015:raise ValueError(report)
    (out/'pylon_and_wing_qa.json').write_text(json.dumps(report,indent=2));print(report,flush=True)
if __name__=='__main__':main()

