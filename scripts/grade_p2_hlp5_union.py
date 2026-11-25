"""Improve CAD union triangle quality while preserving the reconstructed HLP-5 fairing."""
import json
import numpy as np
from scipy.spatial import cKDTree
from meshlib import mrmeshpy as mr,mrmeshnumpy as mn
from p2_geometry_io import *
from verify_p2_cad_shell import quality,verify,region,halo

def main():
    src=GEO/'p2_coarse_hlp5_cad';out=GEO/'p2_coarse_hlp5_graded'
    ps={n:stl_triangles(src/(n+'.stl')) for n in TYPES}

    ts=np.vstack([ps['wall_wing'],ps['wall_nacelles']]);tags=np.repeat([0,1],[len(ps['wall_wing']),len(ps['wall_nacelles'])]);tree=cKDTree(ts.mean(1))
    v,f=indices(ts);m=mn.meshFromFacesVerts(f,v)
    def arrays():
        m.pack();return mn.getNumpyVerts(m).copy(),mn.getNumpyFaces(m.topology).copy()
    def within(c):
        return (c[:,0]>.165)&(c[:,0]<.2709)&(c[:,2]>3.077)&(c[:,2]<3.30)
    for step in range(2):
        v,f=arrays();q=quality(v[f]);mask=within(v[f].mean(1))&(q<.085);good=halo(f,mask,1)
        c=mr.FixMeshDegeneraciesParams();c.region=good;c.maxDeviation=.00026;c.criticalTriAspectRatio=11;c.tinyEdgeLength=.00024;c.mimicPatch=True;c.mode=c.Mode.Decimate;mr.fixMeshDegeneracies(m,c)
    v,f=arrays();reg=region(within(v[f].mean(1)));cfg=mr.RemeshSettings();cfg.region=reg;cfg.targetEdgeLen=.0065
    cfg.maxEdgeSplits=2200;cfg.maxBdShift=.0001;cfg.projectOnOriginalMesh=True;cfg.finalRelaxIters=0;cfg.maxAngleChangeAfterFlip=.12;cfg.packMesh=True
    mr.remesh(m,cfg)
    for _ in range(2):
        v,f=arrays();q=quality(v[f]);mask=within(v[f].mean(1))&(q<.055);k=halo(f,mask,1)
        c=mr.FixMeshDegeneraciesParams();c.region=k;c.maxDeviation=.00022;c.tinyEdgeLength=.00032;c.criticalTriAspectRatio=15;c.mode=c.Mode.Decimate;mr.fixMeshDegeneracies(m,c)
    v,f=arrays();tri=v[f];tag=tags[tree.query(tri.mean(1))[1]];ps['wall_wing']=tri[tag==0];ps['wall_nacelles']=tri[tag==1]
    save_patches(out,ps);verify(out,True)
    cad=np.load(GEO/'cad_components.npz');probes=[]
    for row in json.loads((src/'pylon_and_wing_qa.json').read_text()):
        x,z=row['x_m'],row['z_m'];h=heights(section_segments(tri.astype(float),z),x);y=np.array(row['source_outer_bounds_m'])
        if len(h)<2:raise ValueError(('Missing HLP-5 surface',x,z))
        err=float(np.max(abs(h[[0,-1]]-y)));probes.append(dict(x_m=x,z_m=z,outer_bound_error_m=err))
        if err>.0015:raise ValueError(('HLP5 profile deviation',err))
    q=quality(tri);sel=within(tri.mean(1));rec={'subregions':'HLP-3 wing, HLP-5 physical fairing/wing, stabilizer cut seam','fairing_cad_checks':probes,'minimum_local_shape':float(q[sel].min()),'under_0p01_local':int((q[sel]<.01).sum()),'local_facets':int(sel.sum())};(out/'combined_geometric_qa.json').write_text(json.dumps(rec,indent=2));print(rec)
if __name__=='__main__':main()

