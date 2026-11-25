"""Reduce noncritical coarse wall faces while retaining the corrected aerodynamic contours."""
import argparse,json
import numpy as np
from meshlib import mrmeshpy as mr,mrmeshnumpy as mn
from p2_geometry_io import *
from verify_p2_cad_shell import verify,geom,quality

def make(t):v,f=indices(t);return mn.meshFromFacesVerts(f,v)
def candidate(name,t,g):
    target={'wall_fuselage':3000,'wall_nacelles':5350,'wall_sponson':1270,'wall_empennage':5850}[name]
    cfg={'wall_fuselage':(.008,.24),'wall_nacelles':(.0035,.105),'wall_sponson':(.0028,.098),'wall_empennage':(.00165,.12)}[name]
    m=make(t);v,f=geom(m);c=v[f].mean(1);x,y,z=c.T;locked=np.zeros(len(c),bool)
    if name=='wall_fuselage':locked=(x>.225)&(x<.33)&(z>.405)&(z<.59)&(y>.08)&(y<.18)
    if name=='wall_nacelles':
        locked=(abs(x)<.185)&(z>.73)&(z<.915)
        locked|=(x>.140)&(abs(z-3.769)<.05)&(y<.11)
        for rotor in g['starboard_propellers_detected']:
            locked|=(abs(x-rotor['x_disk_m'])<.036)&(abs(z-rotor['z_axis_m'])<.25)
    if name=='wall_sponson':locked=(abs(x)<.18)&(z>.81)
    if name=='wall_empennage':
        locked=(x>4.836)&(x<4.857)&(z<1.015)&(y<-.37)
        locked|=(x>4.8)&(x<4.827)&(z>.4)&(z<.66)&(y<-.4)
    q=mr.DecimateSettings();q.region=mn.faceBitSetFromBools(~locked)
    q.stabilizer=1.e-8;q.maxError=cfg[0];q.maxEdgeLen=cfg[1];q.maxTriangleAspectRatio=26
    q.touchBdVerts=False;q.touchNearBdEdges=False;q.maxDeletedFaces=max(0,len(f)-target)
    mr.decimateMesh(m,q);v,f=geom(m)
    return v[f]

def main(src,out):
    g=json.loads((GEO/'geometry_audit.json').read_text(encoding='utf-8-sig'))
    ps={k:stl_triangles(src/(k+'.stl')) for k in TYPES};stats={}
    for k in WALLS[1:]:
        old=ps[k];ps[k]=candidate(k,old,g)
        o=make(old);a=make(ps[k]);dist=float(np.sqrt(mr.findMaxDistanceSq(o,a)))
        stats[k]=dict(old=len(old),new=len(ps[k]),max_bidirectional_vertex_surface_distance_m=dist,min_shape=float(quality(ps[k]).min()))
        print(k,stats[k],flush=True)
    save_patches(out,ps);verify(out,True)
    refs=[('root_trailing_edge_qa.json','rays_detail','wall_wing',GEO/'p2_stair_coarse_root33b'),
          ('outer_tail_tip_qa.json','probes','wall_empennage',GEO/'p2_stair_coarse_tail5c'),
          ('hlp6_aft_qa.json','samples','wall_nacelles',src)]
    measured={}
    for filename,key,wall,tab in refs:
        rows=json.loads((tab/filename).read_text())[key];tr=ps[wall].astype(float)
        if wall=='wall_nacelles':tr=tr[(tr[:,:,1].min(1)<.11)&(abs(tr.mean(1)[:,2]-3.769)<.15)]
        section={};error=[];odd=0
        for row in rows:
            x=row.get('x',row.get('x_m'));z=row.get('z',row.get('z_m'))
            if z not in section:section[z]=section_segments(tr,z)
            h=heights(section[z],x);cad=row.get('CAD',row.get('cad_envelope'))
            if len(h)<2 or len(h)%2:odd+=1;continue
            error.append(float(max(abs(np.array([h.min(),h.max()])-cad))))
        measured[wall]=dict(rays=len(rows),missing_or_odd=odd,maximum_CAD_envelope_error_m=max(error))
        print(wall,measured[wall],flush=True)
    raw=np.load(GEO/'cad_components.npz')['55'].astype(float);tail=ps['wall_empennage'].astype(float);errs=[]
    for z in np.linspace(.42,.65,24):
        a=section_segments(raw,z);b=section_segments(tail,z)
        for x in np.linspace(4.809,4.824,11):
            v=heights(b,x)
            if len(v)!=2:raise ValueError('Stabilizer skin lost')
            errs.append(abs(np.ptp(heights(a,x))-np.ptp(v)))
    measured['wall_empennage_seam']=dict(rays=len(errs),max_CAD_thickness_error_m=float(max(errs)))
    r=dict(source=str(src),walls=stats,local_geometry=measured,wall_faces=sum(len(ps[k]) for k in WALLS))
    (out/'coarse_reduction_qa.json').write_text(json.dumps(r,indent=2))
    return r
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('source',type=Path);p.add_argument('out',type=Path);a=p.parse_args();main(a.source,a.out)

