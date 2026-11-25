"""Conformally subdivide the native collision neighbourhood across the tail/symmetry seam."""
import argparse
import json
from pathlib import Path

import numpy as np

from p2_geometry_io import TYPES, indices, save_patches, stl_triangles
from verify_p2_cad_shell import quality, verify


def split(v, f, labels, point):
    sides = np.sort(f[:, [[0, 1], [1, 2], [2, 0]]], axis=2)
    edges, inverse = np.unique(sides.reshape(-1, 2), axis=0, return_inverse=True)
    inverse = inverse.reshape(-1, 3)
    a, b = v[edges].transpose(1, 0, 2)
    vec = b-a
    length = np.linalg.norm(vec, axis=1)
    frac = np.clip(np.sum((point-a)*vec, axis=1)/length**2, 0, 1)
    distance = np.linalg.norm(a+frac[:, None]*vec-point, axis=1)
    target = np.interp(distance, [0, .006, .02, .045], [.0025, .0035, .0075, .017])
    mark = (distance < .045) & (length > target)
    return subdivide_edges(v,f,labels,edges,inverse,mark)


def subdivide_edges(v,f,labels,edges,inverse,mark):
    a,b=v[edges].transpose(1,0,2)
    if not np.any(mark):
        return v, f, labels, 0
    mids = np.full(len(edges), -1, dtype=int)
    mids[mark] = len(v)+np.arange(mark.sum())
    v = np.vstack((v, (a[mark]+b[mark])/2))
    new, tags = [], []
    for ids, midpoint, label in zip(f, mids[inverse], labels, strict=True):
        flags = midpoint >= 0
        n = int(flags.sum())
        if n == 0:
            out = [ids]
        elif n == 3:
            a0,b0,c0 = ids
            m,n0,o = midpoint
            out = [[a0,m,o],[m,b0,n0],[o,n0,c0],[m,n0,o]]
        elif n == 1:
            j = int(np.flatnonzero(flags)[0])
            a0,b0,c0 = np.roll(ids,-j)
            m = midpoint[j]
            out = [[a0,m,c0],[m,b0,c0]]
        else:
            j = (int(np.flatnonzero(~flags)[0])+1)%3
            a0,b0,c0 = np.roll(ids,-j)
            m,n0,_ = np.roll(midpoint,-j)
            pair1 = [[a0,m,n0],[a0,n0,c0]]
            pair2 = [[a0,m,c0],[m,n0,c0]]
            out = [[m,b0,n0]] + (pair1 if quality(v[pair1]).min()>quality(v[pair2]).min() else pair2)
        new.extend(out)
        tags.extend([label]*len(out))
    return v, np.asarray(new), np.asarray(tags), int(mark.sum())


def main(source,destination,point):
    walls = list(TYPES)
    parts = [stl_triangles(source/(s+'.stl')) for s in walls]
    v,f = indices(np.concatenate(parts))
    labels = np.repeat(np.arange(len(walls)), [len(p) for p in parts])
    initial = dict(zip(walls,map(len,parts)))
    reports = []
    for _ in range(14):
        v,f,labels,n = split(v, f, labels, point)
        reports.append(n)
        if not n:break
    else:raise ValueError('Local subdivision failed to reach target')
    patches = {name:v[f[labels==i]] for i,name in enumerate(walls)}
    save_patches(destination,patches)
    verify(destination,True)
    data=dict(native_collision_m=point.tolist(),source=str(source.resolve()),initial_faces=initial,
              final_faces={k:len(s) for k,s in patches.items()},split_edges=reports,
              geometry='Midpoints remain on their parent planar facets, including across the wall/symmetry boundary.')
    (destination/'tail_symmetry_refinement.json').write_text(json.dumps(data,indent=2),encoding='utf8')
    print(data)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('source',type=Path)
    p.add_argument('destination',type=Path)
    a=p.parse_args()
    main(a.source,a.destination,np.array([4.876663,-.434074,.002493]))

