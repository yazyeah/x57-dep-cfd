"""Replace one folded lower-wing surface patch with a CAD-conforming single-valued surface."""
import argparse,json,shutil
import numpy as np,triangle
from scipy.spatial import cKDTree
from p2_geometry_io import *
from verify_p2_cad_shell import quality,verify
def fit(src,out,xc,zc,upper=False,rx=None,rz=None,step=.007):
    ps={k:stl_triangles(src/(k+'.stl')) for k in TYPES}
    v,f=indices(ps['wall_wing']);ctr=v[f].mean(1);cad=np.load(GEO/'cad_components.npz')['51'].astype(float)
    rr=(((ctr[:,0]-xc)/(rx or (.055 if zc<2 else .042)))**2+((ctr[:,2]-zc)/(rz or (.103 if zc<2 else .095)))**2)<1
    extreme=max if upper else min
    def target(x,z):
        t=cad[(cad[:,:,0].min(1)<=x)&(cad[:,:,0].max(1)>=x)&(cad[:,:,2].min(1)<=z)&(cad[:,:,2].max(1)>=z)]
        if not len(t):return []
        a,b,c=t.transpose(1,0,2);u=b-a;w=c-a;d=u[:,0]*w[:,2]-u[:,2]*w[:,0];ok=abs(d)>1e-15
        a,u,w,d=a[ok],u[ok],w[ok],d[ok];dx=x-a[:,0];dz=z-a[:,2];s=(dx*w[:,2]-dz*w[:,0])/d;q=(dz*u[:,0]-dx*u[:,2])/d
        keep=(s>=-1e-7)&(q>=-1e-7)&(s+q<=1.0000001);return a[keep,1]+u[keep,1]*s[keep]+w[keep,1]*q[keep]
    idx=np.flatnonzero(rr);s=[];yb=[]
    # Avoid the actual trailing cap (control-surface edge).
    for i in idx:
        x,y,z=ctr[i];h=target(x,z)
        if len(h)>=2 and max(h)-min(h)>.004 and ((y>(max(h)+min(h))/2) if upper else (y<(max(h)+min(h))/2)):s.append(i)
    use=np.zeros(len(f),bool);use[s]=True;old=f[use]
    ed=old[:,[[0,1],[1,2],[2,0]]].reshape(-1,2);edges,n=np.unique(np.sort(ed,axis=1),axis=0,return_counts=True);rim=edges[n==1]
    ids,seg=np.unique(rim,return_inverse=True);seg=seg.reshape(-1,2);outer=v[ids][:,[0,2]]
    # Constrained planar remesh with retained boundary coordinates and regular interior sites.
    pslg=triangle.triangulate({'vertices':outer.astype(float),'segments':seg},'pYQ')
    if len(pslg['vertices'])!=len(outer):raise ValueError('Folded patch rim, expand patch or change boundary')
    if not len(pslg['triangles']):raise ValueError('Empty local domain')
    rim0,rim1=outer[seg].transpose(1,0,2);dr=rim1-rim0;rlen=np.einsum('ij,ij->i',dr,dr)
    rimerr=np.array([v[i,1]-extreme(target(v[i,0],v[i,2])) for i in ids])
    def boundary(p):
        frac=np.clip(np.einsum('ij,ij->i',p-rim0,dr)/np.maximum(rlen,1.e-20),0,1);dist=np.linalg.norm(p-rim0-frac[:,None]*dr,axis=1);j=int(np.argmin(dist));return dist[j],(1-frac[j])*rimerr[seg[j,0]]+frac[j]*rimerr[seg[j,1]]
    lo=outer.min(0);hi=outer.max(0)
    seeds=[]
    cells=outer[pslg['triangles']]
    for j,z in enumerate(np.arange(lo[1]+step/2,hi[1],step*.87)):
        for x in np.arange(lo[0]+(1+j%2)*step/2,hi[0],step):
            p=np.array([x,z])
            if boundary(p)[0]<.0038:continue
            a,b,c=cells.transpose(1,0,2);e=b-a;g=c-a;r=p-a;det=e[:,0]*g[:,1]-e[:,1]*g[:,0]
            u=(r[:,0]*g[:,1]-r[:,1]*g[:,0])/det;w=(r[:,1]*e[:,0]-r[:,0]*e[:,1])/det
            if np.any((u>0)&(w>0)&(u+w<1)):seeds.append([x,z])
    pts=np.vstack((outer,seeds));res=triangle.triangulate({'vertices':pts,'segments':seg},'pYQ');nf=res['triangles']
    if len(res['vertices'])!=len(pts):raise ValueError('Boundary altered')
    hnew=[]
    for x,z in seeds:
        h=target(x,z)
        if len(h)<2:raise ValueError('CAD absent at interior local patch node')
        d,err=boundary([x,z]);w=max(0.,1.-d/.020)**2;hnew.append([x,extreme(h)+w*err,z])
    vv=np.vstack([v,hnew]).astype('f4');ii=np.r_[ids,np.arange(len(v),len(vv))];nf=ii[nf];nf=nf if upper else nf[:,::-1]
    # Plane x/z counterclockwise gives negative y, whereas lower aircraft has outward fluid-shell +y.
    ps['wall_wing']=vv[np.vstack((f[~use],nf))];save_patches(out,ps);verify(out,True)
    local=vv[nf].astype(float);nn=np.cross(local[:,1]-local[:,0],local[:,2]-local[:,0]);nn/=np.linalg.norm(nn,axis=1)[:,None]
    e= nf[:,[[0,1],[1,2],[2,0]]].reshape(-1,2);u,iv,c=np.unique(np.sort(e,axis=1),axis=0,return_inverse=True,return_counts=True);o=np.argsort(iv);first=np.r_[0,np.cumsum(c)[:-1]];a,b=(o[first[c==2]+j]//3 for j in (0,1));angles=np.degrees(np.arccos(np.clip(np.einsum('ij,ij->i',nn[a],nn[b]),-1,1)))
    rec={'replaced_faces':int(use.sum()),'replacement_faces':len(nf),'minimum_shape':float(quality(local).min()),'skin':'upper' if upper else 'lower','minimum_consistent_wall_normal_y_magnitude':float((nn[:,1]*(-1 if upper else 1)).min()),'max_interior_normal_turn_deg':float(angles.max()),'max_normal_turn_near_warning_deg':float(angles[np.linalg.norm(vv[u[c==2]].mean(1)-[xc,float(np.mean(vv[nf],axis=(0,1))[1]),zc],axis=1)<.022].max())}
    (out/'hinge_fold_qa.json').write_text(json.dumps(rec,indent=2));print(rec,flush=True)
if __name__=='__main__':
    a=argparse.ArgumentParser();a.add_argument('source',type=Path);a.add_argument('dest',type=Path);a.add_argument('--xc',type=float,default=.253);a.add_argument('--zc',type=float,default=1.899);op=a.parse_args();fit(op.source,op.dest,op.xc,op.zc)

