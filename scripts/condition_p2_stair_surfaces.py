"""Retriangulate facets around the previous native stair-step coordinates under CAD error limits."""
import argparse
import json
import re
from pathlib import Path

import numpy as np
from meshlib import mrmeshpy as mr, mrmeshnumpy as mn
from scipy.spatial import cKDTree

from diagnose_prism_stair_locations import closest
from p2_geometry_io import GEO, TYPES, WALLS, indices, save_patches, stl_triangles
from verify_p2_cad_shell import geom, quality, verify


def condition(source,transcript,destination):
    text=transcript.read_text(errors='replace')
    points=np.array([list(map(float,s.split())) for s in re.findall(r'layers? removed at \(([^)]+)\)',text)])
    if not len(points):raise ValueError('Missing native stair-step coordinates')
    surfaces={k:stl_triangles(source/(k+'.stl')) for k in TYPES}
    models={};distances=[]
    for name in WALLS:
        tr=surfaces[name].astype(float)
        tree=cKDTree(tr.mean(1))
        ids=tree.query(points,k=36)[1]
        distances.append([closest(tr[lst],p)[1] for lst,p in zip(ids,points)])
        v,f=indices(surfaces[name]);models[name]=mn.meshFromFacesVerts(f,v)
    ownership=np.argmin(distances,axis=0); reports={}
    for i,name in enumerate(WALLS):
        seeds=points[ownership==i]
        mesh=models[name]; verts,faces=geom(mesh)
        xyz=verts[faces];cen=xyz.mean(1)
        if not len(seeds):continue
        radius,size={'wall_wing':(.055,.017),'wall_fuselage':(.14,.059),'wall_nacelles':(.050,.016),
                     'wall_sponson':(.060,.022),'wall_empennage':(.065,.020)}[name]
        near=cKDTree(seeds).query(cen)[0]<radius
        x,y,z=cen.T
        if name=='wall_wing':
            near&=~((x>.214)&(x<.35)&(z<.70))
        if name=='wall_nacelles':
            near&=~((abs(x)<.19)&(z>.72)&(z<.93))
            near&=~((x>.12)&(abs(z-3.769)<.06))
        if name=='wall_sponson':
            near&=~((abs(x)<.20)&(z>.80))
        if name=='wall_empennage':
            near&=~((x>4.80)&(x<4.91)&(z<1.04))
        if not near.any():continue
        settings=mr.RemeshSettings()
        settings.region=mn.faceBitSetFromBools(near)
        settings.targetEdgeLen=size;settings.frozenBoundary=True
        settings.projectOnOriginalMesh=True;settings.useCurvature=True
        settings.maxEdgeSplits=max(450,int(near.sum()*1.5))
        settings.maxAngleChangeAfterFlip=.045;settings.finalRelaxIters=0
        if not mr.remesh(mesh,settings):raise RuntimeError('Interrupted remesh '+name)
        verts,faces=geom(mesh);repaired=verts[faces]
        # Topology QA and independent geometric deviations are evaluated before this surface can be used.
        v0,f0=indices(surfaces[name]);orig=mn.meshFromFacesVerts(f0,v0)
        dev=float(np.sqrt(mr.findMaxDistanceSq(orig,mesh)))
        limit={'wall_wing':.00040,'wall_fuselage':.0015,'wall_nacelles':.00060,'wall_sponson':.0006,'wall_empennage':.00045}[name]
        if dev>limit:
            # Use stationary-vertex diagonal flips inside the same witness neighbourhood.
            mesh=mn.meshFromFacesVerts(f0,v0)
            opts=mr.DeloneSettings()
            opts.region=mn.faceBitSetFromBools(near)
            opts.maxDeviationAfterFlip=limit/6
            opts.maxAngleChange=.045
            mr.makeDeloneEdgeFlips(mesh,opts,4)
            verts,faces=geom(mesh);repaired=verts[faces]
            dev=float(np.sqrt(mr.findMaxDistanceSq(orig,mesh)))
            mode='stationary_vertex_flips'
        else:mode='graded_patch_remesh'
        if dev>limit:raise ValueError(f'{name}: surface displacement {dev} exceeds {limit}')
        old=surfaces[name];surfaces[name]=repaired
        reports[name]=dict(native_locations=len(seeds),source_facets_in_patch=int(near.sum()),method=mode,
                           old_faces=len(old),new_faces=len(repaired),sampled_bidirectional_distance_m=dev,
                           shape_q10_before=float(np.quantile(quality(old),.1)),
                           shape_q10_after=float(np.quantile(quality(repaired),.1)))
    save_patches(destination,surfaces)
    verify(destination,True)
    data=dict(source=str(source.resolve()),native_transcript=str(transcript.resolve()),walls=reports)
    (destination/'native_stair_patch_qa.json').write_text(json.dumps(data,indent=2),encoding='utf8')
    print(json.dumps(reports))


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('source',type=Path);p.add_argument('transcript',type=Path);p.add_argument('destination',type=Path)
    a=p.parse_args();condition(a.source,a.transcript,a.destination)

