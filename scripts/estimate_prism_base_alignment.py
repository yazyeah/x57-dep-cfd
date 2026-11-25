"""Locate facets whose ideal first prism already has poor wall-normal alignment."""
import argparse
import json
from pathlib import Path

import numpy as np

from control_gate import atomic_write_json
from p2_geometry_io import WALLS, indices, stl_triangles


def study(folder, source_override=None, face_data=None):
    cfg=json.loads((folder/'mesh_config.json').read_text())
    source=source_override or Path(cfg['source_surface_dir'])
    heights={w:s['first_height_m'] for s in cfg['prism_scopes'] for w in s['walls']}
    surfaces=[stl_triangles(source/(s+'.stl')) for s in WALLS]
    v,f=indices(np.concatenate(surfaces))
    v=v.astype(float)
    label=np.repeat(np.arange(len(WALLS)),[len(t) for t in surfaces])
    height=np.asarray([heights[s] for s in WALLS])[label]
    base=v[f]
    cross=np.cross(base[:,1]-base[:,0],base[:,2]-base[:,0])
    norm=cross/np.linalg.norm(cross,axis=1)[:,None]
    # Airframe facets are outward normals of the fluid domain. Grow into the fluid.
    norm=-norm
    w=np.empty(f.shape)
    for j in range(3):
        a=base[:,(j+1)%3]-base[:,j]
        b=base[:,(j+2)%3]-base[:,j]
        w[:,j]=np.arctan2(np.linalg.norm(np.cross(a,b),axis=1),np.sum(a*b,axis=1))
    A=np.zeros((len(v),3,3))
    rhs=np.zeros((len(v),3))
    smooth=np.zeros((len(v),3))
    for j in range(3):
        val=w[:,j,None]*norm
        np.add.at(rhs,f[:,j],val*height[:,None])
        np.add.at(A,f[:,j],val[:,:,None]*norm[:,None,:])
        np.add.at(smooth,f[:,j],val)
    smooth/=np.maximum(np.linalg.norm(smooth,axis=1)[:,None],1e-20)
    mean=np.zeros(len(v))
    weights=np.zeros(len(v))
    np.add.at(mean,f.ravel(),(w*height[:,None]).ravel())
    np.add.at(weights,f.ravel(),w.ravel())
    smooth*=np.divide(mean,weights)[:,None]
    # The regularized local plane intersection supports sharp folds without long mitres.
    reg=.025*np.trace(A,axis1=1,axis2=2)
    A+=reg[:,None,None]*np.eye(3)
    rhs+=reg[:,None]*smooth
    symmetry=np.abs(v[:,2])<1e-7
    A[symmetry,2,:]=0.0
    A[symmetry,2,2]=1.0
    rhs[symmetry,2]=0.
    miter=np.linalg.solve(A,rhs[:,:,None]).squeeze(2)
    result={}
    for method,dv in [('angle_normal',smooth),('plane_offset',miter)]:
        dis=dv[f]
        cap=base+dis
        # Integrate the closed prism with oriented tetrahedra about its local origin.
        bc=base.mean(axis=1)
        verts=np.concatenate((base-bc[:,None,:],cap-bc[:,None,:]),axis=1)
        volume=np.zeros(len(f))
        moment=np.zeros((len(f),3))
        polys=[[0,1,2],[3,5,4],[0,3,4,1],[1,4,5,2],[2,5,3,0]]
        for ring in polys:
            pts=verts[:,ring]; c=pts.mean(axis=1)
            for j in range(len(ring)):
                x,y=pts[:,j],pts[:,(j+1)%len(ring)]
                vol=np.einsum('ij,ij->i',c,np.cross(x,y))/6
                volume+=vol
                moment+=vol[:,None]*(c+x+y)/4
        rel=moment/np.where(np.abs(volume)>1.e-30,volume,np.nan)[:,None]
        q=np.einsum('ij,ij->i',rel,norm)/np.maximum(np.linalg.norm(rel,axis=1),1e-30)
        if not np.isfinite(q).all():raise ValueError("Degenerate ideal extrusion")
        if face_data is not None:
            face_data[method]=q.copy()
            face_data['centers']=bc.copy()
            face_data['labels']=label.copy()
        by_zone={}
        for j,name in enumerate(WALLS):
            subset=np.flatnonzero(label==j);ids=subset[np.argsort(q[subset])[:12]]
            by_zone[name]=dict(base_faces=len(subset),below_005=int(sum(q[subset]<.05)),
                               below_010=int(sum(q[subset]<.10)),minimum=float(q[subset].min()),
                               worst=[dict(face=int(i-subset[0]),xyz_m=bc[i].tolist(),base_cosine=float(q[i])) for i in ids])
        result[method]=by_zone
    return dict(model="Geometric wall-face cosine for an ideal triangular first prism only. Excludes Fluent smoothing, clipping, conversion and neighbour faces. No mesh acceptance is inferred.",source=str(source),methods=result)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('folder',type=Path)
    a=p.parse_args()
    data=study(a.folder)
    atomic_write_json(a.folder/'first_layer_geometry_estimate.json',data)
    for k,by_zone in data['methods'].items():
        print(k,{z:(s['below_005'],s['below_010']) for z,s in by_zone.items()})

