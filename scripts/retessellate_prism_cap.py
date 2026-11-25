"""Retriangulate acute physical cap facets across a locally movable crease with a metric error bound."""
import numpy as np

from diagnose_prism_stair_locations import closest
from verify_p2_cad_shell import quality
from p2_geometry_io import indices


def displacement(first, second):
    def one_way(a,b):
        edge=(a+np.roll(a,-1,axis=1))*.5
        samples=np.vstack([a.mean(1),edge.reshape(-1,3)])
        return max(closest(b,p)[1] for p in samples)
    return max(one_way(first,second),one_way(second,first))


def improve(triangles, wall, all_prism_bases=False):
    v,f=indices(triangles)
    v=v.astype(float)
    f=f.copy()
    original=f.copy()
    operations=0
    for iteration in range(10):
        tri=v[f]
        center=tri.mean(1)
        shape=quality(tri)
        x,y,z=center.T
        roi=(x>.275)&(x<.347)&(z>.50)&(z<.71) if wall=='wall_wing' else (x>.13)&(x<.17)&(abs(z-3.769)<.043)&(y<.105)
        if all_prism_bases:
            roi=np.ones(len(f),dtype=bool)
        seeds=np.flatnonzero(roi & (shape<(.15 if all_prism_bases else .22)))
        ring={}
        scan=np.any(np.isin(f,np.unique(f[seeds])),axis=1)
        for i in np.flatnonzero(scan):
            for u,w in zip(f[i],np.roll(f[i],-1)):
                ring.setdefault((min(u,w),max(u,w)),[]).append(i)
        occupied=set()
        made=0
        for i in seeds[np.argsort(shape[seeds])]:
            if i in occupied:continue
            a=f[i]
            longest=int(np.argmax(np.linalg.norm(v[a]-v[np.roll(a,-1)],axis=1)))
            u,b,w=np.roll(a,-longest)
            pair=ring.get((min(u,b),max(u,b)),[])
            if len(pair)!=2:continue
            j=pair[0] if pair[1]==i else pair[1]
            if j in occupied:continue
            opp=[int(t) for t in f[j] if t!=u and t!=b]
            if len(opp)!=1:continue
            q=opp[0]
            if (min(w,q),max(w,q)) in ring:continue
            new=np.array([[w,u,q],[w,q,b]])
            old=v[f[[i,j]]]
            candidate=v[new]
            if quality(candidate).min() < min(.35,1.25*min(shape[i],shape[j])+.008):continue
            normal=np.cross(old[:,1]-old[:,0],old[:,2]-old[:,0]).sum(0)
            face_normals=np.cross(candidate[:,1]-candidate[:,0],candidate[:,2]-candidate[:,0])
            if np.min(face_normals@normal)<=0:continue
            limit=.00021 if wall=='wall_wing' else .00009
            if all_prism_bases:
                before=np.cross(old[:,1]-old[:,0],old[:,2]-old[:,0])
                before/=np.linalg.norm(before,axis=1)[:,None]
                after=face_normals/np.linalg.norm(face_normals,axis=1)[:,None]
                if before[0]@before[1]<np.cos(np.deg2rad(20)) or (after@before.T).min()<np.cos(np.deg2rad(25)):
                    continue
                limit=.00006
            if displacement(old,candidate)>limit:continue
            f[i],f[j]=new
            occupied.update((i,j))
            occupied.update(k for key in ((u,w),(b,w),(u,q),(b,q)) for k in ring.get(tuple(sorted(key)),[]))
            made+=1
        operations+=made
        if not made:break
    print(wall,'local remediated diagonals',operations,flush=True)
    return v[f].astype('f4')
