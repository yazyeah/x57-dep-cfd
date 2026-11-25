"""Refine the recovered coarse shell in its tangent planes to isolate spatial-discretization error.

Wall zones retain identical geometry. Shared physical interfaces and the CAD-fitted gap
are preserved for the subsequent local fit and the independent 54/5/81-probe check.
"""
import argparse,json
import numpy as np
from p2_geometry_io import *
from verify_p2_cad_shell import verify,quality
TARGETS={'medium':{'wall_wing':25500,'wall_fuselage':8000,'wall_nacelles':5050,'wall_sponson':740,'wall_empennage':11100},
         'fine':{'wall_wing':44200,'wall_fuselage':10300,'wall_nacelles':5800,'wall_sponson':900,'wall_empennage':12500}}

def graded(t,goal,name):
    v,f=indices(t)
    if name=='wall_wing':
        cad=np.load(GEO/'cad_components.npz')['51'].astype(float);span=np.linspace(.39,4.667,53)
        sections=[section_segments(cad,z)[:,:,0] for z in span]
        starts,ends=np.array([[ss.min(),ss.max()] for ss in sections]).T
    for turn in range(8):
        if len(f)+1>=goal:break
        edges=np.stack((f,np.roll(f,-1,axis=1)),axis=2).reshape(-1,2);ed,inv,n=np.unique(np.sort(edges,axis=1),axis=0,return_inverse=True,return_counts=True)
        pairs=v[ed];length=np.linalg.norm(pairs[:,1]-pairs[:,0],axis=1);c=pairs.mean(1);sel=n==2
        if name in ('wall_nacelles','wall_sponson'):
            sel &= ~((abs(c[:,0])<.19)&(c[:,2]>.70)&(c[:,2]<1.00)&(c[:,1]<.16))
        # Long edges and edges on a sharply turning part of the wetted skin are split first.
        tri=v[f].astype(float);norm=np.cross(tri[:,1]-tri[:,0],tri[:,2]-tri[:,0]);norm/=np.maximum(np.linalg.norm(norm,axis=1)[:,None],1.e-30)
        order=np.argsort(inv,kind='stable');start=np.r_[0,np.cumsum(n[:-1])];bend=np.zeros(len(ed));u=np.flatnonzero(sel)
        bend[u]=1-np.einsum('ij,ij->i',norm[order[start[u]]//3],norm[order[start[u]+1]//3])
        # Bisecting only the long side of an already skinny facet can halve its shape metric.
        # Preserve these triangles and refine the adjacent well-shaped surface instead.
        low_shape=quality(tri)<.026
        sel[np.unique(inv.reshape(-1,3)[low_shape])]=False
        u=np.flatnonzero(sel)
        score=length*(1+.25*bend)
        if name=='wall_wing':
            x0=np.interp(c[:,2],span,starts);x1=np.interp(c[:,2],span,ends)
            chord_fraction=(c[:,0]-x0)/np.maximum(x1-x0,.05)
            score*=1.+.55*np.clip((.38-chord_fraction)/.20,0,1)
        budget=min((goal-len(f))//2,int(.24*len(ed)))
        chosen=u[np.argsort(score[u],kind='stable')[-budget:]]
        new=np.full(len(ed),-1,int);new[chosen]=np.arange(len(chosen))+len(v);v=np.vstack((v,pairs[chosen].mean(1)))
        m=new[inv].reshape(-1,3);mask=(m>=0)@np.array([1,2,4]);parts=[f[mask==0]]
        for j in range(3):
            single=1<<j;double=single|(1<<((j+1)%3))
            for k in (single,double):
                a,b,c0=np.roll(f[mask==k],-j,axis=1).T;i1,i2,_=np.roll(m[mask==k],-j,axis=1).T
                if k==single:parts.extend((np.c_[a,i1,c0],np.c_[i1,b,c0]))
                else:
                    parts.append(np.c_[i1,b,i2])
                    a1,a2=np.c_[a,i1,c0],np.c_[i1,i2,c0]
                    b1,b2=np.c_[a,i1,i2],np.c_[a,i2,c0]
                    swap=np.minimum(quality(v[b1]),quality(v[b2]))>np.minimum(quality(v[a1]),quality(v[a2]))
                    parts.extend((np.where(swap[:,None],b1,a1),np.where(swap[:,None],b2,a2)))
        a,b,c0=f[mask==7].T;i,j,k=m[mask==7].T;parts.extend((np.c_[a,i,k],np.c_[i,b,j],np.c_[k,j,c0],np.c_[i,j,k]))
        f=np.concatenate(parts)
    return v[f]
def main(level):
    src=GEO/'p2_hinge_seed';out=GEO/('cad_level_'+level+'_pre_gap')
    patches={k:stl_triangles(src/(k+'.stl')) for k in TYPES}
    for name,goal in TARGETS[level].items():patches[name]=graded(patches[name],goal,name)
    save_patches(out,patches);verify(out,False)
    (out/'surface_refinement.json').write_text(json.dumps({'parent':str(src),'method':'conforming midpoint edge splits on existing surface, with a curvature weight and better local diagonal','goals':TARGETS[level]},indent=2))
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('level',choices=TARGETS);main(p.parse_args().level)

