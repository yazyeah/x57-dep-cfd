"""Conformal facet remeshing at Fluent's measured near-degenerate prism cap locations."""
import argparse
from pathlib import Path
import json

import numpy as np
import triangle
from scipy.spatial import cKDTree

from diagnose_prism_stair_locations import closest
from p2_geometry_io import TYPES, indices, save_patches, stl_triangles
from verify_p2_cad_shell import quality, verify
from repair_p2_native_cap_slivers import probes, GEO

LOCATIONS={
    'wall_wing':np.array([[.318265,.107063,.639885],[.315133,.107541,.670574],[.318844,.106019,.568587]]),
    'wall_nacelles':np.array([[.146366,-.005061,3.753169]])
}


def refine(source, destination):
    names=list(TYPES)
    patches=[stl_triangles(source/(n+'.stl')) for n in names]
    vertices,faces=indices(np.concatenate(patches))
    vertices=vertices.astype(float)
    labels=np.repeat(np.arange(len(names)),[len(t) for t in patches])
    xyz=vertices[faces]
    shape=quality(xyz)
    edges=np.sort(faces[:,[[0,1],[1,2],[2,0]]],axis=2)
    sides={}
    for name,points in LOCATIONS.items():
        ids=np.flatnonzero(labels==names.index(name))
        w=xyz[ids]
        for pt in points:
            nearby=np.all(w.max(1)>=pt-.009,axis=1)&np.all(w.min(1)<=pt+.009,axis=1)
            within=ids[nearby]
            for i in within:
                if shape[i]>.22 or closest(xyz[[i]],pt)[1]>.008:continue
                tri=xyz[i]
                lengths=np.linalg.norm(tri-np.roll(tri,-1,axis=0),axis=1)
                altitude=np.linalg.norm(np.cross(tri[1]-tri[0],tri[2]-tri[0]))/lengths.max()
                # Retain the CAD crease and refine along its span to resolve the thin strip.
                target=max(.00022 if name=='wall_nacelles' else .00075,1.8*altitude,lengths.max()/26)
                for edge, length in zip(edges[i],lengths):
                    key=tuple(edge)
                    n=int(np.ceil(length/target))
                    if n>1:sides[key]=max(n,sides.get(key,1))
    # Propagate spacing to the second long side of a thin neighbouring facet.
    # Otherwise its already-divided edge can generate a new fan of acute triangles.
    for _ in range(10):
        changed=False
        for i in np.flatnonzero(shape<.43):
            pairs=[tuple(k) for k in edges[i]]
            if not any(k in sides for k in pairs):continue
            lengths=np.linalg.norm(xyz[i]-np.roll(xyz[i],-1,axis=0),axis=1)
            spacing=min(length/sides[k] for k,length in zip(pairs,lengths) if k in sides)
            for k,length in zip(pairs,lengths):
                div=min(42,int(np.ceil(length/(1.65*spacing))))
                if div>max(1,sides.get(k,1)):
                    sides[k]=div
                    changed=True
        if not changed:break
    nodes=list(vertices)
    cuts={}
    for (a,b),n in sides.items():
        mid=[]
        for j in range(1,n):
            mid.append(len(nodes))
            nodes.append(vertices[a]+(j/n)*(vertices[b]-vertices[a]))
        cuts[(a,b)]=mid
    new=[]
    tags=[]
    for i,f in enumerate(faces):
        if not any(tuple(k) in cuts for k in edges[i]):
            new.append(f);tags.append(labels[i]);continue
        bound=[]
        first=[]
        side_nodes=[]
        for a,b in zip(f,np.roll(f,-1)):
            mid=cuts.get((min(a,b),max(a,b)),[])
            mid=mid if a<b else mid[::-1]
            first.append(len(bound))
            side_nodes.append([a,*mid,b])
            bound.extend([a,*mid])
        tri=vertices[f]
        axis=tri[1]-tri[0];axis/=np.linalg.norm(axis)
        n=np.cross(axis,tri[2]-tri[0]);n/=np.linalg.norm(n)
        frame=np.c_[axis,np.cross(n,axis)]
        xy=(np.asarray([nodes[v] for v in bound])-tri[0])@frame
        # Interior rows follow each divided edge with geometric grading toward the opposite tip.
        seeds=[]
        for j,edge_group in enumerate(side_nodes):
            count=len(edge_group)-1
            if count<3:continue
            start,end=tri[j],tri[(j+1)%3]
            opp=tri[(j+2)%3]
            le=np.linalg.norm(end-start)
            height=np.linalg.norm(np.cross(end-start,opp-start))/le
            h=le/count
            distance=h
            step=h
            while distance<height-.45*step:
                fraction=distance/height
                m=int((1-fraction)*le/step)
                for k in range(1,m):
                    a=start+(k/m)*(end-start)
                    q=(1-fraction)*a+fraction*opp
                    if min(np.linalg.norm(np.asarray(nodes[b])-q) for b in bound)<.45*step:continue
                    if any(np.linalg.norm(q-u)<.48*step for u in seeds):continue
                    seeds.append(q)
                step*=1.55
                distance+=step
        points=np.vstack((xy,(np.asarray(seeds).reshape(-1,3)-tri[0])@frame))
        k=np.arange(len(bound))
        loc=triangle.triangulate(dict(vertices=points,segments=np.c_[k,np.roll(k,-1)]),'pYQ')
        if len(loc['vertices'])!=len(points):raise ValueError('Unexpected added node on a true facet boundary.')
        ids=np.r_[bound,np.arange(len(nodes),len(nodes)+len(seeds),dtype=int)]
        nodes.extend(seeds)
        local=ids[loc['triangles']]
        new.extend(local);tags.extend([labels[i]]*len(local))
    nodes=np.asarray(nodes).astype('f4');tri=nodes[np.asarray(new)]
    if np.min(quality(tri))<=1e-8:raise ValueError('Degenerate triangle after projection')
    out={n:tri[np.asarray(tags)==k] for k,n in enumerate(names)}
    report={}
    for name,points in LOCATIONS.items():
        hits=[]
        for pt in points:
            row={}
            for k,t in [('original',patches[names.index(name)]),('new',out[name])]:
                take=np.all(t.max(1)>=pt-.014,axis=1)&np.all(t.min(1)<=pt+.014,axis=1)
                local=t[take].astype(float)
                idx,d,_=closest(local,pt)
                row[k]=dict(q=float(quality(local[idx:idx+1])[0]),q10=float(np.quantile(quality(local),.1)),distance_m=d)
            hits.append(row)
        report[name]=dict(native_cap_witnesses=hits,total_faces=len(out[name]))
    for wall,fn,key in [('wall_wing',GEO/'p2_stair_coarse_root33b/root_trailing_edge_qa.json','rays_detail'),
                         ('wall_nacelles',GEO/'p2_stair_coarse_hlp6cad2/hlp6_aft_qa.json','samples')]:
        t=out[wall]
        if wall=='wall_nacelles':t=t[(t[:,:,1].min(1)<.11)&(abs(t.mean(1)[:,2]-3.769)<.15)]
        report[wall]['cad']=probes(t,fn,key)
    print(json.dumps(report),flush=True)
    save_patches(destination,out)
    verify(destination,True)
    (destination/'cap_facet_repair_qa.json').write_text(json.dumps(report,indent=2),encoding='utf-8')


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('source',type=Path);p.add_argument('destination',type=Path)
    a=p.parse_args();refine(a.source,a.destination)
