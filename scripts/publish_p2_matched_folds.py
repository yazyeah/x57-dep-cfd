"""Produce a matched three-level alternate with the same reconstructed surfaces."""
import argparse,json
import numpy as np
from p2_geometry_io import *
from verify_p2_cad_shell import verify,quality,geom,halo,mn,mr,sections
from refine_p2_wall_levels import graded
def build(level,parent=None,destination=None):
    src=Path(parent).resolve(strict=True) if parent else GEO/('p2_coarse_combined_clean' if level=='coarse' else 'p2_matched_coarse')
    out=Path(destination).resolve() if destination else GEO/("p2_matched_"+level)
    if not out.is_relative_to(GEO) or out==src:raise ValueError("Invalid grading destination")
    ps={k:stl_triangles(src/(k+'.stl')) for k in TYPES}
    if level=='coarse':
        v,f=indices(ps['wall_wing']);m=mn.meshFromFacesVerts(f,v)
        for dev in [.00009,.00018]:
            for j in range(2):
                v,f=geom(m);tr=v[f];c=tr.mean(1);mask=(quality(tr)<.035)&(c[:,0]>.268)&(c[:,0]<.287)&(c[:,2]>3.077)&(c[:,2]<3.305)
                reg=halo(f,mask,2);cfg=mr.FixMeshDegeneraciesParams();cfg.region=reg;cfg.maxDeviation=dev;cfg.criticalTriAspectRatio=12;cfg.tinyEdgeLength=dev*1.7;cfg.mode=cfg.Mode.Decimate;mr.fixMeshDegeneracies(m,cfg)
        v,f=geom(m);ps['wall_wing']=v[f]
    else:
        medium={'wall_wing':25500,'wall_fuselage':8000,'wall_nacelles':7900,'wall_sponson':2100,'wall_empennage':11100}
        fine={'wall_wing':44200,'wall_fuselage':10000,'wall_nacelles':8700,'wall_sponson':2400,'wall_empennage':12500}
        for tag,target in (medium if level=='medium' else fine).items():ps[tag]=graded(ps[tag],max(target,len(ps[tag])),tag)
    save_patches(out,ps);verify(out,True)
    orig=np.load(GEO/'cad_components.npz');tail=ps['wall_empennage'].astype(float);wing=np.vstack((ps['wall_wing'],ps['wall_nacelles'])).astype(float)
    checks=[];source=orig['55'].astype(float)
    for z in np.linspace(.42,.65,24):
        ac=section_segments(source,z);at=section_segments(tail,z)
        for x in np.linspace(4.809,4.824,11):
            a=heights(ac,x);b=heights(at,x)
            if len(b)!=2:raise ValueError(('Stabilizer false gap',x,z))
            checks.append(float(abs(np.ptp(b)-np.ptp(a))))
    h=[]
    for x,z in [(.21777572,3.2052927),(.23723802,3.22049),(.24588485,3.17411745),(.25643058,3.14908576)]:
        a=np.r_[heights(section_segments(orig['49'].astype(float),z),x),heights(section_segments(orig['51'].astype(float),z),x)]
        b=heights(section_segments(wing,z),x)
        h.append(float(max(abs(np.array([min(a),max(a)])-b[[0,-1]]))))
    wk={k:float(quality(ps[k]).min()) for k in WALLS}
    if min(wk.values())<.0099 or max(checks)>.001 or max(h)>.001:raise ValueError(('Matched geometry quality check',wk,max(checks),max(h)))
    summary={'structural_and_fluid_geometry':'reconstructed two lower-wing clusters and upper/lower stabilizer skins','wall_shape_minimum_by_zone':wk,
             'stabilizer_rays':len(checks),'max_stabilizer_thickness_error_m':max(checks),'four_HLP5_envelope_errors_m':h,
             'wall_faces':sum(len(ps[k]) for k in WALLS),'parent_source':str(src)}
    (out/'matched_geometry_qa.json').write_text(json.dumps(summary,indent=2));print('MATCHED',level,summary,flush=True)
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('level',choices=['coarse','medium','fine']);p.add_argument('--parent');p.add_argument('--out');args=p.parse_args();build(args.level,args.parent,args.out)

