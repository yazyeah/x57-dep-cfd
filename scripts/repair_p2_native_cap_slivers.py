"""Repair the narrow base triangles beneath measured Fluent prism cap maxima."""
import argparse
import json
from pathlib import Path

import numpy as np
from meshlib import mrmeshpy as mr, mrmeshnumpy as mn

from diagnose_prism_stair_locations import closest
from p2_geometry_io import GEO, TYPES, heights, indices, save_patches, section_segments, stl_triangles
from verify_p2_cad_shell import geom, quality, verify


def surface_mesh(triangles):
    vert, face = indices(triangles)
    return mn.meshFromFacesVerts(face, vert)


def local_repair(triangles, wall, scale, flips, bounded, diagonals):
    mesh = surface_mesh(triangles)
    verts, fs = geom(mesh)
    xyz = verts[fs]
    p = xyz.mean(axis=1)
    x,y,z = p.T
    if wall == 'wall_wing':
        mask = (x>.276)&(x<.347)&(z>.51)&(z<.723)
        target=.0035*scale
        points=[[.318265,.107063,.639885],[.315133,.107541,.670574]]
    else:
        mask = (x>.126)&(x<.175)&(abs(z-3.769)<.047)&(y<.105)
        target=.0016*scale
        points=[[.146366,-.005061,3.753169]]
    crease = mr.findCreaseEdges(mesh.topology,mesh.points,np.deg2rad(26.))
    opts=mr.RemeshSettings()
    opts.region=mn.faceBitSetFromBools(mask)
    opts.notFlippable=crease
    opts.targetEdgeLen=target
    opts.maxEdgeSplits=4500
    opts.maxAngleChangeAfterFlip=.14
    opts.frozenBoundary=True
    opts.projectOnOriginalMesh=True
    opts.useCurvature=False
    opts.finalRelaxIters=0
    if diagonals:
        from retessellate_prism_cap import improve
        mesh=surface_mesh(improve(triangles,wall))
    elif bounded:
        # Replace the submillimetre acute tips of constrained facets, allowing the
        # two sides of each physical crease to be retriangulated together.
        from verify_p2_cad_shell import halo
        for tolerance in [.000035,.00007,.00012,.00018]:
            vv,ff=geom(mesh)
            tri=vv[ff]; xx,yy,zz=tri.mean(1).T
            roi=(xx>.27)&(xx<.345)&(zz>.52)&(zz<.716) if wall=='wall_wing' else (xx>.131)&(xx<.168)&(abs(zz-3.769)<.04)&(yy<.105)
            bad=roi&(quality(tri)<.17)
            if not bad.any():break
            control=mr.FixMeshDegeneraciesParams()
            control.region=halo(ff,bad,1)
            control.mode=control.Mode.Decimate
            control.maxDeviation=tolerance
            control.criticalTriAspectRatio=6
            control.maxAngleChange=.3
            control.tinyEdgeLength=1.5*tolerance
            control.mimicPatch=True
            mr.fixMeshDegeneracies(mesh,control)
    elif flips:
        setting=mr.DeloneSettings()
        setting.region=opts.region
        setting.notFlippable=crease
        setting.maxDeviationAfterFlip=.000045
        setting.maxAngleChange=.20
        mr.makeDeloneEdgeFlips(mesh,setting,16)
    elif not mr.remesh(mesh,opts):
        raise ValueError('Remeshing interrupted')
    verts,fs=geom(mesh)
    new=verts[fs]
    diff=np.sqrt(mr.findMaxDistanceSq(surface_mesh(triangles),mesh))
    witness=[]
    for point in np.asarray(points):
        row={'native_cap_m':point.tolist()}
        for key,t in [('original',triangles),('candidate',new)]:
            take=np.all(t.max(1)>=point-.022,axis=1)&np.all(t.min(1)<=point+.022,axis=1)
            sub=t[take].astype(float)
            i,d,_=closest(sub,point)
            row[key]=dict(distance_m=d,nearest_face_shape=float(quality(sub[i:i+1])[0]),
                          near_p10_shape=float(np.quantile(quality(sub),.10)))
        witness.append(row)
    print(wall,'faces',len(triangles),len(new),'deviation',float(diff),'witnesses',witness,flush=True)
    return new, dict(before=len(triangles),after=len(new),max_vertex_to_opposite_mesh_m=float(diff),witness=witness)


def probes(triangles, file, key):
    ref=json.loads(file.read_text())[key]
    look={}
    errors=[]
    odd=0
    for r in ref:
        x=r.get('x_m',r.get('x')); z=r.get('z_m',r.get('z'))
        if z not in look:look[z]=section_segments(triangles.astype(float),z)
        v=heights(look[z],x)
        if len(v)<2 or len(v)%2:
            odd+=1
            continue
        a=r.get('cad_envelope',r.get('CAD'))
        errors.append(float(np.max(np.abs([v[0]-a[0],v[-1]-a[-1]]))))
    return dict(count=len(ref),missing_or_odd=odd,max_cad_envelope_error_m=max(errors))


def main(src,dest,scale,flips,bounded,diagonals):
    parts={name:stl_triangles(src/(name+'.stl')) for name in TYPES}
    report={}
    for wall,filename,key in [
        ('wall_wing',GEO/'p2_stair_coarse_root33b/root_trailing_edge_qa.json','rays_detail'),
        ('wall_nacelles',GEO/'p2_stair_coarse_hlp6cad2/hlp6_aft_qa.json','samples')
    ]:
        old=parts[wall]
        new,row=local_repair(old,wall,scale,flips,bounded,diagonals)
        a,b=old,new
        if wall=='wall_nacelles':
            a=a[(a[:,:,1].min(1)<.11)&(abs(a.mean(1)[:,2]-3.769)<.15)]
            b=b[(b[:,:,1].min(1)<.11)&(abs(b.mean(1)[:,2]-3.769)<.15)]
        row['original_cad']=probes(a,filename,key)
        row['new_cad']=probes(b,filename,key)
        report[wall]=row
        parts[wall]=new
        print(wall,'CAD',row['original_cad'],row['new_cad'],flush=True)
    dest.mkdir(exist_ok=False,parents=True)
    (dest/'cap_repair_qa.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    for row in report.values():
        if row['max_vertex_to_opposite_mesh_m']>.0005 or row['new_cad']['missing_or_odd']:
            raise ValueError('Geometry fidelity failed. Keep previous production shell.')
        if row['new_cad']['max_cad_envelope_error_m']>row['original_cad']['max_cad_envelope_error_m']+1.e-6:
            raise ValueError('Measured CAD envelope exceeds the previous production error')
    save_patches(dest,parts)
    verify(dest,True)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('source',type=Path)
    p.add_argument('destination',type=Path)
    p.add_argument('--scale',type=float,default=1)
    p.add_argument('--flips', action='store_true')
    p.add_argument('--bounded', action='store_true')
    p.add_argument('--diagonals', action='store_true')
    a=p.parse_args()
    main(a.source,a.destination,a.scale,a.flips,a.bounded,a.diagonals)
