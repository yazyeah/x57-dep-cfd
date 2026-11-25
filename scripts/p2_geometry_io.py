"""Shared P2 geometry readers and exact welded Fluent surface export in SI."""
from pathlib import Path
import re
import numpy as np
from inspect_x57_geometry import write_binary_stl
ROOT=Path(__file__).resolve().parents[1]
GEO=ROOT/'01_geometry'
WALLS=['wall_wing','wall_fuselage','wall_nacelles','wall_sponson','wall_empennage']
TYPES={'symmetry':('symmetry',7),'runway_ground':('wall',3),'farfield_inlet':('pressure-inlet',4),
       'farfield_top':('pressure-inlet',4),'farfield_side':('pressure-inlet',4),'farfield_outlet':('pressure-outlet',5)}
TYPES.update({k:('wall',3) for k in WALLS})
dtype=np.dtype([('n','<f4',3),('v','<f4',(3,3)),('attr','<u2')])
def stl_triangles(path):
    with path.open('rb') as fp:
        fp.seek(80);n=int.from_bytes(fp.read(4),'little')
        if path.stat().st_size!=84+n*50:raise ValueError(path)
        return np.fromfile(fp,dtype=dtype,count=n)['v'].copy()
def indices(t):
    v,f=np.unique(t.reshape(-1,3),axis=0,return_inverse=True)
    return v,f.reshape(-1,3).astype('i4')
def read_patches(path):
    rows=path.read_text().splitlines()
    a=next(i for i,s in enumerate(rows) if s.startswith('(10 (1 '))
    b=rows.index('))',a+1);v=np.loadtxt(rows[a+1:b]);patches={}
    for i,row in enumerate(rows):
        if row.startswith('(13 (') and row.endswith(')('):
            j=rows.index('))',i+1)
            f=np.array([[int(k,16)-1 for k in ln.split()[:3]] for ln in rows[i+1:j]],dtype='i4')
            name=re.search(r'\(45 \(\d+ \S+ (\S+)\)\(',rows[j+1]).group(1)
            if name in TYPES:patches[name]=v[f].astype('f4')
            elif not name.endswith('_boi'):raise ValueError(name)
    if set(patches)!=set(TYPES):raise ValueError(patches.keys())
    return patches
def write_surface(path,patches,verify_shell=True):
    v,f=indices(np.concatenate(list(patches.values())))
    if verify_shell:
        edges=f[:,[[0,1],[1,2],[2,0]]].reshape(-1,2);u,i,c=np.unique(np.sort(edges,axis=1),axis=0,return_inverse=True,return_counts=True)
        if np.any(c!=2) or np.any(np.bincount(i,weights=np.sign(edges[:,1]-edges[:,0]))):raise ValueError('Nonmanifold or misoriented edges')
        tri=v[f].astype(float);n=np.cross(tri[:,1]-tri[:,0],tri[:,2]-tri[:,0])
        if (np.linalg.norm(n,axis=1)==0).any():raise ValueError('Zero-area facet')
    with path.open('w',encoding='ascii') as h:
        h.write(f'(2 3)\n(10 (0 1 {len(v):x} 0 3))\n(10 (1 1 {len(v):x} 1 3)(\n')
        np.savetxt(h,v,fmt='%.12g');h.write(f'))\n(13 (0 1 {len(f):x} 0))\n');offset=0
        for zid,(k,t) in enumerate(patches.items(),2):
            typ,code=TYPES[k];h.write(f'(13 ({zid:x} {offset+1:x} {offset+len(t):x} {code:x} 3)(\n')
            np.savetxt(h,f[offset:offset+len(t)]+1,fmt='%x %x %x 0 0');h.write(f'))\n(45 ({zid} {typ} {k})())\n');offset+=len(t)
def section_segments(t,z):
    t=t[(t[:,:,2].min(1)<=z)&(t[:,:,2].max(1)>z)]
    end=np.roll(t,-1,axis=1);hit=(t[:,:,2]<=z)!=(end[:,:,2]<=z);a,b=t[hit],end[hit]
    return (a+(b-a)*((z-a[:,2])/(b[:,2]-a[:,2]))[:,None])[:,:2].reshape(-1,2,2)
def heights(seg,x):
    a,b=seg[:,0],seg[:,1];use=(a[:,0]<=x)!=(b[:,0]<=x);a,b=a[use],b[use]
    return np.unique(np.round(a[:,1]+(b[:,1]-a[:,1])*(x-a[:,0])/(b[:,0]-a[:,0]),8))
def save_patches(out,patches):
    out.mkdir(exist_ok=True)
    write_surface(out/'aircraft_domain.msh',patches)
    for k,t in patches.items():write_binary_stl(out/(k+'.stl'),t,k)

